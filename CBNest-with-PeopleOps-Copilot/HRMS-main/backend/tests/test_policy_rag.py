from types import SimpleNamespace

from app.services.ai import policy_rag


def test_chunk_text_splits_on_paragraph_boundaries():
    text = "Para one.\n\nPara two.\n\nPara three."
    chunks = policy_rag.chunk_text(text, max_chars=20, overlap=5)
    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)


def test_chunk_text_empty_input_returns_no_chunks():
    assert policy_rag.chunk_text("") == []
    assert policy_rag.chunk_text("   \n\n  ") == []


def test_chunk_text_falls_back_to_newlines_without_blank_lines():
    text = "Line one.\nLine two.\nLine three."
    chunks = policy_rag.chunk_text(text, max_chars=1000)
    assert len(chunks) == 1
    assert "Line one." in chunks[0]


def _fake_policy(policy_id=1, title="Leave Policy", category="LEAVE", filename="seed_policy_01.md"):
    return SimpleNamespace(id=policy_id, title=title, category=category, original_filename=filename)


async def test_answer_policy_question_returns_grounded_answer_with_sources(monkeypatch, fake_llm):
    monkeypatch.setattr(policy_rag, "load_vocabulary", lambda: {"vocab": {}, "idf": {}, "n_docs": 1})
    monkeypatch.setattr(policy_rag, "embed_text", lambda text, vocab_data: [1.0])

    policy = _fake_policy()

    async def fake_search(db, query_embedding, top_k=4):
        return [
            {"score": 0.9, "text": "Casual, sick, and earned leave are allocated per policy.", "policy_id": 1, "policy": policy}
        ]

    monkeypatch.setattr(policy_rag.vector_store, "search", fake_search)
    fake_llm.when(lambda system, user: "CONTEXT" in user, "Leave is allocated per the Leave Policy.")

    result = await policy_rag.answer_policy_question(db=None, question="What is the leave policy?")

    assert result["sources"] == [{"title": "Leave Policy", "category": "LEAVE", "filename": "seed_policy_01.md"}]
    assert "Leave Policy" in result["answer"]


async def test_answer_policy_question_refuses_when_nothing_relevant(monkeypatch, fake_llm):
    monkeypatch.setattr(policy_rag, "load_vocabulary", lambda: {"vocab": {}, "idf": {}, "n_docs": 1})
    monkeypatch.setattr(policy_rag, "embed_text", lambda text, vocab_data: [1.0])

    async def fake_search(db, query_embedding, top_k=4):
        return []

    monkeypatch.setattr(policy_rag.vector_store, "search", fake_search)

    result = await policy_rag.answer_policy_question(db=None, question="What is the meaning of life?")

    assert result["sources"] == []
    assert "don't have enough information" in result["answer"].lower()
    assert not fake_llm.calls  # never even calls the LLM when nothing is retrieved


async def test_answer_policy_question_refuses_below_relevance_threshold(monkeypatch, fake_llm):
    monkeypatch.setattr(policy_rag, "load_vocabulary", lambda: {"vocab": {}, "idf": {}, "n_docs": 1})
    monkeypatch.setattr(policy_rag, "embed_text", lambda text, vocab_data: [1.0])
    weak_policy = _fake_policy(policy_id=9, title="Unrelated Policy")

    async def fake_search(db, query_embedding, top_k=4):
        return [{"score": 0.01, "text": "Barely related text.", "policy_id": 9, "policy": weak_policy}]

    monkeypatch.setattr(policy_rag.vector_store, "search", fake_search)

    result = await policy_rag.answer_policy_question(db=None, question="Irrelevant question")

    assert result["sources"] == []
    assert not fake_llm.calls


async def test_answer_policy_question_handles_missing_index_gracefully(monkeypatch):
    def raise_not_indexed():
        raise RuntimeError("not indexed")

    monkeypatch.setattr(policy_rag, "load_vocabulary", raise_not_indexed)

    result = await policy_rag.answer_policy_question(db=None, question="Anything")

    assert result["sources"] == []
    assert "hasn't been indexed" in result["answer"]
