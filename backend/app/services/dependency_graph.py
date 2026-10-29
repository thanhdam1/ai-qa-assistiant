import re
import threading
import zlib
from collections import defaultdict, deque
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.errors import AppError, CyclicDependencyError, NotFoundError
from app.models import Story, StoryDependency, TestCaseSet
from app.schemas import (
    DependencyNode,
    ImpactReportItem,
    ImpactedCaseDetail,
    StoryDependencyCreate,
    StoryDependencyTree,
    StoryImpactAnalysisReport,
)

_process_graph_lock = threading.Lock()


def acquire_graph_lock(db: Session, workspace_id: str = "default") -> None:
    """Acquires a concurrency-safe lock for DAG operations.

    Uses PostgreSQL transactional advisory lock in production, and process thread lock in SQLite/tests.
    """
    _process_graph_lock.acquire()
    try:
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            # Generate stable 32-bit integer key from workspace identifier
            lock_id = zlib.crc32(f"story_dag_{workspace_id}".encode("utf-8")) & 0x7FFFFFFF
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
    finally:
        _process_graph_lock.release()


def would_create_cycle(db: Session, source_id: str, target_id: str) -> bool:
    """Checks whether adding edge source_id -> target_id creates a cycle.

    In a directed graph, adding u -> v creates a cycle if and only if
    there is already an existing directed path from v to u.
    """
    if source_id == target_id:
        return True

    rows = db.execute(
        select(StoryDependency.source_story_id, StoryDependency.target_story_id)
    ).all()

    graph = defaultdict(list)
    for src, dst in rows:
        graph[src].append(dst)

    # Search for path from target_id to source_id
    queue = deque([target_id])
    visited = {target_id}

    while queue:
        curr = queue.popleft()
        if curr == source_id:
            return True
        for neighbor in graph.get(curr, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return False


def add_dependency(
    db: Session, source_id: str, payload: StoryDependencyCreate
) -> StoryDependency:
    """Adds a directional dependency edge (source_id -> target_story_id) safely."""
    acquire_graph_lock(db)

    target_id = payload.target_story_id
    if source_id == target_id:
        raise AppError("invalid_dependency", "A story cannot depend on itself", 400)

    source_story = db.get(Story, source_id)
    if not source_story:
        raise NotFoundError("Source story")

    target_story = db.get(Story, target_id)
    if not target_story:
        raise NotFoundError("Target story")

    # Cycle Detection check
    if would_create_cycle(db, source_id, target_id):
        raise CyclicDependencyError(
            f"Cannot create dependency from '{source_story.title}' to '{target_story.title}' as it creates a circular loop"
        )

    # Check if edge already exists
    existing = db.scalar(
        select(StoryDependency).where(
            StoryDependency.source_story_id == source_id,
            StoryDependency.target_story_id == target_id,
        )
    )

    contract_data = payload.binding_contract.model_dump(mode="json")

    if existing:
        existing.dependency_type = payload.dependency_type.value
        existing.binding_contract = contract_data
        existing.synced_source_version = source_story.version
        existing.target_story_version = target_story.version
        existing.impact_status = "synced"
        existing.stale_reason = None
        db.commit()
        db.refresh(existing)
        return existing

    new_dep = StoryDependency(
        source_story_id=source_id,
        target_story_id=target_id,
        dependency_type=payload.dependency_type.value,
        synced_source_version=source_story.version,
        target_story_version=target_story.version,
        binding_contract=contract_data,
        impact_status="synced",
        stale_reason=None,
        impacted_case_ids=[],
    )
    db.add(new_dep)
    db.commit()
    db.refresh(new_dep)
    return new_dep


def remove_dependency(db: Session, source_id: str, target_id: str) -> None:
    """Removes a directional dependency edge."""
    acquire_graph_lock(db)

    dep = db.scalar(
        select(StoryDependency).where(
            StoryDependency.source_story_id == source_id,
            StoryDependency.target_story_id == target_id,
        )
    )
    if not dep:
        raise NotFoundError("Dependency edge")

    db.delete(dep)
    db.commit()


def get_dependency_tree(
    db: Session, story_id: str, max_depth: int | None = None
) -> StoryDependencyTree:
    """Returns the full DAG tree for a story (both upstream and downstream nodes)."""
    story = db.get(Story, story_id)
    if not story:
        raise NotFoundError("Story")

    all_deps = db.execute(select(StoryDependency)).scalars().all()
    all_stories = {s.id: s for s in db.execute(select(Story)).scalars().all()}

    # Graph adjacency:
    # upstream_graph[target] -> list of (source, dep)
    # downstream_graph[source] -> list of (target, dep)
    upstream_graph = defaultdict(list)
    downstream_graph = defaultdict(list)

    for dep in all_deps:
        upstream_graph[dep.target_story_id].append((dep.source_story_id, dep))
        downstream_graph[dep.source_story_id].append((dep.target_story_id, dep))

    # 1. Traverse Upstream (Stories that this story depends on)
    upstream_nodes: list[DependencyNode] = []
    up_queue = deque([(story_id, 0)])
    up_visited = {story_id}

    while up_queue:
        curr_id, depth = up_queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue

        for up_id, dep in upstream_graph.get(curr_id, []):
            if up_id not in up_visited:
                up_visited.add(up_id)
                up_story = all_stories.get(up_id)
                if up_story:
                    upstream_nodes.append(
                        DependencyNode(
                            id=up_story.id,
                            title=up_story.title,
                            version=up_story.version,
                            dependency_type=dep.dependency_type,
                            impact_status=dep.impact_status,
                            synced_source_version=dep.synced_source_version,
                            current_source_version=up_story.version,
                            stale_reason=dep.stale_reason,
                            impacted_case_ids=dep.impacted_case_ids or [],
                        )
                    )
                up_queue.append((up_id, depth + 1))

    # 2. Traverse Downstream (Stories that depend on this story)
    downstream_nodes: list[DependencyNode] = []
    down_queue = deque([(story_id, 0)])
    down_visited = {story_id}

    while down_queue:
        curr_id, depth = down_queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue

        for down_id, dep in downstream_graph.get(curr_id, []):
            if down_id not in down_visited:
                down_visited.add(down_id)
                down_story = all_stories.get(down_id)
                src_story = all_stories.get(dep.source_story_id)
                if down_story and src_story:
                    downstream_nodes.append(
                        DependencyNode(
                            id=down_story.id,
                            title=down_story.title,
                            version=down_story.version,
                            dependency_type=dep.dependency_type,
                            impact_status=dep.impact_status,
                            synced_source_version=dep.synced_source_version,
                            current_source_version=src_story.version,
                            stale_reason=dep.stale_reason,
                            impacted_case_ids=dep.impacted_case_ids or [],
                        )
                    )
                down_queue.append((down_id, depth + 1))

    return StoryDependencyTree(
        story_id=story.id,
        story_title=story.title,
        story_version=story.version,
        upstream=upstream_nodes,
        downstream=downstream_nodes,
    )


def _extract_text_tokens(text_data: str) -> set[str]:
    """Tokenizes text into normalized lowercase alphanumeric words of length >= 2."""
    if not text_data:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text_data.lower())
    return {w for w in cleaned.split() if len(w) >= 2}


def propagate_story_impact(
    db: Session, story: Story, old_state: dict, changes: dict
) -> list[StoryDependency]:
    """3-Step Semantic Impact Propagation Engine.

    Step 1: Compute Delta (changed ACs, rules, modified fields).
    Step 2: Traverse downstream DAG (Full Transitive Closure) and intersect with binding_contract.
            Applies Zero-False-Alarm principle: if no contract intersection, leaves status as 'synced'.
    Step 3: Granular Test Case Invalidation: inspects latest TestCaseSet of downstream story
            and isolates exactly which test case IDs are affected.
    """
    acquire_graph_lock(db)

    # 1. Step 1: Compute Delta
    old_acs = old_state.get("acceptance_criteria") or []
    new_acs = story.acceptance_criteria or []
    changed_acs = [ac for ac in new_acs if ac not in old_acs]
    removed_acs = [ac for ac in old_acs if ac not in new_acs]

    delta_texts: list[str] = []
    for key in ("title", "description", "business_context"):
        if key in changes and changes[key]:
            delta_texts.append(str(changes[key]))
    delta_texts.extend(changed_acs)
    delta_texts.extend(removed_acs)

    delta_combined = " ".join(delta_texts)
    delta_tokens = _extract_text_tokens(delta_combined)

    delta_summary = {
        "source_story_version": story.version,
        "modified_fields": list(changes.keys()),
        "ac_modified": len(changed_acs) > 0 or len(removed_acs) > 0,
        "summary": f"Story '{story.title}' updated to v{story.version}: {', '.join(changes.keys())} modified",
    }

    # 2. Step 2: Traverse Downstream DAG (Full Transitive Closure)
    queue = deque([(story.id, delta_tokens, delta_summary)])
    visited_edges: set[tuple[str, str]] = set()
    impacted_dependencies: list[StoryDependency] = []

    while queue:
        curr_id, curr_tokens, curr_delta = queue.popleft()
        edges = db.execute(
            select(StoryDependency).where(StoryDependency.source_story_id == curr_id)
        ).scalars().all()

        for dep in edges:
            edge_key = (dep.source_story_id, dep.target_story_id)
            if edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)

            binding = dep.binding_contract or {}
            bound_rules = [r.lower() for r in binding.get("bound_rules", [])]
            consumed_outputs = [o.lower() for o in binding.get("consumed_outputs", [])]

            is_impacted = False
            impact_reason_text = ""
            matched_tokens: set[str] = set()

            if not bound_rules and not consumed_outputs:
                # Unconstrained dependency: any upstream change affects downstream
                is_impacted = True
                impact_reason_text = f"Tác động tổng quát từ Story thượng nguồn '{story.title}' v{story.version}"
            else:
                contract_tokens: set[str] = set()
                for item in bound_rules + consumed_outputs:
                    contract_tokens.update(_extract_text_tokens(item))

                matched_tokens = curr_tokens.intersection(contract_tokens)
                if matched_tokens:
                    is_impacted = True
                    impact_reason_text = (
                        f"Quy tắc/Output ràng buộc [{', '.join(sorted(matched_tokens))}] "
                        f"bị ảnh hưởng bởi thay đổi ở Story '{story.title}' (v{dep.synced_source_version} -> v{story.version})"
                    )

            if not is_impacted:
                # Zero-False-Alarm: Keep status synced and DO NOT cascade
                dep.impact_status = "synced"
                dep.stale_reason = None
                dep.impacted_case_ids = []
            else:
                # Mark suspect_stale
                dep.impact_status = "suspect_stale"
                dep.stale_reason = {
                    "summary": curr_delta.get("summary"),
                    "reason": impact_reason_text,
                    "upstream_version": story.version,
                    "matched_tokens": list(matched_tokens),
                }

                # 3. Step 3: Granular Test Case Invalidation
                target_story = db.get(Story, dep.target_story_id)
                impacted_cases: list[str] = []
                if target_story:
                    latest_test_set = db.scalar(
                        select(TestCaseSet)
                        .where(TestCaseSet.story_id == target_story.id)
                        .order_by(TestCaseSet.created_at.desc())
                    )
                    if latest_test_set and latest_test_set.content:
                        test_cases = latest_test_set.content.get("test_cases", [])
                        for tc in test_cases:
                            tc_text = (
                                f"{tc.get('title', '')} {tc.get('objective', '')} "
                                f"{' '.join(tc.get('preconditions', []))} {' '.join(tc.get('test_data', []))} "
                                f"{tc.get('expected_result', '')}"
                            )
                            tc_tokens = _extract_text_tokens(tc_text)
                            if matched_tokens and tc_tokens.intersection(matched_tokens):
                                impacted_cases.append(tc.get("id"))
                            elif not matched_tokens:
                                impacted_cases.append(tc.get("id"))

                dep.impacted_case_ids = impacted_cases
                impacted_dependencies.append(dep)

                # Continue cascade propagation down the DAG
                queue.append((dep.target_story_id, curr_tokens, curr_delta))

    db.commit()
    return impacted_dependencies


def analyze_story_impact(db: Session, story_id: str) -> StoryImpactAnalysisReport:
    """Generates an impact analysis report for the given story."""
    story = db.get(Story, story_id)
    if not story:
        raise NotFoundError("Story")

    all_stories = {s.id: s for s in db.execute(select(Story)).scalars().all()}

    # 1. Upstream Impacts (Dependencies where this story is target)
    upstream_deps = db.execute(
        select(StoryDependency).where(StoryDependency.target_story_id == story_id)
    ).scalars().all()

    upstream_reports: list[ImpactReportItem] = []

    # Get latest test cases of this story for detail lookup
    latest_test_set = db.scalar(
        select(TestCaseSet)
        .where(TestCaseSet.story_id == story_id)
        .order_by(TestCaseSet.created_at.desc())
    )
    test_cases_by_id = {}
    if latest_test_set and latest_test_set.content:
        for tc in latest_test_set.content.get("test_cases", []):
            test_cases_by_id[tc.get("id")] = tc

    for dep in upstream_deps:
        src_story = all_stories.get(dep.source_story_id)
        src_title = src_story.title if src_story else "Unknown"
        src_version = src_story.version if src_story else dep.synced_source_version

        case_details: list[ImpactedCaseDetail] = []
        for cid in dep.impacted_case_ids or []:
            tc = test_cases_by_id.get(cid)
            title = tc.get("title", f"Test Case {cid}") if tc else f"Test Case {cid}"
            case_details.append(
                ImpactedCaseDetail(
                    case_id=cid,
                    title=title,
                    reason=(dep.stale_reason or {}).get("reason", "Tác động từ thay đổi thượng nguồn"),
                )
            )

        upstream_reports.append(
            ImpactReportItem(
                dependency_id=dep.id,
                source_story_id=dep.source_story_id,
                source_story_title=src_title,
                target_story_id=dep.target_story_id,
                target_story_title=story.title,
                synced_source_version=dep.synced_source_version,
                current_source_version=src_version,
                impact_status=dep.impact_status,
                stale_reason=dep.stale_reason,
                impacted_case_ids=dep.impacted_case_ids or [],
                impacted_cases=case_details,
            )
        )

    # 2. Downstream Impacts (Dependencies where this story is source)
    downstream_deps = db.execute(
        select(StoryDependency).where(StoryDependency.source_story_id == story_id)
    ).scalars().all()

    downstream_reports: list[ImpactReportItem] = []
    for dep in downstream_deps:
        tgt_story = all_stories.get(dep.target_story_id)
        tgt_title = tgt_story.title if tgt_story else "Unknown"

        downstream_reports.append(
            ImpactReportItem(
                dependency_id=dep.id,
                source_story_id=story.id,
                source_story_title=story.title,
                target_story_id=dep.target_story_id,
                target_story_title=tgt_title,
                synced_source_version=dep.synced_source_version,
                current_source_version=story.version,
                impact_status=dep.impact_status,
                stale_reason=dep.stale_reason,
                impacted_case_ids=dep.impacted_case_ids or [],
                impacted_cases=[],
            )
        )

    has_impact = any(item.impact_status != "synced" for item in upstream_reports) or any(
        item.impact_status != "synced" for item in downstream_reports
    )

    return StoryImpactAnalysisReport(
        story_id=story.id,
        story_title=story.title,
        story_version=story.version,
        has_impacted_dependencies=has_impact,
        upstream_impacts=upstream_reports,
        downstream_impacts=downstream_reports,
    )
