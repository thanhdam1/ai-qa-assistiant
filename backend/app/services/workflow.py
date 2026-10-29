import json
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
    CoverageDecisionInput,
    CoverageAcceptanceInput,
    CaseReadinessInput,
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
from app.services.identity import acceptance_criterion_sources, criterion_source_id, fingerprint, normalized_text
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
            selectinload(Story.upstream_dependencies),
            selectinload(Story.downstream_dependencies),
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


def _stable_requirement_id(criterion: ExistingCriterion, source_id: str | None = None) -> str:
    return f"REQ-{fingerprint(source_id or normalized_text(criterion.criterion))}"


def _stable_obligation_id(requirement_id: str, text: str, single_source_rule: bool = False) -> str:
    key = "single" if single_source_rule else normalized_text(text)
    return f"OBL-{fingerprint(f'{requirement_id}:{key}')}"


def _normalize_requirement_ids(
    content: RequirementReviewContent,
    story: Story | None = None,
    previous: RequirementReviewContent | None = None,
) -> RequirementReviewContent:
    """Assign identities once, then retain approved identities and increment revisions."""
    previous_items = previous.existing_acceptance_criteria if previous else []
    previous_by_id = {item.id: item for item in previous_items}
    previous_by_source = {
        item.source_id: item for item in previous_items if item.source_id
    }
    used: set[str] = set()
    items = []
    for criterion in content.existing_acceptance_criteria:
        source_id = criterion_source_id(criterion, story)
        prior_by_claimed_id = previous_by_id.get(criterion.id)
        if (
            prior_by_claimed_id
            and source_id
            and prior_by_claimed_id.source_id
            and prior_by_claimed_id.source_id != source_id
        ):
            prior_by_claimed_id = None
        prior = prior_by_claimed_id or (
            previous_by_source.get(source_id) if source_id else None
        )
        if prior:
            source_id = source_id or prior.source_id
        base = (
            prior.id
            if prior
            else criterion.id
            if story is None and criterion.id.startswith("REQ-")
            else _stable_requirement_id(criterion, source_id)
        )
        identifier = base
        suffix = 2
        while identifier in used:
            identifier = f"{base}-{suffix}"
            suffix += 1
        used.add(identifier)
        revision = (
            prior.revision + (normalized_text(prior.criterion) != normalized_text(criterion.criterion))
            if prior
            else criterion.revision if criterion.id == identifier else 1
        )
        obligations = criterion.obligations or [{"id": "", "text": criterion.criterion}]
        prior_obligations = prior.obligations if prior else []
        prior_by_id = {item.id: item for item in prior_obligations}
        prior_by_text = {normalized_text(item.text): item for item in prior_obligations}
        normalized_obligations = []
        obligation_ids: set[str] = set()
        for obligation in obligations:
            text = obligation.text if hasattr(obligation, "text") else obligation["text"]
            candidate_id = obligation.id if hasattr(obligation, "id") else obligation.get("id", "")
            prior_obligation = prior_by_id.get(candidate_id) or prior_by_text.get(
                normalized_text(text)
            )
            if (
                prior_obligation is None
                and prior
                and len(prior_obligations) == len(obligations) == 1
                and prior.source_id == source_id
            ):
                prior_obligation = prior_obligations[0]
            obligation_id = (
                prior_obligation.id
                if prior_obligation
                else candidate_id
                if story is None and candidate_id.startswith("OBL-")
                else _stable_obligation_id(
                    identifier, text, single_source_rule=bool(source_id) and len(obligations) == 1
                )
            )
            suffix = 2
            base_obligation_id = obligation_id
            while obligation_id in obligation_ids:
                obligation_id = f"{base_obligation_id}-{suffix}"
                suffix += 1
            obligation_ids.add(obligation_id)
            obligation_revision = (
                prior_obligation.revision
                + (normalized_text(prior_obligation.text) != normalized_text(text))
                if prior_obligation
                else 1
            )
            supersedes = (
                list(prior_obligation.supersedes)
                if prior_obligation
                else [prior_obligations[0].id]
                if prior and len(prior_obligations) == 1 and len(obligations) > 1
                else []
            )
            normalized_obligations.append(
                RequirementObligation(
                    id=obligation_id,
                    text=text,
                    revision=obligation_revision,
                    supersedes=supersedes,
                )
            )
        items.append(
            criterion.model_copy(
                update={
                    "id": identifier,
                    "source_id": source_id,
                    "revision": revision,
                    "obligations": normalized_obligations,
                }
            )
        )
    return content.model_copy(update={"existing_acceptance_criteria": items})


def _validate_requirement_review(content: RequirementReviewContent, story: Story | None = None) -> None:
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
    if story is not None:
        required_sources = {item["source_id"] for item in acceptance_criterion_sources(story)}
        source_ids = [
            item.source_id for item in content.existing_acceptance_criteria
            if item.source_id in required_sources
        ]
        if len(source_ids) != len(set(source_ids)):
            raise AppError(
                "duplicate_requirement_source",
                "Each source acceptance criterion must have one review entry",
                422,
            )
        covered_sources = {
            item.source_id for item in content.existing_acceptance_criteria if item.source_id
        }
        missing = required_sources - covered_sources
        if missing:
            raise AppError(
                "incomplete_requirement_review",
                "Every source acceptance criterion needs an anchored review entry",
                422,
                {"missing_source_ids": sorted(missing)},
            )


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
    prior_row = db.scalar(
        select(RequirementReview)
        .where(
            RequirementReview.story_id == story.id,
            RequirementReview.story_version == story.version,
        )
        .order_by(RequirementReview.created_at.desc())
    )
    prior_content = (
        RequirementReviewContent.model_validate(prior_row.content) if prior_row else None
    )
    result = _normalize_requirement_ids(result, story, prior_content)
    # Keep incomplete AI output as a draft so QA can repair omissions before approval.
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
    story = get_story(db, review.story_id)
    if review.story_version != story.version:
        raise StaleVersionError()
    content = _normalize_requirement_ids(
        content, story, RequirementReviewContent.model_validate(review.content)
    )
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
    stored_content = RequirementReviewContent.model_validate(review.content)
    normalized_content = _normalize_requirement_ids(stored_content, story, stored_content)
    _validate_requirement_review(normalized_content, story)
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


def _quarantine_untraced_api_cases(
    result: TestCaseSetContent,
) -> tuple[TestCaseSetContent, list[str]]:
    """Keep unsupported API assertions visible as blocked QA drafts, never as ready tests."""
    blocked_ids: list[str] = []
    updated_cases = []
    for case in result.test_cases:
        if case.api_traceability or not any(
            (case.api_method, case.api_path, case.api_request, case.expected_status_codes)
        ):
            updated_cases.append(case)
            continue
        blocked_ids.append(case.id)
        proposal = " ".join(
            str(part) for part in (case.api_method, case.api_path) if part
        )
        if case.expected_status_codes:
            proposal += f" status={case.expected_status_codes}"
        note = (
            f"QA cần xác nhận liên kết API cho đề xuất {proposal.strip()}. "
            "Bản AI gốc được giữ để đối chiếu."
            if result.language == "vi"
            else f"QA must confirm the API finding for proposed {proposal.strip()}. "
            "The original AI output is retained for audit."
        )
        pending = (
            "Cần QA xác nhận kỳ vọng API. Đề xuất AI chưa xác minh: "
            if result.language == "vi"
            else "QA must confirm the API expectation. Unverified AI proposal: "
        )
        updated_cases.append(
            case.model_copy(
                update={
                    "api_method": None,
                    "api_path": None,
                    "api_request": None,
                    "expected_status_codes": [],
                    "needs_clarification": True,
                    "expected_result": pending + case.expected_result,
                    "assumptions": list(dict.fromkeys([*case.assumptions, note])),
                }
            )
        )
    if not blocked_ids:
        return result, []
    return result.model_copy(update={"test_cases": updated_cases}), blocked_ids


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
        assertion_evidence = []
        unverified_aspects: list[str] = []
        explanations: list[str] = []
        had_covered_row = False
        for row in rows:
            if row.explanation.strip() and row.explanation not in explanations:
                explanations.append(row.explanation)
            for aspect in row.unverified_aspects:
                if aspect not in unverified_aspects:
                    unverified_aspects.append(aspect)
            for evidence in row.assertion_evidence:
                case = cases.get(evidence.test_case_id)
                if (
                    case
                    and evidence.test_case_id in row.test_case_ids
                    and evidence.test_case_id not in [item.test_case_id for item in assertion_evidence]
                    and evidence.assertion in [case.expected_result, *(step.expected_result for step in case.steps)]
                ):
                    assertion_evidence.append(evidence)
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
            if had_covered_row and evidence_ids and any(
                item.test_case_id in evidence_ids for item in assertion_evidence
            ) and not unverified_aspects
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
                assertion_evidence=assertion_evidence,
                unverified_aspects=unverified_aspects,
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

        for evidence in entry.assertion_evidence:
            case = cases.get(evidence.test_case_id)
            if not case or evidence.test_case_id not in entry.test_case_ids:
                raise AppError(
                    "invalid_coverage_evidence",
                    f"Coverage evidence for {entry.target_id} must quote a linked test assertion",
                    422,
                )
            candidates = [case.expected_result, *(step.expected_result for step in case.steps)]
            norm_assertion = evidence.assertion.strip().lower()
            is_matched = any(
                norm_assertion == c.strip().lower()
                or norm_assertion in c.lower()
                or (len(c.strip()) > 5 and c.strip().lower() in norm_assertion)
                for c in candidates
                if c
            )
            if not is_matched:
                raise AppError(
                    "invalid_coverage_evidence",
                    f"Coverage evidence for {entry.target_id} must quote a linked test assertion",
                    422,
                )
        if entry.status == CoverageStatus.covered and entry.unverified_aspects:
            raise AppError(
                "incomplete_coverage_assertion",
                f"Coverage target {entry.target_id} still has unverified aspects",
                422,
            )
        if (
            entry.target_type != CoverageTargetType.category
            and entry.status == CoverageStatus.covered
            and not any(
                evidence.test_case_id in entry.test_case_ids
                and not cases[evidence.test_case_id].needs_clarification
                for evidence in entry.assertion_evidence
            )
        ):
            raise AppError(
                "missing_coverage_assertion",
                f"Covered target {entry.target_id} needs an assertion from an executable linked test",
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


def validate_test_suite(
    content: TestCaseSetContent,
    review: RequirementReviewContent,
    api_review: ApiContractReviewContent | None,
    specification: ApiSpecification | None,
    legacy_requirement_ids: set[str] | None = None,
) -> None:
    _validate_api_test_case_fields(content)
    _validate_coverage_content(content)
    _validate_suite_targets(content, review, api_review, legacy_requirement_ids)
    if api_review and specification:
        _validate_api_review_content(api_review, specification)
    findings = {item.id: item for item in api_review.findings} if api_review else {}
    operations = (
        {(item["method"], item["path"]): item for item in specification.operations}
        if specification
        else {}
    )
    for case in content.test_cases:
        if [step.order for step in case.steps] != list(range(1, len(case.steps) + 1)):
            raise AppError(
                "invalid_test_case_steps",
                f"{case.id} steps must be ordered sequentially starting at 1",
                422,
            )
        if not case.api_traceability:
            if case.expected_status_codes:
                raise AppError(
                    "invalid_test_case",
                    f"{case.id} has API status codes without API finding traceability",
                    422,
                )
            continue
        if not all((case.api_method, case.api_path, case.api_request)):
            # An explicitly blocked case may retain its finding link without an invented request.
            continue
        if any(
            (findings[item_id].method.upper(), findings[item_id].path)
            != (case.api_method.upper(), case.api_path)
            for item_id in case.api_traceability
        ):
            raise AppError(
                "invalid_api_traceability",
                f"{case.id} API finding traceability does not match its operation",
                422,
            )
        operation = operations.get((case.api_method.upper(), case.api_path))
        if not operation:
            raise AppError(
                "invalid_api_operation", f"{case.id} references an unknown operation", 422
            )
        declared = {int(code) for code in operation.get("responses", {}) if str(code).isdigit()}
        if set(case.expected_status_codes) - declared:
            raise AppError(
                "undocumented_status_code",
                f"{case.id} uses an undocumented response status",
                422,
            )


def _validate_test_suite_context(
    db: Session, test_set: TestCaseSet, content: TestCaseSetContent
) -> None:
    review_row = get_review(db, test_set.review_id)
    story = get_story(db, test_set.story_id)
    stored_review = RequirementReviewContent.model_validate(review_row.content)
    review = _normalize_requirement_ids(stored_review, story, stored_review)
    _validate_requirement_review(review, story)
    original = RequirementReviewContent.model_validate(review_row.ai_original)
    legacy_ids = {item.id for item in original.existing_acceptance_criteria}
    api_review = None
    specification = None
    if test_set.api_contract_review_id:
        api_row = get_api_contract_review(db, test_set.api_contract_review_id)
        specification = get_api_specification(db, api_row.specification_id)
        api_review = ApiContractReviewContent.model_validate(api_row.content)
    validate_test_suite(content, review, api_review, specification, legacy_ids)


def _prepare_generated_test_suite(
    result: TestCaseSetContent,
    review: RequirementReviewContent,
    api_review: ApiContractReviewContent | None,
    specification: ApiSpecification | None,
    legacy_requirement_ids: set[str],
) -> TestCaseSetContent:
    result = _normalize_coverage_matrix(result, review, api_review)
    validate_test_suite(result, review, api_review, specification, legacy_requirement_ids)
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
    stored_review = RequirementReviewContent.model_validate(review.content)
    review_content = _normalize_requirement_ids(stored_review, story, stored_review)
    _validate_requirement_review(review_content, story)
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
    validation_failures: list[dict] = []
    quarantined_case_ids: list[str] = []
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
            issue = {"code": exc.code, "message": exc.message, "details": exc.details}
            validation_failures.append(issue)
            logger.warning(
                "Generated test suite validation failed (attempt=%s, code=%s, message=%s, details=%s)",
                repair_attempt + 1, exc.code, exc.message, exc.details,
            )
            if repair_attempt == 1:
                quarantined, blocked_ids = _quarantine_untraced_api_cases(result)
                if blocked_ids:
                    logger.warning(
                        "Quarantined untraced API assertions after repair (case_ids=%s)",
                        blocked_ids,
                    )
                    try:
                        result = _prepare_generated_test_suite(
                            quarantined, review_content, api_review_content,
                            api_specification, legacy_requirement_ids,
                        )
                        quarantined_case_ids.extend(blocked_ids)
                        break
                    except AppError as remaining:
                        exc = remaining
                        validation_failures.append({
                            "code": exc.code, "message": exc.message, "details": exc.details,
                        })
            if repair_attempt == 1 or not hasattr(ai, "repair_test_cases"):
                detail_text = (
                    f"; details={json.dumps(exc.details, ensure_ascii=False)}"
                    if exc.details else ""
                )
                raise AIProviderError(
                    "Generated test suite failed application validation after one repair attempt: "
                    f"{exc.code}: {exc.message}{detail_text}",
                    provider_code=exc.details.get("provider_code", exc.code),
                    validation_details={"failures": validation_failures},
                ) from exc
            issues = [issue]
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
            "quarantined_api_case_ids": quarantined_case_ids,
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
    test_set.content_version += 1
    test_set.coverage_decisions = []
    test_set.case_readiness = []
    test_set.coverage_accepted_at = None
    test_set.coverage_accepted_by = None
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


def _current_assessment_source(db: Session, test_set: TestCaseSet) -> RequirementReview:
    story = get_story(db, test_set.story_id)
    review = get_review(db, test_set.review_id)
    if test_set.stale or review.stale or story.version != test_set.story_version or review.status != "approved":
        raise StaleVersionError()
    if test_set.api_contract_review_id:
        api_review = get_api_contract_review(db, test_set.api_contract_review_id)
        specification = get_api_specification(db, api_review.specification_id)
        if api_review.stale or specification.stale or api_review.status != "approved":
            raise StaleVersionError()
        if (test_set.generation_info or {}).get("api_specification_id") != specification.id:
            raise StaleVersionError()
    return review


def _decision_key(item: dict) -> tuple[str, str]:
    return item["target_type"], item["target_id"]


def decide_coverage_target(
    db: Session, test_set_id: str, payload: CoverageDecisionInput
) -> TestCaseSet:
    test_set = get_test_set(db, test_set_id)
    if not payload.decided_by.strip():
        raise AppError("decision_actor_required", "A QA decision needs a name", 422)
    review = _current_assessment_source(db, test_set)
    content = TestCaseSetContent.model_validate(test_set.content)
    _validate_test_suite_context(db, test_set, content)
    key = (payload.target_type.value, payload.target_id)
    row = next(
        (item for item in content.coverage_matrix if (item.target_type.value, item.target_id) == key),
        None,
    )
    if row is None or payload.target_type == CoverageTargetType.category:
        raise AppError("unknown_coverage_target", "Select a requirement, risk, or API finding target", 422)
    reason = (payload.reason or "").strip()
    owner = (payload.owner or "").strip()
    assertion = (payload.assertion or "").strip()
    if payload.disposition == "confirmed":
        evidence = next(
            (item for item in row.assertion_evidence
             if item.test_case_id == payload.assertion_case_id and item.assertion == assertion),
            None,
        )
        case = next((item for item in content.test_cases if item.id == payload.assertion_case_id), None)
        if (
            row.status != CoverageStatus.covered or row.unverified_aspects or not evidence
            or not case or case.needs_clarification
        ):
            raise AppError(
                "coverage_evidence_unconfirmed",
                "Confirm an existing linked assertion from a case without clarification gaps",
                422,
            )
    else:
        if not reason:
            raise AppError("gap_reason_required", "A gap decision needs a reason", 422)
        if payload.disposition == "deferred" and not owner:
            raise AppError("gap_owner_required", "Deferred coverage needs an owner", 422)
        if payload.disposition in {"accepted_risk", "not_applicable"}:
            severity = None
            if payload.target_type == CoverageTargetType.risk:
                risk = next((item for item in review.content.get("risks", []) if item["id"] == payload.target_id), None)
                severity = risk.get("severity") if risk else None
            elif payload.target_type == CoverageTargetType.api_check and test_set.api_contract_review_id:
                api_review = get_api_contract_review(db, test_set.api_contract_review_id)
                finding = next((item for item in api_review.content.get("findings", []) if item["id"] == payload.target_id), None)
                severity = finding.get("severity") if finding else None
            if severity in {"high", "critical"}:
                raise AppError(
                    "risk_acceptance_requires_authority",
                    "High or critical risk waiver requires verified authority; this MVP has no identity verification",
                    403,
                )
    decision = {
        "target_type": key[0], "target_id": key[1], "disposition": payload.disposition,
        "decided_by": payload.decided_by.strip(), "decided_at": datetime.now(UTC).isoformat(),
        "assertion_case_id": payload.assertion_case_id if payload.disposition == "confirmed" else None,
        "assertion": assertion if payload.disposition == "confirmed" else None,
        "reason": reason or None, "owner": owner or None,
        "story_version": test_set.story_version, "review_id": test_set.review_id,
        "api_contract_review_id": test_set.api_contract_review_id,
        "api_specification_id": (test_set.generation_info or {}).get("api_specification_id"),
        "content_version": test_set.content_version,
    }
    test_set.coverage_decisions = [
        item for item in (test_set.coverage_decisions or []) if _decision_key(item) != key
    ] + [decision]
    test_set.coverage_accepted_at = None
    test_set.coverage_accepted_by = None
    db.commit()
    db.refresh(test_set)
    return test_set


def accept_coverage(
    db: Session, test_set_id: str, payload: CoverageAcceptanceInput
) -> TestCaseSet:
    test_set = get_test_set(db, test_set_id)
    if not payload.accepted_by.strip():
        raise AppError("decision_actor_required", "Coverage acceptance needs a name", 422)
    _current_assessment_source(db, test_set)
    if test_set.status != "approved":
        raise AppError("content_review_required", "QA must approve the suite content first", 409)
    content = TestCaseSetContent.model_validate(test_set.content)
    _validate_test_suite_context(db, test_set, content)
    targets = {
        (item.target_type.value, item.target_id)
        for item in content.coverage_matrix if item.target_type != CoverageTargetType.category
    }
    decisions = {
        _decision_key(item): item for item in (test_set.coverage_decisions or [])
        if item.get("story_version") == test_set.story_version
        and item.get("review_id") == test_set.review_id
        and item.get("api_contract_review_id") == test_set.api_contract_review_id
        and item.get("api_specification_id") == (test_set.generation_info or {}).get("api_specification_id")
        and item.get("content_version") == test_set.content_version
    }
    missing = sorted(f"{kind}:{target}" for kind, target in targets - decisions.keys())
    if missing:
        raise AppError(
            "coverage_decisions_incomplete",
            "Every coverage target needs QA-confirmed assertion evidence or an explicit gap decision",
            409, {"missing": missing},
        )
    test_set.coverage_accepted_at = datetime.now(UTC)
    test_set.coverage_accepted_by = payload.accepted_by.strip()
    db.commit()
    db.refresh(test_set)
    return test_set


def assess_case_readiness(
    db: Session, test_set_id: str, case_id: str, payload: CaseReadinessInput
) -> TestCaseSet:
    test_set = get_test_set(db, test_set_id)
    if not payload.assessed_by.strip():
        raise AppError("decision_actor_required", "Readiness assessment needs a name", 422)
    _current_assessment_source(db, test_set)
    content = TestCaseSetContent.model_validate(test_set.content)
    case = next((item for item in content.test_cases if item.id == case_id), None)
    if case is None:
        raise AppError("unknown_test_case", f"Unknown test case {case_id}", 404)
    if case.needs_clarification and all((payload.environment_ready, payload.test_data_ready, payload.verification_ready)):
        raise AppError("case_needs_clarification", "Resolve test case clarification before marking it runnable", 422)
    assessment = {
        "case_id": case_id, **payload.model_dump(),
        "assessed_at": datetime.now(UTC).isoformat(),
        "story_version": test_set.story_version, "content_version": test_set.content_version,
    }
    test_set.case_readiness = [
        item for item in (test_set.case_readiness or []) if item.get("case_id") != case_id
    ] + [assessment]
    db.commit()
    db.refresh(test_set)
    return test_set
