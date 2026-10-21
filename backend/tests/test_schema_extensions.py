import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.parsers.schema_extensions import SchemaExtensionParser
from app.agents.test_case_agent import TestCaseGenerator
from app.api.v1.qa_assistant import (
    generate_graphql_tests,
    generate_asyncapi_tests,
    GenerateGraphQLTestRequest,
    GenerateAsyncAPITestRequest
)

SAMPLE_GRAPHQL_SDL = """
type User {
    id: ID!
    email: String!
    name: String
}

type Order {
    id: ID!
    total: Float!
    status: String!
}

type Query {
    getUser(id: ID!): User
    listOrders(limit: Int): [Order]!
}

type Mutation {
    createOrder(userId: ID!, total: Float!): Order!
    cancelOrder(orderId: ID!): Boolean!
}
"""

SAMPLE_ASYNCAPI_YAML = """
asyncapi: 2.6.0
info:
  title: Order Events Stream
  version: 1.0.0
channels:
  orders/created:
    publish:
      summary: Publish order created event
      message:
        name: OrderCreatedEvent
        payload:
          type: object
          properties:
            orderId:
              type: string
            amount:
              type: number
  orders/processed:
    subscribe:
      summary: Listen for processed order events
      message:
        name: OrderProcessedEvent
"""

def test_parse_graphql_sdl():
    schema = SchemaExtensionParser.parse_graphql(SAMPLE_GRAPHQL_SDL, title="E-Commerce GraphQL")
    assert schema.title == "E-Commerce GraphQL"
    assert "User" in schema.types
    assert len(schema.queries) == 2
    assert len(schema.mutations) == 2

    query_names = [q.name for q in schema.queries]
    assert "getUser" in query_names
    assert "listOrders" in query_names

    mut_names = [m.name for m in schema.mutations]
    assert "createOrder" in mut_names
    assert "cancelOrder" in mut_names

def test_generate_from_graphql():
    schema = SchemaExtensionParser.parse_graphql(SAMPLE_GRAPHQL_SDL)
    suite = TestCaseGenerator.generate_from_graphql(schema)
    assert suite.total_test_cases >= 4
    categories = [tc.category for tc in suite.test_cases]
    assert "Positive" in categories
    assert "Negative" in categories

def test_parse_asyncapi():
    spec = SchemaExtensionParser.parse_asyncapi(SAMPLE_ASYNCAPI_YAML)
    assert spec.title == "Order Events Stream"
    assert len(spec.channels) == 2
    ch_names = [c.channel_name for c in spec.channels]
    assert "orders/created" in ch_names
    assert "orders/processed" in ch_names

def test_generate_from_asyncapi():
    spec = SchemaExtensionParser.parse_asyncapi(SAMPLE_ASYNCAPI_YAML)
    suite = TestCaseGenerator.generate_from_asyncapi(spec)
    assert suite.total_test_cases == 4  # 2 channels * (Positive + Negative)
    assert any("OrderCreatedEvent" in tc.title or "orders/created" in tc.title for tc in suite.test_cases)

def test_graphql_and_asyncapi_endpoints():
    # Test GraphQL endpoint
    res_gql = generate_graphql_tests(GenerateGraphQLTestRequest(
        schema_sdl=SAMPLE_GRAPHQL_SDL,
        title="Shop GraphQL"
    ))
    assert res_gql.total_test_cases >= 4

    # Test AsyncAPI endpoint
    res_async = generate_asyncapi_tests(GenerateAsyncAPITestRequest(
        spec_content=SAMPLE_ASYNCAPI_YAML
    ))
    assert res_async.total_test_cases == 4
