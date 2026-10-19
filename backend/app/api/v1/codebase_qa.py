from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from app.agents.codebase_agent import CodebaseArchitectureAgent, ArchitectureAnswer

router = APIRouter()

# Global Singleton Agent Instance for the API
codebase_agent = CodebaseArchitectureAgent()

class FileIngestionItem(BaseModel):
    file_path: str = Field(description="Relative path e.g. src/Controllers/OrderController.cs")
    content: str = Field(description="Full source code text")

class IndexCodebaseRequest(BaseModel):
    files: List[FileIngestionItem]

class IndexCodebaseResponse(BaseModel):
    total_files_indexed: int
    total_chunks_created: int
    languages_detected: List[str]

class AskCodebaseRequest(BaseModel):
    query: str = Field(description="Question about architecture or data flow e.g. 'How does order checkout work?'")
    top_k: Optional[int] = 5

@router.post("/index", response_model=IndexCodebaseResponse, summary="Index Codebase Files via AST & Hybrid RAG")
def index_codebase(request: IndexCodebaseRequest):
    if not request.files:
        raise HTTPException(status_code=400, detail="File list cannot be empty.")

    file_dicts = [{"file_path": f.file_path, "content": f.content} for f in request.files]
    codebase_agent.index_files(file_dicts)

    languages = list(set(
        chunk.language for chunk in codebase_agent.indexed_chunks.values()
    ))

    return IndexCodebaseResponse(
        total_files_indexed=len(request.files),
        total_chunks_created=len(codebase_agent.indexed_chunks),
        languages_detected=sorted(languages)
    )

@router.post("/ask", response_model=ArchitectureAnswer, summary="Ask Architecture Questions & Generate Mermaid Diagrams")
def ask_codebase(request: AskCodebaseRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    return codebase_agent.answer_architecture_query(
        query=request.query,
        top_k=request.top_k or 5
    )

@router.get("/symbols", summary="List Indexed Symbols & Components")
def list_symbols():
    return {
        "total_chunks": len(codebase_agent.indexed_chunks),
        "total_unique_symbols": len(codebase_agent.symbol_table),
        "symbols": list(codebase_agent.symbol_table.keys())[:50]
    }
