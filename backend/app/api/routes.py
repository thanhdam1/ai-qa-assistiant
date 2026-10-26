from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ApiContractReviewContent,
    ApiContractReviewRead,
    ApiSpecificationRead,
    RequirementReviewRead,
    ReviewUpdate,
    StoryCreate,
    StoryRead,
    StoryUpdate,
    StoryWorkspace,
    TestCaseSetCreate,
    TestCaseSetRead,
    TestCaseSetUpdate,
)
from app.services.ai import AIProvider, get_ai_provider
from app.services.export import api_contract_review_csv, json_bytes, review_csv, test_set_csv
from app.services.workflow import (
    approve_api_contract_review,
    approve_review,
    approve_test_set,
    create_api_specification,
    create_story,
    edit_api_contract_review,
    edit_review,
    edit_test_set,
    generate_review,
    generate_api_contract_review,
    generate_test_set,
    get_review,
    get_api_contract_review,
    get_story,
    get_test_set,
    list_stories,
    update_story,
)

router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_db)]
AI = Annotated[AIProvider, Depends(get_ai_provider)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/stories", response_model=StoryRead, status_code=status.HTTP_201_CREATED)
def stories_create(payload: StoryCreate, db: Db):
    return create_story(db, payload)


@router.get("/stories", response_model=list[StoryRead])
def stories_list(db: Db):
    return list_stories(db)


@router.get("/stories/{story_id}", response_model=StoryWorkspace)
def stories_get(story_id: str, db: Db):
    return get_story(db, story_id, with_history=True)


@router.patch("/stories/{story_id}", response_model=StoryRead)
def stories_update(story_id: str, payload: StoryUpdate, db: Db):
    return update_story(db, story_id, payload)


@router.post(
    "/stories/{story_id}/api-specifications",
    response_model=ApiSpecificationRead,
    status_code=status.HTTP_201_CREATED,
)
async def api_specifications_upload(story_id: str, db: Db, file: UploadFile = File(...)):
    raw = await file.read(1_000_001)
    return create_api_specification(db, story_id, file.filename or "openapi.json", raw)


@router.post(
    "/api-specifications/{specification_id}/contract-reviews",
    response_model=ApiContractReviewRead,
    status_code=status.HTTP_201_CREATED,
)
async def api_contract_reviews_generate(
    specification_id: str, db: Db, ai: AI, idempotency_key: IdempotencyKey
):
    return await generate_api_contract_review(db, specification_id, idempotency_key, ai)


@router.patch("/api-contract-reviews/{review_id}", response_model=ApiContractReviewRead)
def api_contract_reviews_update(
    review_id: str, payload: ApiContractReviewContent, db: Db
):
    return edit_api_contract_review(db, review_id, payload)


@router.post("/api-contract-reviews/{review_id}/approve", response_model=ApiContractReviewRead)
def api_contract_reviews_approve(review_id: str, db: Db):
    return approve_api_contract_review(db, review_id)


@router.get("/api-contract-reviews/{review_id}/export")
def api_contract_reviews_export(
    review_id: str, db: Db, format: Literal["json", "csv"] = Query("json")
):
    review = get_api_contract_review(db, review_id)
    body = json_bytes(review.content) if format == "json" else api_contract_review_csv(review)
    media = "application/json" if format == "json" else "text/csv; charset=utf-8"
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="api-contract-review-{review.id}.{format}"'
        },
    )


@router.post(
    "/stories/{story_id}/requirement-reviews",
    response_model=RequirementReviewRead,
    status_code=status.HTTP_201_CREATED,
)
async def requirement_reviews_generate(
    story_id: str, db: Db, ai: AI, idempotency_key: IdempotencyKey
):
    return await generate_review(db, story_id, idempotency_key, ai)


@router.patch("/requirement-reviews/{review_id}", response_model=RequirementReviewRead)
def requirement_reviews_update(review_id: str, payload: ReviewUpdate, db: Db):
    return edit_review(db, review_id, payload.content)


@router.post("/requirement-reviews/{review_id}/approve", response_model=RequirementReviewRead)
def requirement_reviews_approve(review_id: str, db: Db):
    return approve_review(db, review_id)


@router.get("/requirement-reviews/{review_id}/export")
def requirement_reviews_export(
    review_id: str, db: Db, format: Literal["json", "csv"] = Query("json")
):
    review = get_review(db, review_id)
    body = json_bytes(review.content) if format == "json" else review_csv(review)
    media = "application/json" if format == "json" else "text/csv; charset=utf-8"
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="requirement-review-{review.id}.{format}"'
        },
    )


@router.post(
    "/stories/{story_id}/test-case-sets",
    response_model=TestCaseSetRead,
    status_code=status.HTTP_201_CREATED,
)
async def test_case_sets_generate(
    story_id: str, payload: TestCaseSetCreate, db: Db, ai: AI, idempotency_key: IdempotencyKey
):
    return await generate_test_set(
        db,
        story_id,
        payload.review_id,
        idempotency_key,
        ai,
        api_contract_review_id=payload.api_contract_review_id,
    )


@router.patch("/test-case-sets/{test_set_id}", response_model=TestCaseSetRead)
def test_case_sets_update(test_set_id: str, payload: TestCaseSetUpdate, db: Db):
    return edit_test_set(db, test_set_id, payload.content)


@router.post("/test-case-sets/{test_set_id}/approve", response_model=TestCaseSetRead)
def test_case_sets_approve(test_set_id: str, db: Db):
    return approve_test_set(db, test_set_id)


@router.get("/test-case-sets/{test_set_id}/export")
def test_case_sets_export(test_set_id: str, db: Db, format: Literal["json", "csv"] = Query("json")):
    test_set = get_test_set(db, test_set_id)
    body = json_bytes(test_set.content) if format == "json" else test_set_csv(test_set)
    media = "application/json" if format == "json" else "text/csv; charset=utf-8"
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="test-cases-{test_set.id}.{format}"'
        },
    )
    create_api_specification,
    edit_api_contract_review,
    generate_api_contract_review,
