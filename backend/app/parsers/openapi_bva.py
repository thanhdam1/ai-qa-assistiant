from typing import Any, Dict, List
from app.parsers.srs_decomposer import decompose_user_story
from app.schemas.zero_gap_contract import AtomicRequirement, BVAPartitionItem


def generate_8_partition_bva(openapi_spec: Dict[str, Any]) -> List[BVAPartitionItem]:
    """Sinh ma trận 8 phân vùng biên tất định từ OpenAPI Schema (RULE-02)."""
    bva_items: List[BVAPartitionItem] = []
    paths = openapi_spec.get("paths", {})

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, details in methods.items():
            if not isinstance(details, dict):
                continue
            if method.lower() not in {"post", "put", "patch", "get", "delete"}:
                continue
            endpoint_key = f"{method.upper()} {path}"
            schema = (
                details.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            properties: Dict[str, Any] = {}
            required_fields = set()

            if isinstance(schema, dict):
                properties = dict(schema.get("properties", {}))
                required_fields = set(schema.get("required", []))

            # Also check parameters (query/path/header)
            parameters = details.get("parameters", [])
            if isinstance(parameters, list):
                for param in parameters:
                    if isinstance(param, dict):
                        p_name = param.get("name")
                        p_schema = param.get("schema", {})
                        if p_name and isinstance(p_schema, dict):
                            properties[p_name] = p_schema
                            if param.get("required"):
                                required_fields.add(p_name)

            for field_name, rules in properties.items():
                if not isinstance(rules, dict):
                    continue
                ftype = rules.get("type", "string")
                partitions: Dict[str, tuple[Any, int]] = {}

                if ftype in {"integer", "number"}:
                    low = rules.get("minimum", 0)
                    high = rules.get("maximum", 1000)
                    mid = (low + high) // 2
                    partitions = {
                        "min_minus_1": (low - 1, 422),
                        "min": (low, 200),
                        "nominal": (mid, 200),
                        "max": (high, 200),
                        "max_plus_1": (high + 1, 422),
                        "null": (None, 422 if field_name in required_fields else 200),
                        "empty": ("", 422),
                        "wrong_type": ("INVALID_NUMBER_TYPE", 422),
                    }
                elif ftype == "string":
                    min_len = rules.get("minLength", 1)
                    max_len = rules.get("maxLength", 50)
                    mid_len = max(1, (min_len + max_len) // 2)
                    partitions = {
                        "min_minus_1": ("a" * max(0, min_len - 1), 422 if min_len > 0 else 200),
                        "min": ("a" * min_len, 200),
                        "nominal": ("a" * mid_len, 200),
                        "max": ("a" * max_len, 200),
                        "max_plus_1": ("a" * (max_len + 1), 422),
                        "null": (None, 422 if field_name in required_fields else 200),
                        "empty": ("", 422 if min_len > 0 or field_name in required_fields else 200),
                        "wrong_type": ({"unexpected": "object"}, 422),
                    }
                elif ftype == "boolean":
                    partitions = {
                        "nominal_true": (True, 200),
                        "nominal_false": (False, 200),
                        "null": (None, 422 if field_name in required_fields else 200),
                        "wrong_type": ("not_a_boolean", 422),
                    }

                for p_type, (val, status_code) in partitions.items():
                    bva_items.append(
                        BVAPartitionItem(
                            bva_id=f"BVA-{field_name}-{p_type}",
                            endpoint=endpoint_key,
                            field_path=field_name,
                            partition_type=p_type,
                            test_value=val,
                            expected_http_status=status_code,
                        )
                    )
    return bva_items
