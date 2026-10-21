import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.webhook import process_webhook_payload

def test_github_webhook_pull_request():
    payload = {
        "action": "opened",
        "number": 105,
        "pull_request": {
            "number": 105,
            "title": "feat(payment): implement 3D secure card verification",
            "diff": """diff --git a/backend/app/api/v1/payment.py b/backend/app/api/v1/payment.py
--- a/backend/app/api/v1/payment.py
+++ b/backend/app/api/v1/payment.py
@@ -15,3 +15,4 @@
+def verify_3d_secure(token: str):
"""
        }
    }

    res = process_webhook_payload(payload, event="pull_request")
    assert res.pr_number == 105
    assert "AI QA Impact Analysis" in res.markdown_comment
    assert res.total_files_changed >= 1

def test_github_webhook_ping():
    res = process_webhook_payload({"zen": "Design for failure."}, event="ping")
    assert res.event_type == "ping"
    assert "active and verified" in res.markdown_comment
