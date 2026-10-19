import os
import hashlib
import numpy as np
from typing import List, Optional
from app.core.config import settings

class EmbeddingService:
    """
    Embedding Service supporting OpenAI text-embedding-3-small / large
    with an automatic deterministic fallback for local testing & offline development.
    """

    DIMENSION = 1536

    @classmethod
    def get_embedding(cls, text: str) -> List[float]:
        return cls.get_embeddings([text])[0]

    @classmethod
    def get_embeddings(cls, texts: List[str]) -> List[List[float]]:
        # Check if OpenAI API key is configured
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.startswith("sk-"):
            try:
                from openai import OpenAI
                client = OpenAI(api_key=settings.OPENAI_API_KEY)
                response = client.embeddings.create(
                    input=texts,
                    model=settings.OPENAI_EMBEDDING_MODEL
                )
                return [item.embedding for item in response.data]
            except Exception as e:
                # Log and fallback to local deterministic vector
                pass

        # Offline / Local fallback: Deterministic normalized pseudo-semantic embedding
        return [cls._generate_deterministic_vector(t) for t in texts]

    @classmethod
    def _generate_deterministic_vector(cls, text: str) -> List[float]:
        """
        Generates a 1536-dimensional normalized vector deterministically from text tokens.
        Allows full end-to-end vector indexing and testing without requiring cloud API keys.
        """
        words = text.lower().split()
        vector = np.zeros(cls.DIMENSION, dtype=np.float32)
        
        if not words:
            vector[0] = 1.0
            return vector.tolist()

        for word in words:
            # Hash word to an index in [0, DIMENSION)
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx = h % cls.DIMENSION
            sign = 1.0 if (h // cls.DIMENSION) % 2 == 0 else -1.0
            vector[idx] += sign

        # Normalize to unit length
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        else:
            vector[0] = 1.0

        return vector.tolist()
