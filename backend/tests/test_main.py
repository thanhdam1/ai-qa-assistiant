import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app

def test_app_metadata():
    assert app.title == "AI QA Assistant & Codebase Q&A API"
    assert app.version == "1.0.0"

def test_app_routes():
    route_paths = [route.path for route in app.routes]
    assert "/" in route_paths
    assert "/health" in route_paths
