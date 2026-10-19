from typing import List, Dict, Any

class CrossEncoderReranker:
    """
    Reranker for contextual precision.
    Takes candidate documents from Hybrid Search and performs fine-grained relevance scoring.
    """

    @classmethod
    def rerank(
        cls,
        query: str,
        candidates: List[Dict[str, Any]],
        top_n: int = 5,
        text_field: str = "content"
    ) -> List[Dict[str, Any]]:
        """
        Reranks candidates based on query term frequency density,
        signature matching, and hybrid RRF score.
        """
        if not candidates:
            return []

        query_terms = set(query.lower().split())

        scored_candidates = []
        for doc in candidates:
            text = doc.get(text_field, "").lower()
            name = doc.get("name", "").lower()
            signature = doc.get("signature", "").lower()
            base_score = doc.get("_rrf_score", 0.0)

            # Bonus for exact name match (e.g. querying for OrderController or Checkout)
            name_bonus = 0.0
            for term in query_terms:
                if term in name:
                    name_bonus += 0.05
                if term in signature:
                    name_bonus += 0.03

            # Keyword density
            term_hits = sum(1 for term in query_terms if term in text)
            density_bonus = (term_hits / max(len(query_terms), 1)) * 0.04

            final_score = base_score + name_bonus + density_bonus
            doc_copy = dict(doc)
            doc_copy["_rerank_score"] = round(final_score, 6)
            scored_candidates.append(doc_copy)

        # Sort by rerank score descending
        scored_candidates.sort(key=lambda x: x["_rerank_score"], reverse=True)
        return scored_candidates[:top_n]
