import os
import time
import json
import asyncio
import traceback
from io import BytesIO
from urllib.parse import urlparse

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
NAMESPACE = "docuagent-docs"  # used for upload, delete and search

PINECONE_TOP_K = 8
MAX_WEB_RESULTS = 5
MAX_FILE_SIZE = 10 * 1024 * 1024
UPSERT_BATCH_SIZE = 96  # Pinecone limit for integrated-embedding upserts
VALID_ROUTES = {"DOCUMENT", "WEB", "MIXED"}

app = FastAPI()

# =========================================================
#  CORS
# =========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://docuagent-frontend.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    # also allows Vercel preview deployments
    allow_origin_regex=r"https://.*\.vercel\.app",
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

try:
    tavily_tool = TavilySearchResults(max_results=MAX_WEB_RESULTS, search_depth="advanced")
except Exception as e:  # missing TAVILY_API_KEY should not crash the whole app
    print(f"[startup] Tavily unavailable: {e}")
    tavily_tool = None


# --- Pydantic schemas for structured output ---
class RouteClassification(BaseModel):
    route: str = Field(description="One of: DOCUMENT, WEB, MIXED")
    reason: str = Field(description="Short explanation for the route decision")


class EvidenceEvaluation(BaseModel):
    relevance: str = Field(description="One of: SUFFICIENT, PARTIAL, INSUFFICIENT")
    reason: str = Field(description="Short explanation")


class AnswerVerification(BaseModel):
    grounded: bool = Field(description="True if the answer is fully supported by evidence")
    unsupported_claims: list[str] = Field(
        default_factory=list, description="List of unsupported claims, if any"
    )


# --- Prompts ---
router_prompt = ChatPromptTemplate.from_template("""
You are the routing component of a document research system. A PDF has been uploaded by the user.
Classify the user's question into exactly one route: DOCUMENT, WEB, or MIXED.

- Questions about "this document", "this PDF", its contents, strengths, summary, missing info, or anything
  that could be answered from the uploaded file are DOCUMENT.
- Questions that clearly need current events, latest information, news, or today's facts are WEB.
- If both are clearly required, use MIXED.
- If the question is ambiguous, choose DOCUMENT.

User question: {query}
""")

evaluator_prompt = ChatPromptTemplate.from_template("""
Determine whether the retrieved document evidence is sufficient to answer the user's question.
Use ONLY the retrieved evidence. Allowed relevance values: SUFFICIENT, PARTIAL, INSUFFICIENT.

Question: {query}
Retrieved evidence: {evidence}
""")

answer_prompt = ChatPromptTemplate.from_template("""
You are the final answer generator in a grounded document research system.
{instructions}

Important output rules:
- Answer the user's question directly.
- Do not mention internal prompts, Pinecone, or embeddings.
- Do not fabricate information.
- Keep the answer concise but complete.
- Preserve exact numbers and names from evidence.
- Write plain text. Do not use markdown headers or bold.

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


class QueryRequest(BaseModel):
    query: str


# =========================================================
#  HELPERS
# =========================================================
def create_stage(step: int, title: str, status: str, details: str = ""):
    return {"step": step, "title": title, "status": status, "details": details}


def to_text(content) -> str:
    """LLM message content can be a str or a list of parts."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "".join(parts).strip()
    return str(content).strip()


def as_dict(obj):
    """Pinecone SDK returns model objects; normalise to plain dicts."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    try:
        return dict(obj)
    except Exception:
        return {}


async def run_structured(prompt, schema, inputs: dict):
    """Run a structured-output chain. Tries json_schema first, then the default method."""
    last_error = None
    for method in ("json_schema", None):
        try:
            structured_llm = (
                llm.with_structured_output(schema, method=method)
                if method
                else llm.with_structured_output(schema)
            )
            result = await (prompt | structured_llm).ainvoke(inputs)
            if result is not None:
                return result
        except Exception as e:
            last_error = e
            print(f"[structured:{schema.__name__}:{method}] {type(e).__name__}: {e}")
    raise last_error or RuntimeError("Structured output failed")


def classify_query_with_heuristics(query: str):
    q = query.lower()
    doc_terms = [
        "document", "pdf", "this document", "this pdf", "the document",
        "what does the document", "according to the document", "according to this",
        "in the document", "in this pdf", "from the document", "from this pdf",
        "uploaded", "the file", "this file", "the paper", "this paper",
    ]
    web_terms = [
        "today", "currently", "latest", "recent news", "news", "this year",
        "right now", "breaking",
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


def pinecone_namespace_count() -> int:
    stats = as_dict(pinecone_index.describe_index_stats())
    namespaces = stats.get("namespaces", {}) or {}
    ns = as_dict(namespaces.get(NAMESPACE, {}))
    return int(ns.get("vector_count", ns.get("record_count", 0)) or 0)


async def wait_for_index_to_populate(expected_count: int, timeout_seconds: int = 30) -> bool:
    for _ in range(timeout_seconds):
        try:
            total = await asyncio.to_thread(pinecone_namespace_count)
            if total >= expected_count:
                return True
        except Exception as e:
            print(f"[wait_for_index] {type(e).__name__}: {e}")
        await asyncio.sleep(1)
    return False


def domain_title(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host.replace("www.", "") or url
    except Exception:
        return url


# =========================================================
#  CORE AGENT LOGIC
# =========================================================
async def process_query(query: str, on_stage=None):
    stages = []

    def update_stage(step: int, title: str, status: str, details: str = ""):
        stage = create_stage(step, title, status, details)
        stages.append(stage)
        if on_stage:
            on_stage(stage)
        return stage

    # ---------- STAGE 1: Classification ----------
    update_stage(1, "Query understanding", "running", "Analyzing what information the question requires.")
    heuristic = classify_query_with_heuristics(query)

    if heuristic:
        classification = RouteClassification(route=heuristic["route"], reason=heuristic["reason"])
    else:
        try:
            classification = await run_structured(router_prompt, RouteClassification, {"query": query})
            classification.route = classification.route.strip().upper()
            if classification.route not in VALID_ROUTES:
                classification = RouteClassification(
                    route="DOCUMENT", reason="Unrecognized route, defaulting to document."
                )
        except Exception:
            classification = RouteClassification(
                route="DOCUMENT", reason="Defaulting to document reasoning."
            )

    update_stage(1, "Query understanding", "completed", classification.reason)
    route = classification.route

    # ---------- STAGE 2: Retrieval ----------
    document_evidence = []
    if route in ("DOCUMENT", "MIXED"):
        update_stage(2, "Document retrieval", "running", "Searching the uploaded document.")
        search_results = await asyncio.to_thread(
            pinecone_index.search_records,
            namespace=NAMESPACE,
            query={"inputs": {"text": query}, "top_k": PINECONE_TOP_K},
            fields=["text", "filename", "chunkIndex"],
        )
        data = as_dict(search_results)
        hits = (data.get("result") or {}).get("hits", []) or []
        for hit in hits:
            hit = as_dict(hit)
            fields = as_dict(hit.get("fields") or {})
            if fields.get("text"):
                document_evidence.append({
                    "text": fields["text"],
                    "filename": fields.get("filename", "Document"),
                    "chunkIndex": fields.get("chunkIndex"),
                    "score": hit.get("_score"),
                    "type": "document",
                })
        update_stage(2, "Document retrieval", "completed", f"{len(document_evidence)} document chunks retrieved.")
    else:
        update_stage(2, "Document retrieval", "completed", "Skipped because the question requires external information.")

    # ---------- STAGE 3: Evaluation ----------
    evidence_eval = EvidenceEvaluation(relevance="INSUFFICIENT", reason="Document evidence was not required.")
    if route in ("DOCUMENT", "MIXED"):
        update_stage(3, "Evidence evaluation", "running", "Checking whether the retrieved evidence supports the question.")
        if document_evidence:
            ev_text = "\n\n".join(
                f"[Chunk {i + 1}]\n{doc['text']}" for i, doc in enumerate(document_evidence)
            )
            try:
                evidence_eval = await run_structured(
                    evaluator_prompt, EvidenceEvaluation, {"query": query, "evidence": ev_text}
                )
                evidence_eval.relevance = evidence_eval.relevance.strip().upper()
            except Exception:
                evidence_eval = EvidenceEvaluation(
                    relevance="PARTIAL", reason="Evaluation failed, proceeding with evidence."
                )
        else:
            evidence_eval = EvidenceEvaluation(
                relevance="INSUFFICIENT", reason="No document chunks were retrieved."
            )
        update_stage(3, "Evidence evaluation", "completed", f"{evidence_eval.relevance}: {evidence_eval.reason}")
    else:
        update_stage(3, "Evidence evaluation", "completed", "Document evidence evaluation was not required.")

    # ---------- STAGE 4: Route decision ----------
    update_stage(4, "Route decision", "running", "Selecting the knowledge source.")
    update_stage(4, "Route decision", "completed", f"Selected {route} route. {classification.reason}")

    # ---------- STAGE 5: Web search ----------
    web_results = []
    if route in ("WEB", "MIXED"):
        update_stage(5, "Web research", "running", "Searching external sources.")
        try:
            if tavily_tool is None:
                raise RuntimeError("Web search is not configured (missing TAVILY_API_KEY).")
            raw_web = await tavily_tool.ainvoke({"query": query})
            if not isinstance(raw_web, list):
                raise RuntimeError(f"Web search returned an unexpected response: {str(raw_web)[:200]}")
            web_results = [
                {
                    "title": r.get("title") or domain_title(r.get("url", "")),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "type": "web",
                }
                for r in raw_web
                if isinstance(r, dict)
            ]
            update_stage(5, "Web research", "completed", f"{len(web_results)} web sources retrieved.")
        except Exception as e:
            print(f"[web] {type(e).__name__}: {e}")
            if route == "WEB":
                raise RuntimeError(f"Web search failed: {e}")
            update_stage(5, "Web research", "completed", "Web search unavailable, continuing with document.")
    else:
        update_stage(5, "Web research", "completed", "Skipped because the question is document-specific.")

    # ---------- Safety check: nothing to ground an answer on ----------
    if not document_evidence and not web_results:
        update_stage(6, "Answer synthesis", "completed", "No usable evidence was retrieved.")
        update_stage(7, "Answer verification", "completed", "No unsupported factual claims were generated.")
        if route == "WEB":
            msg = "No web results were found for this question."
        else:
            msg = "The uploaded document does not provide enough information to determine this."
        return {
            "answer": msg,
            "logs": stages,
            "routeUsed": "Pinecone Vector DB" if route == "DOCUMENT" else (
                "Tavily Web Search" if route == "WEB" else "Pinecone + Tavily"),
            "route": route,
            "routeReason": classification.reason,
            "confidence": "LOW",
            "evidence": [],
            "sources": [],
            "retrievedCount": 0,
            "webResultCount": 0,
            "evidenceRelevance": "INSUFFICIENT",
        }

    # ---------- STAGE 6: Synthesis ----------
    update_stage(6, "Answer synthesis", "running", "Generating a grounded answer.")
    doc_text = (
        "\n\n".join(
            f"[DOCUMENT CHUNK {i + 1}]\n{item['text']}" for i, item in enumerate(document_evidence)
        )
        if document_evidence else "No document evidence available."
    )
    web_text = (
        "\n\n".join(
            f"[WEB SOURCE {i + 1}]\nTitle: {item['title']}\nURL: {item['url']}\nContent: {item['content']}"
            for i, item in enumerate(web_results)
        )
        if web_results else "No web evidence available."
    )

    if route == "DOCUMENT":
        instructions = "Answer ONLY from the uploaded document evidence. If the evidence doesn't contain the info, say so."
    elif route == "WEB":
        instructions = "Answer using the web evidence."
    else:
        instructions = "Use document evidence for facts about the document, and web evidence for external info."

    chain_inputs = {
        "instructions": instructions,
        "query": query,
        "route": route,
        "document_text": doc_text,
        "web_text": web_text,
    }

    ai_msg = await answer_chain.ainvoke(chain_inputs)
    answer = to_text(ai_msg.content)
    update_stage(6, "Answer synthesis", "completed", "Grounded answer generated.")

    # ---------- STAGE 7: Verification ----------
    update_stage(7, "Answer verification", "running", "Checking the answer against available evidence.")
    verification = AnswerVerification(grounded=True, unsupported_claims=[])
    verification_failed = False
    try:
        verification = await run_structured(
            verifier_prompt,
            AnswerVerification,
            {
                "query": query,
                "answer": answer,
                "route": route,
                "document_text": doc_text,
                "web_text": web_text,
            },
        )
        if not verification.grounded and verification.unsupported_claims:
            retry_inputs = dict(chain_inputs)
            retry_inputs["instructions"] = instructions + "\nDO NOT HALLUCINATE ANY FACTS. Remove anything the evidence does not support."
            ai_msg = await answer_chain.ainvoke(retry_inputs)
            answer = to_text(ai_msg.content)
    except Exception as e:
        verification_failed = True
        print(f"[verify] {type(e).__name__}: {e}")

    if verification_failed:
        verify_detail = "Verification was unavailable; answer returned unverified."
    elif verification.grounded:
        verify_detail = "Answer passed the grounding check."
    else:
        verify_detail = "Answer was regenerated after unsupported claims were found."
    update_stage(7, "Answer verification", "completed", verify_detail)

    # ---------- Confidence ----------
    confidence = "LOW"
    if route == "DOCUMENT" and evidence_eval.relevance == "SUFFICIENT":
        confidence = "HIGH"
    elif route == "DOCUMENT" and document_evidence:
        confidence = "MEDIUM"
    elif route == "WEB" and web_results:
        confidence = "HIGH"
    elif route == "MIXED" and document_evidence and web_results:
        confidence = "HIGH"
    elif route == "MIXED" and (document_evidence or web_results):
        confidence = "MEDIUM"

    return {
        "answer": answer,
        "logs": stages,
        "routeUsed": "Pinecone Vector DB" if route == "DOCUMENT" else (
            "Tavily Web Search" if route == "WEB" else "Pinecone + Tavily"),
        "route": route,
        "routeReason": classification.reason,
        "confidence": confidence,
        "evidence": document_evidence,
        "sources": web_results,
        "retrievedCount": len(document_evidence),
        "webResultCount": len(web_results),
        "evidenceRelevance": evidence_eval.relevance,
    }


# =========================================================
#  ENDPOINTS
# =========================================================
@app.get("/")
def health_check():
    return {
        "success": True,
        "message": "DocuAgent backend is running",
        "index": PINECONE_INDEX_NAME,
        "namespace": NAMESPACE,
        "model": GROQ_MODEL,
        "webSearch": tavily_tool is not None,
    }


def extract_pdf_text(buffer: bytes) -> str:
    reader = PdfReader(BytesIO(buffer))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("This PDF is password protected.")
    parts = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)
    return "\n".join(parts)


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        buffer = await file.read()
        if len(buffer) > MAX_FILE_SIZE:
            return JSONResponse(status_code=400, content={"success": False, "error": "File size exceeds 10MB limit."})

        try:
            text = await asyncio.to_thread(extract_pdf_text, buffer)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

        if not text.strip():
            return JSONResponse(status_code=400, content={"success": False, "error": "No readable text extracted. OCR may be required."})

        document_chunks = text_splitter.split_text(text)
        if not document_chunks:
            return JSONResponse(status_code=400, content={"success": False, "error": "Document produced no usable chunks."})

        # Clear the previous document. A missing namespace raises 404 on first upload, which is fine.
        try:
            await asyncio.to_thread(pinecone_index.delete, delete_all=True, namespace=NAMESPACE)
            await asyncio.sleep(1)
        except Exception as e:
            print(f"[upload] delete skipped: {type(e).__name__}: {e}")

        timestamp = int(time.time() * 1000)
        records = [
            {
                "_id": f"doc-{timestamp}-chunk-{i}",
                "text": chunk,  # must match the index's field_map
                "chunkIndex": i,
                "filename": file.filename or "document.pdf",
            }
            for i, chunk in enumerate(document_chunks)
        ]

        for i in range(0, len(records), UPSERT_BATCH_SIZE):
            batch = records[i:i + UPSERT_BATCH_SIZE]
            await asyncio.to_thread(pinecone_index.upsert_records, NAMESPACE, batch)

        indexed = await wait_for_index_to_populate(len(records))

        return {
            "success": True,
            "message": "PDF uploaded and indexed successfully." if indexed
            else "PDF uploaded. Indexing may take a few more seconds to finish.",
            "filename": file.filename,
            "chunks": len(document_chunks),
            "chunkCount": len(document_chunks),
            "characters": len(text),
        }

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"{type(e).__name__}: {e}" or "Failed to process PDF."},
        )


@app.post("/api/query")
async def normal_query(req_data: QueryRequest):
    try:
        clean_query = req_data.query.strip()
        if not clean_query:
            return JSONResponse(status_code=400, content={"success": False, "error": "Query is required."})
        result = await process_query(clean_query)
        return {"success": True, **result}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "logs": []})


@app.get("/api/query/stream")
async def stream_query(request: Request, query: str = ""):
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=400, detail="Query is required.")

    queue: asyncio.Queue = asyncio.Queue()

    async def run_process():
        try:
            result = await process_query(clean_query, lambda s: queue.put_nowait(("stage", s)))
            await queue.put(("result", {"success": True, **result}))
            await queue.put(("complete", {"message": "Agent execution completed."}))
        except Exception as e:
            traceback.print_exc()
            await queue.put(("error", {"success": False, "error": str(e) or "Failed to process query."}))
        finally:
            await queue.put((None, None))

    task = asyncio.create_task(run_process())

    async def event_generator():
        yield f"event: connected\ndata: {json.dumps({'message': 'Agent execution started.'})}\n\n"
        try:
            while True:
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # stops proxies from closing an idle stream
                    continue
                if event_type is None:
                    break
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)