from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import CitizenProfile, HouseholdProfile, CitizenTimeline
from app.schemas import (
    CitizenProfileCreate,
    CitizenProfileUpdate,
    CitizenProfileResponse,
    HouseholdProfileResponse,
    HouseholdProfileUpdate,
    CitizenTimelineCreate,
    CitizenTimelineResponse
)

router = APIRouter(prefix="/api/citizens", tags=["Citizen Registry & CRM"])

@router.get("", response_model=List[CitizenProfileResponse])
def get_citizens(
    name: Optional[str] = None,
    phone: Optional[str] = None,
    village: Optional[str] = None,
    district: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    List and search citizens with basic filters and pagination.
    """
    query = db.query(CitizenProfile)
    if name:
        query = query.filter(CitizenProfile.name.ilike(f"%{name}%"))
    if phone:
        query = query.filter(CitizenProfile.phone.like(f"%{phone}%"))
    if village:
        query = query.filter(CitizenProfile.village.ilike(f"%{village}%"))
    if district:
        query = query.filter(CitizenProfile.district.ilike(f"%{district}%"))
        
    return query.order_by(CitizenProfile.created_at.desc()).offset(skip).limit(limit).all()

@router.get("/{id}", response_model=CitizenProfileResponse)
def get_citizen(id: int, db: Session = Depends(get_db)):
    """
    Retrieve details for a single citizen by ID, loaded with household and timeline.
    """
    citizen = db.query(CitizenProfile).filter(CitizenProfile.id == id).first()
    if not citizen:
        raise HTTPException(status_code=404, detail="Citizen not found")
    return citizen

@router.post("", response_model=CitizenProfileResponse, status_code=status.HTTP_201_CREATED)
def create_citizen(payload: CitizenProfileCreate, db: Session = Depends(get_db)):
    """
    Create a new citizen profile. If household data is included, creates household profile too.
    Logs a Profile Creation timeline event.
    """
    db_household = None
    if payload.household:
        db_household = HouseholdProfile(
            income=payload.household.income,
            housing_status=payload.household.housing_status,
            land_ownership=payload.household.land_ownership,
            occupation=payload.household.occupation,
            poverty_classification=payload.household.poverty_classification,
            family_members=payload.household.family_members
        )
        db.add(db_household)
        db.commit()
        db.refresh(db_household)

    db_citizen = CitizenProfile(
        name=payload.name,
        phone=payload.phone,
        aadhaar_reference=payload.aadhaar_reference,
        gender=payload.gender,
        age=payload.age,
        address=payload.address,
        state=payload.state,
        district=payload.district,
        mandal=payload.mandal,
        village=payload.village,
        household_id=db_household.id if db_household else payload.household_id
    )
    
    db.add(db_citizen)
    db.commit()
    db.refresh(db_citizen)

    # Automatically create the first timeline event
    timeline_event = CitizenTimeline(
        citizen_id=db_citizen.id,
        event_type="Profile Creation",
        description=f"Citizen profile manually created by operator."
    )
    db.add(timeline_event)
    db.commit()
    db.refresh(db_citizen)

    return db_citizen

@router.put("/{id}", response_model=CitizenProfileResponse)
def update_citizen(id: int, payload: CitizenProfileUpdate, db: Session = Depends(get_db)):
    """
    Update citizen details. Optionally updates associated household.
    """
    db_citizen = db.query(CitizenProfile).filter(CitizenProfile.id == id).first()
    if not db_citizen:
        raise HTTPException(status_code=404, detail="Citizen not found")

    # Update citizen fields
    update_data = payload.model_dump(exclude={"household"}, exclude_unset=True)
    for k, v in update_data.items():
        setattr(db_citizen, k, v)

    # Update household if payload contains household updates
    if payload.household and db_citizen.household_id:
        db_household = db.query(HouseholdProfile).filter(HouseholdProfile.id == db_citizen.household_id).first()
        if db_household:
            hh_data = payload.household.model_dump(exclude_unset=True)
            for k, v in hh_data.items():
                setattr(db_household, k, v)

    db.commit()
    db.refresh(db_citizen)
    return db_citizen

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_citizen(id: int, db: Session = Depends(get_db)):
    """
    Delete citizen profile by ID. Automatically cascades and deletes timelines.
    If associated household has no other members, deletes the household as well.
    """
    db_citizen = db.query(CitizenProfile).filter(CitizenProfile.id == id).first()
    if not db_citizen:
        raise HTTPException(status_code=404, detail="Citizen not found")

    hh_id = db_citizen.household_id
    db.delete(db_citizen)
    db.commit()

    # Clean up orphan household if no other citizens belong to it
    if hh_id:
        other_members = db.query(CitizenProfile).filter(CitizenProfile.household_id == hh_id).count()
        if other_members == 0:
            db_household = db.query(HouseholdProfile).filter(HouseholdProfile.id == hh_id).first()
            if db_household:
                db.delete(db_household)
                db.commit()

    return None

@router.post("/{id}/timeline", response_model=CitizenTimelineResponse, status_code=status.HTTP_201_CREATED)
def create_timeline_event(id: int, payload: CitizenTimelineCreate, db: Session = Depends(get_db)):
    """
    Add a new timeline event for a citizen.
    """
    db_citizen = db.query(CitizenProfile).filter(CitizenProfile.id == id).first()
    if not db_citizen:
        raise HTTPException(status_code=404, detail="Citizen not found")

    db_event = CitizenTimeline(
        citizen_id=id,
        event_type=payload.event_type,
        description=payload.description
    )
    if payload.event_date:
        db_event.event_date = payload.event_date

    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@router.get("/households/{hh_id}", response_model=HouseholdProfileResponse)
def get_household(hh_id: int, db: Session = Depends(get_db)):
    """
    Retrieve household details.
    """
    hh = db.query(HouseholdProfile).filter(HouseholdProfile.id == hh_id).first()
    if not hh:
        raise HTTPException(status_code=404, detail="Household not found")
    return hh

@router.put("/households/{hh_id}", response_model=HouseholdProfileResponse)
def update_household(hh_id: int, payload: HouseholdProfileUpdate, db: Session = Depends(get_db)):
    """
    Update household details.
    """
    hh = db.query(HouseholdProfile).filter(HouseholdProfile.id == hh_id).first()
    if not hh:
        raise HTTPException(status_code=404, detail="Household not found")

    hh_data = payload.model_dump(exclude_unset=True)
    for k, v in hh_data.items():
        setattr(hh, k, v)

    db.commit()
    db.refresh(hh)
    return hh
