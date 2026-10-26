import hashlib
import re
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.errors import (
    AIProviderError,
    AppError,
    NotFoundError,
    ReviewNotApprovedError,
    StaleVersionError,
)
from app.models import ApiContractReview, ApiSpecification, RequirementReview, Story, TestCaseSet
from app.schemas import (
    ApiContractReviewContent,
    ApiOperationSummary,
    CoverageEntry,
    CoverageStatus,
    CoverageTargetType,
    ExistingCriterion,
    RequirementReviewContent,
    RequirementObligation,
    StoryCreate,
    StoryUpdate,
    TestCaseType,
    TestCaseSetContent,
)
from app.services.ai import AIProvider
from app.services.openapi_parser import is_valid_source_reference, parse_openapi
from app.services.prompts import (
    API_CONTRACT_PROMPT_VERSION,
    REVIEW_PROMPT_VERSION,
    TEST_CASE_PROMPT_VERSION,
)

def get_story(db: Session, story_id: str, with_history: bool = False) -> Story:
    query = select(Story).where(Story.id == story_id)
    if with_history:
        query = query.options(
            selectinload(Story.reviews),
            selectinload(Story.test_case_sets),
            selectinload(Story.api_specifications),
            selectinload(Story.api_contract_reviews),
        )
    story = db.scalar(query)
    if not story:
        raise NotFoundError("Story")
    return story


def list_stories(db: Session) -> list[Story]:
    return list(db.scalars(select(Story).order_by(Story.updated_at.desc())).all())


def get_api_specification(db: Session, specification_id: str) -> ApiSpecification:
    specification = db.get(ApiSpecification, specification_id)
    if not specification:
        raise NotFoundError("OpenAPI specification")
    return specification


def create_api_specification(
    db: Session, story_id: str, file_name: str, raw: bytes
) -> ApiSpecification:
    story = get_story(db, story_id)
    parsed = parse_openapi(file_name, raw)
    latest = db.scalar(
        select(ApiSpecification)
        .where(ApiSpecification.story_id == story.id, ApiSpecification.stale.is_(False))
        .order_by(ApiSpecification.version.desc())
    )
    if latest and latest.checksum == parsed.checksum:
        return latest
    version = db.scalar(
        select(func.max(ApiSpecification.version)).where(ApiSpecification.story_id == story.id)
    ) or 0
    if latest:
        latest.stale = True
        db.execute(
            update(ApiContractReview)
            .where(ApiContractReview.specification_id == latest.id)
            .values(stale=True)
        )
    db.execute(update(TestCaseSet).where(TestCaseSet.story_id == story.id).values(stale=True))
    specification = ApiSpecification(
        story_id=story.id,
        title=parsed.title,
        file_name=file_name.replace("\\", "/").rsplit("/", 1)[-1][:255],
        openapi_version=parsed.version,
        version=version + 1,
        document=parsed.document,
        operations=parsed.operations,
        checksum=parsed.checksum,
    )
    db.add(specification)
    db.commit()
    db.refresh(specification)
    return specification


def get_api_contract_review(db: Session, review_id: str) -> ApiContractReview:
    review = db.get(ApiContractReview, review_id)
    if not review:
        raise NotFoundError("API contract review")
    return review


def _validate_api_review_content(
    content: ApiContractReviewContent, specification: ApiSpecification
) -> None:
    operation_by_id = {item["operation_id"]: item for item in specification.operations}
    seen: set[str] = set()
    for finding in content.findings:
        operation = operation_by_id.get(finding.operation_id)
        if finding.id in seen:
            raise AppError("invalid_api_review", "API finding IDs must be unique", 422)
        seen.add(finding.id)
        if not operation or (finding.method.upper(), finding.path) != (
            operation["method"], operation["path"]
        ):
            raise AppError("invalid_api_review", f"{finding.id} references an unknown operation", 422)
        if (
            finding.source_reference not in operation.get("source_references", [])
            or not is_valid_source_reference(specification.document, finding.source_reference)
        ):
            raise AppError(
                "invalid_source_reference",
                f"{finding.id} must cite a valid source belonging to its operation",
                422,
            )
        declared = {int(code) for code in operation.get("responses", {}) if str(code).isdigit()}
        if set(finding.expected_status_codes) - declared:
            raise AppError("invalid_api_review", f"{finding.id} contains an undocumented status code", 422)
        if (finding.classification.value == "needs_clarification") != finding.needs_clarification:
            raise AppError(
                "invalid_api_review",
                f"{finding.id} clarification flag must match its classification",
                422,
            )
        if finding.type.value == "conflict" and not finding.story_reference:
            raise AppError(
                "invalid_api_review",
                f"{finding.id} conflict must cite the story side of the conflict",
                422,
            )


def _stable_requirement_id(criterion: ExistingCriterion) -> str:
    normalized = re.sub(r"\s+", " ", criterion.criterion.strip().casefold())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()
    return f"REQ-{digest}"


def _stable_obligation_id(requirement_id: str, text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().casefold())
    digest = hashlib.sha256(f"{requirement_id}:{normalized}".encode("utf-8")).hexdigest()[:12].upper()
    return f"OBL-{digest}"


def _normalize_requirement_ids(content: RequirementReviewContent) -> RequirementReviewContent:
    used: set[str] = set()
    items = []
    for criterion in content.existing_acceptance_criteria:
        base = _stable_requirement_id(criterion)
        identifier = base
        suffix = 2
        while identifier in used:
            identifier = f"{base}-{suffix}"
            suffix += 1
        used.add(identifier)
        obligations = criterion.obligations or [
            {"id": "", "text": criterion.criterion}
        ]
        normalized_obligations = []
        for obligation in obligations:
            text = obligation.text if hasattr(obligation, "text") else obligation["text"]
            normalized_obligations.append(
                RequirementObligation(
                    id=_stable_obligation_id(identifier, text), text=text
                )
            )
        items.append(
            criterion.model_copy(
                update={"id": identifier, "obligations": normalized_obligations}
            )
        )
    return content.model_copy(update={"existing_acceptance_criteria": items})


def _validate_requirement_review(content: RequirementReviewContent) -> None:
    identifiers: set[str] = set()
    groups = (
        content.existing_acceptance_criteria,
        content.missing_acceptance_criteria,
        content.ambiguities_and_conflicts,
        content.stakeholder_questions,
        content.edge_cases,
        content.assumptions,
        content.risks,
    )
    for item in (entry for group in groups for entry in group):
        if item.id in identifiers:
            raise AppError("invalid_requirement_review", "Requirement review IDs must be unique", 422)
        identifiers.add(item.id)
        if not item.source_reference.strip():
            raise AppError("invalid_requirement_review", f"{item.id} needs a source reference", 422)
        if isinstance(item, ExistingCriterion):
            obligation_ids = [obligation.id for obligation in item.obligations]
            if not obligation_ids or len(obligation_ids) != len(set(obligation_ids)):
                raise AppError(
                    "invalid_requirement_review",
                    f"{item.id} needs unique coverage obligations",
                    422,
                )
            if identifiers.intersection(obligation_ids):
                raise AppError(
                    "invalid_requirement_review",
                    "Requirement and obligation IDs must be unique",
                    422,
                )
            identifiers.update(obligation_ids)


def _api_review_by_key(
    db: Session, specification_id: str, idempotency_key: str
) -> ApiContractReview | None:
    return db.scalar(
        select(ApiContractReview).where(
            ApiContractReview.specification_id == specification_id,
            ApiContractReview.idempotency_key == idempotency_key,
        )
    )


def _prepare_api_contract_review(
    result: ApiContractReviewContent,
    specification: ApiSpecification,
    operations: list[ApiOperationSummary],
) -> ApiContractReviewContent:
    operation_by_id = {
        operation["operation_id"]: operation for operation in specification.operations
    }
    for finding in result.findings:
        operation = operation_by_id.get(finding.operation_id)
        if (
            operation is None
            or finding.method.upper() != operation["method"]
            or finding.path != operation["path"]
        ):
            raise AppError(
                "invalid_operation_reference",
                f"{finding.id} references an operation outside the uploaded OpenAPI document",
                422,
            )
        if (
            finding.source_reference not in operation.get("source_references", [])
            or not is_valid_source_reference(specification.document, finding.source_reference)
        ):
            raise AppError(
                "invalid_source_reference",
                f"{finding.id} source must belong to its referenced operation",
                422,
            )
        declared = {
            int(code)
            for code in operation.get("responses", {})
            if str(code).isdigit()
        }
        if set(finding.expected_status_codes) - declared:
            raise AppError(
                "undocumented_status_code",
                f"{finding.id} uses a status code not declared by its operation",
                422,
            )
    result = result.model_copy(update={"operations": operations})
    _validate_api_review_content(result, specification)
    return result


async def generate_api_contract_review(
    db: Session, specification_id: str, idempotency_key: str, ai: AIProvider
) -> ApiContractReview:
    existing = _api_review_by_key(db, specification_id, idempotency_key)
    if existing:
        return existing
    specification = get_api_specification(db, specification_id)
    story = get_story(db, specification.story_id)
    if specification.stale:
        raise StaleVersionError()
    result = await ai.review_api_contract(story, specification)
    raw_result = result.model_dump(mode="json")
    operations = [
        ApiOperationSummary(
            operation_id=operation["operation_id"],
            method=operation["method"],
            path=operation["path"],
            summary=operation.get("summary", ""),
        )
        for operation in specification.operations
    ]
    for repair_attempt in range(2):
        try:
            result = _prepare_api_contract_review(result, specification, operations)
            break
        except AppError as exc:
            if repair_attempt == 1 or not hasattr(ai, "repair_api_contract_review"):
                raise AIProviderError(
                    "API contract review failed application validation after one repair attempt",
                    provider_code=exc.details.get("provider_code", exc.code),
                ) from exc
            result = await ai.repair_api_contract_review(
                story,
                specification,
                result,
                [{"code": exc.details.get("provider_code", exc.code), "message": exc.message}],
            )
    review = ApiContractReview(
        story_id=story.id,
        specification_id=specification.id,
        story_version=story.version,
        ai_original=raw_result,
        content=result.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        model_name=ai.model_name,
        prompt_version=API_CONTRACT_PROMPT_VERSION,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def edit_api_contract_review(
    db: Session, review_id: str, content: ApiContractReviewContent
) -> ApiContractReview:
    review = get_api_contract_review(db, review_id)
    specification = get_api_specification(db, review.specification_id)
    story = get_story(db, review.story_id)
    if review.stale or specification.stale or review.story_version != story.version:
        raise StaleVersionError()
    _validate_api_review_content(content, specification)
    review.content = content.model_dump(mode="json")
    review.status = "draft"
    review.approved_at = None
    db.execute(
        update(TestCaseSet)
        .where(TestCaseSet.api_contract_review_id == review.id)
        .values(stale=True)
    )
    db.commit()
    db.refresh(review)
    return review


def approve_api_contract_review(db: Session, review_id: str) -> ApiContractReview:
    review = get_api_contract_review(db, review_id)
    specification = get_api_specification(db, review.specification_id)
    story = get_story(db, review.story_id)
    if review.stale or specification.stale or review.story_version != story.version:
        raise StaleVersionError()
    _validate_api_review_content(ApiContractReviewContent.model_validate(review.content), specification)
    review.status = "approved"
    review.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(review)
    return review


def _validate_story_size(values: dict) -> None:
    text_parts = [
        values.get("title") or "",
        values.get("description") or "",
        values.get("business_context") or "",
        *(values.get("acceptance_criteria") or []),
        *(values.get("dependencies") or []),
    ]
    actual = sum(len(part) for part in text_parts)
    if actual > settings.max_story_chars:
        raise AppError(
            "story_too_large",
            f"Story content exceeds the configured {settings.max_story_chars} character limit",
            422,
            {"actual": actual, "limit": settings.max_story_chars},
        )


def create_story(db: Session, payload: StoryCreate) -> Story:
    values = payload.model_dump()
    _validate_story_size(values)
    story = Story(**values)
    db.add(story)
    db.commit()
    db.refresh(story)
    return story


def update_story(db: Session, story_id: str, payload: StoryUpdate) -> Story:
    story = get_story(db, story_id)
    changes = payload.model_dump(exclude_unset=True)
    candidate = {
        "title": story.title,
        "description": story.description,
        "acceptance_criteria": story.acceptance_criteria,
        "business_context": story.business_context,
        "dependencies": story.dependencies,
    } | changes
    _validate_story_size(candidate)
    changed = any(getattr(story, key) != value for key, value in changes.items())
    if not changed:
        return story
    for key, value in changes.items():
        setattr(story, key, value)
    story.version += 1
    db.execute(
        update(RequirementReview).where(RequirementReview.story_id == story.id).values(stale=True)
    )
    db.execute(update(TestCaseSet).where(TestCaseSet.story_id == story.id).values(stale=True))
    db.execute(update(ApiContractReview).where(ApiContractReview.story_id == story.id).values(stale=True))
    db.commit()
    db.refresh(story)
    return story


def _review_by_key(db: Session, story_id: str, key: str) -> RequirementReview | None:
    return db.scalar(
        select(RequirementReview).where(
            RequirementReview.story_id == story_id, RequirementReview.idempotency_key == key
        )
    )


async def generate_review(
    db: Session, story_id: str, idempotency_key: str, ai: AIProvider
) -> RequirementReview:
    existing = _review_by_key(db, story_id, idempotency_key)
    if existing:
        return existing
    story = get_story(db, story_id)
    result = await ai.review_requirements(story)
    ai_original_content = result.model_dump(mode="json")
    result = _normalize_requirement_ids(result)
    _validate_requirement_review(result)
    review = RequirementReview(
        story_id=story.id,
        story_version=story.version,
        ai_original=ai_original_content,
        content=result.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        model_name=ai.model_name,
        prompt_version=REVIEW_PROMPT_VERSION,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def get_review(db: Session, review_id: str) -> RequirementReview:
    review = db.get(RequirementReview, review_id)
    if not review:
        raise NotFoundError("Requirement review")
    return review


def edit_review(
    db: Session, review_id: str, content: RequirementReviewContent
) -> RequirementReview:
    review = get_review(db, review_id)
    if review.stale:
        raise StaleVersionError()
    content = _normalize_requirement_ids(content)
    _validate_requirement_review(content)
    review.content = content.model_dump(mode="json")
    review.status = "draft"
    review.approved_at = None
    for test_set in review.test_case_sets:
        test_set.stale = True
    db.commit()
    db.refresh(review)
    return review


def approve_review(db: Session, review_id: str) -> RequirementReview:
    review = get_review(db, review_id)
    story = get_story(db, review.story_id)
    if review.stale or review.story_version != story.version:
        raise StaleVersionError()
    normalized_content = _normalize_requirement_ids(
        RequirementReviewContent.model_validate(review.content)
    )
    _validate_requirement_review(normalized_content)
    review.content = normalized_content.model_dump(mode="json")
    review.status = "approved"
    review.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(review)
    return review


def _testset_by_key(db: Session, story_id: str, key: str) -> TestCaseSet | None:
    return db.scalar(
        select(TestCaseSet).where(
            TestCaseSet.story_id == story_id, TestCaseSet.idempotency_key == key
        )
    )


def _mark_incomplete_api_cases(
    result: TestCaseSetContent, api_review: ApiContractReviewContent
) -> TestCaseSetContent:
    unresolved_findings: set[str] = set()
    valid_findings: set[str] = set()
    updated_cases = []
    language = result.language
    finding_by_id = {finding.id: finding for finding in api_review.findings}
    for case in result.test_cases:
        api_fields = (case.api_method, case.api_path, case.api_request)
        linked_findings = [finding_by_id[id_] for id_ in case.api_traceability if id_ in finding_by_id]
        operation_mismatch = bool(linked_findings) and all(api_fields) and any(
            finding.method.upper() != case.api_method.upper()
            or finding.path != case.api_path
            for finding in linked_findings
        )
        incomplete_context = case.api_traceability and not all(api_fields)
        if incomplete_context or operation_mismatch:
            unresolved_findings.update(case.api_traceability)
            clarification = (
                "Cần QA xác nhận request API: finding và operation được sinh ra không khớp nhau."
                if language == "vi" and operation_mismatch
                else "The API finding and generated operation do not match; QA must confirm this request."
                if operation_mismatch
                else "Cần QA xác nhận method, path và request API trước khi dùng test case này."
                if language == "vi"
                else "QA must confirm the API method, path, and request before this test case can be used."
            )
            updated_cases.append(
                case.model_copy(
                    update={
                        "api_method": None,
                        "api_path": None,
                        "api_request": None,
                        "expected_status_codes": [],
                        "needs_clarification": True,
                        "assumptions": list(dict.fromkeys([*case.assumptions, clarification])),
                    }
                )
            )
            continue
        if case.api_traceability and linked_findings and not case.needs_clarification:
            valid_findings.update(case.api_traceability)
        updated_cases.append(case)

    updated_coverage = []
    for entry in result.coverage_matrix:
        if (
            entry.target_type == CoverageTargetType.api_check
            and entry.target_id in unresolved_findings
            and entry.target_id not in valid_findings
        ):
            explanation = entry.explanation
            if language == "vi":
                explanation += " QA cần xác nhận method, path và request trước khi đánh dấu đã được kiểm thử."
            else:
                explanation += " QA must confirm the method, path, and request before marking this check covered."
            updated_coverage.append(
                entry.model_copy(
                    update={"status": CoverageStatus.needs_clarification, "explanation": explanation}
                )
            )
        else:
            updated_coverage.append(entry)

    if unresolved_findings:
        summary = result.coverage_summary
        if language == "vi":
            summary += " Một số kiểm tra API cần QA xác nhận request trước khi thực thi."
        else:
            summary += " Some API checks need QA to confirm the request before execution."
        return TestCaseSetContent.model_validate(
            {
                **result.model_dump(mode="json"),
                "coverage_summary": summary,
                "test_cases": [case.model_dump(mode="json") for case in updated_cases],
                "coverage_matrix": [entry.model_dump(mode="json") for entry in updated_coverage],
            }
        )
    return result


def _normalize_coverage_matrix(
    result: TestCaseSetContent,
    review: RequirementReviewContent,
    api_review: ApiContractReviewContent | None,
) -> TestCaseSetContent:
    language = result.language
    is_vi = language == "vi"
    cases = {case.id: case for case in result.test_cases}
    category_names = {category.value for category in TestCaseType}
    category_rows: dict[str, list[CoverageEntry]] = {name: [] for name in category_names}
    grouped_rows: dict[tuple[CoverageTargetType, str], list[CoverageEntry]] = {}

    for entry in result.coverage_matrix:
        if entry.target_type == CoverageTargetType.category:
            if entry.target_id in category_rows:
                category_rows[entry.target_id].append(entry)
            continue
        if entry.target_type == CoverageTargetType.acceptance_criterion:
            # Keep new coverage at independently testable obligation granularity.
            continue
        grouped_rows.setdefault((entry.target_type, entry.target_id), []).append(entry)

    required: dict[tuple[CoverageTargetType, str], str] = {
        (CoverageTargetType.requirement_obligation, obligation.id): obligation.text
        for item in review.existing_acceptance_criteria
        for obligation in item.obligations
    }
    required.update(
        {
            (CoverageTargetType.risk, risk.id): risk.title
            for risk in review.risks
            if risk.severity.value in {"high", "critical"}
        }
    )
    if api_review:
        required.update(
            {
                (CoverageTargetType.api_check, finding.id): finding.title
                for finding in api_review.findings
            }
        )

    for key, title in required.items():
        grouped_rows.setdefault(
            key,
            [
                CoverageEntry(
                    target_type=key[0],
                    target_id=key[1],
                    status=CoverageStatus.needs_clarification,
                    test_case_ids=[],
                    explanation=(
                        f"Chưa có dòng coverage cho mục tiêu: {title}."
                        if is_vi
                        else f"The model omitted a coverage row for: {title}."
                    ),
                )
            ],
        )

    normalized_rows: list[CoverageEntry] = []
    for (target_type, target_id), rows in grouped_rows.items():
        traceability_field = (
            "api_traceability" if target_type == CoverageTargetType.api_check else "requirement_traceability"
        )
        linked_ids: list[str] = []
        evidence_ids: set[str] = set()
        explanations: list[str] = []
        had_covered_row = False
        for row in rows:
            if row.explanation.strip() and row.explanation not in explanations:
                explanations.append(row.explanation)
            for case_id in row.test_case_ids:
                case = cases.get(case_id)
                if not case or target_id not in getattr(case, traceability_field):
                    continue
                if case_id not in linked_ids:
                    linked_ids.append(case_id)
                has_api_request = all((case.api_method, case.api_path, case.api_request))
                if not case.needs_clarification and (
                    target_type != CoverageTargetType.api_check or has_api_request
                ):
                    evidence_ids.add(case_id)
            if row.status == CoverageStatus.covered and any(
                case_id in evidence_ids for case_id in row.test_case_ids
            ):
                had_covered_row = True

        status = (
            CoverageStatus.covered
            if had_covered_row and evidence_ids
            else CoverageStatus.needs_clarification
        )
        if status == CoverageStatus.needs_clarification and not explanations:
            explanations.append(
                "Cần QA xác nhận mục tiêu coverage này."
                if is_vi
                else "QA clarification is required for this coverage target."
            )
        normalized_rows.append(
            CoverageEntry(
                target_type=target_type,
                target_id=target_id,
                status=status,
                test_case_ids=linked_ids,
                explanation=" ".join(explanations),
            )
        )

    for category in TestCaseType:
        matching_cases = [case for case in result.test_cases if case.type == category]
        safe_cases = [case for case in matching_cases if not case.needs_clarification]
        if safe_cases:
            status = CoverageStatus.covered
            default_explanation = (
                f"{len(safe_cases)} test case(s) cover the {category.value} category."
            )
            linked_case_ids = [case.id for case in safe_cases]
            source_explanations = [
                row.explanation
                for row in category_rows[category.value]
                if row.status == CoverageStatus.covered and row.explanation.strip()
            ]
        else:
            status = CoverageStatus.needs_clarification
            default_explanation = (
                f"Chưa có test {category.value} an toàn để chạy; cần QA xác nhận."
                if is_vi
                else f"No safe {category.value} test is available; QA clarification is required."
            )
            linked_case_ids = []
            source_explanations = [
                row.explanation
                for row in category_rows[category.value]
                if row.status == CoverageStatus.needs_clarification and row.explanation.strip()
            ]
        normalized_rows.append(
            CoverageEntry(
                target_type=CoverageTargetType.category,
                target_id=category.value,
                status=status,
                test_case_ids=linked_case_ids,
                explanation=" ".join(dict.fromkeys(source_explanations)) or default_explanation,
            )
        )

    return TestCaseSetContent.model_validate(
        {
            **result.model_dump(mode="json"),
            "coverage_matrix": [row.model_dump(mode="json") for row in normalized_rows],
        }
    )


def _validate_api_test_case_fields(content: TestCaseSetContent) -> None:
    for case in content.test_cases:
        api_fields = (case.api_method, case.api_path, case.api_request)
        if any(api_fields) and not all(api_fields):
            raise AppError(
                "invalid_test_case",
                f"{case.id} must include API method, path, and request together",
                422,
            )
        if case.api_traceability and not all(api_fields) and not case.needs_clarification:
            raise AppError(
                "invalid_test_case",
                f"{case.id} needs clarification while API request details are incomplete",
                422,
            )
        if all(api_fields) and not case.api_traceability:
            raise AppError(
                "invalid_test_case",
                f"{case.id} must trace its API request to an approved API finding",
                422,
            )


def _validate_coverage_content(content: TestCaseSetContent) -> None:
    cases = {case.id: case for case in content.test_cases}
    keys = [(entry.target_type, entry.target_id) for entry in content.coverage_matrix]
    if len(keys) != len(set(keys)):
        raise AppError("invalid_test_case_coverage", "Coverage targets must be unique", 422)

    categories = {
        entry.target_id: entry
        for entry in content.coverage_matrix
        if entry.target_type == CoverageTargetType.category
    }
    expected_categories = {category.value for category in TestCaseType}
    if set(categories) != expected_categories:
        raise AppError(
            "invalid_test_case_coverage",
            "Coverage matrix must contain exactly one row for each test category",
            422,
        )

    for entry in content.coverage_matrix:
        if not entry.explanation.strip():
            raise AppError("invalid_test_case_coverage", "Coverage rows need an explanation", 422)
        for case_id in entry.test_case_ids:
            case = cases.get(case_id)
            if not case:
                raise AppError(
                    "invalid_test_case_coverage",
                    f"Coverage references unknown test case {case_id}",
                    422,
                )
            if entry.target_type == CoverageTargetType.category:
                if case.type.value != entry.target_id:
                    raise AppError(
                        "invalid_test_case_coverage",
                        f"Test case {case_id} does not belong to category {entry.target_id}",
                        422,
                    )
            else:
                traceability = (
                    case.api_traceability
                    if entry.target_type == CoverageTargetType.api_check
                    else case.requirement_traceability
                )
                if entry.target_id not in traceability:
                    raise AppError(
                        "invalid_test_case_coverage",
                        f"Test case {case_id} does not trace to {entry.target_id}",
                        422,
                    )

        if entry.target_type == CoverageTargetType.category:
            expected_ids = {
                case.id
                for case in content.test_cases
                if case.type.value == entry.target_id and not case.needs_clarification
            }
            if set(entry.test_case_ids) != expected_ids:
                raise AppError(
                    "invalid_test_case_coverage",
                    f"Category {entry.target_id} must list all and only safe matching test cases",
                    422,
                )
            safe_case_exists = any(
                case.type.value == entry.target_id and not case.needs_clarification
                for case in content.test_cases
            )
            if (entry.status == CoverageStatus.covered) != safe_case_exists:
                raise AppError(
                    "invalid_test_case_coverage",
                    f"Category {entry.target_id} coverage status must match safe test cases",
                    422,
                )
            continue

        safe_link_exists = any(
            not cases[case_id].needs_clarification
            and (
                entry.target_type != CoverageTargetType.api_check
                or all((cases[case_id].api_method, cases[case_id].api_path, cases[case_id].api_request))
            )
            for case_id in entry.test_case_ids
        )
        if entry.status == CoverageStatus.covered and not safe_link_exists:
            raise AppError(
                "invalid_test_case_coverage",
                f"Coverage status for {entry.target_id} must match executable linked cases",
                422,
            )


def _validate_suite_targets(
    content: TestCaseSetContent,
    review: RequirementReviewContent,
    api_review: ApiContractReviewContent | None,
    legacy_requirement_ids: set[str] | None = None,
) -> None:
    requirement_ids = {
        identifier
        for item in review.existing_acceptance_criteria
        for identifier in [item.id, *(obligation.id for obligation in item.obligations)]
    }
    requirement_ids.update(legacy_requirement_ids or set())
    risk_ids = {item.id for item in review.risks}
    api_ids = {item.id for item in api_review.findings} if api_review else set()
    for case in content.test_cases:
        if set(case.requirement_traceability) - requirement_ids - risk_ids:
            raise AppError(
                "invalid_test_case_traceability",
                f"{case.id} references an unknown requirement target",
                422,
            )
        if set(case.api_traceability) - api_ids:
            raise AppError(
                "invalid_test_case_traceability",
                f"{case.id} references an unknown API finding",
                422,
            )

    required = {
        (CoverageTargetType.requirement_obligation, obligation.id)
        for item in review.existing_acceptance_criteria
        for obligation in item.obligations
    }
    required.update(
        (CoverageTargetType.risk, item.id)
        for item in review.risks
        if item.severity.value in {"high", "critical"}
    )
    required.update(
        (CoverageTargetType.api_check, item.id) for item in (api_review.findings if api_review else [])
    )
    required.update(
        (CoverageTargetType.category, category.value) for category in TestCaseType
    )
    coverage_keys = {(entry.target_type, entry.target_id) for entry in content.coverage_matrix}
    if required - coverage_keys:
        raise AppError(
            "incomplete_test_case_coverage",
            "Coverage matrix is missing required requirement, risk, API, or category targets",
            422,
            {"missing": sorted(f"{kind.value}:{target}" for kind, target in required - coverage_keys)},
        )
    allowed = (
        {(CoverageTargetType.requirement_obligation, item) for item in requirement_ids}
        | {(CoverageTargetType.risk, item) for item in risk_ids}
        | {(CoverageTargetType.api_check, item) for item in api_ids}
        | {(CoverageTargetType.category, item.value) for item in TestCaseType}
    )
    if coverage_keys - allowed:
        raise AppError(
            "invalid_test_case_coverage",
            "Coverage matrix contains targets outside the approved requirement and API reviews",
            422,
            {"unknown": sorted(f"{kind.value}:{target}" for kind, target in coverage_keys - allowed)},
        )


def _validate_test_suite_context(
    db: Session, test_set: TestCaseSet, content: TestCaseSetContent
) -> None:
    _validate_api_test_case_fields(content)
    _validate_coverage_content(content)
    review = get_review(db, test_set.review_id)
    review_content = _normalize_requirement_ids(
        RequirementReviewContent.model_validate(review.content)
    )
    _validate_requirement_review(review_content)
    normalized_review = review_content.model_dump(mode="json")
    if review.content != normalized_review:
        # Backfill stable requirement/obligation IDs for reviews created before this schema.
        review.content = normalized_review
        db.commit()
    requirement_ids = {item.id for item in review_content.existing_acceptance_criteria}
    requirement_ids.update(
        obligation.id
        for item in review_content.existing_acceptance_criteria
        for obligation in item.obligations
    )
    original_review = RequirementReviewContent.model_validate(review.ai_original)
    # Historical AI IDs remain valid traceability references for persisted drafts.
    requirement_ids.update(item.id for item in original_review.existing_acceptance_criteria)
    risk_ids = {item.id for item in review_content.risks}
    api_review = None
    specification = None
    api_ids: set[str] = set()
    if test_set.api_contract_review_id:
        api_review_row = get_api_contract_review(db, test_set.api_contract_review_id)
        specification = get_api_specification(db, api_review_row.specification_id)
        api_review = ApiContractReviewContent.model_validate(api_review_row.content)
        _validate_api_review_content(api_review, specification)
        api_ids = {item.id for item in api_review.findings}
    _validate_suite_targets(content, review_content, api_review, requirement_ids)
    for case in content.test_cases:
        if [step.order for step in case.steps] != list(range(1, len(case.steps) + 1)):
            raise AppError(
                "invalid_test_case_steps",
                f"{case.id} steps must be ordered sequentially starting at 1",
                422,
            )
        unknown_requirements = set(case.requirement_traceability) - requirement_ids - risk_ids
        unknown_api = set(case.api_traceability) - api_ids
        if unknown_requirements or unknown_api:
            raise AppError(
                "invalid_test_case_traceability",
                f"{case.id} references unknown requirement or API IDs",
                422,
                {"unknown_requirement_ids": sorted(unknown_requirements), "unknown_api_ids": sorted(unknown_api)},
            )
        if case.api_traceability:
            findings = [item for item in api_review.findings if item.id in case.api_traceability] if api_review else []
            if not findings or any(
                (finding.method.upper(), finding.path) != (case.api_method.upper(), case.api_path)
                for finding in findings
                if case.api_method and case.api_path
            ):
                raise AppError("invalid_api_traceability", f"{case.id} API traceability does not match its operation", 422)
            if case.api_method and case.api_path and specification:
                operation = next((item for item in specification.operations if (item["method"], item["path"]) == (case.api_method.upper(), case.api_path)), None)
                if not operation:
                    raise AppError("invalid_api_operation", f"{case.id} references an unknown operation", 422)
                declared = {int(code) for code in operation.get("responses", {}) if str(code).isdigit()}
                if set(case.expected_status_codes) - declared:
                    raise AppError("undocumented_status_code", f"{case.id} uses an undocumented response status", 422)


def _prepare_generated_test_suite(
    result: TestCaseSetContent,
    review: RequirementReviewContent,
    api_review: ApiContractReviewContent | None,
    specification: ApiSpecification | None,
    legacy_requirement_ids: set[str],
) -> TestCaseSetContent:
    if api_review:
        result = _mark_incomplete_api_cases(result, api_review)
    elif any(
        case.api_traceability or case.api_method or case.api_path or case.api_request
        for case in result.test_cases
    ):
        raise AIProviderError(
            "Generated test cases contain API references without an approved API review",
            provider_code="api_context_missing",
        )
    result = _normalize_coverage_matrix(result, review, api_review)
    if specification and api_review:
        findings = {finding.id: finding for finding in api_review.findings}
        operations = {
            (operation["method"], operation["path"]): operation
            for operation in specification.operations
        }
        for case in result.test_cases:
            if not case.api_traceability:
                if case.api_method or case.api_path or case.api_request:
                    raise AIProviderError(
                        "Generated API test is missing approved API finding traceability",
                        provider_code="invalid_api_traceability",
                    )
                continue
            if not set(case.api_traceability).issubset(findings):
                raise AIProviderError(
                    "Generated API test references an API finding outside the approved review",
                    provider_code="invalid_api_traceability",
                )
            if not all((case.api_method, case.api_path, case.api_request)):
                if case.needs_clarification:
                    continue
                raise AIProviderError(
                    "An API-linked test without request details must be marked needs_clarification",
                    provider_code="incomplete_api_test_case",
                )
            operation = operations.get((case.api_method.upper(), case.api_path))
            if not operation:
                raise AIProviderError(
                    "Generated API test references an operation outside the OpenAPI document",
                    provider_code="invalid_api_operation",
                )
            if any(
                findings[id_].method.upper() != case.api_method.upper()
                or findings[id_].path != case.api_path
                for id_ in case.api_traceability
            ):
                raise AIProviderError(
                    "Generated API test traceability does not match its operation",
                    provider_code="invalid_api_traceability",
                )
            declared = {
                int(code)
                for code in operation.get("responses", {})
                if str(code).isdigit()
            }
            if set(case.expected_status_codes) - declared:
                raise AIProviderError(
                    "Generated API test uses an expected status code not declared by OpenAPI",
                    provider_code="undocumented_status_code",
                )
    _validate_api_test_case_fields(result)
    _validate_coverage_content(result)
    try:
        _validate_suite_targets(result, review, api_review, legacy_requirement_ids)
    except AppError as exc:
        raise AIProviderError(exc.message, provider_code=exc.code) from exc
    return result


async def generate_test_set(
    db: Session,
    story_id: str,
    review_id: str,
    idempotency_key: str,
    ai: AIProvider,
    api_contract_review_id: str | None = None,
) -> TestCaseSet:
    existing = _testset_by_key(db, story_id, idempotency_key)
    if existing:
        return existing
    story = get_story(db, story_id)
    review = get_review(db, review_id)
    if review.story_id != story.id:
        raise ReviewNotApprovedError()
    if review.status != "approved":
        raise ReviewNotApprovedError()
    if review.stale or review.story_version != story.version:
        raise StaleVersionError()
    review_content = RequirementReviewContent.model_validate(review.content)
    current_api_spec = db.scalar(
        select(ApiSpecification)
        .where(ApiSpecification.story_id == story.id, ApiSpecification.stale.is_(False))
        .order_by(ApiSpecification.version.desc())
    )
    if current_api_spec and not api_contract_review_id:
        raise AppError(
            "api_review_not_approved",
            "An approved current API contract review is required for this story's OpenAPI specification",
            409,
        )
    api_contract_review = None
    api_review_content = None
    api_specification = None
    if api_contract_review_id:
        api_contract_review = get_api_contract_review(db, api_contract_review_id)
        api_specification = get_api_specification(db, api_contract_review.specification_id)
        if api_contract_review.story_id != story.id:
            raise ReviewNotApprovedError()
        if api_contract_review.status != "approved":
            raise AppError("api_review_not_approved", "A current approved API contract review is required", 409)
        if (
            api_contract_review.stale
            or api_specification.stale
            or (current_api_spec is not None and api_specification.id != current_api_spec.id)
            or api_contract_review.story_version != story.version
        ):
            raise StaleVersionError()
        api_review_content = ApiContractReviewContent.model_validate(api_contract_review.content)
        result = await ai.generate_test_cases(story, review_content, api_review_content, api_specification)
    else:
        result = await ai.generate_test_cases(story, review_content)
    ai_original_content = result.model_dump(mode="json")
    original_review = RequirementReviewContent.model_validate(review.ai_original)
    legacy_requirement_ids = {
        item.id for item in original_review.existing_acceptance_criteria
    }
    for repair_attempt in range(2):
        try:
            result = _prepare_generated_test_suite(
                result,
                review_content,
                api_review_content,
                api_specification,
                legacy_requirement_ids,
            )
            break
        except AppError as exc:
            if repair_attempt == 1 or not hasattr(ai, "repair_test_cases"):
                raise AIProviderError(
                    "Generated test suite failed application validation after one repair attempt",
                    provider_code=exc.details.get("provider_code", exc.code),
                ) from exc
            issues = [
                {
                    "code": exc.details.get("provider_code", exc.code),
                    "message": exc.message,
                    "details": exc.details,
                }
            ]
            result = await ai.repair_test_cases(
                story,
                review_content,
                api_review_content,
                api_specification,
                result,
                issues,
            )
    test_set = TestCaseSet(
        story_id=story.id,
        review_id=review.id,
        api_contract_review_id=api_contract_review.id if api_contract_review else None,
        story_version=story.version,
        ai_original=ai_original_content,
        content=result.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        model_name=ai.model_name,
        prompt_version=TEST_CASE_PROMPT_VERSION,
        generation_info={
            "review_prompt_version": review.prompt_version,
            "api_contract_review_id": api_contract_review.id if api_contract_review else None,
            "api_specification_id": api_specification.id if api_specification else None,
        },
    )
    db.add(test_set)
    db.commit()
    db.refresh(test_set)
    return test_set


def get_test_set(db: Session, test_set_id: str) -> TestCaseSet:
    test_set = db.get(TestCaseSet, test_set_id)
    if not test_set:
        raise NotFoundError("Test case set")
    return test_set


def edit_test_set(db: Session, test_set_id: str, content: TestCaseSetContent) -> TestCaseSet:
    test_set = get_test_set(db, test_set_id)
    if test_set.stale:
        raise StaleVersionError()
    _validate_test_suite_context(db, test_set, content)
    test_set.content = content.model_dump(mode="json")
    test_set.status = "draft"
    test_set.approved_at = None
    db.commit()
    db.refresh(test_set)
    return test_set


def approve_test_set(db: Session, test_set_id: str) -> TestCaseSet:
    test_set = get_test_set(db, test_set_id)
    story = get_story(db, test_set.story_id)
    review = get_review(db, test_set.review_id)
    if test_set.stale or review.stale or test_set.story_version != story.version:
        raise StaleVersionError()
    if review.status != "approved":
        raise ReviewNotApprovedError()
    approved_content = TestCaseSetContent.model_validate(test_set.content)
    _validate_test_suite_context(db, test_set, approved_content)
    current_api_spec = db.scalar(
        select(ApiSpecification)
        .where(ApiSpecification.story_id == story.id, ApiSpecification.stale.is_(False))
        .order_by(ApiSpecification.version.desc())
    )
    if current_api_spec and not test_set.api_contract_review_id:
        raise AppError(
            "api_review_not_approved",
            "An approved current API contract review is required for this story's OpenAPI specification",
            409,
        )
    if test_set.api_contract_review_id:
        api_review = get_api_contract_review(db, test_set.api_contract_review_id)
        specification = get_api_specification(db, api_review.specification_id)
        if (
            api_review.stale
            or specification.stale
            or api_review.story_version != story.version
            or (current_api_spec is not None and specification.id != current_api_spec.id)
        ):
            raise StaleVersionError()
        if api_review.status != "approved":
            raise AppError("api_review_not_approved", "A current approved API contract review is required", 409)
    test_set.status = "approved"
    test_set.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(test_set)
    return test_set
