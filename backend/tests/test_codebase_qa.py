import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.codebase_agent import CodebaseArchitectureAgent
from app.api.v1.codebase_qa import index_codebase, ask_codebase, list_symbols, IndexCodebaseRequest, AskCodebaseRequest, FileIngestionItem

CONTROLLER_CODE = """
using Microsoft.AspNetCore.Mvc;

namespace App.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class OrderController : ControllerBase
    {
        private readonly IOrderService _orderService;

        public OrderController(IOrderService orderService)
        {
            _orderService = orderService;
        }

        [HttpPost("checkout")]
        public async Task<IActionResult> Checkout(OrderRequest request)
        {
            var res = await _orderService.ProcessPaymentAsync(request);
            return Ok(res);
        }
    }
}
"""

SERVICE_CODE = """
namespace App.Services
{
    public class OrderService : IOrderService
    {
        private readonly IOrderRepository _orderRepo;

        public OrderService(IOrderRepository orderRepo)
        {
            _orderRepo = orderRepo;
        }

        public async Task<OrderResult> ProcessPaymentAsync(OrderRequest request)
        {
            var saved = await _orderRepo.SaveAsync(request);
            return new OrderResult { Success = true };
        }
    }
}
"""

REPO_CODE = """
namespace App.Repositories
{
    public class OrderRepository : IOrderRepository
    {
        public async Task<bool> SaveAsync(OrderRequest request)
        {
            // Writes entity to database
            return true;
        }
    }
}
"""

def test_codebase_agent_indexing_and_call_graph():
    agent = CodebaseArchitectureAgent()
    files = [
        {"file_path": "Controllers/OrderController.cs", "content": CONTROLLER_CODE},
        {"file_path": "Services/OrderService.cs", "content": SERVICE_CODE},
        {"file_path": "Repositories/OrderRepository.cs", "content": REPO_CODE},
    ]

    agent.index_files(files)
    assert len(agent.indexed_chunks) >= 3
    assert "processpaymentasync" in agent.symbol_table
    assert "saveasync" in agent.symbol_table

    # Query architecture
    ans = agent.answer_architecture_query("How does checkout execute through services?", top_k=2)

    assert len(ans.referenced_chunks) >= 2
    # Verify Mermaid diagram
    assert "sequenceDiagram" in ans.mermaid_diagram
    assert any(c in ans.mermaid_diagram for c in ["OrderController", "OrderService", "OrderRepository"])

def test_codebase_qa_api_endpoints():
    req_index = IndexCodebaseRequest(
        files=[
            FileIngestionItem(file_path="src/OrderController.cs", content=CONTROLLER_CODE),
            FileIngestionItem(file_path="src/OrderService.cs", content=SERVICE_CODE)
        ]
    )
    res_index = index_codebase(req_index)
    assert res_index.total_files_indexed == 2
    assert "c_sharp" in res_index.languages_detected

    # Query API
    req_ask = AskCodebaseRequest(query="Explain checkout order flow", top_k=3)
    res_ask = ask_codebase(req_ask)
    assert len(res_ask.components_involved) >= 1
    assert "sequenceDiagram" in res_ask.mermaid_diagram

    # Symbols API
    symbols = list_symbols()
    assert symbols["total_chunks"] >= 2
