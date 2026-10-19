import re
from typing import List, Dict, Any, Tuple
from rank_bm25 import BM25Okapi

class CodeAwareTokenizer:
    """
    Tokenizer designed for code and technical documentation.
    Splits CamelCase, snake_case, URLs, file paths, and punctuation
    while preserving original symbol tokens.
    """

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        if not text:
            return []

        # Find words, identifiers, and special code tokens
        raw_tokens = re.findall(r"[A-Za-z0-9_\.\-\/]+", text)
        processed_tokens: List[str] = []

        for token in raw_tokens:
            token_lower = token.lower()
            processed_tokens.append(token_lower)

            # Split CamelCase: "OrderController" -> ["order", "controller"]
            camel_split = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+", token)
            if len(camel_split) > 1:
                for part in camel_split:
                    processed_tokens.append(part.lower())

            # Split snake_case, kebab-case, or dot-paths: "user_service.get_by_id" -> ["user", "service", "get", "by", "id"]
            if any(sep in token for sep in ["_", "-", ".", "/"]):
                sub_parts = re.split(r"[_\-\.\/]+", token)
                for sp in sub_parts:
                    if sp and sp.lower() != token_lower:
                        processed_tokens.append(sp.lower())

        return processed_tokens

class BM25Indexer:
    """
    Sparse Inverted Index using BM25Okapi for exact code and keyword matching.
    """

    def __init__(self):
        self.corpus_chunks: List[Dict[str, Any]] = []
        self.tokenized_corpus: List[List[str]] = []
        self.bm25: BM25Okapi = None

    def index_documents(self, documents: List[Dict[str, Any]], text_field: str = "content"):
        """
        Indexes a list of documents (dictionaries containing text and metadata).
        """
        self.corpus_chunks = documents
        self.tokenized_corpus = [
            CodeAwareTokenizer.tokenize(doc.get(text_field, ""))
            for doc in documents
        ]
        if self.tokenized_corpus:
            self.bm25 = BM25Okapi(self.tokenized_corpus)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[Dict[str, Any], float]]:
        """
        Searches the indexed corpus using BM25.
        Returns a list of (document, score) tuples sorted by relevance.
        """
        if not self.bm25 or not self.corpus_chunks:
            return []

        query_tokens = CodeAwareTokenizer.tokenize(query)
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        
        # Rank by score descending
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        
        results: List[Tuple[Dict[str, Any], float]] = []
        for idx in ranked_indices[:top_k]:
            if scores[idx] > 0.0:  # Only return documents with matching keywords
                results.append((self.corpus_chunks[idx], float(scores[idx])))

        return results
