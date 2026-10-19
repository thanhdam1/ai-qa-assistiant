import json
import yaml
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class APIParameter(BaseModel):
    name: str
    in_location: str = Field(description="path, query, header, or cookie")
    required: bool = False
    param_type: str = "string"
    description: Optional[str] = None
    default: Optional[Any] = None

class APIRequestBody(BaseModel):
    content_type: str = "application/json"
    required: bool = False
    properties: Dict[str, Any] = Field(default_factory=dict)
    required_fields: List[str] = Field(default_factory=list)
    schema_ref: Optional[str] = None

class APIResponse(BaseModel):
    status_code: str
    description: str = ""
    content_type: Optional[str] = "application/json"
    schema_details: Dict[str, Any] = Field(default_factory=dict)

class APIEndpoint(BaseModel):
    path: str
    method: str
    operation_id: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    parameters: List[APIParameter] = Field(default_factory=list)
    request_body: Optional[APIRequestBody] = None
    responses: List[APIResponse] = Field(default_factory=list)

class ParsedOpenAPI(BaseModel):
    title: str
    version: str
    description: Optional[str] = None
    base_url: Optional[str] = None
    endpoints: List[APIEndpoint] = Field(default_factory=list)
    schemas: Dict[str, Any] = Field(default_factory=dict)

class OpenAPIParser:
    """
    Parses OpenAPI / Swagger v3 specifications (JSON or YAML)
    into structured models for QA test case generation and synthetic data generation.
    """

    @classmethod
    def parse_spec(cls, content: str, is_yaml: bool = False) -> ParsedOpenAPI:
        if is_yaml:
            spec = yaml.safe_load(content)
        else:
            try:
                spec = json.loads(content)
            except json.JSONDecodeError:
                # Try fallback to YAML
                spec = yaml.safe_load(content)

        info = spec.get("info", {})
        title = info.get("title", "API Specification")
        version = info.get("version", "1.0.0")
        description = info.get("description", "")
        
        servers = spec.get("servers", [])
        base_url = servers[0].get("url") if servers else None
        
        components = spec.get("components", {})
        schemas = components.get("schemas", {})

        endpoints: List[APIEndpoint] = []
        paths = spec.get("paths", {})

        for path_url, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
                
            for method, operation in path_item.items():
                if method.lower() not in ["get", "post", "put", "patch", "delete", "options", "head"]:
                    continue
                if not isinstance(operation, dict):
                    continue

                operation_id = operation.get("operationId", f"{method.lower()}_{path_url.replace('/', '_')}")
                summary = operation.get("summary", "")
                op_description = operation.get("description", "")
                tags = operation.get("tags", [])

                # Parameters
                parameters: List[APIParameter] = []
                raw_params = operation.get("parameters", []) + path_item.get("parameters", [])
                for p in raw_params:
                    if not isinstance(p, dict):
                        continue
                    schema = p.get("schema", {})
                    parameters.append(APIParameter(
                        name=p.get("name", ""),
                        in_location=p.get("in", "query"),
                        required=p.get("required", False),
                        param_type=schema.get("type", "string"),
                        description=p.get("description", ""),
                        default=schema.get("default")
                    ))

                # Request Body
                request_body: Optional[APIRequestBody] = None
                raw_body = operation.get("requestBody", {})
                if raw_body and isinstance(raw_body, dict):
                    body_content = raw_body.get("content", {})
                    for content_type, media_type in body_content.items():
                        schema = media_type.get("schema", {})
                        
                        # Resolve $ref if present
                        properties = {}
                        required_fields = []
                        if "$ref" in schema:
                            ref_name = schema["$ref"].split("/")[-1]
                            ref_schema = schemas.get(ref_name, {})
                            properties = ref_schema.get("properties", {})
                            required_fields = ref_schema.get("required", [])
                        else:
                            properties = schema.get("properties", {})
                            required_fields = schema.get("required", [])

                        request_body = APIRequestBody(
                            content_type=content_type,
                            required=raw_body.get("required", False),
                            properties=properties,
                            required_fields=required_fields,
                            schema_ref=schema.get("$ref")
                        )
                        break  # Take primary media type

                # Responses
                responses: List[APIResponse] = []
                raw_responses = operation.get("responses", {})
                for status_code, resp_data in raw_responses.items():
                    if not isinstance(resp_data, dict):
                        continue
                    resp_desc = resp_data.get("description", "")
                    resp_content = resp_data.get("content", {})
                    resp_schema = {}
                    primary_content_type = "application/json"
                    
                    if resp_content:
                        for ct, media in resp_content.items():
                            primary_content_type = ct
                            resp_schema = media.get("schema", {})
                            break

                    responses.append(APIResponse(
                        status_code=str(status_code),
                        description=resp_desc,
                        content_type=primary_content_type,
                        schema_details=resp_schema
                    ))

                endpoints.append(APIEndpoint(
                    path=path_url,
                    method=method.upper(),
                    operation_id=operation_id,
                    summary=summary,
                    description=op_description,
                    tags=tags,
                    parameters=parameters,
                    request_body=request_body,
                    responses=responses
                ))

        return ParsedOpenAPI(
            title=title,
            version=version,
            description=description,
            base_url=base_url,
            endpoints=endpoints,
            schemas=schemas
        )
