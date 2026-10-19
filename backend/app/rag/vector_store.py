import os
import uuid
from typing import List, Dict, Any, Optional, Tuple
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from app.core.config import settings
from app.rag.embeddings import EmbeddingService

class VectorStore:
    """
    Qdrant Vector Store wrapper with payload schemas for code chunks and PRD specs.
    Gracefully falls back to local in-memory storage if the remote Qdrant server is offline.
    """

    def __init__(self, use_memory: bool = False):
        self.client: QdrantClient = None
        self.use_memory = use_memory
        self._connect()
        self.init_collections()

    def _connect(self):
        if self.use_memory:
            self.client = QdrantClient(":memory:")
            return

        try:
            # Attempt remote connection to Docker Qdrant
            self.client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                timeout=3.0
            )
            # Verify connectivity
            self.client.get_collections()
        except Exception:
            # Remote server not running yet; use in-memory client
            self.client = QdrantClient(":memory:")

    def init_collections(self):
        """
        Creates default collections for Codebase Index and PRD Specs Index if they don't already exist.
        """
        for coll_name in [settings.QDRANT_COLLECTION_CODE, settings.QDRANT_COLLECTION_PRD]:
            self.ensure_collection(coll_name)

    def ensure_collection(self, collection_name: str):
        """
        Ensures a collection exists with appropriate cosine vector configuration.
        """
        collections = [c.name for c in self.client.get_collections().collections]
        if collection_name not in collections:
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(
                    size=EmbeddingService.DIMENSION,
                    distance=qmodels.Distance.COSINE
                )
            )

    def upsert_chunks(self, collection_name: str, chunks: List[Dict[str, Any]], text_field: str = "content"):
        """
        Computes embeddings and upserts chunks into the specified collection.
        Automatically ensures collection exists.
        """
        if not chunks:
            return

        self.ensure_collection(collection_name)

        texts = [c.get(text_field, "") for c in chunks]
        embeddings = EmbeddingService.get_embeddings(texts)

        points = []
        for chunk, emb in zip(chunks, embeddings):
            # Generate deterministic UUID from chunk_id if present
            chunk_id = chunk.get("chunk_id")
            if chunk_id:
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))
            else:
                point_id = str(uuid.uuid4())

            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=emb,
                    payload=chunk
                )
            )

        self.client.upsert(
            collection_name=collection_name,
            points=points
        )

    def search(
        self,
        collection_name: str,
        query: str,
        top_k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Searches collection by semantic vector similarity using modern query_points API.
        Returns list of (payload, score) tuples.
        """
        self.ensure_collection(collection_name)
        query_vector = EmbeddingService.get_embedding(query)

        query_filter = None
        if filter_dict:
            must_conditions = []
            for k, v in filter_dict.items():
                must_conditions.append(
                    qmodels.FieldCondition(
                        key=k,
                        match=qmodels.MatchValue(value=v)
                    )
                )
            query_filter = qmodels.Filter(must=must_conditions)

        search_result = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter
        )

        return [(hit.payload, hit.score) for hit in search_result.points]
