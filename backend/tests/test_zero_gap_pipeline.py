import pytest
from app.engine.batch_generator import generate_baseline_skeletons
from app.engine.coverage_gate import evaluate_missing_obligations, run_zero_gap_pipeline
from app.engine.gap_detector import detect_gaps_and_conflicts
from app.parsers.code_ast_parser import extract_python_ast_cfg
from app.parsers.openapi_bva import generate_8_partition_bva
from app.parsers.srs_decomposer import decompose_user_story
from app.schemas.zero_gap_contract import (
    ASTBranchNode,
    AtomicRequirement,
    BVAPartitionItem,
    CanonicalTestContract,
)


def test_srs_decomposer_splits_atomic_requirements():
    story = """
    Khi người dùng nhập số tiền hợp lệ VÀ số dư >= số tiền + phí THÌ chuyển tiền thành công.
    NẾU số dư không đủ THÌ báo lỗi INSUFFICIENT_BALANCE.
    """
    atomic = decompose_user_story(story, module_prefix="REQ-TR")
    assert len(atomic) >= 2
    assert all(r.req_id.startswith("REQ-TR-") for r in atomic)
    assert all(len(r.clause_text) > 0 for r in atomic)


def test_openapi_bva_8_partitions_generation():
    spec = {
        "paths": {
            "/api/transfer": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["amount", "receiver_account"],
                                    "properties": {
                                        "amount": {
                                            "type": "integer",
                                            "minimum": 10000,
                                            "maximum": 50000000,
                                        },
                                        "receiver_account": {
                                            "type": "string",
                                            "minLength": 8,
                                            "maxLength": 20,
                                        },
                                    },
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    bvas = generate_8_partition_bva(spec)
    assert len(bvas) >= 16  # 8 for amount + 8 for receiver_account
    types = {b.partition_type for b in bvas}
    assert "min_minus_1" in types
    assert "min" in types
    assert "max" in types
    assert "max_plus_1" in types
    assert "nominal" in types
    assert "null" in types
    assert "wrong_type" in types


def test_code_ast_parser_cyclomatic_complexity():
    code = """
def process_payment(amount, balance, is_vip):
    if amount <= 0:
        raise ValueError("Invalid amount")
    if balance < amount:
        return "INSUFFICIENT_BALANCE"
    if is_vip:
        fee = 0
    else:
        fee = 1000
    try:
        charge(amount + fee)
    except Exception:
        return "CHARGE_FAILED"
    return "SUCCESS"
    """
    branches, complexity = extract_python_ast_cfg(code)
    assert complexity >= 4
    assert len(branches) >= 4
    assert any(b.function_name == "process_payment" for b in branches)


def test_gap_detector_identifies_shadow_logic():
    reqs = [
        AtomicRequirement(req_id="REQ-001", clause_text="Chuyển tiền thành công", source_ac="AC1"),
    ]
    branches = [
        ASTBranchNode(
            branch_id="AST-B1",
            function_name="check_fraud",
            condition_expression="blacklisted_ip_address_detected",
            line_number=42,
        )
    ]
    conflicts = detect_gaps_and_conflicts(reqs, [], branches)
    assert len(conflicts) >= 1
    assert "Shadow Logic" in conflicts[0]


def test_zero_gap_pipeline_reaches_100_percent():
    contract = CanonicalTestContract(
        mode="2-way",
        requirements=[
            AtomicRequirement(req_id="REQ-001", clause_text="Xác thực OTP thành công", source_ac="AC1"),
            AtomicRequirement(req_id="REQ-002", clause_text="Trừ tiền số dư người gửi", source_ac="AC2"),
        ],
        bva_matrix=[
            BVAPartitionItem(
                bva_id="BVA-amount-min",
                endpoint="POST /transfer",
                field_path="amount",
                partition_type="min",
                test_value=10000,
                expected_http_status=200,
            ),
            BVAPartitionItem(
                bva_id="BVA-amount-min_minus_1",
                endpoint="POST /transfer",
                field_path="amount",
                partition_type="min_minus_1",
                test_value=9999,
                expected_http_status=422,
            ),
        ],
        ast_branches=[],
        cyclomatic_complexity=1,
    )

    response = run_zero_gap_pipeline(contract)
    assert response.effective_coverage_pct == 100.0
    assert len(response.test_cases) >= 4
    assert response.retries_used <= 2

