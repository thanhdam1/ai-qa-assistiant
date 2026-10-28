import re
from typing import List
from app.schemas.zero_gap_contract import AtomicRequirement

SPLIT_PATTERN = re.compile(
    r"\b(?:AND|OR|WHEN|IF|UNLESS|EXCEPT|NHƯNG|HOẶC|NẾU|KHI|TRỪ KHI)\b",
    flags=re.IGNORECASE,
)


def decompose_user_story(raw_story: str, module_prefix: str = "REQ") -> List[AtomicRequirement]:
    """Tách User Story/AC thành các mệnh đề nguyên tử độc lập (RULE-01)."""
    lines = [line.strip(" -•*\t") for line in raw_story.splitlines() if line.strip()]
    atomic_reqs: List[AtomicRequirement] = []
    counter = 1

    for line in lines:
        clauses = [c.strip() for c in SPLIT_PATTERN.split(line) if len(c.strip()) > 5]
        if not clauses and len(line) > 5:
            clauses = [line]
        for clause in clauses:
            atomic_reqs.append(
                AtomicRequirement(
                    req_id=f"{module_prefix}-{counter:03d}",
                    clause_text=clause,
                    source_ac=line,
                )
            )
            counter += 1
    return atomic_reqs
