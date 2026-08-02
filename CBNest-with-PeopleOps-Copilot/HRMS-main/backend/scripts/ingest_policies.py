"""
Index (or re-index) every row in hr_policies into the policy_chunks vector
store used by the Policy RAG Assistant.

Run with (from backend/, venv active):
    python -m scripts.ingest_policies

Safe to re-run at any time — ingestion is idempotent (each policy's old
chunks are replaced). Run this after `python -m scripts.seed` (or after
uploading/editing any policy via POST /api/v1/hr-policies/upload) so the
Policy RAG Assistant has something to retrieve from.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.ai.policy_rag import ingest_all_policies


async def main():
    async with SessionLocal() as db:
        chunk_count = await ingest_all_policies(db)
    if chunk_count == 0:
        print("No HR policies with readable content were found. Seed the DB first (python -m scripts.seed).")
    else:
        print(f"Indexed {chunk_count} policy chunks into the vector store.")


if __name__ == "__main__":
    asyncio.run(main())
