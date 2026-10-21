import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.llm_client import LLMClient
from app.parsers.prd_parser import ParsedPRD, UserStory
from app.parsers.openapi_parser import ParsedOpenAPI, APIEndpoint
from app.parsers.schema_extensions import ParsedGraphQLSchema, ParsedAsyncAPISpec

class TestCase(BaseModel):
    id: str = Field(description="Unique Test ID e.g. TC-01")
    title: str = Field(description="Concise description of the test scenario")
    user_story_id: Optional[str] = None
    acceptance_criteria_id: Optional[str] = None
    category: str = Field(description="Positive, Boundary Value Analysis, Equivalence Partitioning, Negative, Security, OWASP")
    priority: str = Field(default="Medium", description="Critical, High, Medium, Low")
    pre_conditions: List[str] = Field(default_factory=list)
    test_steps: List[str] = Field(default_factory=list)
    test_data: Dict[str, Any] = Field(default_factory=dict)
    expected_result: str
    actual_result: Optional[str] = None
    status: str = "Draft"

class TestSuite(BaseModel):
    feature_title: str
    summary: str
    total_test_cases: int
    test_cases: List[TestCase] = Field(default_factory=list)

class TestCaseGenerator:
    """
    Synthesizes comprehensive ISTQB-grounded Test Suites from PRD and OpenAPI specs.
    Combines Happy Path, Boundary Values, Equivalence Partitions, and OWASP Top 10 Security Cases.
    """

    @classmethod
    def generate_from_prd(
        cls,
        prd: ParsedPRD,
        api_spec: Optional[ParsedOpenAPI] = None,
        retrieved_context: Optional[List[Dict[str, Any]]] = None
    ) -> TestSuite:
        # Attempt LLM generation first via unified hybrid adapter
        try:
            llm_suite = cls._generate_with_llm(prd, api_spec, retrieved_context)
            if llm_suite and llm_suite.test_cases:
                return llm_suite
        except Exception:
            pass  # Fallback to deterministic ISTQB rule generator

        return cls._generate_deterministic_suite(prd, api_spec)

    @classmethod
    def _generate_deterministic_suite(
        cls,
        prd: ParsedPRD,
        api_spec: Optional[ParsedOpenAPI] = None
    ) -> TestSuite:
        test_cases: List[TestCase] = []
        tc_counter = 1

        for us in prd.user_stories:
            for ac in us.acceptance_criteria:
                ac_desc = ac.description
                # 1. Positive / Happy Path
                tc_pos = TestCase(
                    id=f"TC-{tc_counter:03d}",
                    title=f"[Positive] Verify {us.title} - {ac.id}",
                    user_story_id=us.id,
                    acceptance_criteria_id=ac.id,
                    category="Positive",
                    priority="High",
                    pre_conditions=["User is logged in", "Prerequisite test data is loaded"],
                    test_steps=[
                        f"1. Navigate to {us.title} interface",
                        f"2. Execute action: {ac.gherkin_when or ac_desc}",
                        f"3. Submit request"
                    ],
                    test_data={"input_type": "valid", "sample": "Standard valid input"},
                    expected_result=ac.gherkin_then or f"System responds successfully matching criteria: {ac_desc}"
                )
                test_cases.append(tc_pos)
                tc_counter += 1

                # 2. Boundary Value Analysis (BVA)
                tc_bva = TestCase(
                    id=f"TC-{tc_counter:03d}",
                    title=f"[BVA] Boundary Value Check for {ac.id}",
                    user_story_id=us.id,
                    acceptance_criteria_id=ac.id,
                    category="Boundary Value Analysis",
                    priority="Medium",
                    pre_conditions=["Target input fields are loaded"],
                    test_steps=[
                        "1. Enter boundary minimum values (e.g. min, min-1, max, max+1)",
                        "2. Trigger submission"
                    ],
                    test_data={"boundary_min": 0, "boundary_max": 255, "empty_value": ""},
                    expected_result="System accepts boundary minimum/maximum and rejects values exceeding boundary with validation message."
                )
                test_cases.append(tc_bva)
                tc_counter += 1

                # 3. Equivalence Partitioning & Negative Case
                tc_neg = TestCase(
                    id=f"TC-{tc_counter:03d}",
                    title=f"[Negative] Invalid Input & Error Handling for {ac.id}",
                    user_story_id=us.id,
                    acceptance_criteria_id=ac.id,
                    category="Negative",
                    priority="High",
                    pre_conditions=["Target service is reachable"],
                    test_steps=[
                        "1. Leave required fields empty or provide malformed data format",
                        "2. Attempt to submit"
                    ],
                    test_data={"invalid_format": "malformed_value", "missing_required": None},
                    expected_result="System blocks transaction and displays descriptive error message without crashing."
                )
                test_cases.append(tc_neg)
                tc_counter += 1

        primary_us_id = prd.user_stories[0].id if prd.user_stories else "US-01"

        # OWASP Security Suite (Injection, IDOR, Rate Limiting)
        owasp_cases = [
            TestCase(
                id=f"TC-{tc_counter:03d}",
                title=f"[OWASP-A03] SQL & NoSQL Injection Resilience on {prd.title}",
                user_story_id=primary_us_id,
                category="Security",
                priority="Critical",
                pre_conditions=["Authenticated user session"],
                test_steps=[
                    "1. Input malicious SQL syntax payload: ' OR '1'='1' --",
                    "2. Input cross-site scripting payload: <script>alert(1)</script>",
                    "3. Submit form"
                ],
                test_data={"sqli_payload": "' OR '1'='1' --", "xss_payload": "<script>alert(1)</script>"},
                expected_result="Input is properly sanitized/escaped; system returns 400 Bad Request; no script execution or DB leak occurs."
            ),
            TestCase(
                id=f"TC-{tc_counter+1:03d}",
                title=f"[OWASP-A01] Broken Object Level Authorization (IDOR) on {prd.title}",
                user_story_id=primary_us_id,
                category="Security",
                priority="Critical",
                pre_conditions=["User A logged in, User B record exists"],
                test_steps=[
                    "1. User A initiates resource access request with User B's resource ID",
                    "2. Intercept and inspect response payload"
                ],
                test_data={"victim_id": "usr_victim_9999", "caller_id": "usr_attacker_001"},
                expected_result="System returns HTTP 403 Forbidden. Access is strictly denied without leaking data."
            ),
            TestCase(
                id=f"TC-{tc_counter+2:03d}",
                title=f"[OWASP-A07] Rate Limiting & Brute-Force Protection on {prd.title}",
                user_story_id=primary_us_id,
                category="Security",
                priority="High",
                pre_conditions=["Target endpoint reachable"],
                test_steps=[
                    "1. Dispatch 100 consecutive API requests within 10 seconds from single client",
                    "2. Check response codes and headers"
                ],
                test_data={"burst_count": 100, "window_seconds": 10},
                expected_result="System triggers rate limiting after threshold and returns HTTP 429 Too Many Requests."
            )
        ]
        test_cases.extend(owasp_cases)

        return TestSuite(
            feature_title=prd.title,
            summary=f"Automated test suite with {len(test_cases)} scenarios covering Positive, BVA, Negative, and OWASP Security partitions.",
            total_test_cases=len(test_cases),
            test_cases=test_cases
        )

    @classmethod
    def _generate_with_llm(
        cls,
        prd: ParsedPRD,
        api_spec: Optional[ParsedOpenAPI] = None,
        retrieved_context: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[TestSuite]:
        prompt = (
            f"You are an expert QA Lead and ISTQB Specialist.\n"
            f"Generate a comprehensive test suite in strict JSON format matching the TestSuite Pydantic schema.\n\n"
            f"Feature Title: {prd.title}\n"
            f"User Stories & Acceptance Criteria:\n{prd.model_dump_json(indent=2)}\n\n"
        )
        if api_spec:
            prompt += f"OpenAPI Endpoints & Schemas:\n{api_spec.model_dump_json(indent=2)}\n\n"

        prompt += (
            "REQUIREMENTS:\n"
            "1. Cover every Acceptance Criteria with Positive (Happy Path), Boundary Value Analysis (BVA), and Negative cases.\n"
            "2. Include OWASP Security testing (SQLi/XSS, IDOR, Rate Limiting).\n"
            "3. Format exactly as JSON with keys: 'feature_title', 'summary', 'total_test_cases', 'test_cases'.\n"
        )

        response_str = LLMClient.generate(
            prompt=prompt,
            system_instruction="You are an ISTQB Certified Software Tester. Respond in JSON only.",
            json_mode=True,
            temperature=0.2
        )
        if not response_str:
            return None

        data = json.loads(response_str)
        return TestSuite(**data)

    @classmethod
    def generate_from_graphql(cls, schema: ParsedGraphQLSchema) -> TestSuite:
        test_cases: List[TestCase] = []
        tc_idx = 1
        
        for q in schema.queries:
            test_cases.append(TestCase(
                id=f"GQL-Q-{tc_idx:03d}",
                title=f"[GraphQL Query] Execute query '{q.name}' with valid arguments",
                category="Positive",
                priority="High",
                test_steps=[
                    f"1. Construct GraphQL Query document for {q.name}",
                    f"2. Send POST request with query payload to /graphql",
                    f"3. Validate response data matches return type '{q.return_type}'"
                ],
                expected_result=f"Returns 200 OK with non-null '{q.name}' data payload without 'errors' block."
            ))
            tc_idx += 1

        for m in schema.mutations:
            test_cases.append(TestCase(
                id=f"GQL-M-{tc_idx:03d}",
                title=f"[GraphQL Mutation] Execute mutation '{m.name}' with valid input",
                category="Positive",
                priority="Critical",
                test_steps=[
                    f"1. Construct GraphQL Mutation document for {m.name}",
                    f"2. Provide valid variable inputs {list(m.arguments.keys())}",
                    f"3. Execute mutation and verify state change"
                ],
                expected_result=f"Mutation succeeds, returns '{m.return_type}' and database updates accordingly."
            ))
            tc_idx += 1
            test_cases.append(TestCase(
                id=f"GQL-M-{tc_idx:03d}",
                title=f"[GraphQL Negative] Execute mutation '{m.name}' with missing required variables",
                category="Negative",
                priority="High",
                test_steps=[
                    f"1. Construct GraphQL Mutation for {m.name} omitting required arguments",
                    f"2. Submit request to /graphql endpoint"
                ],
                expected_result="Returns 200/400 with 'errors' field detailing GRAPHQL_VALIDATION_FAILED."
            ))
            tc_idx += 1

        return TestSuite(
            feature_title=schema.title,
            summary=f"GraphQL Test Suite for {len(schema.queries)} queries and {len(schema.mutations)} mutations.",
            total_test_cases=len(test_cases),
            test_cases=test_cases
        )

    @classmethod
    def generate_from_asyncapi(cls, async_spec: ParsedAsyncAPISpec) -> TestSuite:
        test_cases: List[TestCase] = []
        tc_idx = 1

        for ch in async_spec.channels:
            op_label = "Produce" if ch.operation_type == "publish" else "Consume"
            test_cases.append(TestCase(
                id=f"ASYNC-{tc_idx:03d}",
                title=f"[Event Broker] {op_label} message on channel '{ch.channel_name}'",
                category="Positive",
                priority="High",
                test_steps=[
                    f"1. Connect to Event Broker (Kafka/RabbitMQ)",
                    f"2. {op_label} message '{ch.message_name}' to topic/queue '{ch.channel_name}'",
                    f"3. Validate consumer receives and processes message successfully"
                ],
                expected_result="Message is acknowledged by broker and successfully processed with offset committed."
            ))
            tc_idx += 1
            test_cases.append(TestCase(
                id=f"ASYNC-{tc_idx:03d}",
                title=f"[Event Schema Fuzzing] Malformed payload rejection on '{ch.channel_name}'",
                category="Negative",
                priority="High",
                test_steps=[
                    f"1. Construct payload violating '{ch.message_name}' JSON schema",
                    f"2. Publish malformed message to channel '{ch.channel_name}'",
                    f"3. Check Dead-Letter Queue (DLQ) routing"
                ],
                expected_result="Consumer rejects malformed event and routes to DLQ without crashing the consumer group."
            ))
            tc_idx += 1

        return TestSuite(
            feature_title=async_spec.title,
            summary=f"AsyncAPI Event-Driven Test Suite covering {len(async_spec.channels)} channel operations.",
            total_test_cases=len(test_cases),
            test_cases=test_cases
        )
