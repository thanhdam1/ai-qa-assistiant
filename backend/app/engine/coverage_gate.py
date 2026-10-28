import asyncio
from typing import Any, Callable, Coroutine, List, Optional, Set, Tuple
from app.engine.batch_generator import (
    BATCH_SIZE,
    expand_skeleton_batch,
    generate_baseline_skeletons,
)
from app.schemas.zero_gap_contract import (
    CanonicalTestContract,
    DetailedTestCase,
    GapForQA,
    ResolutionStatus,
    TestCaseSkeleton,
    ZeroGapSuiteResponse,
)

MAX_HEALING_RETRIES = 2


def evaluate_missing_obligations(
    contract: CanonicalTestContract,
    test_cases: List[DetailedTestCase],
    flagged_ids: Set[str],
) -> Tuple[Set[str], Set[str], Set[str], float]:
    """Tính toán chính xác các ID còn thiếu và tỷ lệ Effective Coverage (RULE-06)."""
    req_total = {r.req_id for r in contract.requirements}
    bva_total = {b.bva_id for b in contract.bva_matrix}
    ast_total = {a.branch_id for a in contract.ast_branches}

    req_cov = {rid for tc in test_cases for rid in tc.covered_req_ids} | (req_total & flagged_ids)
    bva_cov = {bid for tc in test_cases for bid in tc.covered_bva_ids} | (bva_total & flagged_ids)
    ast_cov = {aid for tc in test_cases for aid in tc.covered_ast_ids} | (ast_total & flagged_ids)

    missing_reqs = req_total - req_cov
    missing_bvas = bva_total - bva_cov
    missing_asts = ast_total - ast_cov

    total_count = len(req_total) + len(bva_total) + len(ast_total)
    if total_count == 0:
        return set(), set(), set(), 100.0

    covered_count = len(req_cov) + len(bva_cov) + len(ast_cov)
    coverage_pct = round((covered_count / total_count) * 100.0, 2)
    return missing_reqs, missing_bvas, missing_asts, coverage_pct


async def default_skeleton_fn(contract: CanonicalTestContract) -> List[TestCaseSkeleton]:
    return generate_baseline_skeletons(contract)


async def default_expand_batch_fn(
    batch: List[TestCaseSkeleton], contract: CanonicalTestContract
) -> List[DetailedTestCase]:
    return await expand_skeleton_batch(batch, contract)


async def default_delta_heal_fn(
    missing_reqs: Set[str],
    missing_bvas: Set[str],
    missing_asts: Set[str],
    contract: CanonicalTestContract,
) -> List[DetailedTestCase]:
    """Tạo bù các test case tương ứng với các ID còn thiếu."""
    sub_contract = CanonicalTestContract(
        mode=contract.mode,
        requirements=[r for r in contract.requirements if r.req_id in missing_reqs],
        bva_matrix=[b for b in contract.bva_matrix if b.bva_id in missing_bvas],
        ast_branches=[a for a in contract.ast_branches if a.branch_id in missing_asts],
    )
    skeletons = generate_baseline_skeletons(sub_contract)
    return await expand_skeleton_batch(skeletons, contract)


def run_zero_gap_pipeline(
    contract: CanonicalTestContract,
    existing_flagged_ids: Optional[Set[str]] = None,
) -> ZeroGapSuiteResponse:
    """
    Hàm thực thi Zero-Gap Pipeline theo luồng đồng bộ tất định (deterministic zero-gap engine).
    Bảo đảm hiệu năng tức thì, không phụ thuộc event loop, phù hợp cho unit test và fallback.
    """
    flagged_ids = set(existing_flagged_ids or set())

    # PHA 1: Sinh ma trận Skeleton
    skeletons = generate_baseline_skeletons(contract)

    # PHA 2: Mở rộng chi tiết từng lô
    batches = [skeletons[i : i + BATCH_SIZE] for i in range(0, len(skeletons), BATCH_SIZE)]
    detailed_cases: List[DetailedTestCase] = []
    for batch in batches:
        # expand_skeleton_batch can be called synchronously
        res = expand_skeleton_batch(batch, contract)
        if asyncio.iscoroutine(res):
            # If it's a coroutine, run until complete or handle
            try:
                loop = asyncio.get_event_loop()
                res = loop.run_until_complete(res)
            except Exception:
                pass
        detailed_cases.extend(res)

    # PHA 3: Coverage Gate + Delta Loop
    retries = 0
    missing_reqs, missing_bvas, missing_asts, cov_pct = evaluate_missing_obligations(
        contract, detailed_cases, flagged_ids
    )

    while (missing_reqs or missing_bvas or missing_asts) and retries < MAX_HEALING_RETRIES:
        retries += 1
        sub_contract = CanonicalTestContract(
            mode=contract.mode,
            requirements=[r for r in contract.requirements if r.req_id in missing_reqs],
            bva_matrix=[b for b in contract.bva_matrix if b.bva_id in missing_bvas],
            ast_branches=[a for a in contract.ast_branches if a.branch_id in missing_asts],
        )
        delta_sk = generate_baseline_skeletons(sub_contract)
        delta_cases = expand_skeleton_batch(delta_sk, contract)
        if asyncio.iscoroutine(delta_cases):
            try:
                loop = asyncio.get_event_loop()
                delta_cases = loop.run_until_complete(delta_cases)
            except Exception:
                pass
        for tc in delta_cases:
            tc.resolution_status = ResolutionStatus.HEALED_BY_DELTA
        detailed_cases.extend(delta_cases)

        missing_reqs, missing_bvas, missing_asts, cov_pct = evaluate_missing_obligations(
            contract, detailed_cases, flagged_ids
        )

    # PHA 4: Circuit Breaker
    gaps_for_qa: List[GapForQA] = []
    for conflict in contract.spec_conflicts:
        gaps_for_qa.append(
            GapForQA(
                target_id="SPEC-CONFLICT",
                gap_type="SPEC_CONFLICT",
                reason=conflict,
                status=ResolutionStatus.NEEDS_CLARIFICATION,
            )
        )

    for rid in sorted(missing_reqs):
        gaps_for_qa.append(
            GapForQA(
                target_id=rid,
                gap_type="REQ_GAP",
                reason=f"Chưa thể tự động phủ yêu cầu {rid} sau {retries} vòng lặp Self-Healing. Cần QA làm rõ nghiệp vụ.",
            )
        )
        flagged_ids.add(rid)

    for bid in sorted(missing_bvas):
        gaps_for_qa.append(
            GapForQA(
                target_id=bid,
                gap_type="BVA_GAP",
                reason=f"Biên dữ liệu {bid} xung đột với ràng buộc nghiệp vụ hiện tại.",
            )
        )
        flagged_ids.add(bid)

    for aid in sorted(missing_asts):
        gaps_for_qa.append(
            GapForQA(
                target_id=aid,
                gap_type="AST_GAP",
                reason=f"Nhánh code {aid} (Shadow Logic) không có mô tả tương ứng trong User Story.",
            )
        )
        flagged_ids.add(aid)

    _, _, _, final_effective_cov = evaluate_missing_obligations(
        contract, detailed_cases, flagged_ids
    )

    return ZeroGapSuiteResponse(
        effective_coverage_pct=final_effective_cov,
        verification_mode=contract.mode,
        retries_used=retries,
        test_cases=detailed_cases,
        gaps_for_qa=gaps_for_qa,
    )


# Alias for compatibility with both async and sync pipeline callers
execute_zero_gap_pipeline = run_zero_gap_pipeline


