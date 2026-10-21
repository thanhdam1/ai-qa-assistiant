import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.rag.graph_rag import GraphRAGEngine, GraphNode, GraphEdge
from app.parsers.ast_parser import CodeChunk
from app.api.v1.codebase_qa import (
    trace_impact_endpoint,
    trace_taint_endpoint,
    ImpactTraceRequest,
    TaintFlowRequest
)

def test_graph_rag_construction_and_impact_tracing():
    engine = GraphRAGEngine()

    chunks = [
        CodeChunk(
            chunk_id="chk_ctrl",
            file_path="Controllers/OrderController.cs",
            language="c_sharp",
            node_type="class_declaration",
            name="OrderController",
            parent_name="OrderController",
            start_line=1,
            end_line=10,
            signature="public class OrderController",
            content="public class OrderController {}",
            calls=["_orderService.ProcessPaymentAsync"]
        ),
        CodeChunk(
            chunk_id="chk_srv",
            file_path="Services/OrderService.cs",
            language="c_sharp",
            node_type="class_declaration",
            name="ProcessPaymentAsync",
            parent_name="OrderService",
            start_line=1,
            end_line=10,
            signature="public void ProcessPaymentAsync()",
            content="public void ProcessPaymentAsync() {}",
            calls=["_repo.SaveAsync"]
        ),
        CodeChunk(
            chunk_id="chk_repo",
            file_path="Repositories/OrderRepository.cs",
            language="c_sharp",
            node_type="class_declaration",
            name="SaveAsync",
            parent_name="OrderRepository",
            start_line=1,
            end_line=10,
            signature="public void SaveAsync()",
            content="public void SaveAsync() {}",
            calls=[]
        )
    ]

    engine.build_graph(chunks)
    assert len(engine.nodes) >= 3

    # Trace impact when OrderRepository is modified
    impact = engine.trace_impact("OrderRepository")
    assert impact.origin_symbol == "OrderRepository"
    assert any("Service" in s or "Order" in s for s in impact.impacted_services)

def test_ast_taint_data_flow():
    engine = GraphRAGEngine()
    flow = engine.trace_taint_data_flow("CheckoutController")
    assert len(flow) == 3
    assert flow[0].component == "CheckoutController"
    assert flow[1].component == "CheckoutService"
    assert flow[2].component == "CheckoutRepository"
    assert "body_payload" in flow[0].tainted_fields

def test_adaptive_context_pruning():
    raw_code = """
    // Licensed to the Apache Software Foundation
    // Author: Jane Doe
    /*
     * Multi-line license notice
     * All rights reserved.
     */
    public class PaymentController {
        // Handle checkout payment
        public void Checkout() {
            // Process call
            return;
        }
    }
    """
    pruned = GraphRAGEngine.prune_context(raw_code)
    assert "Licensed to the Apache" not in pruned
    assert "Multi-line license" not in pruned
    assert "public class PaymentController" in pruned
    assert "public void Checkout()" in pruned

def test_graph_rag_api_endpoints():
    res_impact = trace_impact_endpoint(ImpactTraceRequest(symbol_name="OrderService"))
    assert res_impact.origin_symbol == "OrderService"
    assert isinstance(res_impact.traversal_path, list)

    res_taint = trace_taint_endpoint(TaintFlowRequest(entry_endpoint="PaymentController"))
    assert len(res_taint) == 3
