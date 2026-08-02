"""
Shared fixtures for the AI-layer test suite.

`fake_llm` mocks the one real network boundary (`llm_client.complete`, which
`complete_json` also calls internally) so every test is free, deterministic,
and needs no ANTHROPIC_API_KEY. Everything else — prompt building, SQL
guardrails, permission checks, DB retrieval — runs for real. Read-only
queries run against the actual dev database (`app.db.session.SessionLocal`)
since it already has seeded catalog data (employees/projects/skills); no
test in this suite performs a write against it.
"""
import pytest

from app.db.session import SessionLocal


class FakeLLM:
    """Dispatches canned responses to `llm_client.complete` calls based on a
    predicate over (system, user), in registration order. Raises loudly if a
    call doesn't match anything registered, so an untested prompt shape
    fails the test instead of silently returning nonsense."""

    def __init__(self):
        self._rules = []
        self.calls = []

    def when(self, predicate, response):
        self._rules.append((predicate, response))
        return self

    def __call__(self, system, user, max_tokens=1024, temperature=0.2, usage_sink=None):
        self.calls.append({"system": system, "user": user})
        if usage_sink is not None:
            usage_sink.append({"input_tokens": 100, "output_tokens": 20, "duration_ms": 5.0})
        for predicate, response in self._rules:
            if predicate(system, user):
                return response
        raise AssertionError(f"fake_llm: no rule matched this prompt:\n{user[:300]}")


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("app.services.ai.llm_client.complete", fake)
    return fake


@pytest.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session
