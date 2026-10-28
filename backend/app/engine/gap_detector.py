import re
from typing import List
from app.schemas.zero_gap_contract import (
    ASTBranchNode,
    AtomicRequirement,
    BVAPartitionItem,
)

# Từ điển ánh xạ khái niệm nghiệp vụ đa ngữ (Vietnamese Requirements <-> Code / OpenAPI)
DOMAIN_SYNONYMS = {
    "wallet": {"ví", "wallet", "tài khoản", "account", "người dùng", "khách hàng"},
    "account": {"tài khoản", "account", "ngân hàng", "stk", "ví"},
    "status": {"trạng thái", "status", "active", "locked", "suspended", "hoạt động", "khóa", "tạm ngừng"},
    "active": {"active", "hoạt động", "trạng thái", "status"},
    "amount": {"tiền", "số tiền", "amount", "mức", "rút", "chuyển", "giá trị"},
    "balance": {"số dư", "balance", "khả dụng", "available_balance", "tiền"},
    "fee": {"phí", "fee", "khấu trừ", "deduct", "chi phí", "tổng", "total"},
    "limit": {"hạn mức", "limit", "tối đa", "tối thiểu", "max", "min", "ngày", "daily", "hạn"},
    "daily": {"ngày", "daily", "hôm nay", "today", "24h"},
    "auth": {"xác thực", "auth", "otp", "sinh trắc", "token", "mật khẩu", "pin", "verify"},
    "token": {"token", "otp", "mã", "xác thực"},
    "verify": {"xác thực", "kiểm tra", "verify"},
    "bank": {"ngân hàng", "bank", "nội địa"},
    "kyc": {"kyc", "định danh", "level", "cấp"},
}


def detect_gaps_and_conflicts(
    requirements: List[AtomicRequirement],
    bva_matrix: List[BVAPartitionItem],
    ast_branches: List[ASTBranchNode],
) -> List[str]:
    """
    Phát hiện xung đột Spec 2-Chiều / 3-Chiều và Shadow Logic (RULE-04).
    Hỗ trợ xử lý thông minh đa ngữ (Vietnamese SRS <-> Python AST / OpenAPI).
    """
    conflicts: List[str] = []
    combined_story_text = " ".join([r.clause_text.lower() for r in requirements])

    # 1. Trích xuất các số chuẩn hóa từ Story (VD: 50,000 -> 50000; 50.000 -> 50000; 50,000,000 -> 50000000)
    story_clean_text = combined_story_text
    while re.search(r"(\d+)[\.,_](\d+)", story_clean_text):
        story_clean_text = re.sub(r"(\d+)[\.,_](\d+)", r"\1\2", story_clean_text)

    story_numbers = set(re.findall(r"\b\d+\b", story_clean_text))
    story_words = set(re.findall(r"\w+", combined_story_text.lower()))

    # 2. Thu thập thuộc tính và giá trị từ OpenAPI BVA Matrix
    openapi_fields = {b.field_path.lower() for b in bva_matrix if b.field_path}
    openapi_values = {str(b.test_value) for b in bva_matrix if b.test_value is not None}
    for b in bva_matrix:
        if b.field_path:
            for part in re.split(r"[_\W]+", b.field_path.lower()):
                if len(part) >= 2:
                    openapi_fields.add(part)

    # 3. Kiểm tra Shadow Logic trong mã nguồn (3-Way Mode)
    for branch in ast_branches:
        expr = branch.condition_expression.lower()
        branch_numbers = set(re.findall(r"\b\d+\b", expr.replace("_", "")))
        branch_tokens = {t for t in re.split(r"[_\W]+", expr) if len(t) >= 2}

        # Nhánh được xem là hợp lệ (đã được bao hàm trong Story hoặc OpenAPI) nếu:
        # a) Khớp số biên hoặc mốc giá trị trong Story/OpenAPI (VD: 50000, 50000000, 100000000)
        has_number_match = bool(branch_numbers & (story_numbers | openapi_values))

        # b) Chứa biến / trường định nghĩa trong OpenAPI schema (VD: wallet_id, amount, auth_token, bank_code)
        has_openapi_match = bool(branch_tokens & openapi_fields)

        # c) Chứa từ khóa xuất hiện trực tiếp trong Story
        has_direct_word_match = bool(branch_tokens & story_words)

        # d) Khớp ngữ nghĩa nghiệp vụ qua từ điển Domain Synonyms
        has_semantic_match = False
        for token in branch_tokens:
            if token in DOMAIN_SYNONYMS:
                synonyms = DOMAIN_SYNONYMS[token]
                if any(syn in story_clean_text for syn in synonyms):
                    has_semantic_match = True
                    break

        # Nếu không thỏa mãn bất kỳ tiêu chí nào -> Gắn cờ Shadow Logic
        if not (has_number_match or has_openapi_match or has_direct_word_match or has_semantic_match):
            conflicts.append(
                f"Shadow Logic phát hiện tại nhánh code {branch.branch_id}: '{branch.condition_expression}' không có mô tả trong User Story."
            )

    return conflicts
