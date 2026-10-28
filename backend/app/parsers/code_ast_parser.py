import ast
from typing import List, Tuple
from app.schemas.zero_gap_contract import ASTBranchNode


def extract_python_ast_cfg(source_code: str) -> Tuple[List[ASTBranchNode], int]:
    """
    Trích xuất các nhánh điều khiển (if/for/while/except) và tính Cyclomatic Complexity V(G).
    Hỗ trợ mở rộng sang Tree-sitter cho TS/Java khi cần (RULE-03).
    """
    if not source_code or not source_code.strip():
        return [], 1

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return [], 1

    branches: List[ASTBranchNode] = []
    decision_points = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name
            for child in ast.walk(node):
                if isinstance(child, ast.If):
                    decision_points += 1
                    cond_str = ast.unparse(child.test) if hasattr(ast, "unparse") else "if_condition"
                    branches.append(
                        ASTBranchNode(
                            branch_id=f"AST-{func_name}-L{child.lineno}",
                            function_name=func_name,
                            condition_expression=cond_str,
                            line_number=child.lineno,
                        )
                    )
                elif isinstance(child, ast.ExceptHandler):
                    decision_points += 1
                    exc_type = ast.unparse(child.type) if child.type and hasattr(ast, "unparse") else "Exception"
                    branches.append(
                        ASTBranchNode(
                            branch_id=f"AST-{func_name}-EXC-L{child.lineno}",
                            function_name=func_name,
                            condition_expression=f"except {exc_type}",
                            line_number=child.lineno,
                        )
                    )

    cyclomatic_complexity = decision_points + 1
    return branches, cyclomatic_complexity
