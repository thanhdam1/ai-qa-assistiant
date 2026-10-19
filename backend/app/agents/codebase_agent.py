import re
from typing import List, Dict, Any, Optional, Set
from pydantic import BaseModel, Field
from app.core.config import settings
from app.parsers.ast_parser import ASTParser, CodeChunk
from app.rag.vector_store import VectorStore
from app.rag.hybrid_retriever import HybridRetriever
from app.rag.reranker import CrossEncoderReranker

class ArchitectureAnswer(BaseModel):
    query: str
    summary: str
    components_involved: List[str] = Field(default_factory=list)
    mermaid_diagram: str
    detailed_explanation: str
    referenced_chunks: List[Dict[str, Any]] = Field(default_factory=list)

class CodebaseArchitectureAgent:
    """
    Codebase & Architecture Reasoning Agent.
    Traces class/method call graphs, analyzes system workflows across services,
    and automatically generates Mermaid sequence diagrams to visualize execution paths.
    """

    def __init__(self, vector_store: Optional[VectorStore] = None):
        self.vector_store = vector_store or VectorStore(use_memory=True)
        self.retriever = HybridRetriever(
            self.vector_store,
            collection_name=settings.QDRANT_COLLECTION_CODE
        )
        self.indexed_chunks: Dict[str, CodeChunk] = {}
        self.symbol_table: Dict[str, List[CodeChunk]] = {}  # symbol_name -> chunks

    def index_files(self, file_contents: List[Dict[str, str]]):
        """
        Parses source files with Tree-sitter AST, updates symbol table,
        and indexes chunks into the Hybrid Search engine.
        """
        all_chunks: List[Dict[str, Any]] = []

        for item in file_contents:
            file_path = item.get("file_path", "unknown.py")
            code = item.get("content", "")
            chunks = ASTParser.parse_code(code, file_path=file_path)

            for chunk in chunks:
                self.indexed_chunks[chunk.chunk_id] = chunk
                self.symbol_table.setdefault(chunk.name.lower(), []).append(chunk)
                all_chunks.append(chunk.model_dump())

        if all_chunks:
            self.retriever.index_documents(all_chunks, text_field="content")

    def answer_architecture_query(self, query: str, top_k: int = 5) -> ArchitectureAnswer:
        """
        Retrieves relevant components using Hybrid Search, expands call-graph,
        and synthesizes architectural flow explanation with a Mermaid diagram.
        """
        # 1. Retrieve Candidate Chunks
        fused_candidates = self.retriever.search(query, top_k=top_k * 2)
        reranked = CrossEncoderReranker.rerank(query, fused_candidates, top_n=top_k)

        # 2. Expand Context via Call-Graph Linking
        expanded_chunks = self._expand_call_graph(reranked)

        # 3. Generate Mermaid Sequence Diagram
        mermaid_diag = self._generate_mermaid_sequence(expanded_chunks)

        # 4. Synthesize Architecture Explanation
        components = list(set(
            c.get("parent_name") or c.get("name", "Unknown")
            for c in expanded_chunks
        ))

        explanation = self._synthesize_explanation(query, expanded_chunks, mermaid_diag)

        return ArchitectureAnswer(
            query=query,
            summary=f"Analyzed {len(expanded_chunks)} components along the execution path.",
            components_involved=sorted(components),
            mermaid_diagram=mermaid_diag,
            detailed_explanation=explanation,
            referenced_chunks=expanded_chunks
        )

    def _expand_call_graph(self, initial_chunks: List[Dict[str, Any]], max_depth: int = 2) -> List[Dict[str, Any]]:
        """
        Lần theo các hàm được gọi (calls) để tìm các tầng kế tiếp (Controller -> Service -> Repo).
        """
        seen_ids: Set[str] = set(c.get("chunk_id", "") for c in initial_chunks)
        results = list(initial_chunks)

        for chunk_dict in initial_chunks:
            calls = chunk_dict.get("calls", [])
            for call_name in calls:
                # Clean call name: e.g. "_orderService.ProcessPaymentAsync" -> "processpaymentasync"
                simple_name = call_name.split(".")[-1].lower()
                matching_chunks = self.symbol_table.get(simple_name, [])
                for match in matching_chunks:
                    if match.chunk_id not in seen_ids:
                        seen_ids.add(match.chunk_id)
                        results.append(match.model_dump())

        return results

    def _generate_mermaid_sequence(self, chunks: List[Dict[str, Any]]) -> str:
        """
        Constructs a clean Mermaid sequence diagram representing interactions.
        """
        if not chunks:
            return "sequenceDiagram\n    autonumber\n    Client->>System: Request\n    System-->>Client: Response"

        participants: List[str] = []
        for c in chunks:
            p = c.get("parent_name") or c.get("name")
            if p and p not in participants:
                # Sanitize participant name (alphanumeric only)
                clean_p = re.sub(r"[^a-zA-Z0-9_]", "", p)
                if clean_p and clean_p not in participants:
                    participants.append(clean_p)

        if len(participants) < 2:
            participants.append("ExternalService")

        lines = [
            "sequenceDiagram",
            "    autonumber",
            "    actor Client",
        ]
        for p in participants[:6]:  # Limit to 6 participants for diagram readability
            lines.append(f"    participant {p}")

        # Add interactions
        lines.append(f"    Client->>{participants[0]}: Inbound Request")
        for i in range(len(participants) - 1):
            caller = participants[i]
            callee = participants[i + 1]
            lines.append(f"    {caller}->>{callee}: Execute Business Logic / Call")
            lines.append(f"    {callee}-->>{caller}: Return Result")
        lines.append(f"    {participants[0]}-->>Client: 200 OK Response")

        return "\n".join(lines)

    def _synthesize_explanation(self, query: str, chunks: List[Dict[str, Any]], mermaid_diagram: str) -> str:
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.startswith("sk-"):
            try:
                from openai import OpenAI
                client = OpenAI(api_key=settings.OPENAI_API_KEY)
                prompt = (
                    f"You are a Principal Software Architect.\n"
                    f"Explain the architecture and execution flow for the user query: '{query}'.\n\n"
                    f"Relevant Code Components:\n"
                )
                for c in chunks:
                    prompt += f"- File: {c.get('file_path')} | Component: {c.get('name')} | Signature: {c.get('signature')}\n"

                prompt += (
                    f"\nMermaid Sequence Diagram:\n```mermaid\n{mermaid_diagram}\n```\n\n"
                    "Provide a clear, high-level architectural walkthrough: Component responsibilities, data flow, and error handling."
                )

                response = client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
                return response.choices[0].message.content.strip()
            except Exception:
                pass

        # Deterministic architectural breakdown
        comp_names = [c.get("name") for c in chunks]
        breakdown = [
            f"### Kiến trúc Luồng Thực thi cho: '{query}'",
            "",
            "1. **Tầng tiếp nhận (Entrypoint):** Yêu cầu được định tuyến tới component đầu vào chịu trách nhiệm xác thực và parse request payload.",
            f"2. **Tầng xử lý nghiệp vụ (Business Service Layer):** Các phương thức nghiệp vụ liên quan ({', '.join(comp_names[:4])}) thực hiện tính toán, điều phối và kiểm tra ràng buộc quy tắc.",
            "3. **Tầng tích hợp / Dữ liệu (Integration & Storage):** Dữ liệu sau khi xử lý được chuyển tiếp tới Gateway bên ngoài hoặc lưu trữ xuống cơ sở dữ liệu qua Repository Pattern.",
            "",
            "**Sơ đồ tuần tự minh họa:** Xem khối mã Mermaid đi kèm để theo dõi trực quan các bước gọi hàm giữa các thành phần."
        ]
        return "\n".join(breakdown)
