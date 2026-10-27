import json

from app.services.openapi_parser import parse_openapi


def parse(document):
    return parse_openapi("contract.json", json.dumps(document).encode()).operations[0]


def base(version="3.1.0"):
    return {
        "openapi": version,
        "info": {"title": "QA API", "version": "1"},
        "servers": [{"url": "https://root.example"}],
        "paths": {"/orders/{id}": {"get": {"operationId": "getOrder", "responses": {"200": {"description": "ok"}}}}},
    }


def test_operation_parameter_overrides_path_parameter():
    document = base()
    item = document["paths"]["/orders/{id}"]
    item["parameters"] = [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "locale", "in": "query", "schema": {"type": "string"}},
    ]
    item["get"]["parameters"] = [
        {"name": "locale", "in": "query", "schema": {"type": "string", "enum": ["vi"]}}
    ]
    operation = parse(document)
    parameters = {(value["name"], value["in"]): value for value in operation["parameters"]}
    assert len(operation["parameters"]) == 2
    assert parameters[("locale", "query")]["schema"]["enum"] == ["vi"]


def test_servers_precedence_is_operation_then_path_then_root():
    document = base()
    item = document["paths"]["/orders/{id}"]
    item["servers"] = [{"url": "https://path.example"}]
    assert parse(document)["servers"][0]["url"] == "https://path.example"
    item["get"]["servers"] = [{"url": "https://operation.example"}]
    assert parse(document)["servers"][0]["url"] == "https://operation.example"


def test_reference_siblings_follow_openapi_version_and_schema_context():
    document = base("3.1.0")
    document["components"] = {
        "responses": {"Ok": {"description": "original"}},
        "schemas": {"Name": {"type": "string"}},
    }
    operation = document["paths"]["/orders/{id}"]["get"]
    operation["responses"]["200"] = {"$ref": "#/components/responses/Ok", "description": "overridden"}
    operation["requestBody"] = {
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Name", "minLength": 2}}}
    }
    parsed = parse(document)
    assert parsed["responses"]["200"]["description"] == "overridden"
    assert parsed["request_body"]["content"]["application/json"]["schema"] == {
        "allOf": [{"type": "string"}, {"minLength": 2}]
    }

    document["openapi"] = "3.0.3"
    parsed = parse(document)
    assert parsed["responses"]["200"]["description"] == "original"


def test_path_item_ref_merges_local_operations():
    document = base()
    document["paths"]["/orders/{id}"] = {"$ref": "#/components/pathItems/Order", "post": {"operationId": "createOrder", "responses": {"201": {"description": "created"}}}}
    document["components"] = {
        "pathItems": {
            "Order": {
                "get": {"operationId": "getOrder", "responses": {"200": {"description": "ok"}}}
            }
        }
    }
    parsed = parse_openapi("contract.json", json.dumps(document).encode())
    by_id = {operation["operation_id"]: operation for operation in parsed.operations}
    assert set(by_id) == {"getOrder", "createOrder"}
    assert by_id["getOrder"]["source_reference"] == "#/components/pathItems/Order/get"
    assert by_id["createOrder"]["source_reference"] == "#/paths/~1orders~1{id}/post"


def test_schema_reference_siblings_keep_both_constraints():
    document = base()
    document["components"] = {
        "schemas": {
            "Amount": {"type": "integer", "minimum": 10000},
            "RequiredFields": {"type": "object", "required": ["walletId"]},
            "AllowedValues": {"type": "string", "enum": ["active", "paused"]},
            "Denied": False,
        }
    }
    operation = document["paths"]["/orders/{id}"]["get"]
    operation["responses"]["200"]["content"] = {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "amount": {"$ref": "#/components/schemas/Amount", "minimum": 1},
                    "request": {"$ref": "#/components/schemas/RequiredFields", "required": ["currency"]},
                    "state": {"$ref": "#/components/schemas/AllowedValues", "enum": ["active"]},
                    "denied": {"$ref": "#/components/schemas/Denied", "type": "string"},
                },
            }
        }
    }
    properties = parse(document)["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
    assert properties["amount"] == {"allOf": [{"type": "integer", "minimum": 10000}, {"minimum": 1}]}
    assert properties["request"]["allOf"][0]["required"] == ["walletId"]
    assert properties["request"]["allOf"][1]["required"] == ["currency"]
    assert properties["state"]["allOf"][0]["enum"] == ["active", "paused"]
    assert properties["state"]["allOf"][1]["enum"] == ["active"]
    assert properties["denied"] == {"allOf": [False, {"type": "string"}]}
