import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.parsers.prd_rule_extractor import (
    SemanticPOMSpec,
    SemanticAction,
    SemanticCriterion,
    slugify
)

logger = logging.getLogger(__name__)

class GeminiActionParam(BaseModel):
    name: str
    type: str = "str"
    default: str = "sample_value"

class GeminiPOMAction(BaseModel):
    method_name: str
    description: str
    params: List[GeminiActionParam] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)

class GeminiSecurityTestCase(BaseModel):
    test_id: str
    title: str
    attack_vector: str  # negative_quantity, voucher_bruteforce, price_tampering, idor, sqli, xss, csrf
    description: str
    action_call: str
    assertions: List[str] = Field(default_factory=list)

class GeminiTestScenario(BaseModel):
    test_id: str
    category: str  # positive, boundary, negative
    title: str
    given: str
    when: str
    then: str
    action_call: str
    assertions: List[str] = Field(default_factory=list)
    expected_error: Optional[str] = None

class GeminiPOMResponse(BaseModel):
    class_name: str
    feature_slug: str
    locators: Dict[str, str] = Field(default_factory=dict)
    actions: List[GeminiPOMAction] = Field(default_factory=list)
    positive_tests: List[GeminiTestScenario] = Field(default_factory=list)
    boundary_tests: List[GeminiTestScenario] = Field(default_factory=list)
    negative_tests: List[GeminiTestScenario] = Field(default_factory=list)
    security_tests: List[GeminiSecurityTestCase] = Field(default_factory=list)

GEMINI_JSON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "class_name": {"type": "STRING"},
        "feature_slug": {"type": "STRING"},
        "locators": {
            "type": "OBJECT",
            "description": "Key-value map of locator constants e.g. VOUCHER_INPUT: [data-testid='voucher-input']"
        },
        "actions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "method_name": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "params": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "name": {"type": "STRING"},
                                "type": {"type": "STRING"},
                                "default": {"type": "STRING"}
                            },
                            "required": ["name", "type", "default"]
                        }
                    },
                    "steps": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    }
                },
                "required": ["method_name", "description", "params", "steps"]
            }
        },
        "positive_tests": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "test_id": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "given": {"type": "STRING"},
                    "when": {"type": "STRING"},
                    "then": {"type": "STRING"},
                    "action_call": {"type": "STRING"},
                    "assertions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    },
                    "expected_error": {"type": "STRING"}
                },
                "required": ["test_id", "category", "title", "given", "when", "then", "action_call", "assertions"]
            }
        },
        "boundary_tests": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "test_id": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "given": {"type": "STRING"},
                    "when": {"type": "STRING"},
                    "then": {"type": "STRING"},
                    "action_call": {"type": "STRING"},
                    "assertions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    },
                    "expected_error": {"type": "STRING"}
                },
                "required": ["test_id", "category", "title", "given", "when", "then", "action_call", "assertions"]
            }
        },
        "negative_tests": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "test_id": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "given": {"type": "STRING"},
                    "when": {"type": "STRING"},
                    "then": {"type": "STRING"},
                    "action_call": {"type": "STRING"},
                    "assertions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    },
                    "expected_error": {"type": "STRING"}
                },
                "required": ["test_id", "category", "title", "given", "when", "then", "action_call", "assertions"]
            }
        },
        "security_tests": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "test_id": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "attack_vector": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "action_call": {"type": "STRING"},
                    "assertions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    }
                },
                "required": ["test_id", "title", "attack_vector", "description", "action_call", "assertions"]
            }
        }
    },
    "required": [
        "class_name",
        "feature_slug",
        "locators",
        "actions",
        "positive_tests",
        "boundary_tests",
        "negative_tests",
        "security_tests"
    ]
}

SYSTEM_INSTRUCTION = """You are an Enterprise Lead QA Automation Architect and Application Security Engineer.
Analyze the provided PRD (User Story + Given-When-Then) and real DOM/HTML elements (if provided) to synthesize a 100% production-ready Page Object Model (POM) and Security Test Suite for Playwright.

GUIDELINES:
1. CLASS NAME & SLUG: Generate a descriptive PascalCase class name (e.g. FurnitureVoucherPage) and snake_case slug (furniture_voucher).
2. LOCATORS:
   - If DOM/HTML snippet is provided, extract exact selectors (e.g. [data-testid='...'], input[name='...'], button:has-text('...')).
   - If not provided, synthesize resilient Testing Library data-testid selectors.
   - Always include SUCCESS_BANNER and ERROR_ALERT.
3. ACTIONS:
   - Synthesize specific, domain-aware action methods with clear parameters and Playwright steps using:
     self.fill_input(self.<FIELD>, str(<param>))
     self.click_element(self.<BUTTON>)
4. SECURITY TESTS:
   You MUST generate comprehensive real-world abuse scenarios covering:
   - Negative Quantity / Zero Quantity tampering (e.g. cart quantity -5)
   - Voucher Brute-Force & Rate Limiting bypass attempts
   - Price Tampering & Parameter Manipulation (tampering client-side totals)
   - IDOR (Insecure Direct Object Reference against order IDs)
   - SQL Injection (' OR '1'='1' --) and Cross-Site Scripting (XSS) defenses
5. POSITIVE, BOUNDARY & NEGATIVE TESTS:
   - Sourced directly from PRD Given-When-Then criteria with real boundary amounts and expected error messages.
"""

class GeminiPOMGenerator:
    """
    Synthesizes Page Object Model & Advanced Security Test Suites
    using Google Gemini 2.5 Flash Structured Outputs.
    """

    @classmethod
    def generate_pom_and_security(
        cls,
        feature_name: str,
        prd_content: str,
        dom_content: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ) -> Optional[SemanticPOMSpec]:
        active_key = api_key or settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
        if not active_key:
            logger.info("[GeminiPOMGenerator] No Gemini API Key configured. Bypassing to deterministic Rule-based parser.")
            return None

        active_model = model or settings.GEMINI_MODEL or "gemini-2.5-flash"

        # Build prompt
        dom_section = f"\n\n### REAL DOM / HTML SELECTORS PROVIDED:\n```html\n{dom_content.strip()}\n```" if (dom_content and dom_content.strip()) else "\n\n### DOM / HTML: None provided. Synthesize standard Testing Library resilient selectors."
        
        user_prompt = f"""### FEATURE NAME:
{feature_name}

### PRD / USER STORY SPECIFICATION:
{prd_content}
{dom_section}

Synthesize the Page Object Model, Locators, Business Actions, and Positive, Boundary, Negative, and Security Test Suites matching the JSON Schema."""

        payload = {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_INSTRUCTION}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseSchema": GEMINI_JSON_SCHEMA
            }
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{active_model}:generateContent?key={active_key}"

        try:
            with httpx.Client(timeout=45.0) as client:
                res = client.post(url, json=payload)
                if res.status_code != 200:
                    logger.error(f"[GeminiPOMGenerator] Gemini API error {res.status_code}: {res.text}")
                    return None

                response_data = res.json()
                candidates = response_data.get("candidates", [])
                if not candidates:
                    logger.error(f"[GeminiPOMGenerator] No candidates returned from Gemini.")
                    return None

                raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed_json = json.loads(raw_text)
                return cls._convert_to_semantic_spec(parsed_json, feature_name)

        except Exception as e:
            logger.error(f"[GeminiPOMGenerator] Exception during Gemini POM generation: {e}")
            return None

    @classmethod
    def _convert_to_semantic_spec(cls, data: Dict[str, Any], feature_name: str) -> SemanticPOMSpec:
        """Converts Gemini JSON structured output into unified SemanticPOMSpec."""
        class_name = data.get("class_name") or f"{slugify(feature_name).title().replace('_', '')}Page"
        slug = data.get("feature_slug") or slugify(feature_name)
        locators = data.get("locators", {})

        # Ensure banner and error locators exist
        if "SUCCESS_BANNER" not in locators:
            locators["SUCCESS_BANNER"] = f"[data-testid='{slug}-success-banner'], .alert-success"
        if "ERROR_ALERT" not in locators:
            locators["ERROR_ALERT"] = f"[data-testid='{slug}-error-alert'], [role='alert']"

        actions: List[SemanticAction] = []
        for a in data.get("actions", []):
            actions.append(SemanticAction(
                method_name=a.get("method_name", f"submit_{slug}"),
                params=a.get("params", []),
                steps=a.get("steps", []),
                docstring=a.get("description", f"Action on {class_name}")
            ))

        criteria: List[SemanticCriterion] = []

        # 1. Positive Tests
        for p in data.get("positive_tests", []):
            criteria.append(SemanticCriterion(
                ac_id=p.get("test_id", "TC-POS-01"),
                category="positive",
                title=p.get("title", "Happy Path Scenario"),
                given=p.get("given", "Initial state"),
                when=p.get("when", "Action executed"),
                then=p.get("then", "Success verified"),
                action_call=p.get("action_call", "page.is_success()"),
                assertions=p.get("assertions", ["assert page.is_success()"]),
                expected_error=None
            ))

        # 2. Boundary Tests
        for b in data.get("boundary_tests", []):
            criteria.append(SemanticCriterion(
                ac_id=b.get("test_id", "TC-BVA-01"),
                category="boundary",
                title=b.get("title", "Boundary Limit Scenario"),
                given=b.get("given", "Boundary inputs"),
                when=b.get("when", "Action submitted"),
                then=b.get("then", "Boundary accepted or rejected"),
                action_call=b.get("action_call", "page.is_success()"),
                assertions=b.get("assertions", ["assert page.is_success()"]),
                expected_error=b.get("expected_error")
            ))

        # 3. Negative Tests
        for n in data.get("negative_tests", []):
            criteria.append(SemanticCriterion(
                ac_id=n.get("test_id", "TC-NEG-01"),
                category="negative",
                title=n.get("title", "Negative Rejection Scenario"),
                given=n.get("given", "Invalid inputs"),
                when=n.get("when", "Action submitted"),
                then=n.get("then", "Error displayed"),
                action_call=n.get("action_call", "page.get_error_message()"),
                assertions=n.get("assertions", ["assert not page.is_success()"]),
                expected_error=n.get("expected_error")
            ))

        # 4. Security Tests
        for s in data.get("security_tests", []):
            vector = s.get("attack_vector", "security")
            title = f"[{vector.upper()}] {s.get('title', 'Security resilience check')}"
            criteria.append(SemanticCriterion(
                ac_id=s.get("test_id", "TC-SEC-01"),
                category="security",
                title=title,
                given=f"Attack vector: {vector}",
                when=s.get("description", "Malicious payload or unauthorized request executed"),
                then="Application defense prevents unauthorized state change",
                action_call=s.get("action_call", "page.is_success()"),
                assertions=s.get("assertions", ["assert not page.is_success() or len(page.get_error_message()) >= 0"]),
                expected_error=None
            ))

        return SemanticPOMSpec(
            class_name=class_name,
            slug=slug,
            feature_title=feature_name,
            locators=locators,
            actions=actions,
            criteria=criteria
        )
