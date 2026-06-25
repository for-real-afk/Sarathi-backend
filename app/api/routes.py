import time
import uuid
import os
import logging
import json
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, status
from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn.error")

from app.config import settings
from app.database import get_db, SessionLocal
from app.models.document import KnowledgeDocument
from app.models.scheme import SchemeRegistry, SchemeChunk, SchemeVersionHistory
from app.models.chat_log import ChatLog
from app.schemas import (
    RawTextIngest,
    UrlIngest,
    SchemeCreate,
    SchemeUpdate,
    SchemeResponse,
    SchemeVersionHistoryResponse,
    ChatRequest,
    ChatResponse,
    EligibleSchemeRecommendation,
    ChatFeedbackRequest,
    BenchmarkLogResponse
)
from app.services.document_parser import DocumentParserService
from app.services.embedding import LocalBGEM3EmbeddingProvider
from app.services.reranker import LocalBGERerankerProvider
from app.services.llm import LMStudioLLMProvider, AWSBedrockClaudeLLMProvider, OpenAIChatLLMProvider
from app.services.retrieval import HybridSearchService
from app.services.eligibility import EligibilityService
from app.tasks.background import parse_and_index_document, rebuild_all_embeddings

router = APIRouter()

# Initialize AI Service Singletons
embedding_provider = LocalBGEM3EmbeddingProvider()
rerank_provider = LocalBGERerankerProvider()

def get_llm_provider():
    provider_type = settings.LLM_PROVIDER.lower()
    if provider_type == "openai":
        logger.info(f"Using OpenAI LLM provider with model: {settings.OPENAI_MODEL}")
        return OpenAIChatLLMProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            api_url="https://api.openai.com/v1/chat/completions"
        )
    elif provider_type == "groq":
        logger.info(f"Using Groq LLM provider with model: {settings.GROQ_MODEL}")
        return OpenAIChatLLMProvider(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            api_url="https://api.groq.com/openai/v1/chat/completions"
        )
    elif provider_type == "gemini":
        logger.info(f"Using Google Gemini LLM provider with model: {settings.GEMINI_MODEL}")
        return OpenAIChatLLMProvider(
            api_key=settings.GEMINI_API_KEY,
            model=settings.GEMINI_MODEL,
            api_url="https://generativelanguage.googleapis.com/v1beta/chat/completions"
        )
    elif provider_type == "bedrock":
        logger.info(f"Using AWS Bedrock LLM provider with model: {settings.AWS_BEDROCK_MODEL}")
        return AWSBedrockClaudeLLMProvider(model_id=settings.AWS_BEDROCK_MODEL)
    else:
        logger.info(f"Using LM Studio LLM provider at: {settings.LM_STUDIO_URL}")
        return LMStudioLLMProvider(api_url=settings.LM_STUDIO_URL)

llm_provider = get_llm_provider()
search_service = HybridSearchService(embedding_provider, rerank_provider)


# --- 1. KNOWLEDGE INGESTION ENDPOINTS ---

@router.post("/documents/upload", status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    verification_level: Optional[str] = Form("COMMUNITY_SOURCE"),
    db: Session = Depends(get_db)
):
    """
    Ingests a document (PDF, DOCX, or TXT) and triggers background segmentation, 
    scheme extraction, hierarchical chunking, and embedding generation.
    """
    temp_file_path = f"./temp_{uuid.uuid4()}_{file.filename}"
    try:
        # Save file to temporary local path
        with open(temp_file_path, "wb") as f:
            f.write(file.file.read())
            
        file_ext = os.path.splitext(file.filename)[1].lower()
        content = ""
        doc_title = title or file.filename
 
        # Parse based on file extension
        if file_ext == ".pdf":
            pages = DocumentParserService.parse_pdf(temp_file_path)
            content = "\n\n".join([p["text"] for p in pages])
        elif file_ext in [".docx", ".doc"]:
            content = DocumentParserService.parse_docx(temp_file_path)
        elif file_ext in [".txt", ".md"]:
            with open(temp_file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format: {file_ext}. Only PDF, DOCX, TXT, MD are allowed."
            )
 
        if not content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Extracted document content is empty."
            )
 
        # Create Document record
        doc = KnowledgeDocument(
            title=doc_title,
            file_type=file_ext.replace(".", "").upper(),
            storage_path=temp_file_path,
            content=content,
            verification_level=verification_level
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
 
        # Offload parsing and embedding to background task factory
        background_tasks.add_task(
            parse_and_index_document,
            SessionLocal,
            str(doc.id),
            llm_provider,
            embedding_provider
        )
 
        return {
            "message": "Document upload accepted. Scheme extraction is executing in the background.",
            "document_id": str(doc.id),
            "title": doc.title
        }
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest document: {str(e)}"
        )
 
 
@router.post("/documents/raw-text", status_code=status.HTTP_202_ACCEPTED)
def ingest_raw_text(
    payload: RawTextIngest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Ingests pasted raw scheme texts and queues background structuring.
    """
    doc = KnowledgeDocument(
        title=payload.title,
        file_type="RAW_TEXT",
        content=payload.content,
        verification_level=payload.verification_level
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
 
    background_tasks.add_task(
        parse_and_index_document,
        SessionLocal,
        str(doc.id),
        llm_provider,
        embedding_provider
    )
 
    return {
        "message": "Raw text accepted. Scheme extraction is executing in the background.",
        "document_id": str(doc.id),
        "title": doc.title
    }
 
 
@router.post("/documents/url", status_code=status.HTTP_202_ACCEPTED)
def ingest_url(
    payload: UrlIngest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Scrapes a URL, ingests text content, and schedules scheme extraction.
    """
    try:
        content = DocumentParserService.parse_url(payload.url)
        doc = KnowledgeDocument(
            title=payload.title,
            file_type="URL",
            source_url=payload.url,
            content=content,
            verification_level=payload.verification_level
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
 
        background_tasks.add_task(
            parse_and_index_document,
            SessionLocal,
            str(doc.id),
            llm_provider,
            embedding_provider
        )
 
        return {
            "message": "URL content scraped. Scheme extraction is executing in the background.",
            "document_id": str(doc.id),
            "title": doc.title
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/documents", response_model=List[Dict[str, Any]])
def get_documents(db: Session = Depends(get_db)):
    """
    Lists all ingested documents.
    """
    docs = db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).all()
    return [
        {
            "id": str(d.id),
            "title": d.title,
            "file_type": d.file_type,
            "source_url": d.source_url,
            "created_at": d.created_at
        }
        for d in docs
    ]

@router.delete("/documents/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(id: str, db: Session = Depends(get_db)):
    """
    Deletes an ingested document. Associated schemes and chunks are cascade deleted.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == query_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    # Remove file if saved in temp storage
    if doc.storage_path and os.path.exists(doc.storage_path):
        try:
            os.remove(doc.storage_path)
        except Exception:
            pass
            
    db.delete(doc)
    db.commit()
    return None


# --- 2. ADMIN CRUD SCHEME REGISTRY ENDPOINTS ---

@router.post("/admin/schemes", response_model=SchemeResponse, status_code=status.HTTP_201_CREATED)
def create_scheme(payload: SchemeCreate, db: Session = Depends(get_db)):
    """
    Allows administrator to manually register a new welfare scheme.
    """
    # Check for name duplication
    existing = db.query(SchemeRegistry).filter(SchemeRegistry.scheme_name == payload.scheme_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Scheme name already registered.")
        
    scheme = SchemeRegistry(**payload.model_dump())
    scheme.version = 1
    scheme.is_active = True
    scheme.is_archived = False
    
    db.add(scheme)
    db.commit()
    db.refresh(scheme)
    
    # Create version history record
    history = SchemeVersionHistory(
        scheme_id=scheme.id,
        version=scheme.version,
        scheme_name=scheme.scheme_name,
        state=scheme.state,
        department=scheme.department,
        category=scheme.category,
        description=scheme.description,
        benefits=scheme.benefits,
        eligibility_rules=scheme.eligibility_rules,
        required_documents=scheme.required_documents,
        application_process=scheme.application_process,
        source_urls=scheme.source_urls,
        version_source="manual edit",
        change_summary="Initial registration"
    )
    db.add(history)
    db.commit()
    db.refresh(scheme)
    
    return scheme


@router.get("/admin/schemes", response_model=List[SchemeResponse])
def list_schemes(db: Session = Depends(get_db)):
    """
    Lists all registered schemes.
    """
    return db.query(SchemeRegistry).all()


@router.get("/admin/schemes/{id}", response_model=SchemeResponse)
def get_scheme(id: str, db: Session = Depends(get_db)):
    """
    Fetches details for a single scheme.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    return scheme


@router.put("/admin/schemes/{id}", response_model=SchemeResponse)
def update_scheme(id: str, payload: SchemeUpdate, db: Session = Depends(get_db)):
    """
    Allows admin to modify details and eligibility rules of a registered scheme.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
        
    update_data = payload.model_dump(exclude_unset=True)
    
    version_source = update_data.pop("version_source", "manual edit")
    change_summary = update_data.pop("change_summary", "Scheme updated")
    
    if update_data:
        for k, v in update_data.items():
            setattr(scheme, k, v)
            
        scheme.version += 1
        db.commit()
        db.refresh(scheme)
        
        # Save version history log
        history = SchemeVersionHistory(
            scheme_id=scheme.id,
            version=scheme.version,
            scheme_name=scheme.scheme_name,
            state=scheme.state,
            department=scheme.department,
            category=scheme.category,
            description=scheme.description,
            benefits=scheme.benefits,
            eligibility_rules=scheme.eligibility_rules,
            required_documents=scheme.required_documents,
            application_process=scheme.application_process,
            source_urls=scheme.source_urls,
            version_source=version_source,
            change_summary=change_summary
        )
        db.add(history)
        db.commit()
        db.refresh(scheme)
        
    return scheme


@router.put("/admin/schemes/{id}/disable", response_model=SchemeResponse)
def disable_scheme(id: str, db: Session = Depends(get_db)):
    """
    Disable a scheme.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    
    scheme.is_active = False
    db.commit()
    db.refresh(scheme)
    return scheme


@router.put("/admin/schemes/{id}/enable", response_model=SchemeResponse)
def enable_scheme(id: str, db: Session = Depends(get_db)):
    """
    Enable a scheme.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    
    scheme.is_active = True
    db.commit()
    db.refresh(scheme)
    return scheme


@router.put("/admin/schemes/{id}/archive", response_model=SchemeResponse)
def archive_scheme(id: str, db: Session = Depends(get_db)):
    """
    Archive a scheme.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    
    scheme.is_archived = True
    db.commit()
    db.refresh(scheme)
    return scheme


@router.put("/admin/schemes/{id}/unarchive", response_model=SchemeResponse)
def unarchive_scheme(id: str, db: Session = Depends(get_db)):
    """
    Unarchive a scheme.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    
    scheme.is_archived = False
    db.commit()
    db.refresh(scheme)
    return scheme


@router.get("/admin/schemes/{id}/history", response_model=List[SchemeVersionHistoryResponse])
def get_scheme_history(id: str, db: Session = Depends(get_db)):
    """
    Returns the version history for a given scheme, sorted by version descending.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
        
    history_records = db.query(SchemeVersionHistory).filter(
        SchemeVersionHistory.scheme_id == query_id
    ).order_by(SchemeVersionHistory.version.desc()).all()
    
    return history_records


@router.delete("/admin/schemes/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scheme(id: str, db: Session = Depends(get_db)):
    """
    Wipes a scheme registry and associated chunks.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(id) if is_postgres else str(id)
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.id == query_id).first()
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    db.delete(scheme)
    db.commit()
    return None


@router.post("/admin/reindex", status_code=status.HTTP_202_ACCEPTED)
def trigger_reindex(background_tasks: BackgroundTasks):
    """
    Admin utility to rebuild embeddings for all chunks in the background.
    """
    background_tasks.add_task(rebuild_all_embeddings, SessionLocal, embedding_provider)
    return {"message": "Reindexing triggered in background."}


# --- 3. CHAT COMPLETION & ELIGIBILITY MATCHING FLOW ---

@router.post("/chat/completions", response_model=ChatResponse)
def chat_flow(payload: ChatRequest, db: Session = Depends(get_db)):
    """
    Main Welfare Intelligence API flow:
    1. Extract profile metadata and evaluate deterministic eligibility for all registered schemes.
    2. Pre-filter, run RAG hybrid retrieval (BM25 + pgvector) and rerank candidates.
    3. Generate response via LLM injected with profile details, RAG context, and eligibility logs.
    4. Persist interaction inside the chat logs for quality auditing.
    """
    try:
        start_time = time.time()
        
        profile = payload.profile
        question = payload.question
        
        # 1. Evaluate Deterministic Eligibility against all registered schemes
        all_schemes = db.query(SchemeRegistry).all()
        recommendations = []
        
        for sch in all_schemes:
            # Convert schema object to dict for evaluation
            sch_dict = {
                "scheme_name": sch.scheme_name,
                "eligibility_rules": sch.eligibility_rules,
                "required_documents": sch.required_documents,
                "source_page": sch.source_page or 1,
                "verification_status": sch.verification_status
            }
            res = EligibilityService.evaluate_scheme(profile, sch_dict)
            recommendations.append(EligibleSchemeRecommendation(**res))

        # Sort recommendations: fully eligible (ELIGIBLE), partially eligible, then ineligible
        status_order = {"ELIGIBLE": 0, "PARTIALLY_ELIGIBLE": 1, "NOT_ELIGIBLE": 2}
        recommendations.sort(key=lambda x: (status_order.get(x.eligibility_status, 2), -x.eligibility_score))

        # Pick top eligible/partially eligible recommendations for context
        context_recommendations = [r for r in recommendations if r.eligibility_status != "NOT_ELIGIBLE"]

        # 2. Run Hybrid Search RAG Pipeline (BM25 + pgvector + Rerank)
        logger.info(f"Retrieving RAG chunks for question: '{question}'...")
        retrieved_chunks = search_service.retrieve(db, query=question, profile=profile, top_n=5)

        # 3. Formulate RAG context text
        context_parts = []
        retrieved_scheme_ids = []
        retrieved_sources = []

        for item in retrieved_chunks:
            retrieved_scheme_ids.append(item["scheme_id"])
            retrieved_sources.append({
                "scheme_name": item["scheme_name"],
                "section": item["section"],
                "chunk_text": item["chunk_text"],
                "metadata": item["metadata"],
                "rerank_score": item["rerank_score"]
            })
            context_parts.append(
                f"Scheme: {item['scheme_name']}\n"
                f"Section: {item['section']}\n"
                f"Content: {item['chunk_text']}\n"
                f"Verification Status: {item['metadata'].get('verification_status', 'UNVERIFIED')}\n"
                f"Source Page: {item['metadata'].get('source_page', 1)}\n"
            )
        
        rag_context = "\n---\n".join(context_parts)

        # 4. Formulate System Prompt with Profile Context, RAG document facts, and Rules
        system_prompt = (
            "You are a Welfare Intelligence Platform AI Assistant for Sarathi Reach Foundation.\n"
            "Your core values are: Correctness, Explainability, Traceability, and strict adherence to facts.\n\n"
            "RULES OF INTERACTION:\n"
            "1. Never hallucinate. Only answer using the provided RAG context.\n"
            "2. If information is unavailable in the retrieved context, state clearly: 'I could not find verified information.'\n"
            "3. Always cite: Scheme Name, Source Document/Page, and Verification Status.\n"
            "4. Provide explainable recommendations detailing exactly why a citizen is eligible or not eligible based on rules.\n"
            "5. Outline any document gaps and explain clear action plans for missing certificates.\n\n"
            "CONTEXT FOR THE CURRENT CONVERSATION:\n"
            f"Citizen Profile Data: {json.dumps(profile)}\n\n"
            f"Deterministic Eligibility Results Evaluated by Rule Engine:\n"
        )
        
        # Add rules results summary to system prompt
        for rec in recommendations[:5]:
            system_prompt += (
                f"- Scheme: {rec.scheme_name}\n"
                f"  Status: {rec.eligibility_status} (Score: {rec.eligibility_score})\n"
                f"  Why: {rec.why_recommended}\n"
                f"  Missing Documents: {rec.missing_documents}\n"
                f"  Action Plan: {rec.next_steps}\n"
            )

        system_prompt += f"\nRetrieved Knowledge Base Chunks (RAG Context):\n{rag_context}\n"

        # Assemble chat history if any
        prompt = ""
        if payload.history:
            prompt += "Chat History:\n"
            for msg in payload.history[-5:]:  # Include last 5 messages for conversation continuity
                prompt += f"{msg.role.capitalize()}: {msg.content}\n"
        prompt += f"Current User Query: {question}\nResponse:"

        # 5. Call LLM Provider
        logger.info("Calling LLM Provider to generate response...")
        llm_response = llm_provider.generate(prompt=prompt, system_prompt=system_prompt)

        # 6. Observability Logging
        latency_ms = int((time.time() - start_time) * 1000)
        
        try:
            log = ChatLog(
                session_id=payload.session_id,
                citizen_profile=profile,
                question=question,
                retrieved_chunks=retrieved_sources,
                retrieved_scheme_ids=list(set(retrieved_scheme_ids)),
                llm_response=llm_response,
                latency_ms=latency_ms
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to record ChatLog: {e}")
            db.rollback()

        return ChatResponse(
            response=llm_response,
            recommendations=recommendations,
            retrieved_sources=retrieved_sources
        )
    except Exception as err:
        import traceback
        logger.error(f"Exception in chat completions: {err}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat Completions Error: {str(err)}\n{traceback.format_exc()}"
        )


@router.post("/chat/{log_id}/feedback", response_model=Dict[str, Any])
def submit_chat_feedback(log_id: str, payload: ChatFeedbackRequest, db: Session = Depends(get_db)):
    """
    Submits user feedback (HELPFUL or NOT_HELPFUL) for a specific chat log.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    query_id = uuid.UUID(log_id) if is_postgres else str(log_id)
    
    log = db.query(ChatLog).filter(ChatLog.id == query_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Chat log not found")
        
    log.feedback = payload.rating
    db.commit()
    db.refresh(log)
    return {"message": "Feedback recorded successfully", "log_id": str(log.id), "feedback": log.feedback}


@router.get("/admin/chat-logs/benchmark", response_model=List[BenchmarkLogResponse])
def get_benchmark_dataset(db: Session = Depends(get_db)):
    """
    Retrieve all RAG chat logs to formulate a benchmark evaluation dataset.
    """
    logs = db.query(ChatLog).order_by(ChatLog.created_at.desc()).all()
    return logs
