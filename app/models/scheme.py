import uuid
import json
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, TypeDecorator, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base, engine

# Safe postgresql vs sqlite type selection
is_postgres = False
if engine is not None:
    is_postgres = (engine.dialect.name == "postgresql")

class SQLiteVector(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, dim):
        self.dim = dim
        super().__init__()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

try:
    from pgvector.sqlalchemy import Vector
    VectorType = Vector
except ImportError:
    VectorType = SQLiteVector

# Define portable types
UUID_TYPE = UUID(as_uuid=True) if is_postgres else String(36)
JSON_TYPE = JSONB if is_postgres else JSON
VECTOR_TYPE = VectorType(1024) if is_postgres else SQLiteVector(1024)

class SchemeRegistry(Base):
    __tablename__ = "scheme_registry"

    id = Column(UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()) if not is_postgres else uuid.uuid4)
    document_id = Column(UUID_TYPE, ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True)
    scheme_name = Column(String(255), unique=True, nullable=False, index=True)
    state = Column(String(100), nullable=False, index=True)
    department = Column(String(255), nullable=True, index=True)  # New
    category = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=False)
    benefits = Column(JSON_TYPE, nullable=False)  # Benefit details
    eligibility_rules = Column(JSON_TYPE, nullable=False)  # Rule engine parameters
    required_documents = Column(JSON_TYPE, nullable=False)  # List of strings
    application_process = Column(Text, nullable=False)
    source_page = Column(Integer, nullable=True)
    source_urls = Column(JSON_TYPE, nullable=True)  # New
    verification_status = Column(String(50), default="UNVERIFIED")  # VERIFIED, UNVERIFIED, DRAFT
    
    # Status & Version Controls
    is_active = Column(Boolean, default=True, nullable=False)  # New
    is_archived = Column(Boolean, default=False, nullable=False)  # New
    version = Column(Integer, default=1, nullable=False)  # New
    verification_level = Column(String(50), default="COMMUNITY_SOURCE", nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class SchemeChunk(Base):
    __tablename__ = "scheme_chunks"

    id = Column(UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()) if not is_postgres else uuid.uuid4)
    scheme_id = Column(UUID_TYPE, ForeignKey("scheme_registry.id", ondelete="CASCADE"), nullable=False)
    section = Column(String(100), nullable=False)  # ELIGIBILITY, BENEFITS, DOCUMENTS_REQUIRED, etc.
    chunk_text = Column(Text, nullable=False)
    embedding = Column(VECTOR_TYPE, nullable=True)
    chunk_metadata = Column(JSON_TYPE, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SchemeVersionHistory(Base):
    __tablename__ = "scheme_version_history"

    id = Column(UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()) if not is_postgres else uuid.uuid4)
    scheme_id = Column(UUID_TYPE, ForeignKey("scheme_registry.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    scheme_name = Column(String(255), nullable=False)
    state = Column(String(100), nullable=False)
    department = Column(String(255), nullable=True)
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    benefits = Column(JSON_TYPE, nullable=False)
    eligibility_rules = Column(JSON_TYPE, nullable=False)
    required_documents = Column(JSON_TYPE, nullable=False)
    application_process = Column(Text, nullable=False)
    source_urls = Column(JSON_TYPE, nullable=True)
    verification_level = Column(String(50), default="COMMUNITY_SOURCE", nullable=False)
    
    version_source = Column(String(255), nullable=True)  # manual edit, web scrape, etc.
    change_summary = Column(Text, nullable=True)  # changed threshold, initial upload etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    scheme = relationship("SchemeRegistry")


