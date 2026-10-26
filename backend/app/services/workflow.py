import logging
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
    RequirementReviewContent,
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

logger = logging.getLogger(__name__)


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


def _api_review_by_key(
    db: Session, specification_id: str, idempotency_key: str
) -> ApiContractReview | None:
    return db.scalar(
        select(ApiContractReview).where(
            ApiContractReview.specification_id == specification_id,
            ApiContractReview.idempotency_key == idempotency_key,
        )
    )


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
    operations = [
        ApiOperationSummary(
            operation_id=operation["operation_id"],
            method=operation["method"],
            path=operation["path"],
            summary=operation.get("summary", ""),
        )
        for operation in specification.operations
    ]
    operation_by_id = {operation["operation_id"]: operation for operation in specification.operations}
    for finding in result.findings:
        operation = operation_by_id.get(finding.operation_id)
        if (
            operation is None
            or finding.method.upper() != operation["method"]
            or finding.path != operation["path"]
        ):
            raise AIProviderError(
                "Gemini returned a finding for an operation outside the uploaded OpenAPI document",
                provider_code="invalid_operation_reference",
            )
        if not is_valid_source_reference(specification.document, finding.source_reference):
            # Gemini may cite a path into a dereferenced schema that only exists in the
            # normalized prompt, not in the original uploaded document. Keep the finding
            # reviewable by anchoring it to the known-valid operation pointer.
            logger.warning(
                "Normalizing invalid OpenAPI source reference for finding %s, operation %s",
                finding.id,
                finding.operation_id,
            )
            finding.source_reference = operation["source_reference"]
        declared_statuses = {
            int(code) for code in operation.get("responses", {}) if str(code).isdigit()
        }
        if set(finding.expected_status_codes) - declared_statuses:
            raise AIProviderError(
                "Gemini returned an expected status code not declared by OpenAPI",
                provider_code="undocumented_status_code",
            )
    result = result.model_copy(update={"operations": operations})
    review = ApiContractReview(
        story_id=story.id,
        specification_id=specification.id,
        story_version=story.version,
        ai_original=result.model_dump(mode="json"),
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
    review = RequirementReview(
        story_id=story.id,
        story_version=story.version,
        ai_original=result.model_dump(mode="json"),
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
    story: Story,
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
        grouped_rows.setdefault((entry.target_type, entry.target_id), []).append(entry)

    required: dict[tuple[CoverageTargetType, str], str] = {
        (CoverageTargetType.acceptance_criterion, f"AC-{index:03d}"): criterion
        for index, criterion in enumerate(story.acceptance_criteria, start=1)
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
        result = await ai.generate_test_cases(story, review_content, api_review_content)
    else:
        result = await ai.generate_test_cases(story, review_content)
    ai_original_content = result.model_dump(mode="json")
    if api_review_content:
        result = _mark_incomplete_api_cases(result, api_review_content)
    elif any(
        case.api_traceability or case.api_method or case.api_path or case.api_request
        for case in result.test_cases
    ):
        raise AIProviderError(
            "Generated test cases contain API references without an approved API review",
            provider_code="api_context_missing",
        )
    result = _normalize_coverage_matrix(result, story, review_content, api_review_content)
    if api_specification and api_review_content:
        api_findings = {finding.id: finding for finding in api_review_content.findings}
        api_finding_ids = set(api_findings)
        operations = {
            (operation["method"], operation["path"]): operation
            for operation in api_specification.operations
        }
        for case in result.test_cases:
            if not case.api_traceability:
                if case.api_method or case.api_path or case.api_request:
                    raise AIProviderError(
                        "Generated API test is missing approved API finding traceability",
                        provider_code="invalid_api_traceability",
                    )
                continue
            if not set(case.api_traceability).issubset(api_finding_ids):
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
                api_findings[finding_id].method.upper() != case.api_method.upper()
                or api_findings[finding_id].path != case.api_path
                for finding_id in case.api_traceability
            ):
                raise AIProviderError(
                    "Generated API test traceability does not match its operation",
                    provider_code="invalid_api_traceability",
                )
            declared_statuses = {
                int(code) for code in operation.get("responses", {}) if str(code).isdigit()
            }
            if set(case.expected_status_codes) - declared_statuses:
                raise AIProviderError(
                    "Generated API test uses an expected status code not declared by OpenAPI",
                    provider_code="undocumented_status_code",
                )
    coverage = {
        (entry.target_type, entry.target_id): entry for entry in result.coverage_matrix
    }
    required_targets = {
        (CoverageTargetType.acceptance_criterion, f"AC-{index:03d}")
        for index, _ in enumerate(story.acceptance_criteria, start=1)
    }
    required_targets.update(
        (CoverageTargetType.category, category)
        for category in ("positive", "negative", "boundary", "integration")
    )
    if api_review_content:
        required_targets.update(
            (CoverageTargetType.api_check, finding.id)
            for finding in api_review_content.findings
        )
    required_targets.update(
        (CoverageTargetType.risk, risk.id)
        for risk in review_content.risks
        if risk.severity.value in {"high", "critical"}
    )
    if required_targets - coverage.keys():
        raise AIProviderError(
            "Generated test suite omitted required coverage targets",
            provider_code="incomplete_coverage",
        )
    _validate_api_test_case_fields(result)
    _validate_coverage_content(result)
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
    _validate_api_test_case_fields(content)
    _validate_coverage_content(content)
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
    _validate_api_test_case_fields(approved_content)
    _validate_coverage_content(approved_content)
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
