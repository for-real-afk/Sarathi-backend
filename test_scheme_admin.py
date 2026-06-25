import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models import SchemeRegistry, SchemeVersionHistory

# Use a temporary SQLite database for testing the scheme admin endpoints
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_scheme_admin_temp.db"

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

# Override the database dependency in FastAPI app
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# Generate mock ADMIN authentication token
token_admin = jwt.encode({"sub": "1", "roles": ["ADMIN"]}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
headers_admin = {"Authorization": f"Bearer {token_admin}"}

def clean_db():
    db = TestingSessionLocal()
    db.query(SchemeVersionHistory).delete()
    db.query(SchemeRegistry).delete()
    db.commit()
    db.close()

def test_scheme_registry_admin_flow():
    print("Starting Scheme Registry & Administrative Intelligence tests...")
    clean_db()
    
    # 1. Create a scheme
    print("[Test Step 1] Creating Scheme...")
    scheme_payload = {
        "scheme_name": "Saarthi Central Scholarship",
        "state": "Telangana",
        "department": "Department of Higher Education",
        "category": "Education",
        "description": "Financial assistance for meritorious students",
        "benefits": {"amount": "50000 INR per year", "laptop_included": True},
        "eligibility_rules": {"min_gpa": 8.5, "max_family_income": 300000},
        "required_documents": ["Aadhaar Card", "Income Certificate", "Mark Sheet"],
        "application_process": "Apply online at saarthi-portal.org",
        "source_page": 5,
        "source_urls": ["https://scholarships.gov.in/saarthi", "https://telangana.gov.in/scholarship"],
        "verification_status": "VERIFIED"
    }
    
    response = client.post("/admin/schemes", json=scheme_payload, headers=headers_admin)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["scheme_name"] == "Saarthi Central Scholarship"
    assert data["version"] == 1
    assert data["is_active"] is True
    assert data["is_archived"] is False
    assert data["department"] == "Department of Higher Education"
    assert data["source_urls"] == ["https://scholarships.gov.in/saarthi", "https://telangana.gov.in/scholarship"]
    scheme_id = data["id"]
    
    # Verify version history record is created for version 1
    db = TestingSessionLocal()
    history_v1 = db.query(SchemeVersionHistory).filter(
        SchemeVersionHistory.scheme_id == scheme_id,
        SchemeVersionHistory.version == 1
    ).first()
    assert history_v1 is not None, "Version history log for version 1 was not created!"
    assert history_v1.scheme_name == "Saarthi Central Scholarship"
    assert history_v1.change_summary == "Initial registration"
    assert history_v1.version_source == "manual edit"
    print("✓ Scheme creation and version 1 history logged successfully!")

    # 2. Retrieve schemes
    print("[Test Step 2] Listing Schemes...")
    response = client.get("/admin/schemes", headers=headers_admin)
    assert response.status_code == 200, response.text
    schemes_list = response.json()
    assert len(schemes_list) >= 1
    assert any(s["id"] == scheme_id for s in schemes_list)
    print("✓ Scheme list endpoint returned created scheme!")

    # 3. Retrieve specific scheme by ID
    print("[Test Step 3] Fetching Scheme details...")
    response = client.get(f"/admin/schemes/{scheme_id}", headers=headers_admin)
    assert response.status_code == 200, response.text
    data_by_id = response.json()
    assert data_by_id["scheme_name"] == "Saarthi Central Scholarship"
    print("✓ Fetching scheme by ID succeeded!")

    # 4. Update the scheme to trigger version increment
    print("[Test Step 4] Updating Scheme (Bumping Version)...")
    update_payload = {
        "description": "Financial assistance for meritorious students - Updated for 2026",
        "department": "Ministry of Welfare & Education",
        "source_urls": ["https://scholarships.gov.in/saarthi_v2"],
        "change_summary": "Updated eligibility details and department name for the new term",
        "version_source": "admin dashboard"
    }
    response = client.put(f"/admin/schemes/{scheme_id}", json=update_payload, headers=headers_admin)
    assert response.status_code == 200, response.text
    updated_data = response.json()
    assert updated_data["version"] == 2
    assert updated_data["description"] == "Financial assistance for meritorious students - Updated for 2026"
    assert updated_data["department"] == "Ministry of Welfare & Education"
    assert updated_data["source_urls"] == ["https://scholarships.gov.in/saarthi_v2"]
    
    # Check history table for version 2
    history_v2 = db.query(SchemeVersionHistory).filter(
        SchemeVersionHistory.scheme_id == scheme_id,
        SchemeVersionHistory.version == 2
    ).first()
    assert history_v2 is not None, "Version history log for version 2 was not created!"
    assert history_v2.change_summary == "Updated eligibility details and department name for the new term"
    assert history_v2.version_source == "admin dashboard"
    print("✓ Scheme update bumped version and logged history successfully!")

    # 5. Test status controls
    print("[Test Step 5] Testing Status Controls...")
    # A. Disable
    response = client.put(f"/admin/schemes/{scheme_id}/disable", headers=headers_admin)
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False

    # B. Enable
    response = client.put(f"/admin/schemes/{scheme_id}/enable", headers=headers_admin)
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True

    # C. Archive
    response = client.put(f"/admin/schemes/{scheme_id}/archive", headers=headers_admin)
    assert response.status_code == 200, response.text
    assert response.json()["is_archived"] is True

    # D. Unarchive
    response = client.put(f"/admin/schemes/{scheme_id}/unarchive", headers=headers_admin)
    assert response.status_code == 200, response.text
    assert response.json()["is_archived"] is False
    print("✓ Status controls (disable/enable, archive/unarchive) function correctly without version bump!")

    # 6. Retrieve Version History List
    print("[Test Step 6] Fetching Version History Logs...")
    response = client.get(f"/admin/schemes/{scheme_id}/history", headers=headers_admin)
    assert response.status_code == 200, response.text
    history_list = response.json()
    assert len(history_list) == 2
    # Ensure history list is sorted by version desc (v2 then v1)
    assert history_list[0]["version"] == 2
    assert history_list[1]["version"] == 1
    assert history_list[0]["change_summary"] == "Updated eligibility details and department name for the new term"
    assert history_list[1]["change_summary"] == "Initial registration"
    print("✓ Scheme version history returned correct order and values!")

    db.close()
    print("\nALL SCHEME REGISTRY & ADMINISTRATIVE INTELLIGENCE TESTS PASSED!")

if __name__ == "__main__":
    test_scheme_registry_admin_flow()
