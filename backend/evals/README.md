# API contract reasoning regressions

Run from `backend` with a configured `AI_PROVIDER` and API key:

```powershell
python -m evals.api_contract_regressions --output api-contract-eval-results.json
```

The script calls the configured model once per fixture. A QA reviewer compares each finding
with `qa_check`, sets `qa_result` to `pass` or `fail`, and records the reasoning in `qa_notes`.
The runner does not use another model to grade the output. Keep result files out of Git if
they contain provider output or story data from a real project.
