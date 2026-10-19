import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import tree_sitter_languages

class CodeChunk(BaseModel):
    chunk_id: str
    file_path: str
    language: str
    node_type: str  # class_declaration, method_declaration, interface_declaration, function_declaration
    name: str
    parent_name: Optional[str] = None
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str] = None
    content: str
    imports: List[str] = Field(default_factory=list)
    calls: List[str] = Field(default_factory=list)

class ASTParser:
    """
    Advanced Polyglot AST Code Parser using Tree-sitter.
    Parses C# (.NET), Java (Spring Boot), TypeScript/JavaScript (React), and Python codebases.
    Preserves class and function scopes, docstrings, imports, and method call graphs.
    """

    LANGUAGE_MAP = {
        ".cs": "c_sharp",
        ".java": "java",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".py": "python",
    }

    CLASS_NODE_TYPES = {
        "c_sharp": ["class_declaration", "interface_declaration", "record_declaration", "struct_declaration"],
        "java": ["class_declaration", "interface_declaration", "record_declaration", "enum_declaration"],
        "typescript": ["class_declaration", "interface_declaration"],
        "javascript": ["class_declaration"],
        "python": ["class_definition"],
    }

    FUNCTION_NODE_TYPES = {
        "c_sharp": ["method_declaration", "constructor_declaration"],
        "java": ["method_declaration", "constructor_declaration"],
        "typescript": ["method_definition", "function_declaration", "arrow_function"],
        "javascript": ["method_definition", "function_declaration", "arrow_function"],
        "python": ["function_definition"],
    }

    @classmethod
    def detect_language(cls, file_path: str) -> Optional[str]:
        _, ext = os.path.splitext(file_path.lower())
        return cls.LANGUAGE_MAP.get(ext)

    @classmethod
    def get_parser(cls, language: str):
        try:
            return tree_sitter_languages.get_parser(language)
        except Exception as e:
            raise ValueError(f"Tree-sitter parser not supported for language '{language}': {e}")

    @classmethod
    def parse_code(cls, code: str, file_path: str, language: Optional[str] = None) -> List[CodeChunk]:
        if not language:
            language = cls.detect_language(file_path)
            if not language:
                # Default fallback or unrecognized
                return [
                    CodeChunk(
                        chunk_id=f"{file_path}_raw",
                        file_path=file_path,
                        language="plain_text",
                        node_type="file",
                        name=os.path.basename(file_path),
                        start_line=1,
                        end_line=len(code.splitlines()),
                        signature=os.path.basename(file_path),
                        content=code,
                    )
                ]

        parser = cls.get_parser(language)
        code_bytes = code.encode("utf-8")
        tree = parser.parse(code_bytes)
        root_node = tree.root_node

        # Extract file-level imports
        file_imports = cls._extract_imports(root_node, code_bytes, language)

        chunks: List[CodeChunk] = []
        cls._traverse_node(root_node, code_bytes, file_path, language, file_imports, parent_name=None, chunks=chunks)

        # Fallback if no specific functions/classes detected (e.g. small script)
        if not chunks:
            chunks.append(
                CodeChunk(
                    chunk_id=f"{file_path}_full",
                    file_path=file_path,
                    language=language,
                    node_type="module",
                    name=os.path.basename(file_path),
                    start_line=1,
                    end_line=len(code.splitlines()),
                    signature=f"File: {os.path.basename(file_path)}",
                    content=code,
                    imports=file_imports,
                )
            )

        return chunks

    @classmethod
    def _extract_imports(cls, root_node, code_bytes: bytes, language: str) -> List[str]:
        imports = []
        for child in root_node.children:
            text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
            if language == "c_sharp" and child.type in ["using_directive"]:
                imports.append(text)
            elif language == "java" and child.type in ["import_declaration", "package_declaration"]:
                imports.append(text)
            elif language in ["typescript", "javascript"] and child.type in ["import_statement"]:
                imports.append(text)
            elif language == "python" and child.type in ["import_statement", "import_from_statement"]:
                imports.append(text)
        return imports

    @classmethod
    def _traverse_node(
        cls,
        node,
        code_bytes: bytes,
        file_path: str,
        language: str,
        imports: List[str],
        parent_name: Optional[str],
        chunks: List[CodeChunk]
    ):
        class_types = cls.CLASS_NODE_TYPES.get(language, [])
        func_types = cls.FUNCTION_NODE_TYPES.get(language, [])

        if node.type in class_types:
            name = cls._extract_identifier(node, code_bytes) or "AnonymousClass"
            signature = cls._extract_signature(node, code_bytes)
            content = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            
            chunk_id = f"{file_path}#{name}"
            chunks.append(
                CodeChunk(
                    chunk_id=chunk_id,
                    file_path=file_path,
                    language=language,
                    node_type=node.type,
                    name=name,
                    parent_name=parent_name,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=signature,
                    content=content,
                    imports=imports,
                )
            )

            # Traverse child methods inside class
            for child in node.children:
                cls._traverse_node(child, code_bytes, file_path, language, imports, parent_name=name, chunks=chunks)
            return

        elif node.type in func_types:
            name = cls._extract_identifier(node, code_bytes) or "anonymous_function"
            signature = cls._extract_signature(node, code_bytes)
            content = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            calls = cls._extract_function_calls(node, code_bytes)
            
            prefix = f"{parent_name}." if parent_name else ""
            chunk_id = f"{file_path}#{prefix}{name}"
            
            chunks.append(
                CodeChunk(
                    chunk_id=chunk_id,
                    file_path=file_path,
                    language=language,
                    node_type=node.type,
                    name=name,
                    parent_name=parent_name,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=signature,
                    content=content,
                    imports=imports,
                    calls=calls,
                )
            )
            return

        # Continue traversing
        for child in node.children:
            cls._traverse_node(child, code_bytes, file_path, language, imports, parent_name, chunks)

    @classmethod
    def _extract_identifier(cls, node, code_bytes: bytes) -> Optional[str]:
        # Search direct identifier child
        for child in node.children:
            if child.type in ["identifier", "type_identifier", "property_identifier", "name"]:
                return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
        return None

    @classmethod
    def _extract_signature(cls, node, code_bytes: bytes) -> str:
        text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        first_line = text.splitlines()[0].strip() if text else ""
        return first_line

    @classmethod
    def _extract_function_calls(cls, node, code_bytes: bytes) -> List[str]:
        calls = set()
        stack = [node]
        while stack:
            curr = stack.pop()
            if curr.type in ["invocation_expression", "method_invocation", "call_expression"]:
                call_text = code_bytes[curr.start_byte:curr.end_byte].decode("utf-8", errors="replace").split("(")[0].strip()
                # Clean up call text
                clean_name = call_text.split("\n")[-1].strip()
                if clean_name and len(clean_name) < 80:
                    calls.add(clean_name)
            stack.extend(curr.children)
        return sorted(list(calls))
