import hashlib
import re
from collections import defaultdict, deque
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import (
    CollectionStoryMember,
    Story,
    StoryCollection,
    StoryDependency,
    TestCaseSet,
)
from app.schemas.story_collection import (
    CollectionMemberRead,
    StoryCollectionRead,
)


def find_weakly_connected_components(
    story_ids: set[str], edges: list[tuple[str, str]]
) -> list[set[str]]:
    """Identifies all weakly connected components of size >= 2 from directed edges."""
    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)

    visited = set()
    components = []

    for sid in story_ids:
        if sid not in visited and sid in adj:
            comp = set()
            queue = deque([sid])
            visited.add(sid)
            while queue:
                curr = queue.popleft()
                comp.add(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            if len(comp) >= 2:
                components.append(comp)

    return components


def topological_sort_subgraph(
    component_story_ids: set[str],
    directed_edges: list[tuple[str, str]],
    story_titles: dict[str, str],
) -> list[str]:
    """Sorts stories in a component into topological execution order using Kahn's algorithm."""
    in_degree = {sid: 0 for sid in component_story_ids}
    adj = defaultdict(list)

    for u, v in directed_edges:
        if u in component_story_ids and v in component_story_ids:
            adj[u].append(v)
            in_degree[v] += 1

    # Deterministic tie-breaker using story title / id
    zero_in = [
        sid for sid, deg in in_degree.items() if deg == 0
    ]
    zero_in.sort(key=lambda s: (story_titles.get(s, ""), s))
    zero_queue = deque(zero_in)

    topo_order = []
    while zero_queue:
        curr = zero_queue.popleft()
        topo_order.append(curr)
        next_nodes = []
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                next_nodes.append(neighbor)
        next_nodes.sort(key=lambda s: (story_titles.get(s, ""), s))
        zero_queue.extend(next_nodes)

    # If any nodes were not reachable in DAG, append them deterministically
    remaining = [sid for sid in component_story_ids if sid not in topo_order]
    remaining.sort(key=lambda s: (story_titles.get(s, ""), s))
    topo_order.extend(remaining)

    return topo_order


def generate_collection_identity(
    topo_order: list[str], story_titles: dict[str, str], existing_codes: set[str]
) -> tuple[str, str]:
    """Generates an intuitive collection name and unique alphanumeric code."""
    first_title = story_titles.get(topo_order[0], "Start")
    last_title = story_titles.get(topo_order[-1], "End")

    clean_first = re.sub(r"^(Story\s*\d+\s*:\s*)", "", first_title, flags=re.IGNORECASE).strip()
    clean_last = re.sub(r"^(Story\s*\d+\s*:\s*)", "", last_title, flags=re.IGNORECASE).strip()

    if len(topo_order) == 2:
        name = f"Luồng E2E: {clean_first} ➔ {clean_last}"
    else:
        name = f"Luồng E2E: {clean_first} ➔ ... ➔ {clean_last} ({len(topo_order)} Stories)"

    # Generate a stable deterministic hash code from story IDs
    hash_seed = "-".join(sorted(topo_order))
    short_hash = hashlib.sha256(hash_seed.encode("utf-8")).hexdigest()[:6].upper()
    code = f"COL-{short_hash}"

    idx = 1
    original_code = code
    while code in existing_codes:
        code = f"{original_code}-{idx}"
        idx += 1

    return name, code


def determine_collection_health(
    component_story_ids: set[str], deps: list[StoryDependency]
) -> str:
    """Evaluates the composite health of all DAG edges in this collection."""
    statuses = set()
    for d in deps:
        if d.source_story_id in component_story_ids and d.target_story_id in component_story_ids:
            statuses.add(d.impact_status)

    if "broken" in statuses:
        return "broken"
    if "suspect_stale" in statuses:
        return "suspect_stale"
    return "synced"


def discover_and_sync_collections(db: Session) -> list[StoryCollection]:
    """Auto-clusters all linked stories (>= 2) into StoryCollections safely."""
    deps = db.execute(select(StoryDependency)).scalars().all()
    all_stories = db.execute(select(Story)).scalars().all()
    story_map = {s.id: s for s in all_stories}
    story_titles = {s.id: s.title for s in all_stories}

    directed_edges = [(d.source_story_id, d.target_story_id) for d in deps]
    all_story_ids = set(story_map.keys())

    components = find_weakly_connected_components(all_story_ids, directed_edges)

    existing_collections = db.execute(select(StoryCollection)).scalars().all()
    existing_codes = {c.code for c in existing_collections}

    synced_collections = []

    for comp in components:
        topo_order = topological_sort_subgraph(comp, directed_edges, story_titles)
        health = determine_collection_health(comp, deps)

        # Check if an existing collection already covers this exact component
        matched_collection = None
        for col in existing_collections:
            member_ids = {m.story_id for m in col.members}
            if member_ids == comp:
                matched_collection = col
                break

        if matched_collection:
            matched_collection.execution_order = topo_order
            matched_collection.health_status = health
            matched_collection.updated_at = datetime.now(UTC)

            # Re-sync members sequence & roles
            db.execute(
                delete(CollectionStoryMember).where(
                    CollectionStoryMember.collection_id == matched_collection.id
                )
            )
            for idx, sid in enumerate(topo_order):
                role = "entry_point" if idx == 0 else ("terminal" if idx == len(topo_order) - 1 else "intermediate")
                db.add(
                    CollectionStoryMember(
                        collection_id=matched_collection.id,
                        story_id=sid,
                        sequence_order=idx + 1,
                        role_in_flow=role,
                    )
                )
            synced_collections.append(matched_collection)
        else:
            name, code = generate_collection_identity(topo_order, story_titles, existing_codes)
            existing_codes.add(code)

            new_col = StoryCollection(
                name=name,
                code=code,
                description=f"Bộ luồng kiểm thử E2E tự động kết nối {len(topo_order)} User Stories.",
                collection_type="dag_journey",
                execution_order=topo_order,
                health_status=health,
                metadata_info={"discovered_at": datetime.now(UTC).isoformat()},
            )
            db.add(new_col)
            db.flush()

            for idx, sid in enumerate(topo_order):
                role = "entry_point" if idx == 0 else ("terminal" if idx == len(topo_order) - 1 else "intermediate")
                db.add(
                    CollectionStoryMember(
                        collection_id=new_col.id,
                        story_id=sid,
                        sequence_order=idx + 1,
                        role_in_flow=role,
                    )
                )
            synced_collections.append(new_col)

    db.commit()
    for col in synced_collections:
        db.refresh(col)

    return synced_collections


def get_all_collections_with_stats(db: Session) -> list[StoryCollectionRead]:
    """Retrieves all story collections enriched with member details and test statistics."""
    # Run auto-discovery first to guarantee current sync
    discover_and_sync_collections(db)

    collections = db.execute(
        select(StoryCollection).order_by(StoryCollection.created_at.desc())
    ).scalars().all()

    stories = {s.id: s for s in db.execute(select(Story)).scalars().all()}
    test_sets = db.execute(select(TestCaseSet)).scalars().all()

    # Map story_id -> latest test cases count and status
    story_test_stats = defaultdict(lambda: {"count": 0, "status": "no_tests"})
    for ts in test_sets:
        cases = (ts.content or {}).get("test_cases", [])
        story_test_stats[ts.story_id] = {
            "count": len(cases),
            "status": ts.status,
        }

    read_collections = []
    for col in collections:
        member_reads = []
        total_tc = 0

        # Sort members by sequence_order
        sorted_members = sorted(col.members, key=lambda m: m.sequence_order)
        for m in sorted_members:
            st = stories.get(m.story_id)
            stats = story_test_stats.get(m.story_id, {"count": 0, "status": "no_tests"})
            total_tc += stats["count"]

            member_reads.append(
                CollectionMemberRead(
                    id=m.id,
                    collection_id=m.collection_id,
                    story_id=m.story_id,
                    story_title=st.title if st else f"Story {m.story_id[:8]}",
                    story_version=st.version if st else 1,
                    sequence_order=m.sequence_order,
                    role_in_flow=m.role_in_flow,
                    test_cases_count=stats["count"],
                    test_set_status=stats["status"],
                )
            )

        read_collections.append(
            StoryCollectionRead(
                id=col.id,
                name=col.name,
                code=col.code,
                description=col.description,
                collection_type=col.collection_type,
                execution_order=col.execution_order,
                health_status=col.health_status,
                metadata_info=col.metadata_info,
                created_at=col.created_at,
                updated_at=col.updated_at,
                members=member_reads,
                total_stories=len(member_reads),
                total_test_cases=total_tc,
            )
        )

    return read_collections


def get_collection_by_id(db: Session, collection_id: str) -> StoryCollectionRead:
    """Retrieves a single collection by ID with full details."""
    col = db.get(StoryCollection, collection_id)
    if not col:
        raise NotFoundError(f"Story Collection '{collection_id}'")

    stories = {s.id: s for s in db.execute(select(Story)).scalars().all()}
    test_sets = db.execute(select(TestCaseSet)).scalars().all()

    story_test_stats = defaultdict(lambda: {"count": 0, "status": "no_tests"})
    for ts in test_sets:
        cases = (ts.content or {}).get("test_cases", [])
        story_test_stats[ts.story_id] = {
            "count": len(cases),
            "status": ts.status,
        }

    sorted_members = sorted(col.members, key=lambda m: m.sequence_order)
    member_reads = []
    total_tc = 0
    for m in sorted_members:
        st = stories.get(m.story_id)
        stats = story_test_stats.get(m.story_id, {"count": 0, "status": "no_tests"})
        total_tc += stats["count"]
        member_reads.append(
            CollectionMemberRead(
                id=m.id,
                collection_id=m.collection_id,
                story_id=m.story_id,
                story_title=st.title if st else f"Story {m.story_id[:8]}",
                story_version=st.version if st else 1,
                sequence_order=m.sequence_order,
                role_in_flow=m.role_in_flow,
                test_cases_count=stats["count"],
                test_set_status=stats["status"],
            )
        )

    return StoryCollectionRead(
        id=col.id,
        name=col.name,
        code=col.code,
        description=col.description,
        collection_type=col.collection_type,
        execution_order=col.execution_order,
        health_status=col.health_status,
        metadata_info=col.metadata_info,
        created_at=col.created_at,
        updated_at=col.updated_at,
        members=member_reads,
        total_stories=len(member_reads),
        total_test_cases=total_tc,
    )


def update_collection(
    db: Session,
    collection_id: str,
    name: str | None = None,
    description: str | None = None,
    execution_order: list[str] | None = None,
) -> StoryCollectionRead:
    """Updates metadata or customized sequence of a collection."""
    col = db.get(StoryCollection, collection_id)
    if not col:
        raise NotFoundError(f"Story Collection '{collection_id}'")

    if name is not None and name.strip():
        col.name = name.strip()
    if description is not None:
        col.description = description.strip()
    if execution_order is not None:
        col.execution_order = execution_order

    col.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(col)
    return get_collection_by_id(db, collection_id)


def delete_collection(db: Session, collection_id: str) -> None:
    """Deletes a collection group without deleting the member stories themselves."""
    col = db.get(StoryCollection, collection_id)
    if not col:
        raise NotFoundError(f"Story Collection '{collection_id}'")
    db.delete(col)
    db.commit()


def export_collection_postman(db: Session, collection_id: str) -> dict:
    """Generates an official Postman Collection v2.1 JSON structure for the entire E2E flow."""
    col_read = get_collection_by_id(db, collection_id)
    test_sets = db.execute(select(TestCaseSet)).scalars().all()
    test_set_by_story = {ts.story_id: ts for ts in test_sets}

    folders = []
    for member in col_read.members:
        ts = test_set_by_story.get(member.story_id)
        cases = (ts.content or {}).get("test_cases", []) if ts else []

        items = []
        for case in cases:
            method = case.get("api_method") or "POST"
            path = case.get("api_path") or f"/api/stories/{member.story_id}"
            req_body = case.get("api_request") or "{}"

            # Postman item
            item = {
                "name": f"[{case.get('id', 'TC')}] {case.get('title', 'Test Case')}",
                "request": {
                    "method": method,
                    "header": [
                        {"key": "Content-Type", "value": "application/json"},
                        {"key": "Authorization", "value": "Bearer {{jwt_token}}"},
                    ],
                    "body": {
                        "mode": "raw",
                        "raw": req_body,
                        "options": {"raw": {"language": "json"}},
                    },
                    "url": {
                        "raw": f"{{{{baseUrl}}}}{path}",
                        "host": ["{{baseUrl}}"],
                        "path": [p for p in path.strip("/").split("/") if p],
                    },
                    "description": case.get("objective") or "",
                },
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                f"// Assertion: {case.get('expected_result', 'Success')}",
                                "pm.test('Status code is 200 or expected', function () {",
                                "    pm.expect(pm.response.code).to.be.oneOf([200, 201, 422]);",
                                "});",
                                "",
                                "// E2E Data Pipe: Auto-capture runtime tokens for downstream stories",
                                "try {",
                                "    var res = pm.response.json();",
                                "    if (res.jwt_token) pm.collectionVariables.set('jwt_token', res.jwt_token);",
                                "    if (res.customer_id) pm.collectionVariables.set('customer_id', res.customer_id);",
                                "    if (res.order_id) pm.collectionVariables.set('order_id', res.order_id);",
                                "} catch (e) {}",
                            ],
                        },
                    }
                ],
            }
            items.append(item)

        folders.append(
            {
                "name": f"Step {member.sequence_order}: {member.story_title} ({member.role_in_flow})",
                "item": items,
                "description": f"Story ID: {member.story_id} • Cases: {len(items)}",
            }
        )

    return {
        "info": {
            "_postman_id": col_read.id,
            "name": f"{col_read.name} [{col_read.code}]",
            "description": col_read.description or "E2E Journey Suite generated by AI QA Assistant",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": folders,
        "variable": [
            {"key": "baseUrl", "value": "http://127.0.0.1:8000", "type": "string"},
            {"key": "jwt_token", "value": "", "type": "string"},
            {"key": "customer_id", "value": "", "type": "string"},
            {"key": "order_id", "value": "", "type": "string"},
        ],
    }
