import sys
import os
import pytest

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.parsers.ast_parser import ASTParser
from app.parsers.prd_parser import PRDParser
from app.parsers.openapi_parser import OpenAPIParser

def test_ast_parser_csharp():
    csharp_code = """
using Microsoft.AspNetCore.Mvc;
using System.Threading.Tasks;

namespace MyApp.Controllers
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
        public async Task<IActionResult> Checkout([FromBody] CheckoutRequest request)
        {
            var result = await _orderService.ProcessPaymentAsync(request);
            return Ok(result);
        }
    }
}
"""
    chunks = ASTParser.parse_code(csharp_code, "OrderController.cs", language="c_sharp")
    
    assert len(chunks) >= 2
    # Verify class chunk
    class_chunk = next(c for c in chunks if c.node_type == "class_declaration")
    assert class_chunk.name == "OrderController"
    assert "using Microsoft.AspNetCore.Mvc;" in class_chunk.imports

    # Verify method chunk
    checkout_chunk = next(c for c in chunks if c.name == "Checkout")
    assert checkout_chunk.parent_name == "OrderController"
    assert "_orderService.ProcessPaymentAsync" in checkout_chunk.calls or any("ProcessPaymentAsync" in call for call in checkout_chunk.calls)

def test_ast_parser_typescript():
    ts_code = """
import React, { useState } from 'react';
import { apiService } from '../services/api';

export const LoginForm = ({ onLoginSuccess }) => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();
        const res = await apiService.login(email, password);
        onLoginSuccess(res.data);
    };

    return <form onSubmit={handleSubmit}><button type="submit">Login</button></form>;
};
"""
    chunks = ASTParser.parse_code(ts_code, "LoginForm.tsx", language="typescript")
    assert len(chunks) >= 1
    assert any("import" in imp for imp in chunks[0].imports)

def test_prd_parser():
    prd_markdown = """
# Checkout Feature PRD

## User Story: Place Order
As a registered customer, I want to checkout my shopping cart, so that I can purchase items.

### Acceptance Criteria:
- Given user has items in cart When user clicks checkout Then display order summary.
- Given order total is greater than 0 When user enters valid credit card Then process transaction.
- Given cart is empty When user clicks checkout Then show error message "Cart cannot be empty".
"""
    parsed = PRDParser.parse_markdown(prd_markdown, "Checkout_PRD.md")
    assert parsed.title == "Checkout Feature PRD"
    assert len(parsed.user_stories) >= 1
    us = parsed.user_stories[0]
    assert len(us.acceptance_criteria) >= 2

def test_openapi_parser():
    swagger_json = """
{
  "openapi": "3.0.0",
  "info": { "title": "Store API", "version": "1.0.0" },
  "paths": {
    "/api/orders": {
      "post": {
        "operationId": "createOrder",
        "summary": "Create a new order",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["customerId", "amount"],
                "properties": {
                  "customerId": { "type": "string" },
                  "amount": { "type": "number", "minimum": 1 }
                }
              }
            }
          }
        },
        "responses": {
          "201": { "description": "Order created successfully" },
          "400": { "description": "Invalid order payload" }
        }
      }
    }
  }
}
"""
    parsed = OpenAPIParser.parse_spec(swagger_json)
    assert parsed.title == "Store API"
    assert len(parsed.endpoints) == 1
    ep = parsed.endpoints[0]
    assert ep.path == "/api/orders"
    assert ep.method == "POST"
    assert ep.request_body is not None
    assert "amount" in ep.request_body.properties
    assert "400" in [r.status_code for r in ep.responses]
