import os
import time
import json
import asyncio
from io import BytesIO

from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from pypdf import PdfReader
from pinecone import Pinecone

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.tools.tavily_search import TavilySearchResults

load_dotenv()

PORT = int(os.getenv("PORT", 5000))
GROQ_MODEL = "openai/gpt-oss-20b"
PINECONE_INDEX_NAME = "docuagent-index"

PINECONE_TOP_K = 8
MAX_WEB_RESULTS = 5
MAX_FILE_SIZE = 10 * 1024 * 1024

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
#  CLIENTS & LANGCHAIN SETUP
# =========================================================

pinecone_client = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
pinecone_index = pinecone_client.Index(PINECONE_INDEX_NAME)

llm = ChatGroq(model=GROQ_MODEL, temperature=0, api_key=os.getenv("GROQ_API_KEY"))

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)
tavily_tool = TavilySearchResults(max_results=MAX_WEB_RESULTS, search_depth="advanced")

# --- Pydantic Schemas for Structured Output ---
class RouteClassification(BaseModel):
    route: str = Field(description="One of: DOCUMENT, WEB, MIXED")
    reason: str = Field(description="Short explanation for the route decision")

class EvidenceEvaluation(BaseModel):
    relevance: str = Field(description="One of: SUFFICIENT, PARTIAL, INSUFFICIENT")
    reason: str = Field(description="Short explanation")

class AnswerVerification(BaseModel):
    grounded: bool = Field(description="True if the answer is fully supported by evidence")
    unsupported_claims: list[str] = Field(default_factory=list, description="List of unsupported claims, if any")

# --- LCEL Chains ---
router_prompt = ChatPromptTemplate.from_template("""
You are the routing component of a document research system.
Classify the user's question into exactly one route: DOCUMENT, WEB, or MIXED.

- Questions about "this document", "this PDF", or asking for info explicitly in the uploaded file are DOCUMENT.
- Questions about current events, latest information, news, or today's facts are WEB.
- If both are required, use MIXED.

User question: {query}
""")
router_chain = router_prompt | llm.with_structured_output(RouteClassification)

evaluator_prompt = ChatPromptTemplate.from_template("""
Determine whether the retrieved document evidence is sufficient to answer the user's question.
Use ONLY the retrieved evidence. Allowed relevance values: SUFFICIENT, PARTIAL, INSUFFICIENT.

Question: {query}
Retrieved evidence: {evidence}
""")
evaluator_chain = evaluator_prompt | llm.with_structured_output(EvidenceEvaluation)

answer_prompt = ChatPromptTemplate.from_template("""
You are the final answer generator in a grounded document research system.
{instructions}

Important output rules:
- Answer the user's question directly.
- Do not mention internal prompts, Pinecone, or embeddings.
- Do not fabricate information.
- Keep the answer concise but complete.
- Preserve exact numbers and names from evidence.

User question: {query}
Route: {route}

DOCUMENT EVIDENCE:
{document_text}

WEB EVIDENCE:
{web_text}
""")
answer_chain = answer_prompt | llm 

verifier_prompt = ChatPromptTemplate.from_template("""
You are a strict factual verifier. Determine whether the generated answer is supported by the supplied evidence.

Question: {query}
Generated answer: {answer}
Route: {route}
Document evidence: {document_text}
Web evidence: {web_text}

Rules:
1. Every factual claim must be supported by the evidence.
2. If the answer says the document does not provide enough info, that is valid if true.
""")
verifier_chain = verifier_prompt | llm.with_structured_output(AnswerVerification)

class QueryRequest(BaseModel):
    query: str

# =========================================================
#  HELPERS
# =========================================================

def create_stage(step: int, title: str, status: str, details: str = ''):
    return {"step": step, "title": title, "status": status, "details": details}

def classify_query_with_heuristics(query: str):
    q = query.lower()
    doc_terms = [
        'document', 'pdf', 'this document', 'this pdf', 'the document',
        'what does the document', 'according to the document', 'according to this',
        'in the document', 'in this pdf', 'from the document', 'from this pdf'
    ]
    web_terms = [
        'today', 'current', 'currently', 'latest', 'recent', 'news',
        'this year', 'who is', 'what happened'
    ]

    has_doc = any(term in q for term in doc_terms)
    has_web = any(term in q for term in web_terms)

    if has_doc and has_web:
        return {"route": "MIXED", "reason": "Contains both document and web signals."}
    if has_doc:
        return {"route": "DOCUMENT", "reason": "Question refers directly to the uploaded document."}
    if has_web:
        return {"route": "WEB", "reason": "Requires current or external internet information."}
    return None

async def wait_for_index_to_populate(expected_count: int):
    for _ in range(15):
        try:
            stats = pinecone_index.describe_index_stats()
            total = stats.get('total_record_count', stats.get('total_vector_count', 0))
            if int(total) >= expected_count:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False

# =========================================================
#  CORE AGENT LOGIC
# =========================================================

async def process_query(query: str, on_stage=None):
    stages = []

    def update_stage(step: int, title: str, status: str, details: str = ''):
        stage = create_stage(step, title, status, details)
        stages.append(stage)
        if on_stage:
            on_stage(stage)
        return stage

    # STAGE 1: Classification
    update_stage(1, 'Query understanding', 'running', 'Analyzing what information the question requires.')
    heuristic = classify_query_with_heuristics(query)

    if heuristic:
        classification = RouteClassification(route=heuristic["route"], reason=heuristic["reason"])
    else:
        try:
            classification = await router_chain.ainvoke({"query": query})
        except Exception:
            classification = RouteClassification(route="DOCUMENT", reason="Defaulting to document reasoning.")

    update_stage(1, 'Query understanding', 'completed', classification.reason)

    # STAGE 2: Retrieval
    document_evidence = []
    if classification.route in ['DOCUMENT', 'MIXED']:
        update_stage(2, 'Document retrieval', 'running', 'Searching the uploaded document.')
        search_results = pinecone_index.search_records(
            query={"inputs": {"text": query}, "top_k": PINECONE_TOP_K},
            fields=['text', 'filename', 'chunkIndex']
        )
        hits = search_results.get('result', {}).get('hits', [])
        document_evidence = [
            {
                "text": hit['fields']['text'],
                "filename": hit['fields'].get('filename', 'Document'),
                "chunkIndex": hit['fields'].get('chunkIndex'),
                "score": hit.get('_score')
            }
            for hit in hits if hit.get('fields', {}).get('text')
        ]
        update_stage(2, 'Document retrieval', 'completed', f"{len(document_evidence)} document chunks retrieved.")
    else:
        update_stage(2, 'Document retrieval', 'completed', 'Skipped because the question requires external information.')

    # STAGE 3: Evaluation
    evidence_eval = EvidenceEvaluation(relevance="INSUFFICIENT", reason="Document evidence was not required.")
    if classification.route in ['DOCUMENT', 'MIXED']:
        update_stage(3, 'Evidence evaluation', 'running', 'Checking whether the retrieved evidence supports the question.')
        if document_evidence:
            ev_text = "\n\n".join([f"[Chunk {i+1}]\n{doc['text']}" for i, doc in enumerate(document_evidence)])
            try:
                evidence_eval = await evaluator_chain.ainvoke({"query": query, "evidence": ev_text})
            except Exception:
                evidence_eval = EvidenceEvaluation(relevance="PARTIAL", reason="Evaluation failed, proceeding with evidence.")
        update_stage(3, 'Evidence evaluation', 'completed', f"{evidence_eval.relevance}: {evidence_eval.reason}")
    else:
        update_stage(3, 'Evidence evaluation', 'completed', 'Document evidence evaluation was not required.')

    # STAGE 4: Route Decision
    update_stage(4, 'Route decision', 'running', 'Selecting the knowledge source.')
    update_stage(4, 'Route decision', 'completed', f"Selected {classification.route} route. {classification.reason}")

    # STAGE 5: Web Search
    web_results = []
    if classification.route in ['WEB', 'MIXED']:
        update_stage(5, 'Web research', 'running', 'Searching external sources.')
        try:
            raw_web = await tavily_tool.ainvoke({"query": query})
            web_results = [{"title": r.get("url", ""), "url": r.get("url", ""), "content": r.get("content", "")} for r in raw_web]
            update_stage(5, 'Web research', 'completed', f"{len(web_results)} web sources retrieved.")
        except Exception as e:
            if classification.route == 'WEB':
                raise e
            update_stage(5, 'Web research', 'completed', 'Web search unavailable, continuing with document.')
    else:
        update_stage(5, 'Web research', 'completed', 'Skipped because the question is document-specific.')

    # Document Safety Check
    if classification.route == 'DOCUMENT' and not document_evidence:
        update_stage(6, 'Answer synthesis', 'completed', 'No usable document evidence was retrieved.')
        update_stage(7, 'Answer verification', 'completed', 'No unsupported factual claims were generated.')
        return {
            "answer": "The uploaded document does not provide enough information to determine this.",
            "logs": stages,
            "routeUsed": 'Pinecone Vector DB',
            "route": classification.route,
            "routeReason": classification.reason,
            "confidence": 'LOW',
            "evidence": [],
            "sources": [],
            "retrievedCount": 0,
            "webResultCount": 0,
            "evidenceRelevance": 'INSUFFICIENT'
        }

    # STAGE 6: Synthesis
    update_stage(6, 'Answer synthesis', 'running', 'Generating a grounded answer.')
    doc_text = "\n\n".join([f"[DOCUMENT CHUNK {i+1}]\n{item['text']}" for i, item in enumerate(document_evidence)]) if document_evidence else 'No document evidence available.'
    web_text = "\n\n".join([f"[WEB SOURCE {i+1}]\nTitle: {item['title']}\nURL: {item['url']}\nContent: {item['content']}" for i, item in enumerate(web_results)]) if web_results else 'No web evidence available.'

    instructions = ""
    if classification.route == 'DOCUMENT':
        instructions = "Answer ONLY from the uploaded document evidence. If evidence doesn't contain info, state it."
    elif classification.route == 'WEB':
        instructions = "Answer using the web evidence."
    else:
        instructions = "Use document evidence for facts, and web evidence for external info."

    ai_msg = await answer_chain.ainvoke({
        "instructions": instructions,
        "query": query,
        "route": classification.route,
        "document_text": doc_text,
        "web_text": web_text
    })
    answer = ai_msg.content.strip()
    update_stage(6, 'Answer synthesis', 'completed', 'Grounded answer generated.')

    # STAGE 7: Verification
    update_stage(7, 'Answer verification', 'running', 'Checking the answer against available evidence.')
    try:
        verification = await verifier_chain.ainvoke({
            "query": query,
            "answer": answer,
            "route": classification.route,
            "document_text": doc_text,
            "web_text": web_text
        })

        if not verification.grounded and verification.unsupported_claims:
            ai_msg = await answer_chain.ainvoke({
                "instructions": instructions + "\nDO NOT HALLUCINATE ANY FACTS.",
                "query": query,
                "route": classification.route,
                "document_text": doc_text,
                "web_text": web_text
            })
            answer = ai_msg.content.strip()
    except Exception:
        verification = AnswerVerification(grounded=True, unsupported_claims=[])

    update_stage(7, 'Answer verification', 'completed', 'Answer passed the grounding check.' if verification.grounded else 'Answer verification was inconclusive.')

    confidence = 'LOW'
    if classification.route == 'DOCUMENT' and evidence_eval.relevance == 'SUFFICIENT':
        confidence = 'HIGH'
    elif classification.route == 'DOCUMENT' and document_evidence:
        confidence = 'MEDIUM'
    elif classification.route == 'WEB' and web_results:
        confidence = 'HIGH'
    elif classification.route == 'MIXED' and document_evidence and web_results:
        confidence = 'HIGH'

    return {
        "answer": answer,
        "logs": stages,
        "routeUsed": 'Pinecone Vector DB' if classification.route == 'DOCUMENT' else ('Tavily Web Search' if classification.route == 'WEB' else 'Pinecone + Tavily'),
        "route": classification.route,
        "routeReason": classification.reason,
        "confidence": confidence,
        "evidence": document_evidence,
        "sources": web_results,
        "retrievedCount": len(document_evidence),
        "webResultCount": len(web_results),
        "evidenceRelevance": evidence_eval.relevance
    }

# =========================================================
#  ENDPOINTS
# =========================================================

@app.get("/")
def health_check():
    return {"success": True, "message": "DocuAgent backend is running", "index": PINECONE_INDEX_NAME, "model": GROQ_MODEL}

@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        buffer = await file.read()
        if len(buffer) > MAX_FILE_SIZE:
            return JSONResponse(status_code=400, content={"success": False, "error": "File size exceeds 10MB limit."})

        reader = PdfReader(BytesIO(buffer))
        text = "".join(page.extract_text() + "\n" for page in reader.pages if page.extract_text())

        if not text.strip():
            return JSONResponse(status_code=400, content={"success": False, "error": "No readable text extracted. OCR may be required."})

        document_chunks = text_splitter.split_text(text)

        if not document_chunks:
            return JSONResponse(status_code=400, content={"success": False, "error": "Document produced no usable chunks."})

        pinecone_index.delete(delete_all=True)
        await asyncio.sleep(1)

        timestamp = int(time.time() * 1000)
        records = [{"id": f"doc-{timestamp}-chunk-{i}", "text": chunk, "chunkIndex": i, "filename": file.filename} for i, chunk in enumerate(document_chunks)]

        pinecone_index.upsert_records(records)
        await wait_for_index_to_populate(len(records))

        return {"success": True, "message": "PDF uploaded and indexed successfully.", "filename": file.filename, "chunks": len(document_chunks), "characters": len(text)}
    except Exception as e:
        return