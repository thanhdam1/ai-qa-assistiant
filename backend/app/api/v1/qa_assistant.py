from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import io

from app.parsers.prd_parser import PRDParser
from app.parsers.openapi_parser import OpenAPIParser
from app.agents.test_case_agent import TestCaseGenerator, TestSuite
from app.agents.rtm_agent import RTMAgent, RTMMatrix
from app.agents.synthetic_data import SyntheticDataGenerator, SyntheticDataset
from app.agents.export_service import ExportService
from app.agents.pom_codegen_agent import POMCodeGenerator, POMTestSuite

router = APIRouter()

class GenerateTestRequest(BaseModel):
    prd_content: str = Field(description="Raw markdown or text content of the PRD/SRS/User Stories")
    filename: Optional[str] = "Feature_PRD.md"
    openapi_spec: Optional[str] = Field(default=None, description="Optional Swagger/OpenAPI JSON/YAML spec")

class GenerateTestResponse(BaseModel):
    test_suite: TestSuite
    rtm_matrix: RTMMatrix

@router.post("/generate-test-cases", response_model=GenerateTestResponse, summary="Generate Test Cases & RTM from PRD")
def generate_test_cases(request: GenerateTestRequest):
    if not request.prd_content.strip():
        raise HTTPException(status_code=400, detail="PRD content cannot be empty.")

    # 1. Parse PRD
    prd = PRDParser.parse_markdown(request.prd_content, filename=request.filename)

    # 2. Parse OpenAPI if provided
    api_spec = None
    if request.openapi_spec and request.openapi_spec.strip():
        try:
            api_spec = OpenAPIParser.parse_spec(request.openapi_spec)
        except Exception:
            pass

    # 3. Synthesize Test Suite
    test_suite = TestCaseGenerator.generate_from_prd(prd, api_spec=api_spec)

    # 4. Construct Requirements Traceability Matrix (RTM)
    rtm_matrix = RTMAgent.build_matrix(prd, test_suite)

    return GenerateTestResponse(
        test_suite=test_suite,
        rtm_matrix=rtm_matrix
    )

class SyntheticDataRequest(BaseModel):
    schema_definition: Dict[str, Any] = Field(description="OpenAPI Schema properties object")
    endpoint_path: Optional[str] = "/api/resource"
    method: Optional[str] = "POST"

@router.post("/synthetic-data", response_model=SyntheticDataset, summary="Generate Synthetic Test Fixtures")
def generate_synthetic_data(request: SyntheticDataRequest):
    if not request.schema_definition:
        raise HTTPException(status_code=400, detail="Schema definition must not be empty.")

    return SyntheticDataGenerator.generate_for_schema(
        schema=request.schema_definition,
        endpoint_path=request.endpoint_path,
        method=request.method
    )

class GeneratePOMRequest(BaseModel):
    feature_name: str = Field(description="Name of the feature e.g. 'User Login' or 'Checkout'")
    language: Optional[str] = Field(default="python", description="Target language: python or typescript")
    prd_content: Optional[str] = None

@router.post("/generate-pom-scripts", response_model=POMTestSuite, summary="Synthesize Page Object Model Automation Scripts")
def generate_pom_scripts(request: GeneratePOMRequest):
    if not request.feature_name.strip():
        raise HTTPException(status_code=400, detail="Feature name cannot be empty.")

    test_suite = None
    if request.prd_content and request.prd_content.strip():
        prd = PRDParser.parse_markdown(request.prd_content)
        test_suite = TestCaseGenerator.generate_from_prd(prd)

    return POMCodeGenerator.generate_playwright_suite(
        feature_name=request.feature_name,
        test_suite=test_suite,
        language=request.language or "python"
    )

@router.post("/export-excel", summary="Export Test Suite to Excel (.xlsx)")
def export_excel(test_suite: TestSuite):
    excel_bytes = ExportService.to_excel_bytes(test_suite)
    filename = f"{test_suite.feature_title.replace(' ', '_')}_TestCases.xlsx"

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.post("/export-csv", summary="Export Test Suite to CSV")
def export_csv(test_suite: TestSuite):
    csv_str = ExportService.to_csv(test_suite)
    filename = f"{test_suite.feature_title.replace(' ', '_')}_TestCases.csv"

    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
