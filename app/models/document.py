import uuid
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base, engine

is_postgres = False
if engine is not None:
    is_postgres = (engine.dialect.name == "postgresql")

UUID_TYPE = UUID(as_uuid=True) if is_postgres else String(36)

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()) if not is_postgres else uuid.uuid4)
    title = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # PDF, DOCX, TXT, URL, RAW_TEXT
    source_url = Column(String(1024), nullable=True)
    storage_path = Column(String(1024), nullable=True)
    content = Column(Text, nullable=False)
    verification_level = Column(String(50), default="COMMUNITY_SOURCE", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
