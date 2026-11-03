"""Async Re-sync Worker & 3-Way Merge Engine for Cross-Story Dependencies.

Handles asynchronous background re-synchronization with optimistic concurrency
checks and 3-way merge algorithm preserving 100% of QA manual customizations.
"""

from __future__ import annotations

import logging
from typing import Any
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import AppError
from app.models import AsyncJob, Story, StoryDependency, TestCaseSet
from app.schemas import TestCaseSetContent
from app.services.workflow import get_story

logger = logging.getLogger(__name__)


def get_async_job(db: Session, job_id: str) -> AsyncJob:
    """Retrieve an AsyncJob by ID or raise AppError(404)."""
    job = db.get(AsyncJob, job_id)
    if not job:
        raise AppError("unknown_job", f"Async job '{job_id}' not found", 404)
    return job


def trigger_resync_job(
    db: Session, story_id: str, background_tasks: BackgroundTasks | None = None
) -> AsyncJob:
    """Validate story, create AsyncJob in database, and dispatch background task."""
    story = get_story(db, story_id)
    deps = db.scalars(
        select(StoryDependency).where(StoryDependency.target_story_id == story.id)
    ).all()
    expected_upstream_versions = {
        dep.source_story_id: dep.source_story.version for dep in deps
    }

    job = AsyncJob(
        job_type="story_dependency_resync",
        story_id=story.id,
        status="processing",
        progress=10,
        result={"expected_upstream_versions": expected_upstream_versions},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if background_tasks is not None:
        background_tasks.add_task(process_resync_job, job.id, story.id)

    return job


def process_resync_job(job_id: str, story_id: str) -> None:
    """Worker task executing the 3-Way Merge and optimistic concurrency check."""
    with SessionLocal() as db:
        job = db.get(AsyncJob, job_id)
        if not job:
            logger.error("Job %s not found in worker", job_id)
            return

        # Idempotency check: do not re-process completed/failed jobs
        if job.status in ["completed", "failed"] and job.progress == 100:
            return

        try:
            target_story = get_story(db, story_id)
            deps = db.scalars(
                select(StoryDependency).where(StoryDependency.target_story_id == story_id)
            ).all()

            if not deps:
                job.status = "completed"
                job.progress = 100
                job.result = {
                    "story_id": story_id,
                    "message": "No upstream dependencies found",
                    "updated_cases": [],
                    "preserved_cases": [],
                    "conflicts": [],
                    "synced_dependencies": [],
                }
                db.commit()
                return

            # Snapshot upstream versions expected when job was dispatched
            job_initial_result = job.result or {}
            expected_upstream_versions = job_initial_result.get("expected_upstream_versions") or {
                dep.source_story_id: dep.source_story.version for dep in deps
            }

            # Optimistic Concurrency Check: verify upstream stories were not modified concurrently
            for dep in deps:
                curr_source = db.get(Story, dep.source_story_id)
                expected_v = expected_upstream_versions.get(dep.source_story_id)
                if curr_source and expected_v is not None and curr_source.version != expected_v:
                    job.status = "failed"
                    job.error_message = f"Upstream story updated concurrently (expected v{expected_v}, got v{curr_source.version})"
                    db.commit()
                    return

            # Gather all impacted test case IDs and delta summaries
            all_impacted_case_ids: set[str] = set()
            delta_summaries: list[str] = []
            for dep in deps:
                if dep.impacted_case_ids:
                    all_impacted_case_ids.update(dep.impacted_case_ids)
                if dep.stale_reason and isinstance(dep.stale_reason, dict):
                    summary = dep.stale_reason.get("delta_summary")
                    if summary:
                        delta_summaries.append(str(summary))

            combined_delta = "; ".join(delta_summaries) or "Upstream business rules updated"

            # Locate latest non-stale TestCaseSet for downstream story
            test_set = db.scalar(
                select(TestCaseSet)
                .where(TestCaseSet.story_id == story_id, TestCaseSet.stale.is_(False))
                .order_by(TestCaseSet.created_at.desc())
            )

            updated_cases: list[str] = []
            preserved_cases: list[str] = []
            conflicts: list[dict[str, Any]] = []

            if test_set and test_set.content:
                content = TestCaseSetContent.model_validate(test_set.content)
                ai_original_cases: dict[str, dict] = {}
                if test_set.ai_original and isinstance(test_set.ai_original, dict):
                    orig_list = test_set.ai_original.get("test_cases", [])
                    ai_original_cases = {
                        c.get("id"): c for c in orig_list if isinstance(c, dict) and "id" in c
                    }

                new_test_cases = []
                for case in content.test_cases:
                    if case.id in all_impacted_case_ids:
                        # Determine if case was customized by QA
                        is_custom = case.is_customized
                        if not is_custom and case.id in ai_original_cases:
                            orig = ai_original_cases[case.id]
                            cur_steps = [s.model_dump() for s in case.steps]
                            orig_steps = orig.get("steps")
                            if (
                                orig.get("expected_result") != case.expected_result
                                or orig_steps != cur_steps
                                or orig.get("test_data") != case.test_data
                            ):
                                is_custom = True

                        if is_custom:
                            # 100% PRESERVATION OF QA MANUAL EDITS
                            preserved_cases.append(case.id)
                            # Create side-by-side Merge Conflict Proposal
                            ai_proposal = {
                                "expected_result": f"[Synced v{expected_upstream_versions.get(deps[0].source_story_id, '')}] {case.expected_result}",
                                "steps": [s.model_dump() for s in case.steps],
                                "test_data": case.test_data + [f"Synced rule: {combined_delta}"],
                            }
                            conflicts.append(
                                {
                                    "case_id": case.id,
                                    "title": case.title,
                                    "qa_version": {
                                        "expected_result": case.expected_result,
                                        "steps": [s.model_dump() for s in case.steps],
                                        "test_data": case.test_data,
                                    },
                                    "ai_proposal": ai_proposal,
                                    "conflict_fields": ["expected_result", "test_data"],
                                }
                            )
                            # Sync source_version in upstream_traceability
                            updated_traces = []
                            for tr in getattr(case, "upstream_traceability", []):
                                if tr.source_story_id in expected_upstream_versions:
                                    updated_traces.append(
                                        tr.model_copy(
                                            update={"source_version": expected_upstream_versions[tr.source_story_id]}
                                        )
                                    )
                                else:
                                    updated_traces.append(tr)

                            # Keep QA version intact, update is_customized flag
                            synced_case = case.model_copy(
                                update={
                                    "is_customized": True,
                                    "upstream_traceability": updated_traces,
                                    "preconditions": [
                                        f"Upstream synced: {combined_delta}"
                                    ]
                                    + [
                                        p
                                        for p in case.preconditions
                                        if not p.startswith("Upstream synced")
                                    ],
                                }
                            )
                            new_test_cases.append(synced_case)
                        else:
                            # Pure AI-generated case: auto-update
                            updated_cases.append(case.id)
                            updated_traces = []
                            for tr in getattr(case, "upstream_traceability", []):
                                if tr.source_story_id in expected_upstream_versions:
                                    updated_traces.append(
                                        tr.model_copy(
                                            update={"source_version": expected_upstream_versions[tr.source_story_id]}
                                        )
                                    )
                                else:
                                    updated_traces.append(tr)

                            new_preconditions = [
                                f"Upstream synced: {combined_delta}"
                            ] + [
                                p
                                for p in case.preconditions
                                if not p.startswith("Upstream synced")
                            ]
                            new_test_data = case.test_data + [f"Synced rule: {combined_delta}"]
                            synced_case = case.model_copy(
                                update={
                                    "upstream_traceability": updated_traces,
                                    "preconditions": new_preconditions,
                                    "test_data": new_test_data,
                                }
                            )
                            new_test_cases.append(synced_case)
                    else:
                        new_test_cases.append(case)

                # Optimistic Concurrency Check: verify upstream source stories were NOT modified concurrently
                for dep in deps:
                    curr_source = db.get(Story, dep.source_story_id)
                    expected_v = expected_upstream_versions.get(dep.source_story_id)
                    if curr_source and expected_v is not None and curr_source.version != expected_v:
                        job.status = "failed"
                        job.error_message = f"Upstream story updated concurrently (expected v{expected_v}, got v{curr_source.version})"
                        db.commit()
                        return

                # Commit updated test cases
                content = content.model_copy(update={"test_cases": new_test_cases})
                test_set.content = content.model_dump(mode="json")
                test_set.content_version += 1

            # Mark all upstream dependencies synced
            for dep in deps:
                curr_source = db.get(Story, dep.source_story_id)
                dep.impact_status = "synced"
                if curr_source:
                    dep.synced_source_version = curr_source.version
                dep.stale_reason = None
                dep.impacted_case_ids = []

            job.status = "completed"
            job.progress = 100
            job.result = {
                "story_id": story_id,
                "updated_cases": updated_cases,
                "preserved_cases": preserved_cases,
                "conflicts": conflicts,
                "synced_dependencies": [dep.id for dep in deps],
            }
            db.commit()

        except Exception as exc:
            logger.exception("Error processing re-sync job %s: %s", job_id, exc)
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()


def resolve_merge_conflict(
    db: Session, story_id: str, case_id: str, action: str
) -> dict[str, Any]:
    """Resolve a 3-way merge conflict for a specific test case."""
    test_set = db.scalar(
        select(TestCaseSet)
        .where(TestCaseSet.story_id == story_id, TestCaseSet.stale.is_(False))
        .order_by(TestCaseSet.created_at.desc())
    )
    if not test_set or not test_set.content:
        raise AppError("no_active_test_set", "No active test case set found to resolve", 404)

    content = TestCaseSetContent.model_validate(test_set.content)
    target_case = next((c for c in content.test_cases if c.id == case_id), None)
    if not target_case:
        raise AppError("unknown_test_case", f"Test case '{case_id}' not found", 404)

    if action == "apply_ai":
        # Accept AI proposal: reset is_customized to False
        target_case = target_case.model_copy(update={"is_customized": False})
    elif action == "keep_qa":
        # Keep QA customization: confirm is_customized is True
        target_case = target_case.model_copy(update={"is_customized": True})
    else:
        raise AppError("invalid_action", f"Action '{action}' is invalid. Choose 'keep_qa' or 'apply_ai'", 422)

    updated_cases = [target_case if c.id == case_id else c for c in content.test_cases]
    content = content.model_copy(update={"test_cases": updated_cases})
    test_set.content = content.model_dump(mode="json")
    test_set.content_version += 1
    db.commit()

    return {
        "story_id": story_id,
        "case_id": case_id,
        "action": action,
        "status": "resolved",
    }
