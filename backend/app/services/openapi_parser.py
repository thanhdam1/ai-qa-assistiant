from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

import yaml
from yaml.events import AliasEvent

from app.errors import AppError

MAX_OPENAPI_BYTES = 1_000_000
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


class LimitedSafeLoader(yaml.SafeLoader):
    def __init__(self, stream: str):
        self.alias_count = 0
        super().__init__(stream)

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            self.alias_count += 1
            if self.alias_count > 100:
                raise yaml.YAMLError("OpenAPI YAML exceeds the alias limit")
        return super().compose_node(parent, index)


@dataclass(frozen=True)
class ParsedOpenApi:
    title: str
    version: str
    document: dict[str, Any]
    operations: list[dict[str, Any]]
    checksum: str


def _pointer_value(document: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"External or unsupported reference: {ref}")
    current: Any = document
    for token in ref[2:].split("/"):
        key = unquote(token).replace("~1", "/").replace("~0", "~")
        if isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
            continue
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Unresolved local reference: {ref}")
        current = current[key]
    return current


def is_valid_source_reference(document: dict[str, Any], ref: str) -> bool:
    if not ref.startswith("#/"):
        return False
    current: Any = document
    visited_refs: set[str] = set()
    for token in ref[2:].split("/"):
        while isinstance(current, dict) and current.get("$ref"):
            target_ref = current["$ref"]
            if target_ref in visited_refs:
                return False
            visited_refs.add(target_ref)
            try:
                current = _pointer_value(document, target_ref)
            except ValueError:
                return False
        key = unquote(token).replace("~1", "/").replace("~0", "~")
        if isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        elif isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return False
    return True


def _collect_source_references(
    document: dict[str, Any], value: Any, pointer: str, visited_refs: frozenset[str] = frozenset()
) -> set[str]:
    references = {pointer}
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            references.add(ref)
            if ref not in visited_refs:
                target = _pointer_value(document, ref)
                references.update(
                    _collect_source_references(document, target, ref, visited_refs | {ref})
                )
        for key, item in value.items():
            if key == "$ref":
                continue
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            references.update(
                _collect_source_references(
                    document, item, f"{pointer}/{escaped}", visited_refs
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            references.update(
                _collect_source_references(document, item, f"{pointer}/{index}", visited_refs)
            )
    return references


def _resolve(value: Any, document: dict[str, Any], stack: tuple[str, ...] = ()) -> Any:
    if isinstance(value, list):
        return [_resolve(item, document, stack) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if ref:
        if ref in stack:
            return {"$ref": ref, "recursive_reference": True}
        target = _pointer_value(document, ref)
        resolved = _resolve(target, document, (*stack, ref))
        if isinstance(resolved, dict):
            siblings = {key: item for key, item in value.items() if key != "$ref"}
            return resolved | _resolve(siblings, document, stack)
        return resolved
    return {key: _resolve(item, document, stack) for key, item in value.items()}


def _validate_references(value: Any, document: dict[str, Any]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if ref:
            _pointer_value(document, ref)
        for item in value.values():
            _validate_references(item, document)
    elif isinstance(value, list):
        for item in value:
            _validate_references(item, document)


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"Unsupported YAML value type: {type(value).__name__}")


def parse_openapi(file_name: str, raw: bytes) -> ParsedOpenApi:
    suffix = PurePosixPath(file_name.replace("\\", "/")).suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        raise AppError("unsupported_openapi_format", "Upload a JSON or YAML OpenAPI file", 422)
    if not raw or len(raw) > MAX_OPENAPI_BYTES:
        raise AppError(
            "openapi_too_large",
            f"OpenAPI file must be between 1 byte and {MAX_OPENAPI_BYTES} bytes",
            413,
            {"limit_bytes": MAX_OPENAPI_BYTES, "actual_bytes": len(raw)},
        )
    try:
        source = raw.decode("utf-8-sig")
        document = json.loads(source) if suffix == ".json" else yaml.load(source, Loader=LimitedSafeLoader)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise AppError("invalid_openapi", "Could not parse the OpenAPI JSON/YAML document", 422) from exc
    if not isinstance(document, dict):
        raise AppError("invalid_openapi", "The OpenAPI document root must be an object", 422)
    try:
        document = _json_compatible(document)
    except ValueError as exc:
        raise AppError("invalid_openapi", "The OpenAPI document contains unsupported YAML values", 422) from exc
    version = document.get("openapi")
    if not isinstance(version, str) or not (version.startswith("3.0.") or version.startswith("3.1.")):
        raise AppError("unsupported_openapi_version", "Only OpenAPI 3.0.x and 3.1.x are supported", 422)
    info = document.get("info")
    paths = document.get("paths")
    components = document.get("components", {})
    if not isinstance(info, dict) or not isinstance(info.get("title"), str):
        raise AppError("invalid_openapi", "OpenAPI info.title is required", 422)
    if not isinstance(paths, dict):
        raise AppError("invalid_openapi", "OpenAPI paths must be an object", 422)
    if not isinstance(components, dict):
        raise AppError("invalid_openapi", "OpenAPI components must be an object", 422)
    try:
        _validate_references(document, document)
        operations = []
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            resolved_path_item = _resolve(path_item, document)
            for method, operation in resolved_path_item.items():
                method = method.lower()
                if method not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                pointer = f"#/paths/{path.replace('~', '~0').replace('/', '~1')}/{method}"
                raw_operation = path_item.get(method, operation)
                resolved = _resolve(operation, document)
                source_references = _collect_source_references(
                    document, raw_operation, pointer
                )
                source_references.update(
                    _collect_source_references(
                        document,
                        path_item.get("parameters", []),
                        f"#/paths/{path.replace('~', '~0').replace('/', '~1')}/parameters",
                    )
                )
                operations.append(
                    {
                        "operation_id": resolved.get("operationId") or f"{method.upper()} {path}",
                        "method": method.upper(),
                        "path": path,
                        "summary": resolved.get("summary", ""),
                        "source_reference": pointer,
                        "source_references": sorted(source_references),
                        "parameters": _resolve(resolved_path_item.get("parameters", []), document)
                        + _resolve(resolved.get("parameters", []), document),
                        "request_body": _resolve(resolved.get("requestBody"), document),
                        "responses": _resolve(resolved.get("responses", {}), document),
                        "security": resolved.get("security", document.get("security", [])),
                        "security_schemes": _resolve(
                            components.get("securitySchemes", {}), document
                        ),
                        "servers": _resolve(resolved.get("servers", document.get("servers", [])), document),
                    }
                )
    except ValueError as exc:
        raise AppError("invalid_openapi_reference", str(exc), 422) from exc
    if not operations:
        raise AppError("invalid_openapi", "The OpenAPI document contains no supported operations", 422)
    operation_ids = [operation["operation_id"] for operation in operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise AppError("invalid_openapi", "OpenAPI operationId values must be unique", 422)
    if len(json.dumps(operations, ensure_ascii=False)) > 200_000:
        raise AppError(
            "openapi_analysis_too_large",
            "The normalized operations exceed the MVP analysis limit of 200,000 characters",
            413,
        )
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ParsedOpenApi(
        title=info["title"][:240],
        version=version,
        document=document,
        operations=operations,
        checksum=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
