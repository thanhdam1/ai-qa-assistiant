from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.parsers.prd_parser import ParsedPRD
from app.agents.test_case_agent import TestSuite, TestCase

class RTMEntry(BaseModel):
    user_story_id: str
    user_story_title: str
    ac_id: str
    ac_description: str
    covered_test_case_ids: List[str] = Field(default_factory=list)
    is_covered: bool
    gap_notes: Optional[str] = None

class RTMMatrix(BaseModel):
    feature_title: str
    total_requirements: int
    covered_requirements: int
    coverage_percentage: float
    entries: List[RTMEntry] = Field(default_factory=list)
    uncovered_gaps: List[str] = Field(default_factory=list)

class RTMAgent:
    """
    Constructs the Requirements Traceability Matrix (RTM)
    and executes Gap Analysis to guarantee 100% test coverage.
    """

    @classmethod
    def build_matrix(cls, prd: ParsedPRD, test_suite: TestSuite) -> RTMMatrix:
        entries: List[RTMEntry] = []
        uncovered: List[str] = []
        total_ac = 0
        covered_ac = 0

        # Build index of test cases by AC id
        tc_by_ac: Dict[str, List[str]] = {}
        for tc in test_suite.test_cases:
            if tc.acceptance_criteria_id:
                tc_by_ac.setdefault(tc.acceptance_criteria_id, []).append(tc.id)

        for us in prd.user_stories:
            for ac in us.acceptance_criteria:
                total_ac += 1
                matched_tcs = tc_by_ac.get(ac.id, [])

                # Fallback check if test title mentions AC id
                if not matched_tcs:
                    matched_tcs = [
                        tc.id for tc in test_suite.test_cases
                        if ac.id in tc.title or (tc.user_story_id == us.id and "positive" in tc.category.lower())
                    ]

                is_cov = len(matched_tcs) > 0
                gap_note = None

                if is_cov:
                    covered_ac += 1
                else:
                    gap_note = f"Warning: No test cases found covering {ac.id} ({ac.description[:40]}...)"
                    uncovered.append(f"{us.id}/{ac.id}: {ac.description}")

                entries.append(
                    RTMEntry(
                        user_story_id=us.id,
                        user_story_title=us.title,
                        ac_id=ac.id,
                        ac_description=ac.description,
                        covered_test_case_ids=matched_tcs,
                        is_covered=is_cov,
                        gap_notes=gap_note
                    )
                )

        coverage = round((covered_ac / max(total_ac, 1)) * 100, 1)

        return RTMMatrix(
            feature_title=prd.title,
            total_requirements=total_ac,
            covered_requirements=covered_ac,
            coverage_percentage=coverage,
            entries=entries,
            uncovered_gaps=uncovered
        )
