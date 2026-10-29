import threading
import zlib
from collections import defaultdict, deque
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.errors import AppError, CyclicDependencyError, NotFoundError
from app.models import Story, StoryDependency
from app.schemas import (
    DependencyNode,
    StoryDependencyCreate,
    StoryDependencyTree,
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
