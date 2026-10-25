import csv
import io
import json

from app.models import RequirementReview, TestCaseSet


def json_bytes(content: dict) -> bytes:
    return json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")


def review_csv(review: RequirementReview) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["section", "id", "title", "detail", "severity", "source_reference", "classification"])
    content = review.content
    writer.writerow(["business_summary", "", "", content["business_summary"], "", "", "requirement"])
    for item in content.get("existing_acceptance_criteria", []):
        writer.writerow(
            [
                "existing_acceptance_criteria",
                item["id"],
                "",
                item["criterion"],
                "",
                item["source_reference"],
                "requirement",
            ]
        )
    for section in (
        "missing_acceptance_criteria",
        "ambiguities_and_conflicts",
        "stakeholder_questions",
        "edge_cases",
        "assumptions",
        "risks",
    ):
        for item in content.get(section, []):
            writer.writerow(
                [
                    section,
                    item["id"],
                    item["title"],
                    item["detail"],
                    item["severity"],
                    item["source_reference"],
                    item.get("classification", "recommendation"),
                ]
            )
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def test_set_csv(test_set: TestCaseSet) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "title",
            "objective",
            "type",
            "basis",
            "priority",
            "preconditions",
            "test_data",
            "steps",
            "expected_result",
            "requirement_traceability",
            "assumptions",
            "needs_clarification",
            "coverage_target_type",
            "coverage_target_id",
            "coverage_status",
            "coverage_test_case_ids",
            "coverage_explanation",
        ]
    )
    for case in test_set.content.get("test_cases", []):
        steps = "\n".join(
            f"{step['order']}. {step['action']} => {step['expected_result']}"
            for step in case["steps"]
        )
        writer.writerow(
            [
                case["id"],
                case["title"],
                case["objective"],
                case["type"],
                case.get("basis", "recommendation"),
                case["priority"],
                "\n".join(case["preconditions"]),
                "\n".join(case["test_data"]),
                steps,
                case["expected_result"],
                "\n".join(case["requirement_traceability"]),
                "\n".join(case["assumptions"]),
                str(case["needs_clarification"]).lower(),
                "",
                "",
                "",
                "",
                "",
            ]
        )
    for entry in test_set.content.get("coverage_matrix", []):
        writer.writerow(
            [
                "coverage",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                entry["target_type"],
                entry["target_id"],
                entry["status"],
                "\n".join(entry.get("test_case_ids", [])),
                entry["explanation"],
            ]
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8")
