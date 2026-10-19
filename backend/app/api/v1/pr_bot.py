import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from app.agents.codebase_agent import CodebaseArchitectureAgent

router = APIRouter()

# Re-use shared codebase agent instance
from app.api.v1.codebase_qa import codebase_agent

class PRAnalyzeRequest(BaseModel):
    pr_title: str = Field(description="Title of the pull request")
    pr_number: int = Field(default=1, description="PR Number on GitHub/GitLab")
    git_diff: str = Field(description="Raw unified git diff output from git diff main...HEAD")
    author: Optional[str] = "developer"

class ImpactedComponent(BaseModel):
    file_path: str
    modified_functions: List[str] = Field(default_factory=list)
    impacted_callers: List[str] = Field(default_factory=list)
    risk_level: str = "Medium"  # Low, Medium, High

class PRImpactResponse(BaseModel):
    pr_number: int
    pr_title: str
    total_files_changed: int
    impacted_components: List[ImpactedComponent] = Field(default_factory=list)
    recommended_regression_tests: List[str] = Field(default_factory=list)
    markdown_comment: str

DISALLOWED_KEYWORDS = {
    "if", "while", "for", "switch", "catch", "new", "await", "return",
    "using", "typeof", "sizeof", "print", "console", "assert", "throw"
}

@router.post("/analyze-impact", response_model=PRImpactResponse, summary="Analyze PR Git Diff & Suggest Regression Tests")
def analyze_pr_diff(request: PRAnalyzeRequest):
    if not request.git_diff.strip():
        raise HTTPException(status_code=400, detail="Git diff cannot be empty.")

    diff_lines = request.git_diff.splitlines()
    files_changed: Dict[str, List[str]] = {}
    current_file = None

    # Parse unified diff
    for line in diff_lines:
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].lstrip("b/")
                files_changed[current_file] = []
        elif line.startswith("+") and not line.startswith("+++"):
            clean_line = line.lstrip("+").strip()
            # Language-agnostic method detection: find identifier preceding '('
            matches = re.findall(r"\b([a-zA-Z0-9_]+)\s*\(", clean_line)
            if matches and current_file:
                for func_name in matches:
                    if func_name.lower() not in DISALLOWED_KEYWORDS and not func_name.startswith("_"):
                        if func_name not in files_changed[current_file]:
                            files_changed[current_file].append(func_name)

    impacted_list: List[ImpactedComponent] = []
    regression_tests: List[str] = []

    for f_path, funcs in files_changed.items():
        impacted_callers = []
        for func in funcs:
            callers = [
                c.chunk_id for c in codebase_agent.indexed_chunks.values()
                if func.lower() in [call.lower() for call in c.calls]
            ]
            impacted_callers.extend(callers)
            regression_tests.append(f"tests/test_{func.lower()}.py")

        risk = "High" if len(impacted_callers) > 2 or "service" in f_path.lower() else "Medium"
        if not funcs:
            risk = "Low"

        impacted_list.append(
            ImpactedComponent(
                file_path=f_path,
                modified_functions=funcs,
                impacted_callers=list(set(impacted_callers)),
                risk_level=risk
            )
        )

    if not regression_tests:
        regression_tests.append("tests/test_regression_smoke.py")

    # Generate Markdown comment for GitHub PR
    comment_lines = [
        f"### 🤖 AI QA Impact Analysis for PR #{request.pr_number}: {request.pr_title}",
        "",
        f"> **Total Files Changed:** `{len(files_changed)}` | **Impacted Components:** `{len(impacted_list)}`",
        "",
        "| File Path | Modified Methods | Callers at Risk | Risk Level |",
        "| :--- | :--- | :--- | :--- |"
    ]

    for comp in impacted_list:
        funcs_str = ", ".join(f"`{f}`" for f in comp.modified_functions) or "*Global/Config changes*"
        callers_str = ", ".join(f"`{c.split('#')[-1]}`" for c in comp.impacted_callers[:3]) or "*Direct scope only*"
        badge = "🔴 High" if comp.risk_level == "High" else ("🟡 Medium" if comp.risk_level == "Medium" else "🟢 Low")
        comment_lines.append(f"| `{comp.file_path}` | {funcs_str} | {callers_str} | {badge} |")

    comment_lines.extend([
        "",
        "#### 🎯 Recommended Regression Test Suites to Run:",
        *[f"- [ ] `{test}`" for test in set(regression_tests)],
        "",
        "---",
        "*Automated with [AI QA Assistant](https://github.com/)*"
    ])

    return PRImpactResponse(
        pr_number=request.pr_number,
        pr_title=request.pr_title,
        total_files_changed=len(files_changed),
        impacted_components=impacted_list,
        recommended_regression_tests=list(set(regression_tests)),
        markdown_comment="\n".join(comment_lines)
    )
