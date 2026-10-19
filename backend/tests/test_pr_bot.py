import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.pr_bot import analyze_pr_diff, PRAnalyzeRequest

SAMPLE_GIT_DIFF = """
diff --git a/src/Services/OrderService.cs b/src/Services/OrderService.cs
index e69de29..d95f3ad 100644
--- a/src/Services/OrderService.cs
+++ b/src/Services/OrderService.cs
@@ -10,6 +10,8 @@ namespace App.Services
     {
+        public async Task<OrderResult> ProcessPaymentAsync(CheckoutRequest req)
+        {
             // Updated payment processing logic
+            return await _repo.SaveOrderAsync(req);
+        }
     }
"""

def test_pr_impact_bot():
    req = PRAnalyzeRequest(
        pr_title="Feat: Update Checkout Payment Logic",
        pr_number=42,
        git_diff=SAMPLE_GIT_DIFF
    )
    res = analyze_pr_diff(req)

    assert res.pr_number == 42
    assert res.total_files_changed == 1
    assert len(res.impacted_components) == 1
    
    comp = res.impacted_components[0]
    assert "OrderService.cs" in comp.file_path
    assert "ProcessPaymentAsync" in comp.modified_functions

    # Check regression tests
    assert any("test_processpaymentasync.py" in test for test in res.recommended_regression_tests)

    # Check markdown comment
    assert "AI QA Impact Analysis for PR #42" in res.markdown_comment
    assert "OrderService.cs" in res.markdown_comment
