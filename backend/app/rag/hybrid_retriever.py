from typing import List, Dict, Any, Optional
from collections import defaultdict
from app.rag.vector_store import VectorStore
from app.rag.bm25_indexer import BM25Indexer

class HybridRetriever:
    """
    Hybrid Search Engine fusing Dense Vector Retrieval (Qdrant)
    and Sparse Keyword Retrieval (BM25) via Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, vector_store: VectorStore, collection_name: str, k_rrf: int = 60):
        self.vector_store = vector_store
        self.collection_name = collection_name
        self.bm25_indexer = BM25Indexer()
        self.k_rrf = k_rrf  # Standard constant for RRF

    def index_documents(self, chunks: List[Dict[str, Any]], text_field: str = "content"):
        """
        Simultaneously indexes chunks into Qdrant Vector Store and In-Memory BM25 Index.
        """
        # 1. Upsert into Vector DB
        self.vector_store.upsert_chunks(self.collection_name, chunks, text_field=text_field)
        # 2. Index into BM25
        self.bm25_indexer.index_documents(chunks, text_field=text_field)

    def search(
        self,
        query: str,
        top_k: int = 10,
        dense_weight: float = 0.6,
        sparse_weight: float = 0.4,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes Hybrid Retrieval using Reciprocal Rank Fusion (RRF).
        Returns top_k fused documents with metadata and fused scores.
        """
        candidate_pool_size = max(top_k * 2, 20)

        # 1. Dense Search (Vector DB)
        dense_results = self.vector_store.search(
            collection_name=self.collection_name,
            query=query,
            top_k=candidate_pool_size,
            filter_dict=filter_dict
        )

        # 2. Sparse Search (BM25)
        sparse_results = self.bm25_indexer.search(
            query=query,
            top_k=candidate_pool_size
        )

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores: Dict[str, float] = defaultdict(float)
        doc_store: Dict[str, Dict[str, Any]] = {}

        # Process Dense Ranks
        for rank, (payload, _) in enumerate(dense_results, start=1):
            doc_id = payload.get("chunk_id") or payload.get("name") or str(hash(payload.get("content", "")))
            doc_store[doc_id] = payload
            rrf_scores[doc_id] += dense_weight / (self.k_rrf + rank)

        # Process Sparse Ranks
        for rank, (payload, _) in enumerate(sparse_results, start=1):
            doc_id = payload.get("chunk_id") or payload.get("name") or str(hash(payload.get("content", "")))
            doc_store[doc_id] = payload
            rrf_scores[doc_id] += sparse_weight / (self.k_rrf + rank)

        # Sort by RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda d: rrf_scores[d], reverse=True)

        results: List[Dict[str, Any]] = []
        for doc_id in sorted_ids[:top_k]:
            doc_item = dict(doc_store[doc_id])
            doc_item["_rrf_score"] = round(rrf_scores[doc_id], 6)
            results.append(doc_item)

        return results
