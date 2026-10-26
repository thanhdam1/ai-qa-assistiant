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


def _resolve(
    value: Any,
    document: dict[str, Any],
    stack: tuple[str, ...] = (),
    openapi_version: str = "3.1.0",
    schema_context: bool = False,
) -> Any:
    if isinstance(value, list):
        return [_resolve(item, document, stack, openapi_version, schema_context) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if ref:
        if ref in stack:
            return {"$ref": ref, "recursive_reference": True}
        target = _pointer_value(document, ref)
        resolved = _resolve(target, document, (*stack, ref), openapi_version, schema_context)
        if isinstance(resolved, dict):
            siblings = {key: item for key, item in value.items() if key != "$ref"}
            if schema_context and openapi_version.startswith("3.1."):
                return resolved | _resolve(siblings, document, stack, openapi_version, True)
            if not schema_context and openapi_version.startswith("3.1."):
                allowed = {key: item for key, item in siblings.items() if key in {"summary", "description"}}
                return resolved | _resolve(allowed, document, stack, openapi_version, False)
            return resolved
        return resolved
    return {
        key: _resolve(
            item,
            document,
            stack,
            openapi_version,
            schema_context or key in {"schema", "schemas", "items", "properties", "additionalProperties"},
        )
        for key, item in value.items()
    }


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _merge_parameters(path_parameters: Any, operation_parameters: Any) -> list[dict[str, Any]]:
    """Apply OpenAPI operation-level parameter overrides by (name, in)."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for parameter in path_parameters if isinstance(path_parameters, list) else []:
        if isinstance(parameter, dict) and isinstance(parameter.get("name"), str) and isinstance(parameter.get("in"), str):
            merged[(parameter["name"], parameter["in"])] = parameter
    for parameter in operation_parameters if isinstance(operation_parameters, list) else []:
        if isinstance(parameter, dict) and isinstance(parameter.get("name"), str) and isinstance(parameter.get("in"), str):
            merged[(parameter["name"], parameter["in"])] = parameter
    return list(merged.values())


def _resolve_path_item(
    value: dict[str, Any], document: dict[str, Any], version: str, stack: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Path Item $ref has its own sibling/merge semantics, separate from Reference Object."""
    ref = value.get("$ref")
    base: dict[str, Any] = {}
    if isinstance(ref, str):
        if ref in stack:
            raise ValueError(f"Cyclic Path Item reference: {ref}")
        target = _pointer_value(document, ref)
        if not isinstance(target, dict):
            raise ValueError(f"Path Item reference must resolve to an object: {ref}")
        base = _resolve_path_item(target, document, version, (*stack, ref))
    siblings = {key: item for key, item in value.items() if key != "$ref"}
    resolved_siblings = _resolve(siblings, document, openapi_version=version)
    return base | resolved_siblings


def _path_item_operation_source(
    value: dict[str, Any],
    pointer: str,
    method: str,
    document: dict[str, Any],
    stack: tuple[str, ...] = (),
) -> tuple[dict[str, Any] | None, str | None]:
    local = value.get(method)
    if isinstance(local, dict):
        return local, f"{pointer}/{method}"
    ref = value.get("$ref")
    if isinstance(ref, str) and ref not in stack:
        target = _pointer_value(document, ref)
        if isinstance(target, dict):
            return _path_item_operation_source(
                target, ref, method, document, (*stack, ref)
            )
    return None, None


def _path_item_field_source(
    value: dict[str, Any],
    pointer: str,
    field: str,
    document: dict[str, Any],
    stack: tuple[str, ...] = (),
) -> str | None:
    if field in value:
        return f"{pointer}/{field}"
    ref = value.get("$ref")
    if isinstance(ref, str) and ref not in stack:
        target = _pointer_value(document, ref)
        if isinstance(target, dict):
            return _path_item_field_source(target, ref, field, document, (*stack, ref))
    return None


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
            resolved_path_item = _resolve_path_item(path_item, document, version)
            for method, operation in resolved_path_item.items():
                method = method.lower()
                if method not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                path_pointer = f"#/paths/{_escape_pointer(path)}"
                raw_operation, operation_pointer = _path_item_operation_source(
                    path_item, path_pointer, method, document
                )
                if raw_operation is None:
                    raw_operation = operation
                    operation_pointer = f"{path_pointer}/{method}"
                pointer = operation_pointer
                resolved = _resolve(operation, document, openapi_version=version)
                raw_path_parameters = path_item.get(
                    "parameters", resolved_path_item.get("parameters", [])
                )
                path_parameters_pointer = _path_item_field_source(
                    path_item, path_pointer, "parameters", document
                )
                raw_operation_parameters = raw_operation.get("parameters", []) if isinstance(raw_operation, dict) else []
                path_parameters = _resolve(raw_path_parameters, document, openapi_version=version)
                operation_parameters = _resolve(resolved.get("parameters", []), document, openapi_version=version)
                effective_parameters = _merge_parameters(path_parameters, operation_parameters)

                if isinstance(raw_operation, dict) and "servers" in raw_operation:
                    servers = _resolve(raw_operation["servers"], document, openapi_version=version)
                    servers_source_pointer = f"{pointer}/servers"
                elif "servers" in resolved_path_item:
                    servers = _resolve(resolved_path_item["servers"], document, openapi_version=version)
                    servers_source_pointer = _path_item_field_source(
                        path_item, path_pointer, "servers", document
                    )
                elif "servers" in document:
                    servers = _resolve(document["servers"], document, openapi_version=version)
                    servers_source_pointer = "#/servers"
                else:
                    servers = []
                    servers_source_pointer = None

                if isinstance(raw_operation, dict) and "security" in raw_operation:
                    security = _resolve(raw_operation["security"], document, openapi_version=version)
                    security_source_pointer = f"{pointer}/security"
                elif "security" in document:
                    security = _resolve(document["security"], document, openapi_version=version)
                    security_source_pointer = "#/security"
                else:
                    security = []
                    security_source_pointer = None
                security_schemes = _resolve(components.get("securitySchemes", {}), document, openapi_version=version)
                security_source_references = (
                    {security_source_pointer} if security_source_pointer else set()
                )
                if security_source_pointer:
                    security_source_references.update(
                        _collect_source_references(document, security, security_source_pointer)
                    )
                for requirement in security if isinstance(security, list) else []:
                    if isinstance(requirement, dict):
                        for scheme_name in requirement:
                            if scheme_name not in components.get("securitySchemes", {}):
                                raise ValueError(
                                    f"Unresolved security scheme: {scheme_name}"
                                )
                            scheme_pointer = (
                                f"#/components/securitySchemes/{_escape_pointer(str(scheme_name))}"
                            )
                            security_source_references.update(
                                _collect_source_references(
                                    document,
                                    components["securitySchemes"][scheme_name],
                                    scheme_pointer,
                                )
                            )

                source_references = _collect_source_references(
                    document, raw_operation, pointer
                )
                if "$ref" in path_item:
                    source_references.update(
                        _collect_source_references(document, path_item, path_pointer)
                    )
                elif "parameters" in path_item:
                    source_references.update(
                        _collect_source_references(
                            document, path_item["parameters"], f"{path_pointer}/parameters"
                        )
                    )
                if isinstance(raw_operation, dict) and "parameters" in raw_operation:
                    source_references.update(
                        _collect_source_references(
                            document, raw_operation["parameters"], f"{pointer}/parameters"
                        )
                    )
                source_references.update(
                    _collect_source_references(document, security, security_source_pointer)
                    if security_source_pointer
                    else set()
                )
                source_references.update(security_source_references)
                source_references.update(
                    _collect_source_references(document, servers, servers_source_pointer)
                    if servers_source_pointer
                    else set()
                )
                if "securitySchemes" in components:
                    source_references.update(
                        _collect_source_references(
                            document,
                            components["securitySchemes"],
                            "#/components/securitySchemes",
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
                        "parameters": effective_parameters,
                        "parameters_source_references": sorted(
                            (
                                _collect_source_references(
                                    document,
                                    _pointer_value(document, path_parameters_pointer),
                                    path_parameters_pointer,
                                )
                                if path_parameters_pointer
                                else set()
                            )
                            | (
                                _collect_source_references(
                                    document,
                                    raw_operation_parameters,
                                    f"{pointer}/parameters",
                                )
                                if isinstance(raw_operation, dict)
                                and "parameters" in raw_operation
                                else set()
                            )
                        ),
                        "request_body": _resolve(resolved.get("requestBody"), document, openapi_version=version),
                        "responses": _resolve(resolved.get("responses", {}), document, openapi_version=version),
                        "security": security,
                        "security_schemes": security_schemes,
                        "security_source_references": sorted(security_source_references),
                        "servers": servers,
                        "servers_source_references": sorted(
                            _collect_source_references(document, servers, servers_source_pointer)
                            if servers_source_pointer
                            else set()
                        ),
                        "openapi_version": version,
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
