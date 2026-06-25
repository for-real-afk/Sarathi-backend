from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import jwt

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models import CitizenProfile, HouseholdProfile, CitizenTimeline

# Use an in-memory SQLite database for testing the CRM logic
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_crm_temp.db"

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

def clean_db():
    db = TestingSessionLocal()
    db.query(CitizenTimeline).delete()
    db.query(CitizenProfile).delete()
    db.query(HouseholdProfile).delete()
    db.commit()
    db.close()

def test_survey_auto_sync():
    print("[Test 1] Testing survey auto sync to CRM...")
    clean_db()
    
    survey_payload = {
        "firstName": "Ramesh",
        "lastName": "Kumar",
        "primaryMobile": "9988776655",
        "dob": "1985-05-15",
        "gender": "Male",
        "maritalStatus": "Married",
        "religion": "Hindu",
        "socialCategory": "OBC",
        "residentialStatus": "Permanent",
        "houseNo": "Flat 202",
        "street": "Sai Nagar",
        "village": "Gachibowli",
        "mandal": "Serilingampally",
        "district": "Rangareddy",
        "state": "Telangana",
        
        "adults": "2",
        "childrenCount": "2",
        "seniors": "0",
        "familyStructure": "NUCLEAR",
        "familyMembers": [
            {
                "name": "Sita Kumar",
                "relation": "Spouse",
                "age": "35",
                "gender": "F",
                "education": "Intermediate",
                "employment": "Housewife",
                "income": "0",
                "disability": "No",
                "illness": ""
            }
        ],

        "mainOccupation": "Driver",
        "employmentNature": "Self-employed",
        "secondaryIncome": [],
        "empChallenges": [],

        "monthlyIncomeRange": "10000-15000",
        "annualIncome": "130000",
        "bankAccount": "YES",
        "insuranceCoverage": [],
        "householdDebt": {},
        
        "housingType": "Pucca",
        "housingOwnership": "Rented",
        "agriLand": "NO",
        "livestock": "NO",
        
        "hasSmartphone": "YES",
        
        "consentStatus": "AGREED",
        "signatureName": "Ramesh Kumar",
        "consentDate": "2026-06-23",
        "surveyorName": "Volunteer John",
        "surveyorId": "V999",
        "surveyLocation": "Gachibowli",
        
        "survey_language": "en"
    }
    
    res = client.post("/submit", json=survey_payload)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    
    db = TestingSessionLocal()
    citizen = db.query(CitizenProfile).filter(CitizenProfile.phone == "9988776655").first()
    assert citizen is not None, "CitizenProfile not created"
    assert citizen.name == "Ramesh Kumar", f"Expected 'Ramesh Kumar', got {citizen.name}"
    assert citizen.village == "Gachibowli", f"Expected 'Gachibowli', got {citizen.village}"
    
    assert citizen.household_id is not None, "Household ID is None"
    hh = db.query(HouseholdProfile).filter(HouseholdProfile.id == citizen.household_id).first()
    assert hh is not None, "HouseholdProfile not created"
    assert hh.poverty_classification == "APL", f"Expected 'APL', got {hh.poverty_classification}"
    assert len(hh.family_members) == 1, f"Expected 1 family member, got {len(hh.family_members)}"
    assert hh.family_members[0]["name"] == "Sita Kumar", f"Expected 'Sita Kumar', got {hh.family_members[0]['name']}"
    
    timelines = db.query(CitizenTimeline).filter(CitizenTimeline.citizen_id == citizen.id).all()
    assert len(timelines) >= 2, f"Expected at least 2 timeline events, got {len(timelines)}"
    event_types = [t.event_type for t in timelines]
    assert "Profile Creation" in event_types, "'Profile Creation' event not in timeline"
    assert "Eligibility Runs" in event_types, "'Eligibility Runs' event not in timeline"
    db.close()
    print("Test 1 Passed!")

def test_citizen_manual_crud():
    print("[Test 2] Testing citizen manual CRUD...")
    clean_db()
    
    citizen_payload = {
        "name": "Babu Rao",
        "phone": "9848022338",
        "aadhaar_reference": "XXXX-XXXX-9999",
        "gender": "Male",
        "age": 50,
        "address": "Opp Police Station, Main Road",
        "state": "Andhra Pradesh",
        "district": "Guntur",
        "mandal": "Tenali",
        "village": "Angalakuduru",
        "household": {
            "income": "90000",
            "housing_status": "Kutcha (Owned)",
            "land_ownership": "None",
            "occupation": "Tailor",
            "poverty_classification": "BPL",
            "family_members": []
        }
    }
    
    token = jwt.encode({"sub": "1", "roles": ["ADMIN"]}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    auth_header = {"Authorization": f"Bearer {token}"}
    
    res = client.post("/api/citizens", json=citizen_payload, headers=auth_header)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    created = res.json()
    assert created["name"] == "Babu Rao"
    assert created["household"] is not None
    assert created["household"]["poverty_classification"] == "BPL"
    citizen_id = created["id"]
    
    res_list = client.get("/api/citizens", headers=auth_header)
    assert res_list.status_code == 200
    citizens = res_list.json()
    assert len(citizens) >= 1
    assert any(c["id"] == citizen_id for c in citizens)
    
    event_payload = {
        "event_type": "Volunteer Visit",
        "description": "Visited Babu Rao. Verified ration card details."
    }
    res_event = client.post(f"/api/citizens/{citizen_id}/timeline", json=event_payload, headers=auth_header)
    assert res_event.status_code == 201
    
    res_detail = client.get(f"/api/citizens/{citizen_id}", headers=auth_header)
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert len(detail["timeline"]) >= 2
    assert detail["timeline"][1]["event_type"] == "Volunteer Visit"

    update_payload = {
        "age": 51,
        "household": {
            "income": "95000",
            "poverty_classification": "BPL"
        }
    }
    res_update = client.put(f"/api/citizens/{citizen_id}", json=update_payload, headers=auth_header)
    assert res_update.status_code == 200
    updated = res_update.json()
    assert updated["age"] == 51
    assert updated["household"]["income"] == "95000"

    res_delete = client.delete(f"/api/citizens/{citizen_id}", headers=auth_header)
    assert res_delete.status_code == 204
    
    res_check = client.get(f"/api/citizens/{citizen_id}", headers=auth_header)
    assert res_check.status_code == 404
    print("Test 2 Passed!")

if __name__ == "__main__":
    test_survey_auto_sync()
    test_citizen_manual_crud()
    print("\nALL STANDALONE CRM TESTS PASSED!")
