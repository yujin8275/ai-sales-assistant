from contextlib import contextmanager

import pytest
from psycopg import OperationalError
from sqlalchemy.exc import DBAPIError

from backend.app import repository


def test_temporary_connection_error_retried_once(monkeypatch):
    calls = []

    @contextmanager
    def snapshot(engine):
        calls.append(1)
        if len(calls) == 1:
            raise DBAPIError(None, None, OperationalError("connection refused"))
        yield "repository"

    monkeypatch.setattr(repository, "snapshot", snapshot)
    assert repository.read_once_retry(None, lambda repo: repo) == "repository"
    assert len(calls) == 2


def test_connection_error_not_retried_indefinitely(monkeypatch):
    calls = []

    @contextmanager
    def snapshot(engine):
        calls.append(1)
        raise DBAPIError(None, None, OperationalError("connection refused"))
        yield

    monkeypatch.setattr(repository, "snapshot", snapshot)
    with pytest.raises(DBAPIError):
        repository.read_once_retry(None, lambda repo: repo)
    assert len(calls) == 2


def test_query_error_not_retried(monkeypatch):
    calls = []

    @contextmanager
    def snapshot(engine):
        calls.append(1)
        raise DBAPIError(None, None, ValueError("invalid query"))
        yield

    monkeypatch.setattr(repository, "snapshot", snapshot)
    with pytest.raises(DBAPIError):
        repository.read_once_retry(None, lambda repo: repo)
    assert len(calls) == 1
