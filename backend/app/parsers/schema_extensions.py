"""
Schema Extensions Parser: AsyncAPI (Event-driven / Kafka / RabbitMQ) & GraphQL.
Expands API ingestion capabilities to support modern asynchronous and graph architectures.
"""

import re
import json
import yaml
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class GraphQLField(BaseModel):
    name: str
    field_type: str
    is_required: bool = False
    is_list: bool = False
    arguments: Dict[str, str] = Field(default_factory=dict)

class GraphQLOperation(BaseModel):
    name: str
    operation_type: str  # Query, Mutation, Subscription
    return_type: str
    arguments: Dict[str, str] = Field(default_factory=dict)
    description: Optional[str] = None

class ParsedGraphQLSchema(BaseModel):
    title: str = "GraphQL Schema"
    types: Dict[str, List[GraphQLField]] = Field(default_factory=dict)
    queries: List[GraphQLOperation] = Field(default_factory=list)
    mutations: List[GraphQLOperation] = Field(default_factory=list)
    subscriptions: List[GraphQLOperation] = Field(default_factory=list)

class AsyncChannelOperation(BaseModel):
    channel_name: str
    operation_type: str  # publish, subscribe
    message_name: str
    summary: Optional[str] = None
    payload_schema: Dict[str, Any] = Field(default_factory=dict)

class ParsedAsyncAPISpec(BaseModel):
    title: str = "AsyncAPI Spec"
    version: str = "2.6.0"
    channels: List[AsyncChannelOperation] = Field(default_factory=list)

class SchemaExtensionParser:
    """
    Parses GraphQL Schema Definition Language (SDL) and AsyncAPI specifications.
    """

    @classmethod
    def parse_graphql(cls, sdl_content: str, title: str = "GraphQL API") -> ParsedGraphQLSchema:
        schema = ParsedGraphQLSchema(title=title)
        
        # Clean comments
        lines = [line.strip() for line in sdl_content.splitlines() if not line.strip().startswith("#")]
        clean_text = "\n".join(lines)

        # 1. Parse types
        type_blocks = re.findall(r"type\s+([A-Za-z0-9_]+)\s*\{([^}]+)\}", clean_text)
        for type_name, body in type_blocks:
            fields = []
            for field_line in body.strip().splitlines():
                field_line = field_line.strip()
                if not field_line or field_line.startswith("#"):
                    continue
                # field(args): Type!
                f_match = re.match(r"([A-Za-z0-9_]+)(?:\(([^)]*)\))?\s*:\s*(\[?[A-Za-z0-9_!]+\]?!?)(?:.*)", field_line)
                if f_match:
                    fname, fargs, ftype = f_match.groups()
                    is_req = "!" in ftype
                    is_lst = "[" in ftype
                    clean_ftype = ftype.replace("!", "").replace("[", "").replace("]", "").strip()

                    parsed_args = {}
                    if fargs:
                        for arg_item in fargs.split(","):
                            if ":" in arg_item:
                                aname, atype = arg_item.split(":", 1)
                                parsed_args[aname.strip()] = atype.strip()

                    field_obj = GraphQLField(
                        name=fname,
                        field_type=clean_ftype,
                        is_required=is_req,
                        is_list=is_lst,
                        arguments=parsed_args
                    )

                    if type_name == "Query":
                        schema.queries.append(GraphQLOperation(
                            name=fname,
                            operation_type="Query",
                            return_type=ftype,
                            arguments=parsed_args
                        ))
                    elif type_name == "Mutation":
                        schema.mutations.append(GraphQLOperation(
                            name=fname,
                            operation_type="Mutation",
                            return_type=ftype,
                            arguments=parsed_args
                        ))
                    elif type_name == "Subscription":
                        schema.subscriptions.append(GraphQLOperation(
                            name=fname,
                            operation_type="Subscription",
                            return_type=ftype,
                            arguments=parsed_args
                        ))
                    else:
                        fields.append(field_obj)

            if type_name not in ["Query", "Mutation", "Subscription"]:
                schema.types[type_name] = fields

        return schema

    @classmethod
    def parse_asyncapi(cls, content: str) -> ParsedAsyncAPISpec:
        try:
            raw = json.loads(content)
        except Exception:
            raw = yaml.safe_load(content) or {}

        info = raw.get("info", {})
        title = info.get("title", "Event-Driven AsyncAPI")
        version = info.get("version", "1.0.0")
        channels_dict = raw.get("channels", {})

        channels_list: List[AsyncChannelOperation] = []

        for ch_name, ch_data in channels_dict.items():
            for op_type in ["publish", "subscribe"]:
                if op_type in ch_data:
                    op = ch_data[op_type]
                    msg = op.get("message", {})
                    payload = msg.get("payload", {})
                    channels_list.append(AsyncChannelOperation(
                        channel_name=ch_name,
                        operation_type=op_type,
                        message_name=msg.get("name") or f"{ch_name}_{op_type}_message",
                        summary=op.get("summary") or msg.get("title"),
                        payload_schema=payload
                    ))

        return ParsedAsyncAPISpec(
            title=title,
            version=version,
            channels=channels_list
        )
