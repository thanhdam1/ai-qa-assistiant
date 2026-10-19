import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.rag.embeddings import EmbeddingService
from app.rag.bm25_indexer import CodeAwareTokenizer, BM25Indexer
from app.rag.vector_store import VectorStore
from app.rag.hybrid_retriever import HybridRetriever
from app.rag.reranker import CrossEncoderReranker

def test_code_aware_tokenizer():
    text = "OrderController.ProcessPaymentAsync(CheckoutRequest request)"
    tokens = CodeAwareTokenizer.tokenize(text)
    
    assert "order" in tokens
    assert "controller" in tokens
    assert "process" in tokens
    assert "payment" in tokens
    assert "async" in tokens
    assert "checkout" in tokens
    assert "request" in tokens

def test_embedding_service():
    v1 = EmbeddingService.get_embedding("Process order payment checkout")
    v2 = EmbeddingService.get_embedding("Process order payment checkout")
    v3 = EmbeddingService.get_embedding("Completely unrelated text about weather and flowers")
    
    assert len(v1) == 1536
    assert v1 == v2  # Deterministic consistency
    assert v1 != v3  # Differentiability

def test_bm25_indexer():
    docs = [
        {"chunk_id": "c1", "content": "public class OrderController : ControllerBase"},
        {"chunk_id": "c2", "content": "public class CustomerService : ICustomerService"},
        {"chunk_id": "c3", "content": "public async Task<IActionResult> Checkout(OrderDto order)"},
    ]
    indexer = BM25Indexer()
    indexer.index_documents(docs)

    results = indexer.search("Checkout", top_k=2)
    assert len(results) >= 1
    assert results[0][0]["chunk_id"] == "c3"

def test_vector_store_in_memory():
    store = VectorStore(use_memory=True)
    chunks = [
        {"chunk_id": "c_auth", "name": "AuthService", "content": "Handles JWT authentication and bearer tokens"},
        {"chunk_id": "c_pay", "name": "PaymentGateway", "content": "Processes Stripe and PayPal credit card transactions"},
    ]
    store.upsert_chunks("codebase_index", chunks)
    
    results = store.search("codebase_index", "Stripe payment transactions", top_k=1)
    assert len(results) == 1
    assert results[0][0]["chunk_id"] == "c_pay"

def test_hybrid_retriever_rrf():
    store = VectorStore(use_memory=True)
    retriever = HybridRetriever(store, collection_name="codebase_index")

    codebase_chunks = [
        {
            "chunk_id": "OrderController.cs#Checkout",
            "name": "Checkout",
            "signature": "public async Task<IActionResult> Checkout([FromBody] CheckoutRequest request)",
            "content": "public async Task<IActionResult> Checkout([FromBody] CheckoutRequest request) { return await _orderService.ProcessAsync(request); }"
        },
        {
            "chunk_id": "ProductController.cs#GetProducts",
            "name": "GetProducts",
            "signature": "public IActionResult GetProducts([FromQuery] int page)",
            "content": "public IActionResult GetProducts([FromQuery] int page) { return Ok(_catalog.List()); }"
        },
        {
            "chunk_id": "NotificationService.cs#SendEmail",
            "name": "SendEmail",
            "signature": "public void SendEmail(string to, string subject, string body)",
            "content": "public void SendEmail(string to, string subject, string body) { _smtp.Send(...); }"
        }
    ]

    retriever.index_documents(codebase_chunks)

    # Search for checkout endpoint
    fused_results = retriever.search("How does the checkout endpoint process orders?", top_k=2)
    
    assert len(fused_results) >= 1
    top_hit = fused_results[0]
    assert top_hit["chunk_id"] == "OrderController.cs#Checkout"
    assert "_rrf_score" in top_hit
    assert top_hit["_rrf_score"] > 0

    # Test Reranker
    reranked = CrossEncoderReranker.rerank("Checkout request", fused_results, top_n=1)
    assert len(reranked) == 1
    assert reranked[0]["name"] == "Checkout"
    assert "_rerank_score" in reranked[0]
