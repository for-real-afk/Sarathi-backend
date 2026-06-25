import jwt
import io
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models import WelfareCase, CaseTimeline, CitizenProfile, User

# Use a temporary SQLite database for testing the case timeline
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_case_timeline_temp.db"

import os
if os.path.exists("test_case_timeline_temp.db"):
    try:
        os.remove("test_case_timeline_temp.db")
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
    db.query(CaseTimeline).delete()
    db.query(WelfareCase).delete()
    db.query(CitizenProfile).delete()
    db.commit()
    db.close()

def test_case_timeline_flow():
    print("Starting Case Timeline & Upload flow verification...")
    clean_db()
    
    db = TestingSessionLocal()
    # 1. Create a dummy citizen
    citizen = CitizenProfile(name="Timeline Test Citizen", district="Hyderabad", state="Telangana")
    db.add(citizen)
    db.commit()
    db.refresh(citizen)
    citizen_id = citizen.id
    db.close()

    # 2. Create case
    print("[Test Step 1] Creating Case...")
    case_payload = {
        "citizen_id": citizen_id,
        "title": "Aadhaar Sync Support",
        "description": "Help citizen link Aadhaar with portal",
        "status": "OPEN",
        "follow_up_tasks": []
    }
    res = client.post("/api/volunteer-ops/cases", json=case_payload, headers=headers_admin)
    assert res.status_code == 201, res.text
    case_data = res.json()
    case_id = case_data["id"]
    assert case_data["status"] == "OPEN"
    print("✓ Case created successfully!")

    # Verify initial CaseTimeline creation event exists
    db = TestingSessionLocal()
    timeline = db.query(CaseTimeline).filter(CaseTimeline.case_id == case_id).all()
    assert len(timeline) == 1, f"Expected 1 timeline event, got {len(timeline)}"
    assert timeline[0].event_type == "CREATION"
    assert "Case created" in timeline[0].description
    print("✓ Case creation event logged in timeline!")
    db.close()

    # 3. Test Invalid Status Transition Validation
    print("[Test Step 2] Testing Invalid Status Validation...")
    update_invalid = {
        "status": "INVALID_STATUS_NAME"
    }
    res = client.put(f"/api/volunteer-ops/cases/{case_id}", json=update_invalid, headers=headers_admin)
    assert res.status_code == 422, "Expected 422 validation error for invalid status transition"
    print("✓ Invalid status transition validation works!")

    # 4. Test Valid Status Transition
    print("[Test Step 3] Updating Status (Bumping State)...")
    update_valid = {
        "status": "IN_PROGRESS"
    }
    res = client.put(f"/api/volunteer-ops/cases/{case_id}", json=update_valid, headers=headers_admin)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "IN_PROGRESS"
    
    # Check CaseTimeline for status change event
    db = TestingSessionLocal()
    timeline_events = db.query(CaseTimeline).filter(CaseTimeline.case_id == case_id).order_by(CaseTimeline.id.desc()).all()
    assert len(timeline_events) == 2, f"Expected 2 timeline events, got {len(timeline_events)}"
    assert timeline_events[0].event_type == "STATUS_CHANGE"
    assert "Status changed from OPEN to IN_PROGRESS" in timeline_events[0].description
    print("✓ Status change logged successfully in CaseTimeline!")
    db.close()

    # 5. Add a Note/Comment
    print("[Test Step 4] Adding Notes/Comments...")
    note_payload = {
        "note": "Citizen is out of town until Friday. Will follow up then."
    }
    res = client.post(f"/api/volunteer-ops/cases/{case_id}/timeline/notes", json=note_payload, headers=headers_admin)
    assert res.status_code == 201, res.text
    note_data = res.json()
    assert note_data["event_type"] == "NOTE"
    assert note_data["note"] == note_payload["note"]
    print("✓ Manual case note posted successfully!")

    # 6. Upload an Attachment
    print("[Test Step 5] Uploading Case Attachment...")
    file_content = b"Mock PDF document contents for Aadhaar verification"
    file_mock = io.BytesIO(file_content)
    
    res = client.post(
        f"/api/volunteer-ops/cases/{case_id}/timeline/attachments",
        files={"file": ("aadhaar_proof.pdf", file_mock, "application/pdf")},
        headers=headers_admin
    )
    assert res.status_code == 201, res.text
    attachment_data = res.json()
    assert attachment_data["event_type"] == "ATTACHMENT"
    assert attachment_data["attachment_name"] == "aadhaar_proof.pdf"
    assert attachment_data["attachment_url"].startswith("/uploads/")
    
    # Verify local file exists in the uploads folder
    local_filename = attachment_data["attachment_url"].replace("/uploads/", "")
    local_filepath = os.path.join("uploads", local_filename)
    assert os.path.exists(local_filepath), "Uploaded attachment file does not exist locally!"
    
    # Read/serve check: verify static route serves the file
    res_serve = client.get(attachment_data["attachment_url"])
    assert res_serve.status_code == 200
    assert res_serve.content == file_content
    print("✓ File attachment uploaded, logged, and served successfully!")

    # Clean up uploaded test file
    if os.path.exists(local_filepath):
        os.remove(local_filepath)

    # 7. List Case Timeline
    print("[Test Step 6] Fetching Timeline list...")
    res = client.get(f"/api/volunteer-ops/cases/{case_id}/timeline", headers=headers_admin)
    assert res.status_code == 200, res.text
    timeline_list = res.json()
    assert len(timeline_list) == 4, f"Expected 4 timeline events, got {len(timeline_list)}"
    
    # Ensure they are sorted by creation date descending:
    # 1. ATTACHMENT
    # 2. NOTE
    # 3. STATUS_CHANGE
    # 4. CREATION
    assert timeline_list[0]["event_type"] == "ATTACHMENT"
    assert timeline_list[1]["event_type"] == "NOTE"
    assert timeline_list[2]["event_type"] == "STATUS_CHANGE"
    assert timeline_list[3]["event_type"] == "CREATION"
    print("✓ Timeline list retrieved and sorted correctly!")

    print("\nALL CASE TIMELINE & UPLOAD FLOW TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_case_timeline_flow()
