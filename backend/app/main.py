import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.v1.qa_assistant import router as qa_router
from app.api.v1.codebase_qa import router as codebase_router
from app.api.v1.pr_bot import router as pr_router

app = FastAPI(
    title="AI QA Assistant & Codebase Q&A API",
    description="Enterprise RAG Engine for QA Test Generation, Page Object Model Code Synthesis, and AST-based Codebase Architecture Q&A",
    version="1.0.0",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Locate static directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse, tags=["UI Dashboard"])
def serve_dashboard():
    """Serves the interactive single-page Web Dashboard."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>AI QA Assistant API is online. Static dashboard not found.</h1>"

@app.get("/dashboard", response_class=HTMLResponse, tags=["UI Dashboard"])
def redirect_dashboard():
    return serve_dashboard()

@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "qdrant": {
            "host": settings.QDRANT_HOST,
            "port": settings.QDRANT_PORT,
        },
        "llm_provider": settings.LLM_PROVIDER,
    }

# Include API Routers
app.include_router(qa_router, prefix="/api/v1/qa", tags=["QA Assistant"])
app.include_router(codebase_router, prefix="/api/v1/codebase", tags=["Codebase Q&A"])
app.include_router(pr_router, prefix="/api/v1/pr", tags=["CI/CD PR Bot"])
