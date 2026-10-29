import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["OPENAI_API_KEY"] = "test-key"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, get_db
from app.main import app
from app.schemas import (
    ApiContractReviewContent,
    ApiOperationSummary,
    ExistingCriterion,
    RequirementReviewContent,
    ReviewItem,
    TestCase,
    TestCaseSetContent,
    TestStep,
)
from app.services.ai import get_ai_provider


def finding(item_id: str, title: str = "Finding") -> ReviewItem:
    return ReviewItem(
        id=item_id,
        title=title,
        detail="Concrete detail",
        severity="high",
        source_reference="Story description",
    )


@pytest.fixture
def review_content() -> RequirementReviewContent:
    return RequirementReviewContent(
        language="vi",
        business_summary="Người dùng đăng nhập bằng email.",
        existing_acceptance_criteria=[
            ExistingCriterion(
                id="AC-001", criterion="Đăng nhập thành công", source_reference="AC 1"
            )
        ],
        missing_acceptance_criteria=[finding("MAC-001")],
        ambiguities_and_conflicts=[finding("AMB-001")],
        stakeholder_questions=[finding("QUE-001")],
        edge_cases=[finding("EDG-001")],
        assumptions=[finding("ASM-001")],
        risks=[finding("RSK-001")],
    )


@pytest.fixture
def test_content() -> TestCaseSetContent:
    cases = []
    for index, kind in enumerate(("positive", "negative", "boundary", "integration"), 1):
        cases.append(
            TestCase(
                id=f"TC-{index:03}",
                title=f"{kind} case",
                objective="Verify behavior",
                type=kind,
                priority="high",
                preconditions=["User exists"],
                test_data=["sample"],
                steps=[
                    TestStep(order=1, action="Perform action", expected_result="System responds")
                ],
                expected_result="Expected behavior occurs",
                requirement_traceability=["AC-001"],
                assumptions=[],
                needs_clarification=kind == "integration",
            )
        )
    return TestCaseSetContent(
        language="vi", coverage_summary="Covers four categories", test_cases=cases
    )


@pytest.fixture
def client(review_content, test_content):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    class FakeAI:
        model_name = "fake-model"

        async def review_requirements(self, _story):
            return review_content

        async def generate_test_cases(self, _story, _review, _api_review=None, _specification=None):
            return test_content

        async def review_api_contract(self, _story, specification):
            ops = [
                ApiOperationSummary(
                    operation_id=op["operation_id"],
                    method=op["method"],
                    path=op["path"],
                    summary=op.get("summary", ""),
                )
                for op in specification.operations
            ]
            return ApiContractReviewContent(
                language="vi",
                summary="API review summary",
                operations=ops,
                findings=[],
            )

    def db_override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_ai_provider] = lambda: FakeAI()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
