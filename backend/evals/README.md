# API contract reasoning regressions

Run from `backend` with a configured `AI_PROVIDER` and API key:

```powershell
python -m evals.api_contract_regressions --output api-contract-eval-results.json
```

The script calls the configured model once per fixture. A QA reviewer compares each finding
with `qa_check`, sets `qa_result` to `pass` or `fail`, and records the reasoning in `qa_notes`.
The runner does not use another model to grade the output. Keep result files out of Git if
they contain provider output or story data from a real project.

## Requirement review reasoning

```sh
python -m evals.requirement_regressions --output requirement-eval-results.json
```

Seven bilingual fixtures cover exact status codes, atomic limits and state changes, unanswered
questions, conflicts, sample data, upstream contracts, and prompt injection. Optional `--case`
selects one fixture. QA records pass/fail against `qa_check`. Structural validation is not a
semantic quality score. This opt-in command calls the configured model.

Review v5 separates `proposed_ac` from analysis in `detail`. Adding an AC requires confirmed
behavior, expected result, reviewer name, review ID and expected story version. The finding
retains its accepted AC and reviewer. Replaying the same acceptance is idempotent; stale and
conflicting requests fail. Old findings without a proposed AC require manual entry. Existing
AC text is never rewritten automatically.

New approvals verify local story sources. Paraphrases and obligations outside literal source
substrings require human confirmation; this is not automatic semantic proof or authenticated
identity. Blocking questions need an answer/rejection reason and reviewer before approval.
Existing approved artifacts are not retroactively revoked; re-review them to apply new checks.
Missing ACs trigger at most one model repair, then remain draft if incomplete. Keep real story
and model outputs out of Git.
