from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "online",
        "service": "AI QA Assistant & Codebase Q&A",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
    }

@app.get("/health", tags=["Health"])
async def health_check():
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
