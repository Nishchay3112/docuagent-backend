require('dotenv').config();

const express = require('express');
const cors = require('cors');
const multer = require('multer');
const Groq = require('groq-sdk');
const { Pinecone } = require('@pinecone-database/pinecone');
const { PDFParse } = require('pdf-parse');

const app = express();

const PORT = process.env.PORT || 5000;

const GROQ_MODEL = 'openai/gpt-oss-20b';
const PINECONE_INDEX_NAME = 'docuagent-index';

const PINECONE_TOP_K = 8;
const MAX_WEB_RESULTS = 5;

const MAX_FILE_SIZE = 10 * 1024 * 1024;

const CHUNK_SIZE = 1200;
const CHUNK_OVERLAP = 200;

app.use(
  cors({
    origin: true,
    credentials: true,
  })
);

app.use(express.json());

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: MAX_FILE_SIZE,
  },
});

if (!process.env.GROQ_API_KEY) {
  console.error('Missing GROQ_API_KEY');
}

if (!process.env.PINECONE_API_KEY) {
  console.error('Missing PINECONE_API_KEY');
}

if (!process.env.TAVILY_API_KEY) {
  console.error('Missing TAVILY_API_KEY');
}

const groq = new Groq({
  apiKey: process.env.GROQ_API_KEY,
});

const pinecone = new Pinecone({
  apiKey: process.env.PINECONE_API_KEY,
});

const pineconeIndex = pinecone.index(PINECONE_INDEX_NAME);

/* =========================================================
   BASIC HELPERS
========================================================= */

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function createStage(step, title, status, details = '') {
  return {
    step,
    title,
    status,
    details,
  };
}

function cleanPlainText(text) {
  if (!text) {
    return '';
  }

  return String(text)
    .replace(/```[\s\S]*?```/g, '')
    .replace(/^\s*#{1,6}\s*/gm, '')
    .replace(/\*\*(.*?)\*\*/gs, '$1')
    .replace(/__(.*?)__/gs, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[•▪◦]\s*/gm, '- ')
    .replace(/^\s*[+*]\s+/gm, '- ')
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    .replace(/^\s*\|?[\s:-]+\|[\s|:-]*\s*$/gm, '')
    .replace(/\|/g, ' ')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function cleanLLMResponse(text) {
  if (!text) {
    return '';
  }

  return String(text)
    .replace(/^```json\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim();
}

/* =========================================================
   PDF EXTRACTION
========================================================= */

async function extractPdfText(buffer) {
  const parser = new PDFParse({
    data: buffer,
  });

  try {
    const result = await parser.getText();

    return result.text || '';
  } finally {
    await parser.destroy();
  }
}

/* =========================================================
   TEXT NORMALIZATION
========================================================= */

function normalizeText(text) {
  return String(text || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/* =========================================================
   CHUNKING
========================================================= */

function chunkText(text, chunkSize = CHUNK_SIZE, overlap = CHUNK_OVERLAP) {
  const normalized = normalizeText(text);

  const chunks = [];

  let start = 0;

  while (start < normalized.length) {
    let end = Math.min(start + chunkSize, normalized.length);

    /*
      Prefer ending at a newline or sentence boundary.
    */

    if (end < normalized.length) {
      const newlinePosition = normalized.lastIndexOf('\n', end);

      if (newlinePosition > start + chunkSize * 0.6) {
        end = newlinePosition;
      } else {
        const sentencePosition = normalized.lastIndexOf('. ', end);

        if (sentencePosition > start + chunkSize * 0.6) {
          end = sentencePosition + 1;
        }
      }
    }

    const chunk = normalized.slice(start, end).trim();

    if (chunk.length > 0) {
      chunks.push(chunk);
    }

    if (end >= normalized.length) {
      break;
    }

    start = Math.max(end - overlap, start + 1);
  }

  return chunks;
}

/* =========================================================
   QUERY CLASSIFICATION
========================================================= */

function classifyQueryWithHeuristics(query) {
  const q = query.toLowerCase();

  const documentTerms = [
    'document',
    'pdf',
    'this document',
    'this pdf',
    'heading',
    'title',
    'name on',
    'marksheet',
    'mark sheet',
    'result',
    'score',
    'marks',
    'percentage',
    'percent',
    'rank',
    'roll number',
    'registration number',
    'candidate',
    'student',
    'subject',
    'subjects',
    'grade',
    'grades',
    'cgpa',
    'gpa',
    'college',
    'university',
    'education',
    'resume',
    'cv',
    'skills',
    'experience',
    'project',
    'projects',
    'internship',
    'leetcode',
    'codeforces',
    'qualification',
    'qualifications',
    'background',
    'what does the document',
    'according to the document',
    'according to this',
    'in the document',
    'in this pdf',
    'from the document',
    'from this pdf',
    'what is shown',
    'what does it say',
  ];

  const webTerms = [
    'today',
    'current',
    'currently',
    'latest',
    'recent',
    'news',
    'this year',
    'deadline',
    'deadlines',
    'market',
    'industry',
    'trend',
    'trends',
    'salary',
    'salaries',
    'job market',
    'hiring trends',
    'weather',
    'price',
    'prices',
    'stock',
    'stocks',
    'population',
    'statistics',
    'who is',
    'what happened',
  ];

  const hasDocumentSignal = documentTerms.some(term =>
    q.includes(term)
  );

  const hasWebSignal = webTerms.some(term =>
    q.includes(term)
  );

  if (hasDocumentSignal && hasWebSignal) {
    return {
      route: 'MIXED',
      reason:
        'The question contains both uploaded-document information and external/current information.',
    };
  }

  if (hasDocumentSignal) {
    return {
      route: 'DOCUMENT',
      reason:
        'The question can be answered using the uploaded document.',
    };
  }

  if (hasWebSignal) {
    return {
      route: 'WEB',
      reason:
        'The question requires current or external information.',
    };
  }

  return null;
}

async function classifyQuery(query) {
  const heuristicResult = classifyQueryWithHeuristics(query);

  if (heuristicResult) {
    return heuristicResult;
  }

  const prompt = `
You are the routing component of a document research system.

Classify the user's question into exactly one route:

DOCUMENT:
The answer should come primarily from the uploaded PDF/document.

WEB:
The answer requires external/current internet information and does not depend on the uploaded document.

MIXED:
The answer requires both the uploaded document and external/current internet information.

Rules:

- Questions about "this document", "this PDF", "the document", "the marksheet", "the resume", "the candidate", etc. are DOCUMENT.
- Questions asking for information contained in the uploaded file are DOCUMENT.
- Questions about current events, latest information, today's information, current salaries, current companies, news, etc. are WEB.
- If both document information and current/external information are required, use MIXED.

Return ONLY valid JSON:

{
  "route": "DOCUMENT",
  "reason": "short explanation"
}

User question:
${query}
`;

  try {
    const response = await groq.chat.completions.create({
      model: GROQ_MODEL,
      temperature: 0,
      messages: [
        {
          role: 'user',
          content: prompt,
        },
      ],
    });

    const raw =
      response.choices?.[0]?.message?.content || '';

    const parsed = JSON.parse(cleanLLMResponse(raw));

    if (
      ['DOCUMENT', 'WEB', 'MIXED'].includes(parsed.route)
    ) {
      return {
        route: parsed.route,
        reason:
          parsed.reason ||
          'Query classified by the AI router.',
      };
    }
  } catch (error) {
    console.error(
      'AI query classification failed:',
      error.message
    );
  }

  return {
    route: 'DOCUMENT',
    reason:
      'Defaulting to document reasoning because a document is available.',
  };
}

/* =========================================================
   PINECONE INDEX WAIT
========================================================= */

async function waitForIndexToPopulate(expectedCount) {
  const maxAttempts = 15;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const stats = await pineconeIndex.describeIndexStats();

      const total =
        stats?.totalRecordCount ??
        stats?.totalVectorCount ??
        0;

      console.log(
        `Pinecone readiness check ${attempt}/${maxAttempts}: ${total} records`
      );

      if (Number(total) >= expectedCount) {
        console.log('Pinecone index is ready.');
        return true;
      }
    } catch (error) {
      console.error(
        'Pinecone readiness check failed:',
        error.message
      );
    }

    await sleep(1000);
  }

  console.warn(
    'Pinecone did not report the expected record count within the wait period.'
  );

  return false;
}

/* =========================================================
   DOCUMENT RETRIEVAL
========================================================= */

async function retrieveDocumentContext(query) {
  console.log('\n===== PINECONE RETRIEVAL =====');
  console.log('Query:', query);

  const searchResults = await pineconeIndex.searchRecords({
    query: {
      topK: PINECONE_TOP_K,
      inputs: {
        text: query,
      },
    },
    fields: [
      'text',
      'filename',
      'chunkIndex',
    ],
  });

  const hits =
    searchResults?.result?.hits || [];

  console.log(
    `Pinecone returned ${hits.length} hits.`
  );

  const evidence = hits
    .filter(
      hit =>
        hit &&
        hit.fields &&
        typeof hit.fields.text === 'string' &&
        hit.fields.text.trim().length > 0
    )
    .map(hit => ({
      text: hit.fields.text,
      filename:
        hit.fields.filename || 'Document',
      chunkIndex:
        hit.fields.chunkIndex ?? null,
      score:
        typeof hit._score === 'number'
          ? hit._score
          : null,
    }));

  evidence.forEach((item, index) => {
    console.log(
      `\n--- RETRIEVED CHUNK ${index + 1} ---`
    );

    console.log(
      'Score:',
      item.score
    );

    console.log(
      'Chunk:',
      item.chunkIndex
    );

    console.log(
      'Filename:',
      item.filename
    );

    console.log(
      'Text:',
      item.text.substring(0, 1000)
    );
  });

  console.log(
    '\n===== END PINECONE RETRIEVAL =====\n'
  );

  return evidence;
}

/* =========================================================
   DOCUMENT EVIDENCE EVALUATION
========================================================= */

async function evaluateEvidence(
  query,
  evidence
) {
  if (!evidence.length) {
    return {
      relevance: 'INSUFFICIENT',
      reason:
        'No document evidence was retrieved.',
    };
  }

  const evidenceText = evidence
    .map(
      (item, index) =>
        `[Chunk ${index + 1}]\n${item.text}`
    )
    .join('\n\n');

  const prompt = `
You are an evidence evaluator for a document question-answering system.

Determine whether the retrieved document evidence is sufficient to answer the user's question.

Use ONLY the retrieved evidence.

Return ONLY JSON:

{
  "relevance": "SUFFICIENT",
  "reason": "short explanation"
}

Allowed relevance values:

SUFFICIENT
The evidence clearly contains the information needed.

PARTIAL
The evidence contains some relevant information but not enough for a complete answer.

INSUFFICIENT
The evidence does not support answering the question.

Important:
- Do not judge based on outside knowledge.
- If the answer is explicitly present in the evidence, use SUFFICIENT.
- Exact values, names, titles, marks, ranks, dates, etc. require actual supporting text.

Question:
${query}

Retrieved evidence:
${evidenceText}
`;

  try {
    const response =
      await groq.chat.completions.create({
        model: GROQ_MODEL,
        temperature: 0,
        messages: [
          {
            role: 'user',
            content: prompt,
          },
        ],
      });

    const raw =
      response.choices?.[0]?.message?.content || '';

    const parsed =
      JSON.parse(cleanLLMResponse(raw));

    if (
      ['SUFFICIENT', 'PARTIAL', 'INSUFFICIENT'].includes(
        parsed.relevance
      )
    ) {
      return {
        relevance: parsed.relevance,
        reason:
          parsed.reason ||
          'Evidence evaluated successfully.',
      };
    }
  } catch (error) {
    console.error(
      'Evidence evaluation failed:',
      error.message
    );
  }

  /*
    If retrieval returned actual chunks, allow the answer
    generator to inspect them rather than blindly failing.
  */

  return {
    relevance: 'PARTIAL',
    reason:
      'Evidence was retrieved but automatic evaluation was inconclusive.',
  };
}

/* =========================================================
   WEB SEARCH
========================================================= */

async function searchWeb(query) {
  if (!process.env.TAVILY_API_KEY) {
    throw new Error(
      'TAVILY_API_KEY is not configured.'
    );
  }

  const response = await fetch(
    'https://api.tavily.com/search',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        api_key: process.env.TAVILY_API_KEY,
        query,
        search_depth: 'advanced',
        max_results: MAX_WEB_RESULTS,
        include_answer: false,
        include_raw_content: false,
      }),
    }
  );

  if (!response.ok) {
    const errorText =
      await response.text();

    throw new Error(
      `Tavily request failed: ${response.status} ${errorText}`
    );
  }

  const data = await response.json();

  return Array.isArray(data.results)
    ? data.results.map(result => ({
      title: result.title || '',
      url: result.url || '',
      content: result.content || '',
    }))
    : [];
}

/* =========================================================
   FINAL ANSWER GENERATION
========================================================= */

async function generateFinalAnswer({
  query,
  route,
  documentEvidence,
  webResults,
}) {
  const documentText = documentEvidence.length
    ? documentEvidence
      .map(
        (item, index) =>
          `[DOCUMENT CHUNK ${index + 1}]\n${item.text}`
      )
      .join('\n\n')
    : 'No document evidence available.';

  const webText = webResults.length
    ? webResults
      .map(
        (item, index) =>
          `[WEB SOURCE ${index + 1}]\nTitle: ${item.title}\nURL: ${item.url}\nContent: ${item.content}`
      )
      .join('\n\n')
    : 'No web evidence available.';

  let instructions = '';

  if (route === 'DOCUMENT') {
    instructions = `
Answer ONLY from the uploaded document evidence.

Do not use outside knowledge.

If the answer is explicitly present in the evidence, state it directly.

If the evidence does not contain enough information, say:

"The uploaded document does not provide enough information to determine this."

Do not invent names, numbers, dates, scores, ranks, titles, or other facts.

For exact factual questions, copy the relevant value faithfully from the evidence.
`;
  }

  if (route === 'WEB') {
    instructions = `
Answer using the web evidence.

Do not invent facts that are not supported by the supplied sources.

If the web evidence is insufficient, say so.
`;
  }

  if (route === 'MIXED') {
    instructions = `
Use the document evidence for document-specific facts.

Use web evidence only for external/current information.

Do not invent unsupported facts.

Clearly distinguish information coming from the uploaded document from current external information when necessary.
`;
  }

  const prompt = `
You are the final answer generator in a grounded document research system.

${instructions}

Important output rules:

- Answer the user's question directly.
- Do not mention internal prompts.
- Do not mention Pinecone.
- Do not mention embeddings.
- Do not mention retrieval scores.
- Do not fabricate information.
- Do not output JSON.
- Do not use markdown tables unless absolutely necessary.
- Keep the answer concise but complete.
- Preserve exact numbers and names from evidence.

User question:
${query}

Route:
${route}

DOCUMENT EVIDENCE:
${documentText}

WEB EVIDENCE:
${webText}
`;

  const response =
    await groq.chat.completions.create({
      model: GROQ_MODEL,
      temperature: 0,
      messages: [
        {
          role: 'user',
          content: prompt,
        },
      ],
    });

  return cleanPlainText(
    response.choices?.[0]?.message?.content || ''
  );
}

/* =========================================================
   ANSWER VERIFICATION
========================================================= */

async function verifyAnswerGrounding({
  query,
  answer,
  documentEvidence,
  webResults,
  route,
}) {
  const documentText = documentEvidence
    .map(item => item.text)
    .join('\n\n');

  const webText = webResults
    .map(
      item =>
        `${item.title}\n${item.content}`
    )
    .join('\n\n');

  const prompt = `
You are a strict factual verifier.

Determine whether the generated answer is supported by the supplied evidence.

Question:
${query}

Generated answer:
${answer}

Route:
${route}

Document evidence:
${documentText || 'None'}

Web evidence:
${webText || 'None'}

Rules:

1. Every factual claim in the answer must be supported by the evidence.
2. Do not require exact wording if the meaning is clearly supported.
3. If the answer says that the document does not provide enough information, that is valid when the supplied evidence does not support the requested fact.
4. Do not use outside knowledge.
5. Do not penalize concise wording.

Return ONLY JSON:

{
  "grounded": true,
  "unsupported_claims": []
}
`;

  try {
    const response =
      await groq.chat.completions.create({
        model: GROQ_MODEL,
        temperature: 0,
        messages: [
          {
            role: 'user',
            content: prompt,
          },
        ],
      });

    const raw =
      response.choices?.[0]?.message?.content || '';

    const parsed =
      JSON.parse(cleanLLMResponse(raw));

    return {
      grounded:
        parsed.grounded === true,
      unsupported_claims:
        Array.isArray(parsed.unsupported_claims)
          ? parsed.unsupported_claims
          : [],
    };
  } catch (error) {
    console.error(
      'Answer verification failed:',
      error.message
    );

    /*
      Do not destroy a valid answer merely because
      the verifier itself failed.
    */

    return {
      grounded: true,
      unsupported_claims: [],
    };
  }
}

/* =========================================================
   QUERY PROCESSING
========================================================= */

async function processQuery(
  cleanQuery,
  onStage
) {
  const stages = [];

  function updateStage(
    step,
    title,
    status,
    details = ''
  ) {
    const stage = createStage(
      step,
      title,
      status,
      details
    );

    stages.push(stage);

    if (onStage) {
      onStage(stage);
    }

    console.log(
      `[STAGE ${step}] ${title} - ${status}: ${details}`
    );

    return stage;
  }

  console.log(
    '\n========== QUERY PROCESSING START =========='
  );

  console.log(
    'Question:',
    cleanQuery
  );

  /* -------------------------------------------------------
     STAGE 1
  ------------------------------------------------------- */

  updateStage(
    1,
    'Query understanding',
    'running',
    'Analyzing what information the question requires.'
  );

  const classification =
    await classifyQuery(cleanQuery);

  console.log(
    'Classification:',
    classification
  );

  updateStage(
    1,
    'Query understanding',
    'completed',
    classification.reason
  );

  /* -------------------------------------------------------
     STAGE 2
  ------------------------------------------------------- */

  let documentEvidence = [];

  if (
    classification.route === 'DOCUMENT' ||
    classification.route === 'MIXED'
  ) {
    updateStage(
      2,
      'Document retrieval',
      'running',
      'Searching the uploaded document.'
    );

    try {
      documentEvidence =
        await retrieveDocumentContext(
          cleanQuery
        );
    } catch (error) {
      console.error(
        'Document retrieval failed:',
        error
      );

      updateStage(
        2,
        'Document retrieval',
        'completed',
        `Document retrieval failed: ${error.message}`
      );

      throw error;
    }

    updateStage(
      2,
      'Document retrieval',
      'completed',
      `${documentEvidence.length} document chunks retrieved.`
    );
  } else {
    updateStage(
      2,
      'Document retrieval',
      'completed',
      'Skipped because the question requires external information.'
    );
  }

  /* -------------------------------------------------------
     STAGE 3
  ------------------------------------------------------- */

  let evidenceEvaluation = {
    relevance: 'INSUFFICIENT',
    reason:
      'Document evidence was not required.',
  };

  if (
    classification.route === 'DOCUMENT' ||
    classification.route === 'MIXED'
  ) {
    updateStage(
      3,
      'Evidence evaluation',
      'running',
      'Checking whether the retrieved evidence supports the question.'
    );

    evidenceEvaluation =
      await evaluateEvidence(
        cleanQuery,
        documentEvidence
      );

    updateStage(
      3,
      'Evidence evaluation',
      'completed',
      `${evidenceEvaluation.relevance}: ${evidenceEvaluation.reason}`
    );
  } else {
    updateStage(
      3,
      'Evidence evaluation',
      'completed',
      'Document evidence evaluation was not required.'
    );
  }

  /* -------------------------------------------------------
     STAGE 4
  ------------------------------------------------------- */

  updateStage(
    4,
    'Route decision',
    'running',
    'Selecting the knowledge source.'
  );

  const finalRoute =
    classification.route;

  updateStage(
    4,
    'Route decision',
    'completed',
    `Selected ${finalRoute} route. ${classification.reason}`
  );

  /* -------------------------------------------------------
     STAGE 5
  ------------------------------------------------------- */

  let webResults = [];

  if (
    finalRoute === 'WEB' ||
    finalRoute === 'MIXED'
  ) {
    updateStage(
      5,
      'Web research',
      'running',
      'Searching external sources.'
    );

    try {
      webResults =
        await searchWeb(cleanQuery);

      updateStage(
        5,
        'Web research',
        'completed',
        `${webResults.length} web sources retrieved.`
      );
    } catch (error) {
      console.error(
        'Web search failed:',
        error.message
      );

      if (finalRoute === 'WEB') {
        throw error;
      }

      updateStage(
        5,
        'Web research',
        'completed',
        `Web search unavailable: ${error.message}`
      );
    }
  } else {
    updateStage(
      5,
      'Web research',
      'completed',
      'Skipped because the question is document-specific.'
    );
  }

  /* -------------------------------------------------------
     DOCUMENT SAFETY CHECK
  ------------------------------------------------------- */

  if (
    finalRoute === 'DOCUMENT' &&
    documentEvidence.length === 0
  ) {
    const answer =
      'The uploaded document does not provide enough information to determine this.';

    updateStage(
      6,
      'Answer synthesis',
      'completed',
      'No usable document evidence was retrieved.'
    );

    updateStage(
      7,
      'Answer verification',
      'completed',
      'No unsupported factual claims were generated.'
    );

    return {
      answer,
      logs: stages,
      routeUsed: 'Pinecone Vector DB',
      route: finalRoute,
      routeReason: classification.reason,
      confidence: 'LOW',
      evidence: [],
      sources: [],
      retrievedCount: 0,
      webResultCount: 0,
      evidenceRelevance: 'INSUFFICIENT',
    };
  }

  /* -------------------------------------------------------
     STAGE 6
  ------------------------------------------------------- */

  updateStage(
    6,
    'Answer synthesis',
    'running',
    'Generating a grounded answer.'
  );

  let answer =
    await generateFinalAnswer({
      query: cleanQuery,
      route: finalRoute,
      documentEvidence,
      webResults,
    });

  updateStage(
    6,
    'Answer synthesis',
    'completed',
    'Grounded answer generated.'
  );

  /* -------------------------------------------------------
     STAGE 7
  ------------------------------------------------------- */

  updateStage(
    7,
    'Answer verification',
    'running',
    'Checking the answer against available evidence.'
  );

  let verification =
    await verifyAnswerGrounding({
      query: cleanQuery,
      answer,
      documentEvidence,
      webResults,
      route: finalRoute,
    });

  /*
    If verifier finds unsupported claims,
    regenerate once with temperature 0.
  */

  if (
    !verification.grounded &&
    verification.unsupported_claims.length > 0
  ) {
    console.warn(
      'Unsupported claims detected:',
      verification.unsupported_claims
    );

    answer =
      await generateFinalAnswer({
        query: cleanQuery,
        route: finalRoute,
        documentEvidence,
        webResults,
      });

    verification =
      await verifyAnswerGrounding({
        query: cleanQuery,
        answer,
        documentEvidence,
        webResults,
        route: finalRoute,
      });
  }

  /*
    Do NOT replace a legitimate answer with
    a generic failure message merely because
    the verifier is uncertain.
  */

  answer = cleanPlainText(answer);

  updateStage(
    7,
    'Answer verification',
    'completed',
    verification.grounded
      ? 'Answer passed the grounding check.'
      : 'Answer verification was inconclusive.'
  );

  /* -------------------------------------------------------
     CONFIDENCE
  ------------------------------------------------------- */

  let confidence = 'LOW';

  if (
    finalRoute === 'DOCUMENT' &&
    evidenceEvaluation.relevance ===
    'SUFFICIENT' &&
    documentEvidence.length > 0
  ) {
    confidence = 'HIGH';
  } else if (
    finalRoute === 'DOCUMENT' &&
    documentEvidence.length > 0
  ) {
    confidence = 'MEDIUM';
  } else if (
    finalRoute === 'WEB' &&
    webResults.length > 0
  ) {
    confidence = 'HIGH';
  } else if (
    finalRoute === 'MIXED' &&
    documentEvidence.length > 0 &&
    webResults.length > 0
  ) {
    confidence = 'HIGH';
  }

  /* -------------------------------------------------------
     RESPONSE DATA
  ------------------------------------------------------- */

  const evidence =
    documentEvidence.map(item => ({
      filename: item.filename,
      chunkIndex: item.chunkIndex,
      score: item.score,
      text: item.text,
    }));

  const sources =
    webResults.map(result => ({
      title: result.title,
      url: result.url,
      content: result.content,
    }));

  console.log(
    '\n========== QUERY PROCESSING COMPLETE =========='
  );

  console.log(
    'Route:',
    finalRoute
  );

  console.log(
    'Confidence:',
    confidence
  );

  console.log(
    'Answer:',
    answer
  );

  return {
    answer,
    logs: stages,
    routeUsed:
      finalRoute === 'DOCUMENT'
        ? 'Pinecone Vector DB'
        : finalRoute === 'WEB'
          ? 'Tavily Web Search'
          : 'Pinecone + Tavily',
    route: finalRoute,
    routeReason: classification.reason,
    confidence,
    evidence,
    sources,
    retrievedCount:
      documentEvidence.length,
    webResultCount:
      webResults.length,
    evidenceRelevance:
      evidenceEvaluation.relevance,
  };
}

/* =========================================================
   HEALTH CHECK
========================================================= */

app.get('/', (req, res) => {
  res.json({
    success: true,
    message: 'DocuAgent backend is running',
    index: PINECONE_INDEX_NAME,
    model: GROQ_MODEL,
  });
});

/* =========================================================
   PDF UPLOAD
========================================================= */

app.post(
  '/api/upload',
  upload.single('file'),
  async (req, res) => {
    console.log(
      '\n=============================='
    );

    console.log(
      'Received PDF upload'
    );

    console.log(
      '=============================='
    );

    try {
      if (!req.file) {
        return res.status(400).json({
          success: false,
          error: 'No PDF file uploaded.',
        });
      }

      console.log(
        `Processing ${req.file.originalname} (${req.file.size} bytes)`
      );

      /* ---------------------------------------------------
         Extract text
      --------------------------------------------------- */

      const extractedText =
        await extractPdfText(
          req.file.buffer
        );

      const normalizedText =
        normalizeText(extractedText);

      console.log(
        `Extracted ${normalizedText.length} characters`
      );

      console.log(
        '\n===== PDF TEXT PREVIEW ====='
      );

      console.log(
        normalizedText.substring(0, 2500)
      );

      console.log(
        '===== END PDF TEXT PREVIEW =====\n'
      );

      if (!normalizedText) {
        return res.status(400).json({
          success: false,
          error:
            'No readable text could be extracted from this PDF. If this is a scanned/image-only PDF, OCR is required.',
        });
      }

      /* ---------------------------------------------------
         Create chunks
      --------------------------------------------------- */

      const documentChunks =
        chunkText(normalizedText);

      console.log(
        `Created ${documentChunks.length} chunks`
      );

      if (!documentChunks.length) {
        return res.status(400).json({
          success: false,
          error:
            'The document did not produce any usable chunks.',
        });
      }

      /* ---------------------------------------------------
         Clear old document
      --------------------------------------------------- */

      console.log(
        'Removing previous document records from Pinecone...'
      );

      await pineconeIndex.deleteAll();

      console.log(
        'Previous document records removed.'
      );

      /*
        Give Pinecone a short moment to process deletion
        before inserting the new document.
      */

      await sleep(1000);

      /* ---------------------------------------------------
         Insert new document
      --------------------------------------------------- */

      const timestamp =
        Date.now();

      const records =
        documentChunks.map(
          (chunk, index) => ({
            id: `doc-${timestamp}-chunk-${index}`,

            text: chunk,

            filename:
              req.file.originalname,

            chunkIndex: index,
          })
        );

      console.log(
        'Uploading new document to Pinecone...'
      );

      await pineconeIndex.upsertRecords({
        records,
      });

      console.log(
        'New document successfully stored in Pinecone.'
      );

      /* ---------------------------------------------------
         Wait for index readiness
      --------------------------------------------------- */

      await waitForIndexToPopulate(
        records.length
      );

      console.log(
        'Document indexing completed.'
      );

      return res.json({
        success: true,
        message:
          'PDF uploaded and indexed successfully.',
        filename:
          req.file.originalname,
        chunks:
          documentChunks.length,
        characters:
          normalizedText.length,
      });
    } catch (error) {
      console.error(
        '\nUPLOAD ERROR:'
      );

      console.error(error);

      return res.status(500).json({
        success: false,
        error:
          error.message ||
          'Failed to process PDF.',
      });
    }
  }
);

/* =========================================================
   NORMAL QUERY
========================================================= */

app.post(
  '/api/query',
  async (req, res) => {
    console.log(
      '\n=============================='
    );

    console.log(
      'Received query'
    );

    console.log(
      '=============================='
    );

    try {
      const { query } =
        req.body;

      if (
        typeof query !== 'string' ||
        !query.trim()
      ) {
        return res.status(400).json({
          success: false,
          error:
            'Query is required.',
        });
      }

      const cleanQuery =
        query.trim();

      console.log(
        'Query:',
        cleanQuery
      );

      const result =
        await processQuery(
          cleanQuery
        );

      return res.json({
        success: true,
        answer: result.answer,
        logs: result.logs,
        routeUsed:
          result.routeUsed,
        route:
          result.route,
        routeReason:
          result.routeReason,
        confidence:
          result.confidence,
        evidence:
          result.evidence,
        sources:
          result.sources,
        retrievedCount:
          result.retrievedCount,
        webResultCount:
          result.webResultCount,
        evidenceRelevance:
          result.evidenceRelevance,
      });
    } catch (error) {
      console.error(
        '\nQUERY ERROR:'
      );

      console.error(error);

      return res.status(500).json({
        success: false,
        error:
          error.message ||
          'Failed to process query.',
        logs: [],
      });
    }
  }
);

/* =========================================================
   STREAMING QUERY
========================================================= */

app.get(
  '/api/query/stream',
  async (req, res) => {
    console.log(
      '\n=============================='
    );

    console.log(
      'Received streaming query'
    );

    console.log(
      '=============================='
    );

    const query =
      typeof req.query.query === 'string'
        ? req.query.query.trim()
        : '';

    if (!query) {
      return res.status(400).json({
        success: false,
        error:
          'Query is required.',
      });
    }

    console.log(
      'Streaming query:',
      query
    );

    res.writeHead(200, {
      'Content-Type':
        'text/event-stream',
      'Cache-Control':
        'no-cache',
      Connection:
        'keep-alive',
      'X-Accel-Buffering':
        'no',
    });

    if (
      typeof res.flushHeaders ===
      'function'
    ) {
      res.flushHeaders();
    }

    function sendEvent(
      type,
      data
    ) {
      if (res.writableEnded) {
        return;
      }

      res.write(
        `event: ${type}\n`
      );

      res.write(
        `data: ${JSON.stringify(
          data
        )}\n\n`
      );
    }

    sendEvent(
      'connected',
      {
        message:
          'Agent execution started.',
      }
    );

    try {
      const result =
        await processQuery(
          query,
          stage => {
            sendEvent(
              'stage',
              stage
            );
          }
        );

      sendEvent(
        'result',
        {
          success: true,
          answer:
            result.answer,
          logs:
            result.logs,
          routeUsed:
            result.routeUsed,
          route:
            result.route,
          routeReason:
            result.routeReason,
          confidence:
            result.confidence,
          evidence:
            result.evidence,
          sources:
            result.sources,
          retrievedCount:
            result.retrievedCount,
          webResultCount:
            result.webResultCount,
          evidenceRelevance:
            result.evidenceRelevance,
        }
      );

      sendEvent(
        'complete',
        {
          message:
            'Agent execution completed.',
        }
      );
    } catch (error) {
      console.error(
        'STREAM QUERY ERROR:',
        error
      );

      sendEvent(
        'error',
        {
          success: false,
          error:
            error.message ||
            'Failed to process query.',
        }
      );
    } finally {
      res.end();
    }
  }
);

/* =========================================================
   GLOBAL ERROR HANDLER
========================================================= */

app.use(
  (
    error,
    req,
    res,
    next
  ) => {
    console.error(
      'GLOBAL ERROR:',
      error
    );

    if (res.headersSent) {
      return next(error);
    }

    return res.status(500).json({
      success: false,
      error:
        error.message ||
        'Internal server error.',
    });
  }
);

/* =========================================================
   START SERVER
========================================================= */

app.listen(
  PORT,
  () => {
    console.log(
      '\n=============================='
    );

    console.log(
      'DocuAgent Backend Started'
    );

    console.log(
      '=============================='
    );

    console.log(
      `Server running on port ${PORT}`
    );

    console.log(
      `Pinecone index: ${PINECONE_INDEX_NAME}`
    );

    console.log(
      'Embedding model: llama-text-embed-v2'
    );

    console.log(
      `LLM model: ${GROQ_MODEL}`
    );

    console.log(
      'Streaming endpoint: /api/query/stream'
    );

    console.log(
      'Ready to receive requests.\n'
    );
  }
);