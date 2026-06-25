import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models import Hub, VolunteerProfile, WelfareCase, CitizenProfile, CitizenTimeline, User
from app.services.auth import hash_password

# Use an in-memory SQLite database for testing the CRM logic
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_vol_ops_temp.db"

import os
if os.path.exists("test_vol_ops_temp.db"):
    try:
        os.remove("test_vol_ops_temp.db")
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

# Override the database dependency in FastAPI app
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# Generate mock ADMIN authentication token
token_admin = jwt.encode({"sub": "1", "roles": ["ADMIN"]}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
headers_admin = {"Authorization": f"Bearer {token_admin}"}

def clean_db():
    db = TestingSessionLocal()
    db.query(WelfareCase).delete()
    db.query(CitizenTimeline).delete()
    db.query(CitizenProfile).delete()
    db.query(VolunteerProfile).delete()
    db.query(Hub).delete()
    db.query(User).filter(User.username.like("test_vol_%")).delete()
    db.commit()
    db.close()

def create_test_user(db, username, role_name):
    # Retrieve role
    from app.models.role import Role
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        role = Role(name=role_name, description=f"{role_name} Role")
        db.add(role)
        db.commit()
        db.refresh(role)

    user = User(
        username=username,
        email=f"{username}@saarthi.org",
        hashed_password=hash_password("password123"),
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user.roles.append(role)
    db.commit()
    return user

def test_volunteer_and_hub_operations():
    print("Starting Volunteer & Hub Operations verification...")
    clean_db()
    db = TestingSessionLocal()
    
    # 1. Create Users
    u_vol1 = create_test_user(db, "test_vol_1", "VOLUNTEER")
    u_vol2 = create_test_user(db, "test_vol_2", "VOLUNTEER")
    u_vol3 = create_test_user(db, "test_vol_3", "VOLUNTEER")
    
    # 2. Register Hubs via API
    print("[Step 1] Creating Hubs...")
    hub_payload = {
        "name": "Test central Hub",
        "hub_type": "CENTRAL",
        "district": "Hyderabad"
    }
    res = client.post("/api/volunteer-ops/hubs", json=hub_payload, headers=headers_admin)
    assert res.status_code == 201, res.text
    central_hub_id = res.json()["id"]

    local_hub_payload = {
        "name": "Test Rangareddy Local Hub",
        "hub_type": "LOCAL",
        "district": "Rangareddy",
        "parent_hub_id": central_hub_id
    }
    res = client.post("/api/volunteer-ops/hubs", json=local_hub_payload, headers=headers_admin)
    assert res.status_code == 201, res.text
    local_hub_id = res.json()["id"]

    # 3. Create Volunteer Profiles
    print("[Step 2] Creating Volunteer Profiles...")
    # Volunteer 1: Rangareddy, Available
    res = client.post("/api/volunteer-ops/volunteers", json={
        "user_id": u_vol1.id,
        "contact_phone": "9000000001",
        "district": "Rangareddy",
        "availability": True,
        "hub_id": local_hub_id
    }, headers=headers_admin)
    assert res.status_code == 201, res.text
    vol1_id = res.json()["id"]

    # Volunteer 2: Rangareddy, Available
    res = client.post("/api/volunteer-ops/volunteers", json={
        "user_id": u_vol2.id,
        "contact_phone": "9000000002",
        "district": "Rangareddy",
        "availability": True,
        "hub_id": local_hub_id
    }, headers=headers_admin)
    assert res.status_code == 201, res.text
    vol2_id = res.json()["id"]

    # Volunteer 3: Medchal, Available
    res = client.post("/api/volunteer-ops/volunteers", json={
        "user_id": u_vol3.id,
        "contact_phone": "9000000003",
        "district": "Medchal",
        "availability": True,
        "hub_id": local_hub_id
    }, headers=headers_admin)
    assert res.status_code == 201, res.text
    vol3_id = res.json()["id"]

    # 4. Create Citizens
    print("[Step 3] Registering Citizens...")
    c_rangareddy = CitizenProfile(name="Ranga Citizen", district="Rangareddy", state="Telangana")
    c_medchal = CitizenProfile(name="Medchal Citizen", district="Medchal", state="Telangana")
    db.add(c_rangareddy)
    db.add(c_medchal)
    db.commit()
    db.refresh(c_rangareddy)
    db.refresh(c_medchal)

    # 5. Test Case Assignment Engine (Geography + Workload balancer)
    print("[Step 4] Running Assignment Engine tests...")
    
    # Case 1: Rangareddy Citizen. Available vols: Vol 1 (workload 0), Vol 2 (workload 0).
    # Engine matches one. Let's register.
    res = client.post("/api/volunteer-ops/cases", json={
        "citizen_id": c_rangareddy.id,
        "title": "Aasara Pension case 1",
        "description": "Needs verification.",
        "follow_up_tasks": [{"task_name": "Aadhaar Xerox", "completed": False}]
    }, headers=headers_admin)
    assert res.status_code == 201, res.text
    case1 = res.json()
    assert case1["status"] == "ASSIGNED"
    assigned_vol_id_1 = case1["volunteer_id"]
    assert assigned_vol_id_1 in [vol1_id, vol2_id]
    
    # Case 2: Rangareddy Citizen.
    # Workload balance check: one volunteer now has 1 active case, the other has 0.
    # Engine must match the one with 0 active cases!
    res = client.post("/api/volunteer-ops/cases", json={
        "citizen_id": c_rangareddy.id,
        "title": "Aasara Pension Case 2",
        "description": "Check electricity bills.",
        "follow_up_tasks": []
    }, headers=headers_admin)
    assert res.status_code == 201, res.text
    case2 = res.json()
    assert case2["status"] == "ASSIGNED"
    assigned_vol_id_2 = case2["volunteer_id"]
    assert assigned_vol_id_2 in [vol1_id, vol2_id]
    assert assigned_vol_id_2 != assigned_vol_id_1, "Load balancer failed! Assigned to same volunteer instead of the idle one."
    print("✓ Workload balance check successful!")

    # Case 3: Medchal Citizen. Available vols: Vol 3 (Medchal).
    res = client.post("/api/volunteer-ops/cases", json={
        "citizen_id": c_medchal.id,
        "title": "Health Card Registration",
        "description": "Medical support",
        "follow_up_tasks": []
    }, headers=headers_admin)
    assert res.status_code == 201, res.text
    case3 = res.json()
    assert case3["status"] == "ASSIGNED"
    assert case3["volunteer_id"] == vol3_id, "Geographical routing failed! Should match Medchal volunteer."
    print("✓ Geographical routing successful!")

    # Case 4: Medchal Citizen, but set Volunteer 3 availability to False
    print("[Step 5] Testing availability check...")
    # Disable Vol 3
    db_vol3 = db.query(VolunteerProfile).filter(VolunteerProfile.id == vol3_id).first()
    db_vol3.availability = False
    db.commit()

    # Register Case 4. Since Vol 3 is unavailable, should remain OPEN.
    res = client.post("/api/volunteer-ops/cases", json={
        "citizen_id": c_medchal.id,
        "title": "Pension Support 2",
        "description": "Check eligibility.",
        "follow_up_tasks": []
    }, headers=headers_admin)
    assert res.status_code == 201, res.text
    case4 = res.json()
    assert case4["status"] == "OPEN"
    assert case4["volunteer_id"] is None
    print("✓ Availability checks successful (case remains OPEN when no volunteer is available)!")

    # 6. Test updates to case
    print("[Step 6] Testing case updates...")
    case1_id = case1["id"]
    res = client.put(f"/api/volunteer-ops/cases/{case1_id}", json={
        "status": "IN_PROGRESS",
        "upcoming_visit_date": "2026-06-24T10:00:00+00:00",
        "follow_up_tasks": [{"task_name": "Aadhaar Xerox", "completed": True}]
      }, headers=headers_admin)
    assert res.status_code == 200, res.text
    updated_case1 = res.json()
    assert updated_case1["status"] == "IN_PROGRESS"
    assert updated_case1["follow_up_tasks"][0]["completed"] == True
    
    # Check that the citizen's timeline recorded a "Volunteer Visit" event!
    timeline_events = db.query(CitizenTimeline).filter(
        CitizenTimeline.citizen_id == c_rangareddy.id,
        CitizenTimeline.event_type == "Volunteer Visit"
    ).all()
    assert len(timeline_events) > 0, "No timeline event posted for scheduled visit!"
    print("✓ Case updates and timeline triggers verified!")
    
    db.close()
    print("\nALL VOLUNTEER & HUB OPERATIONS TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_volunteer_and_hub_operations()
