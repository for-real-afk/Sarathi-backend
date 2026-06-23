import uuid
import logging
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from typing import Any

from app.models.document import KnowledgeDocument
from app.models.scheme import SchemeRegistry, SchemeChunk
from app.services.document_parser import DocumentParserService
from app.services.embedding import EmbeddingProvider
from app.services.llm import LLMProvider

logger = logging.getLogger("uvicorn.error")

def parse_and_index_document(
    db_session_factory: Any,
    document_id: str,
    llm_provider: LLMProvider,
    embedding_provider: EmbeddingProvider
):
    """
    Background job to parse ingested documents, extract schemes, segment them hierarchically,
    generate embeddings, and populate scheme_registry and scheme_chunks.
    """
    db = db_session_factory()
    try:
        is_postgres = (db.bind.dialect.name == "postgresql")
        doc_uuid = uuid.UUID(document_id) if is_postgres else str(document_id)
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_uuid).first()
        if not doc:
            logger.error(f"Background task error: Document {document_id} not found in DB.")
            return

        logger.info(f"Background job started: processing document '{doc.title}' (ID: {doc.id})")
        
        # 1. Detect boundaries to segment raw text
        blocks = DocumentParserService.split_document_by_boundaries(doc.content)
        logger.info(f"Segmented document into {len(blocks)} raw scheme block(s)")

        for idx, block in enumerate(blocks):
            raw_text = block["text"]
            source_page = block["source_page"]

            # 2. Structure each block using LLM or heuristic
            logger.info(f"Structuring scheme block {idx + 1}/{len(blocks)} using LLM...")
            structured_data = DocumentParserService.structure_scheme_with_llm(raw_text, llm_provider, source_page)
            
            # 3. Save Scheme Registry record
            scheme = SchemeRegistry(
                document_id=doc.id,
                scheme_name=structured_data["scheme_name"],
                state=structured_data["state"],
                category=structured_data["category"],
                description=structured_data["description"],
                benefits=structured_data["benefits"],
                eligibility_rules=structured_data["eligibility_rules"],
                required_documents=structured_data["required_documents"],
                application_process=structured_data["application_process"],
                source_page=structured_data["source_page"],
                verification_status=structured_data["verification_status"],
                verification_level=doc.verification_level
            )
            
            # Check for name collisions, delete old matching scheme if present to allow re-indexing
            existing = db.query(SchemeRegistry).filter(SchemeRegistry.scheme_name == scheme.scheme_name).first()
            if existing:
                logger.info(f"Scheme '{scheme.scheme_name}' already exists. Overwriting...")
                db.delete(existing)
                db.flush()
                
            db.add(scheme)
            db.flush()  # Populates scheme.id

            # 4. Generate section chunks for Hierarchical Chunking
            # Sections: Eligibility, Benefits, Documents Required, Application Process
            sections = {
                "Eligibility": f"Scheme Name: {scheme.scheme_name}\nSection: Eligibility\nCriteria:\n- State: {scheme.state}\n- Category: {scheme.category}\n- Description: {scheme.description}\n- Detailed Rules: {structured_data['eligibility_rules']}",
                "Benefits": f"Scheme Name: {scheme.scheme_name}\nSection: Benefits\nDetails:\n{structured_data['benefits']}",
                "Required Documents": f"Scheme Name: {scheme.scheme_name}\nSection: Required Documents\nDocuments:\n" + "\n".join([f"- {d}" for d in scheme.required_documents]),
                "Application Process": f"Scheme Name: {scheme.scheme_name}\nSection: Application Process\nSteps:\n{scheme.application_process}"
            }

            for sec_name, chunk_text in sections.items():
                # Generate BGE-M3 Embeddings (1024 dims)
                logger.info(f"Generating embedding for section '{sec_name}'...")
                embedding_vector = embedding_provider.embed_query(chunk_text)

                metadata = {
                    "scheme_id": str(scheme.id),
                    "scheme_name": scheme.scheme_name,
                    "state": scheme.state,
                    "category": scheme.category,
                    "source": doc.title,
                    "source_page": scheme.source_page,
                    "verification_status": scheme.verification_status,
                    "verification_level": doc.verification_level
                }

                chunk = SchemeChunk(
                    scheme_id=scheme.id,
                    section=sec_name,
                    chunk_text=chunk_text,
                    embedding=embedding_vector,
                    chunk_metadata=metadata
                )
                db.add(chunk)

        db.commit()
        logger.info(f"Successfully finished processing document: {doc.title}")
    except Exception as e:
        db.rollback()
        logger.error(f"Exception encountered in background parse job: {e}", exc_info=True)
    finally:
        db.close()


def rebuild_all_embeddings(db_session_factory: Any, embedding_provider: EmbeddingProvider):
    """
    Background job to re-compute and update embeddings for all scheme chunks.
    """
    db = db_session_factory()
    try:
        chunks = db.query(SchemeChunk).all()
        logger.info(f"Starting embeddings rebuild job for {len(chunks)} chunk(s)...")
        for chunk in chunks:
            logger.info(f"Rebuilding embedding for chunk ID {chunk.id} ({chunk.section})")
            embedding_vector = embedding_provider.embed_query(chunk.chunk_text)
            chunk.embedding = embedding_vector
            db.add(chunk)
        db.commit()
        logger.info("Embeddings rebuild completed successfully.")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to rebuild embeddings: {e}")
    finally:
        db.close()
