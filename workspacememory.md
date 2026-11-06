# Workspace Memory
This file is maintained automatically by Code Janitor so Claude, Codex, Bob, and any other AI agent can reuse repo context without rescanning everything from scratch.
Generated: 2026-11-06T23:07:07.292Z
Workspace: backend
Workspace root: c:\Users\Nishchay\OneDrive\Desktop\Projects\DocuAgent\docuagent-ai\backend
Refresh reason: tracked-change
Output path: graphify-out/WORKSPACE_MEMORY.md
Shared mirror: workspacememory.md
Structured manifest: workspace.json
## Handoff Guidance
- Read `graphify-out/GRAPH_REPORT.md` first when the request is about architecture, dependencies, file ownership, or codebase navigation.
- Use this memory file and the workspace-root `workspacememory.md` mirror for recent activity, hot files, Git-aware status, and GitHub-enriched project context.
- Use the workspace-root `workspace.json` file when an AI agent wants machine-readable repo metadata, file inventory, package details, and Git/Graphify summaries without rescanning the repository.
- Refresh this file with the `Code Janitor: Refresh Workspace Memory` command after significant edits or branch changes.
## Repository Blueprint
- Audience: any AI agent working in this repository can treat this file as the current handoff ledger.
- Graphify report: not available yet
- Graphify graph: not available yet
- Last activity: 2026-11-06T23:07:05.517Z
## Workspace Focus
- Active file in focus: server.py
- Hottest files right now: server.py (37), requirements.txt (3)
- Suggested starting points: server.py, requirements.txt, .gitignore, package-lock.json, package.json
## Current Workspace
- Active file: server.py
- Tracked files in snapshot: 8
- Top-level areas: [root] (8)
- Primary file types: .json (3), [no extension] (2), .md (1), .py (1), .txt (1)
- Key files: .gitignore, package-lock.json, package.json
## Package Snapshot
- Package: backend v1.0.0
- Package manager: not declared
- Scripts: test
- Runtime dependencies: @google/genai, @pinecone-database/pinecone, cors, dotenv, express, groq-sdk, multer, pdf-parse
- Dev dependencies: nodemon
## Current Stack
- Logged change events: 40
- Change mix: save (38), create (1), rename (1)
- Remembered file snapshots: 2
- Working tree summary: 4 modifieds
## Tracked Snapshots
- server.py | 435 lines | 18492 chars | hash fe45101e66ac
  Last snapshot: 2026-11-06T23:07:05.517Z
  Preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- requirements.txt | 12 lines | 165 chars | hash 1167e52339a0
  Last snapshot: 2026-11-06T22:32:41.753Z
  Preview: "fastapi / uvicorn / python-dotenv / pydantic / pypdf / pinecone / langchain-groq / langchain-core / langchain-community / langchain-text-splitters / requests / python-multipart"

## Recent Changes
### 2026-11-06T23:07:05.517Z | saved | server.py
- Summary: Line 382: inserted 1 line.
- Before: 435 lines | 18,490 chars | hash 3eacb999d268 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 435 lines | 18,492 chars | hash fe45101e66ac | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- Current fragment: "#"

### 2026-11-06T23:07:01.858Z | saved | server.py
- Summary: Line 382: removed 1 line.
- Before: 435 lines | 18,510 chars | hash c33548a0b90d | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 435 lines | 18,490 chars | hash 3eacb999d268 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- Previous fragment: "# MISSING: Standard"

### 2026-11-06T23:06:54.280Z | saved | server.py
- Summary: Line 378: inserted 16 lines.
- Before: 420 lines | 17,705 chars | hash 7ae6dabc9f34 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 435 lines | 18,510 chars | hash c33548a0b90d | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- Current fragment: "except Exception as e: / return JSONResponse(status_code=500, content={"success": False, "error": str(e) or "Failed to process PDF."}) / # --------------------------------------..."

### 2026-11-06T23:06:53.101Z | saved | server.py
- Summary: Line 378: removed 2 lines.
- Before: 421 lines | 17,743 chars | hash 18f76f5227a8 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 420 lines | 17,705 chars | hash 7ae6dabc9f34 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- Previous fragment: "except Exception as e: / return"

### 2026-11-06T22:43:46.458Z | saved | server.py
- Summary: Line 379: inserted 43 lines.
- Before: 379 lines | 16,171 chars | hash 3faaa79b89e2 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 421 lines | 17,743 chars | hash 18f76f5227a8 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- Current fragment: "@app.get("/api/query/stream") / async def stream_query(request: Request, query: str = ""): / clean_query = query.strip() / if not clean_query: / # Fallback to query parameters f..."

### 2026-11-06T22:43:17.379Z | saved | server.py
- Summary: Saved without a textual diff.
- Before: 379 lines | 16,171 chars | hash 3faaa79b89e2 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 379 lines | 16,171 chars | hash 3faaa79b89e2 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."

### 2026-11-06T22:32:41.753Z | saved | requirements.txt
- Summary: Line 6: removed 1 line.
- Before: 12 lines | 172 chars | hash 5ddbc72c6143 | preview: "fastapi / uvicorn / python-dotenv / pydantic / pypdf / pinecone-client / langchain-groq / langchain-core / langchain-community / langchain-text-splitters / requests / python-multipart"
- After: 12 lines | 165 chars | hash 1167e52339a0 | preview: "fastapi / uvicorn / python-dotenv / pydantic / pypdf / pinecone / langchain-groq / langchain-core / langchain-community / langchain-text-splitters / requests / python-multipart"
- Previous fragment: "-client"

### 2026-11-06T22:24:02.234Z | saved | server.py
- Summary: Line 22: replaced 380 lines with 358 lines.
- Before: 401 lines | 16,857 chars | hash bf9ce563bd5f | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 379 lines | 16,171 chars | hash 3faaa79b89e2 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- Previous fragment: "'PORT', 5000)) / GROQ_MODEL = 'openai/gpt-oss-20b' / PINECONE_INDEX_NAME = 'docuagent-index' / PINECONE_TOP_K = 8 / MAX_WEB_RESULTS = 5 / MAX_FILE_SIZE = 10 * 1024 * 1024 / app..."
- Current fragment: ""PORT", 5000)) / GROQ_MODEL = "openai/gpt-oss-20b" / PINECONE_INDEX_NAME = "docuagent-index" / PINECONE_TOP_K = 8 / MAX_WEB_RESULTS = 5 / MAX_FILE_SIZE = 10 * 1024 * 1024 / app..."

### 2026-11-06T22:21:40.753Z | saved | server.py
- Summary: Line 153: inserted 1 line.
- Before: 401 lines | 16,855 chars | hash 7f840a75afca | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 401 lines | 16,857 chars | hash bf9ce563bd5f | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."

### 2026-11-06T22:21:37.532Z | saved | server.py
- Summary: Line 152: removed 1 line.
- Before: 401 lines | 16,857 chars | hash 4d9045cea9c9 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 401 lines | 16,855 chars | hash 7f840a75afca | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."

### 2026-11-06T22:21:35.807Z | saved | server.py
- Summary: Saved without a textual diff.
- Before: 401 lines | 16,857 chars | hash 4d9045cea9c9 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 401 lines | 16,857 chars | hash 4d9045cea9c9 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."

### 2026-11-06T22:21:33.732Z | saved | server.py
- Summary: Line 148: removed 1 line.
- Before: 401 lines | 16,861 chars | hash 2d4f4a67a159 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 401 lines | 16,859 chars | hash d91d896d1b82 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."

### 2026-11-06T22:21:29.621Z | saved | server.py
- Summary: Line 150: inserted 2 lines.
- Before: 400 lines | 16,855 chars | hash a0c51ee85e00 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 401 lines | 16,861 chars | hash 2d4f4a67a159 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."

### 2026-11-06T22:21:27.160Z | saved | server.py
- Summary: Line 1: inserted 400 lines.
- Before: 0 lines | 0 chars | hash empty
- After: 400 lines | 16,855 chars | hash a0c51ee85e00 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- Current fragment: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware..."

### 2026-11-06T22:21:24.828Z | saved | server.py
- Summary: Line 151: inserted 2 lines.
- Before: 399 lines | 16,849 chars | hash f4e1aafef24a | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."
- After: 400 lines | 16,853 chars | hash de7faf3218f1 | preview: "import os / import time / import json / import asyncio / from io import BytesIO / from fastapi import FastAPI, UploadFile, File, Request, HTTPException / from fastapi.middleware.cors import CORSMiddleware / from fasta..."


## Hot Files
- server.py (37 tracked changes)
- requirements.txt (3 tracked changes)

## Git Snapshot
- Branch: main
- HEAD: 2026-11-07 e9d4551 update code to handle stream api
- Working tree summary: 4 modifieds
- M graphify-out/WORKSPACE_MEMORY.md
- M server.py
- M workspace.json
- M workspacememory.md

## GitHub Snapshot
GitHub Repository: Nishchay3112/docuagent-backend
Description: A CRAG system made using react.js and python fast api , langchain
Visibility: public | Default branch: main
Stars: 0 | Forks: 0 | Open issues: 0

Latest commit on main:
- e9d4551 by Nishchay on 2026-11-06
  update code to handle stream api

URL: https://github.com/Nishchay3112/docuagent-backend

## Graphify Snapshot
Graphify report not found. Generate Graphify output if you want architecture-aware memory excerpts here.

## Project Planner
- Project planner is not configured yet. Enable it in the chat panel to generate a time-based todo list and progress rescue briefs.

## Agent Notes
- If a future task asks what changed recently, start with `Recent Changes`, `Tracked Snapshots`, `Hot Files`, and `Git Snapshot`.
- If a future task asks how the project is organized, combine this file with `graphify-out/GRAPH_REPORT.md`.
- If a future task needs repository-level context, use `Package Snapshot`, the GitHub snapshot, and the Graphify snapshot before rescanning broad parts of the repo.
