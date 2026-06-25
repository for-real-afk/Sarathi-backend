import jwt
import io
import os
import time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models import KnowledgeDocument, SchemeRegistry, SchemeChunk, ChatLog
from app.tasks.background import parse_and_index_document
from app.api.routes import llm_provider, embedding_provider

# Use a temporary SQLite database for testing AI hardening
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_ai_hardening_temp.db"

import os
if os.path.exists("test_ai_hardening_temp.db"):
    try:
        os.remove("test_ai_hardening_temp.db")
    except Exception:
        pass

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Setup database tables
Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

# Override database dependency in FastAPI app
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# Generate mock ADMIN token
token_admin = jwt.encode({"sub": "1", "roles": ["ADMIN"]}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
headers_admin = {"Authorization": f"Bearer {token_admin}"}

def clean_db():
    db = TestingSessionLocal()
    db.query(ChatLog).delete()
    db.query(SchemeChunk).delete()
    db.query(SchemeRegistry).delete()
    db.query(KnowledgeDocument).delete()
    db.commit()
    db.close()

def test_ai_hardening_trust_feedback_flow():
    print("Starting AI Hardening & Trust Layer verification...")
    clean_db()
    
    # 1. Test Ingest Raw Text with Official Verification Level
    print("[Test Step 1] Ingesting Scheme via Raw Text with TRUSTED_INSTITUTION level...")
    raw_payload = {
        "title": "Trusted Scholarship Manual",
        "content": "Scheme Name: Prime Minister Scholarship\nState: Telangana\nCategory: Education\nDescription: Support PM studies.\nBenefits: 30000 INR.\nEligibility Rules: GPA > 8.0\nRequired Documents: Aadhaar, GPA sheet\nApplication Process: Portal apply.\nVerification Status: VERIFIED",
        "verification_level": "TRUSTED_INSTITUTION"
    }
    res = client.post("/documents/raw-text", json=raw_payload, headers=headers_admin)
    assert res.status_code == 202, res.text
    data = res.json()
    doc_id = data["document_id"]
    
    # Verify Document is saved with correct verification level
    db = TestingSessionLocal()
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    assert doc is not None
    assert doc.verification_level == "TRUSTED_INSTITUTION"
    print("✓ Knowledge document ingested and verification level stored successfully!")
    db.close()

    # 2. Run background indexer synchronously for testing
    print("[Test Step 2] Running Background Indexer synchronously...")
    parse_and_index_document(TestingSessionLocal, doc_id, llm_provider, embedding_provider)
    
    # Verify scheme and chunk verification level propagation
    db = TestingSessionLocal()
    scheme = db.query(SchemeRegistry).filter(SchemeRegistry.document_id == doc_id).first()
    assert scheme is not None
    assert scheme.verification_level == "TRUSTED_INSTITUTION"
    
    chunks = db.query(SchemeChunk).filter(SchemeChunk.scheme_id == scheme.id).all()
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.chunk_metadata["verification_level"] == "TRUSTED_INSTITUTION"
    print("✓ Verification level correctly propagated to SchemeRegistry and SchemeChunk metadata!")
    db.close()

    # 3. Test RAG Chat Log & Latency Tracking
    print("[Test Step 3] Testing Chat RAG Observability...")
    chat_payload = {
        "session_id": "test_obs_session_99",
        "profile": {"state": "Telangana", "gender": "Male", "age": 22},
        "question": "What are the benefits of Prime Minister Scholarship?",
        "history": []
    }
    
    start_time = time.time()
    res_chat = client.post("/chat/completions", json=chat_payload)
    assert res_chat.status_code == 200, res_chat.text
    chat_response = res_chat.json()
    assert "response" in chat_response
    assert len(chat_response["retrieved_sources"]) > 0
    
    # Verify ChatLog was written correctly
    db = TestingSessionLocal()
    log = db.query(ChatLog).filter(ChatLog.session_id == "test_obs_session_99").first()
    assert log is not None
    assert log.question == chat_payload["question"]
    assert log.latency_ms > 0
    assert len(log.retrieved_chunks) > 0
    # Check that verification level details are in logged retrieved sources
    assert log.retrieved_chunks[0]["metadata"]["verification_level"] == "TRUSTED_INSTITUTION"
    log_id = str(log.id)
    print("✓ Chat request processed and RAG analytics logged (Question, Retrieved Chunks, Answer, Latency)!")
    db.close()

    # 4. Test Chat Feedback API
    print("[Test Step 4] Testing Feedback capture...")
    feedback_payload = {
        "rating": "HELPFUL"
    }
    res_feed = client.post(f"/chat/{log_id}/feedback", json=feedback_payload, headers=headers_admin)
    assert res_feed.status_code == 200, res_feed.text
    assert res_feed.json()["feedback"] == "HELPFUL"
    
    # Verify DB update
    db = TestingSessionLocal()
    updated_log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    assert updated_log.feedback == "HELPFUL"
    print("✓ Feedback rating (HELPFUL) successfully captured and logged!")
    db.close()

    # 5. Test Benchmark Evaluation Dataset Export
    print("[Test Step 5] Testing Benchmark Dataset Export...")
    res_bench = client.get("/admin/chat-logs/benchmark", headers=headers_admin)
    assert res_bench.status_code == 200, res_bench.text
    dataset = res_bench.json()
    assert len(dataset) >= 1
    assert dataset[0]["session_id"] == "test_obs_session_99"
    assert dataset[0]["feedback"] == "HELPFUL"
    assert dataset[0]["latency_ms"] > 0
    assert len(dataset[0]["retrieved_chunks"]) > 0
    print("✓ Benchmark evaluation dataset compiled and exported successfully!")

    print("\nALL AI HARDENING & TRUST LAYER TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_ai_hardening_trust_feedback_flow()
