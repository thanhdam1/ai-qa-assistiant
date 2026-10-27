"""Opt-in behavioral evaluation for API review reasoning.

Run from backend/: python -m evals.api_contract_regressions --output eval-results.json
This calls the configured AI provider and leaves scoring to a QA reviewer.
"""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.models import Story
from app.services.ai import get_ai_provider
from app.services.openapi_parser import parse_openapi

CASES = [
    {
        "id": "permissive_schema",
        "story": "The service rejects malformed customer email addresses.",
        "properties": {"email": {"type": "string"}},
        "required": ["email"],
        "responses": {"200": {"description": "Accepted"}, "400": {"description": "Bad request"}},
        "qa_check": "Do not claim runtime email validation is absent merely because the schema is permissive.",
    },
    {
        "id": "weaker_schema",
        "story": "The OTP has exactly six digits.",
        "properties": {"otp": {"type": "string", "minLength": 4, "maxLength": 8}},
        "required": ["otp"],
        "responses": {"200": {"description": "Verified"}},
        "qa_check": "Treat the weaker schema as a documentation gap or clarification, not automatically a direct runtime conflict.",
    },
    {
        "id": "idempotency_header",
        "story": "A payment request includes an Idempotency-Key header.",
        "properties": {"amount": {"type": "integer", "minimum": 1}},
        "required": ["amount"],
        "header": True,
        "responses": {"200": {"description": "Accepted"}},
        "qa_check": "Do not infer replay safety or duplicate suppression from the required header alone.",
    },
    {
        "id": "otp_length_vs_lifetime",
        "story": "The customer enters a six digit OTP.",
        "properties": {"otp": {"type": "string", "minLength": 6, "maxLength": 6}},
        "required": ["otp"],
        "responses": {"200": {"description": "Verified"}},
        "qa_check": "Do not infer OTP correctness checks or expiration from its length constraint.",
    },
    {
        "id": "generic_error_code",
        "story": "The customer submits an OTP.",
        "properties": {"otp": {"type": "string"}},
        "required": ["otp"],
        "responses": {"200": {"description": "Verified"}, "400": {"description": "Bad request"}},
        "qa_check": "Do not assign 400 to every OTP failure merely because the operation lists a generic 400 response.",
    },
]


def document_for(case: dict) -> dict:
    operation = {
        "operationId": case["id"],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object", "required": case["required"],
                "properties": case["properties"],
            }}},
        },
        "responses": case["responses"],
    }
    if case.get("header"):
        operation["parameters"] = [{
            "name": "Idempotency-Key", "in": "header", "required": True,
            "schema": {"type": "string"},
        }]
    return {
        "openapi": "3.1.0", "info": {"title": case["id"], "version": "1.0.0"},
        "paths": {"/action": {"post": operation}},
    }


async def evaluate(case_ids: set[str] | None = None) -> list[dict]:
    provider = get_ai_provider()
    results = []
    for case in CASES:
        if case_ids and case["id"] not in case_ids:
            continue
        parsed = parse_openapi("fixture.json", json.dumps(document_for(case)).encode())
        story = Story(
            title=case["id"], description=case["story"],
            acceptance_criteria=[], dependencies=[], language="en", version=1,
        )
        specification = SimpleNamespace(
            title=parsed.title, openapi_version=parsed.version, operations=parsed.operations,
        )
        output = await provider.review_api_contract(story, specification)
        results.append({
            "id": case["id"], "qa_check": case["qa_check"],
            "qa_result": "pending", "qa_notes": "",
            "output": output.model_dump(mode="json"),
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=[case["id"] for case in CASES])
    args = parser.parse_args()
    results = asyncio.run(evaluate(set(args.case) if args.case else None))
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(results)} cases to {args.output}")


if __name__ == "__main__":
    main()
