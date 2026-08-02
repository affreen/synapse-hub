from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PolicyChunk(Base):
    """
    Retrieval-friendly chunks of an HRPolicy's content, produced by the
    ingestion pipeline in app/services/ai/policy_rag.py.

    HRPolicy already had a placeholder `embedding` column (whole-document,
    Phase-3 stub). We add this table instead of using that column directly
    because the assignment calls for chunk-level retrieval, which needs
    multiple embedding rows per policy, not one. HRPolicy.embedding is left
    untouched/unused by this feature.
    """

    __tablename__ = "policy_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("hr_policies.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[str] = mapped_column(Text)  # JSON-encoded list[float]
