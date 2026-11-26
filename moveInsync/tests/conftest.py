"""
Shared test fixtures.
"""
import os
import pytest

# Always use in-memory SQLite and fake LLM for tests
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
