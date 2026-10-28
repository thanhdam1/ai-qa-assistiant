from typing import List, Optional
from sqlalchemy.orm import Session
from app.engine.coverage_gate import run_zero_gap_pipeline
from app.engine.gap_detector import detect_gaps_and_conflicts
from app.errors import AppError
from app.models import Story
from app.parsers.code_ast_parser import extract_python_ast_cfg
from app.parsers.openapi_bva import generate_8_partition_bva
from app.parsers.srs_decomposer import decompose_user_story
from app.schemas.zero_gap_contract import (
    CanonicalTestContract,
    ZeroGapSuiteResponse,
)


def build_canonical_contract_for_story(
    db: Session,
    story_id: str,
    source_code: Optional[str] = None,
) -> CanonicalTestContract:
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise AppError("story_not_found", "Story not found", 404)

    # 1. Tách Atomic Requirements từ Story & AC
    story_text_parts = [
        f"Title: {story.title}",
        f"Description: {story.description}",
        "Acceptance Criteria:",
        *story.acceptance_criteria,
    ]
    if story.business_context:
        story_text_parts.append(f"Business Context: {story.business_context}")
    raw_story = "\n".join(story_text_parts)
    requirements = decompose_user_story(raw_story, module_prefix="REQ")

    # 2. Sinh ma trận 8 phân vùng BVA nếu có OpenAPI spec
    bva_matrix = []
    active_spec = next((s for s in story.api_specifications if not s.stale), None)
    if not active_spec and story.api_specifications:
        active_spec = story.api_specifications[0]
    if active_spec and active_spec.document:
        bva_matrix = generate_8_partition_bva(active_spec.document)

    # 3. Phân tích AST & Cyclomatic Complexity nếu có source code (3-Way Mode)
    ast_branches = []
    complexity = 1
    mode = "2-way"
    if source_code and source_code.strip():
        ast_branches, complexity = extract_python_ast_cfg(source_code)
        mode = "3-way"

    # 4. Phát hiện xung đột Spec & Shadow Logic
    conflicts = detect_gaps_and_conflicts(requirements, bva_matrix, ast_branches)

    return CanonicalTestContract(
        mode=mode,
        requirements=requirements,
        bva_matrix=bva_matrix,
        ast_branches=ast_branches,
        cyclomatic_complexity=complexity,
        spec_conflicts=conflicts,
    )


def generate_zero_gap_suite_for_story(
    db: Session,
    story_id: str,
    source_code: Optional[str] = None,
    existing_flagged_ids: Optional[List[str]] = None,
) -> ZeroGapSuiteResponse:
    contract = build_canonical_contract_for_story(db, story_id, source_code)
    flagged = set(existing_flagged_ids or [])
    return run_zero_gap_pipeline(contract, existing_flagged_ids=flagged)
