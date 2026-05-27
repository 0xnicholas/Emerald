"""Integration tests for file upload against real services."""

import pytest


def test_upload_creates_document():
    # TODO: unskip when MinIO + PostgreSQL + Celery worker are running in CI
    pytest.skip("Requires running MinIO + PostgreSQL + Celery worker")
