import asyncio
from typing import Any, Dict, List
from app.schemas.zero_gap_contract import (
    CanonicalTestContract,
    DetailedTestCase,
    ResolutionStatus,
    TestCaseSkeleton,
)

BATCH_SIZE = 8


def generate_baseline_skeletons(contract: CanonicalTestContract) -> List[TestCaseSkeleton]:
    """
    Sinh ma trận Skeleton bao phủ toàn bộ CanonicalTestContract (Pha 1).
    Đảm bảo 100% Target REQ, BVA và AST Branch đều có ít nhất 1 TestCaseSkeleton ánh xạ.
    """
    skeletons: List[TestCaseSkeleton] = []
    case_idx = 1

    # 1. Khung cho từng Atomic Requirement
    for req in contract.requirements:
        skeletons.append(
            TestCaseSkeleton(
                test_case_id=f"TC-ZG-{case_idx:03d}",
                title=f"Xác minh yêu cầu: {req.clause_text[:80]}",
                category="Functional",
                covered_req_ids=[req.req_id],
                covered_bva_ids=[],
                covered_ast_ids=[],
            )
        )
        case_idx += 1

    # 2. Khung cho từng BVA Partition Item
    for bva in contract.bva_matrix:
        is_neg = "minus" in bva.partition_type or "plus" in bva.partition_type or "wrong" in bva.partition_type or (bva.partition_type == "empty" and bva.expected_http_status >= 400) or (bva.partition_type == "null" and bva.expected_http_status >= 400)
        cat = "Negative" if is_neg else "Boundary"
        skeletons.append(
            TestCaseSkeleton(
                test_case_id=f"TC-ZG-{case_idx:03d}",
                title=f"Kiểm thử biên [{bva.partition_type}] trường '{bva.field_path}' trên {bva.endpoint}",
                category=cat,
                covered_req_ids=[],
                covered_bva_ids=[bva.bva_id],
                covered_ast_ids=[],
            )
        )
        case_idx += 1

    # 3. Khung cho từng AST Branch Node
    for branch in contract.ast_branches:
        skeletons.append(
            TestCaseSkeleton(
                test_case_id=f"TC-ZG-{case_idx:03d}",
                title=f"Kiểm thử nhánh rẽ {branch.function_name} ({branch.condition_expression})",
                category="Integration",
                covered_req_ids=[],
                covered_bva_ids=[],
                covered_ast_ids=[branch.branch_id],
            )
        )
        case_idx += 1

    return skeletons


def expand_skeleton_batch(
    skeletons: List[TestCaseSkeleton],
    contract: CanonicalTestContract,
) -> List[DetailedTestCase]:
    """
    Mở rộng chi tiết cho một lô <= 8 Test Cases (Pha 2).
    Điền Preconditions, Test Steps, Test Data Payload, Status Code và Expected Result.
    """
    detailed: List[DetailedTestCase] = []

    # Map tra cứu nhanh
    req_map = {r.req_id: r for r in contract.requirements}
    bva_map = {b.bva_id: b for b in contract.bva_matrix}
    ast_map = {a.branch_id: a for a in contract.ast_branches}

    for sk in skeletons:
        steps: List[str] = []
        preconditions: List[str] = ["Hệ thống ở trạng thái hoạt động bình thường."]
        payload: Dict[str, Any] = {}
        expected_status = 200
        expected_res = "Hệ thống xử lý thành công theo đúng yêu cầu nghiệp vụ."

        if sk.covered_bva_ids:
            bva_item = bva_map.get(sk.covered_bva_ids[0])
            if bva_item:
                payload[bva_item.field_path] = bva_item.test_value
                expected_status = bva_item.expected_http_status
                steps = [
                    f"1. Chuẩn bị payload chứa trường '{bva_item.field_path}' với giá trị '{bva_item.test_value}' (phân vùng {bva_item.partition_type}).",
                    f"2. Gửi request đến endpoint {bva_item.endpoint}.",
                    f"3. Kiểm tra mã phản hồi HTTP trả về và thông điệp lỗi (nếu có).",
                ]
                expected_res = f"Hệ thống trả về mã HTTP {expected_status} phù hợp với phân vùng {bva_item.partition_type}."

        elif sk.covered_req_ids:
            req_item = req_map.get(sk.covered_req_ids[0])
            if req_item:
                steps = [
                    f"1. Thiết lập tiền đề cho yêu cầu {req_item.req_id}.",
                    f"2. Thực hiện hành động: {req_item.clause_text}.",
                    f"3. Đối soát kết quả phản hồi và trạng thái lưu trữ.",
                ]
                expected_res = f"Hành vi hệ thống đáp ứng mệnh đề: '{req_item.clause_text}'."

        elif sk.covered_ast_ids:
            ast_item = ast_map.get(sk.covered_ast_ids[0])
            if ast_item:
                steps = [
                    f"1. Khởi tạo dữ liệu đầu vào kích hoạt điều kiện: {ast_item.condition_expression}.",
                    f"2. Gọi hàm/luồng {ast_item.function_name}.",
                    f"3. Xác nhận luồng điều khiển đi đúng vào nhánh tại dòng {ast_item.line_number}.",
                ]
                expected_res = f"Nhánh rẽ '{ast_item.condition_expression}' được thực thi đầy đủ."

        if not steps:
            steps = ["1. Thực hiện kịch bản kiểm thử.", "2. Kiểm tra kết quả phản hồi."]

        detailed.append(
            DetailedTestCase(
                test_case_id=sk.test_case_id,
                title=sk.title,
                category=sk.category,
                covered_req_ids=sk.covered_req_ids,
                covered_bva_ids=sk.covered_bva_ids,
                covered_ast_ids=sk.covered_ast_ids,
                priority="High" if sk.category in {"Security", "Functional"} else "Medium",
                preconditions=preconditions,
                test_steps=steps,
                test_data_payload=payload,
                expected_http_status=expected_status,
                expected_result=expected_res,
                resolution_status=ResolutionStatus.COVERED_AUTOMATED,
            )
        )

    return detailed
