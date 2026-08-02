"""
Vector store for policy chunks — uses the app's own SQLite DB
(policy_chunks table) as the vector store, per the assignment's "existing
database field" option, keeping the whole stack to one datastore. Swapping
to Chroma/FAISS/Qdrant later only means changing this module.
"""
import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_policy import HRPolicy
from app.models.policy_chunk import PolicyChunk
from app.services.ai.embeddings import cosine_similarity


async def upsert_chunks(db: AsyncSession, policy_id: int, chunks: list[str], embeddings: list[list[float]]) -> None:
    await db.execute(delete(PolicyChunk).where(PolicyChunk.policy_id == policy_id))
    for idx, (text, emb) in enumerate(zip(chunks, embeddings)):
        db.add(PolicyChunk(policy_id=policy_id, chunk_index=idx, text=text, embedding_json=json.dumps(emb)))
    await db.commit()


async def search(db: AsyncSession, query_embedding: list[float], top_k: int = 4) -> list[dict]:
    """Brute-force cosine similarity — fine for a policy library of tens to
    low hundreds of documents. Swap for an ANN index at larger scale."""
    chunk_rows = (await db.execute(select(PolicyChunk))).scalars().all()
    if not chunk_rows:
        return []

    policy_ids = {c.policy_id for c in chunk_rows}
    policies = (await db.execute(select(HRPolicy).where(HRPolicy.id.in_(policy_ids)))).scalars().all()
    policy_by_id = {p.id: p for p in policies}

    scored = []
    for chunk in chunk_rows:
        emb = json.loads(chunk.embedding_json)
        score = cosine_similarity(query_embedding, emb)
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, chunk in scored[:top_k]:
        policy = policy_by_id.get(chunk.policy_id)
        if policy is None:
            continue
        results.append({"score": score, "text": chunk.text, "policy_id": chunk.policy_id, "policy": policy})
    return results
