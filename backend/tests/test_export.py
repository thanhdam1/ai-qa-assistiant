from app import models
from app.services import export


def test_csv_exports_are_utf8_bom_and_preserve_multiline(review_content, test_content):
    review = models.RequirementReview(content=review_content.model_dump(mode="json"))
    test_set = models.TestCaseSet(content=test_content.model_dump(mode="json"))
    review_bytes = export.review_csv(review)
    tests_bytes = export.test_set_csv(test_set)
    assert review_bytes.startswith(b"\xef\xbb\xbf")
    assert "Người dùng đăng nhập" in review_bytes.decode("utf-8-sig")
    assert tests_bytes.startswith(b"\xef\xbb\xbf")
    assert "TC-001" in tests_bytes.decode("utf-8-sig")
