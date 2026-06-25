import logging
import os
import shutil
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.database import get_db
from app.models import Hub, VolunteerProfile, WelfareCase, CitizenProfile, CitizenTimeline, User, CaseTimeline
from app.schemas import (
    HubCreate,
    HubResponse,
    VolunteerProfileCreate,
    VolunteerProfileResponse,
    WelfareCaseCreate,
    WelfareCaseUpdate,
    WelfareCaseResponse,
    CaseTimelineNoteCreate,
    CaseTimelineResponse
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/volunteer-ops", tags=["Volunteer & Hub Operations"])

@router.post("/hubs", response_model=HubResponse, status_code=status.HTTP_201_CREATED)
def create_hub(payload: HubCreate, db: Session = Depends(get_db)):
    """
    Register a Central or Local Hub.
    """
    existing = db.query(Hub).filter(Hub.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Hub name already registered.")
        
    db_hub = Hub(
        name=payload.name,
        hub_type=payload.hub_type,
        district=payload.district,
        parent_hub_id=payload.parent_hub_id
    )
    db.add(db_hub)
    db.commit()
    db.refresh(db_hub)
    return db_hub

@router.get("/hubs", response_model=List[HubResponse])
def get_hubs(db: Session = Depends(get_db)):
    """
    List all registered hubs.
    """
    return db.query(Hub).all()

@router.post("/volunteers", response_model=VolunteerProfileResponse, status_code=status.HTTP_201_CREATED)
def create_or_update_volunteer(payload: VolunteerProfileCreate, db: Session = Depends(get_db)):
    """
    Register or update a volunteer profile.
    """
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    vol = db.query(VolunteerProfile).filter(VolunteerProfile.user_id == payload.user_id).first()
    if vol:
        # Update existing
        vol.contact_phone = payload.contact_phone
        vol.district = payload.district
        if payload.availability is not None:
            vol.availability = payload.availability
        vol.hub_id = payload.hub_id
    else:
        # Create new
        vol = VolunteerProfile(
            user_id=payload.user_id,
            contact_phone=payload.contact_phone,
            district=payload.district,
            availability=payload.availability if payload.availability is not None else True,
            hub_id=payload.hub_id
        )
        db.add(vol)

    db.commit()
    db.refresh(vol)
    return vol

@router.get("/volunteers/me", response_model=VolunteerProfileResponse)
def get_my_profile(request: Request, db: Session = Depends(get_db)):
    """
    Get the volunteer profile associated with the currently authenticated user.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    vol = db.query(VolunteerProfile).filter(VolunteerProfile.user_id == int(user_id)).first()
    if not vol:
        raise HTTPException(status_code=404, detail="Volunteer profile not found.")
    return vol

@router.post("/cases", response_model=WelfareCaseResponse, status_code=status.HTTP_201_CREATED)
def create_case(payload: WelfareCaseCreate, db: Session = Depends(get_db)):
    """
    Register a new case and run the Assignment Engine to match it to a volunteer.
    Assignments are load-balanced based on:
    1. Geography: Citizen district == Volunteer district.
    2. Availability: Volunteer availability is True.
    3. Workload: Least number of active cases.
    """
    citizen = db.query(CitizenProfile).filter(CitizenProfile.id == payload.citizen_id).first()
    if not citizen:
        raise HTTPException(status_code=404, detail="Citizen profile not found.")

    # 1. Assignment Engine
    matched_vol_id = None
    assigned_status = "OPEN"
    
    if citizen.district:
        # Query available volunteers in the same district
        candidates = db.query(VolunteerProfile).filter(
            VolunteerProfile.district.ilike(citizen.district),
            VolunteerProfile.availability == True
        ).all()
        
        if candidates:
            # Find the volunteer with the lowest active cases (status != RESOLVED)
            least_workload = None
            selected_vol = None
            
            for vol in candidates:
                active_cases_count = db.query(WelfareCase).filter(
                    WelfareCase.volunteer_id == vol.id,
                    WelfareCase.status != "RESOLVED"
                ).count()
                
                if least_workload is None or active_cases_count < least_workload:
                    least_workload = active_cases_count
                    selected_vol = vol
            
            if selected_vol:
                matched_vol_id = selected_vol.id
                assigned_status = "ASSIGNED"

    db_case = WelfareCase(
        citizen_id=payload.citizen_id,
        volunteer_id=matched_vol_id,
        title=payload.title,
        description=payload.description,
        status=assigned_status,
        upcoming_visit_date=payload.upcoming_visit_date,
        follow_up_tasks=payload.follow_up_tasks
    )
    
    db.add(db_case)
    db.commit()
    db.refresh(db_case)

    # Add Timeline event to Citizen CRM timeline
    timeline_desc = f"New Case created: '{payload.title}'."
    if matched_vol_id:
        vol_user = db.query(User).join(VolunteerProfile).filter(VolunteerProfile.id == matched_vol_id).first()
        timeline_desc += f" Automatically assigned to volunteer '{vol_user.username}' (District: {citizen.district})."
    else:
        timeline_desc += " Case remains unassigned (No available volunteers in the district)."
        
    timeline_event = CitizenTimeline(
        citizen_id=citizen.id,
        event_type="Cases Created",
        description=timeline_desc
    )
    db.add(timeline_event)
    db.commit()

    # Create first CaseTimeline entry
    creation_timeline_desc = f"Case created. Status set to {db_case.status}."
    if matched_vol_id:
        vol_user = db.query(User).join(VolunteerProfile).filter(VolunteerProfile.id == matched_vol_id).first()
        creation_timeline_desc += f" Automatically assigned to volunteer '{vol_user.username if vol_user else 'Unknown'}'."
    
    case_timeline_event = CaseTimeline(
        case_id=db_case.id,
        event_type="CREATION",
        description=creation_timeline_desc
    )
    db.add(case_timeline_event)
    db.commit()
    db.refresh(db_case)

    return db_case

@router.get("/cases/assigned", response_model=List[WelfareCaseResponse])
def get_assigned_cases(request: Request, db: Session = Depends(get_db)):
    """
    Get cases assigned to the currently authenticated volunteer.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    vol = db.query(VolunteerProfile).filter(VolunteerProfile.user_id == int(user_id)).first()
    if not vol:
        return []
        
    return db.query(WelfareCase).filter(WelfareCase.volunteer_id == vol.id).order_by(WelfareCase.created_at.desc()).all()

@router.put("/cases/{case_id}", response_model=WelfareCaseResponse)
def update_case(case_id: int, payload: WelfareCaseUpdate, db: Session = Depends(get_db)):
    """
    Update details of a welfare case (status, checklist tasks, or volunteer ID).
    Automatically fires timeline updates.
    """
    db_case = db.query(WelfareCase).filter(WelfareCase.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Welfare case not found.")

    old_status = db_case.status
    old_visit_date = db_case.upcoming_visit_date

    # Update fields
    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(db_case, k, v)

    db.commit()
    db.refresh(db_case)

    # Automatically generate citizen timeline audit trails
    timeline_desc = ""
    event_type = None

    if payload.status and payload.status != old_status:
        if payload.status == "ASSIGNED":
            event_type = "Cases Created"
            vol_user = db.query(User).join(VolunteerProfile).filter(VolunteerProfile.id == db_case.volunteer_id).first()
            timeline_desc = f"Case '{db_case.title}' assigned to volunteer '{vol_user.username if vol_user else 'Unknown'}'."
        elif payload.status == "IN_PROGRESS":
            event_type = "Volunteer Visit"
            timeline_desc = f"Home visit scheduled for case '{db_case.title}'."
            if db_case.upcoming_visit_date:
                timeline_desc += f" Scheduled Date: {db_case.upcoming_visit_date.strftime('%Y-%m-%d %H:%M')}."
        elif payload.status == "RESOLVED":
            event_type = "Resolutions"
            timeline_desc = f"Case '{db_case.title}' has been successfully resolved and closed."

    elif payload.upcoming_visit_date and payload.upcoming_visit_date != old_visit_date:
        event_type = "Volunteer Visit"
        timeline_desc = f"Home visit scheduled or modified for case '{db_case.title}'. Date: {db_case.upcoming_visit_date.strftime('%Y-%m-%d %H:%M')}."

    if event_type and timeline_desc:
        timeline_event = CitizenTimeline(
            citizen_id=db_case.citizen_id,
            event_type=event_type,
            description=timeline_desc
        )
        db.add(timeline_event)
        db.commit()

    # Log status or update history in CaseTimeline
    if payload.status and payload.status != old_status:
        case_timeline_event = CaseTimeline(
            case_id=db_case.id,
            event_type="STATUS_CHANGE",
            description=f"Status changed from {old_status} to {payload.status}."
        )
        db.add(case_timeline_event)
        db.commit()
    elif len(update_data) > 0:
        updated_fields = ", ".join(update_data.keys())
        case_timeline_event = CaseTimeline(
            case_id=db_case.id,
            event_type="UPDATE",
            description=f"Case updated. Fields modified: {updated_fields}."
        )
        db.add(case_timeline_event)
        db.commit()

    db.refresh(db_case)
    return db_case

@router.post("/cases/{case_id}/timeline/notes", response_model=CaseTimelineResponse, status_code=status.HTTP_201_CREATED)
def add_case_note(case_id: int, payload: CaseTimelineNoteCreate, db: Session = Depends(get_db)):
    """
    Add a manual note/comment to the case timeline.
    """
    db_case = db.query(WelfareCase).filter(WelfareCase.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Welfare case not found.")

    timeline_event = CaseTimeline(
        case_id=case_id,
        event_type="NOTE",
        description="Volunteer added a note.",
        note=payload.note
    )
    db.add(timeline_event)
    db.commit()
    db.refresh(timeline_event)
    return timeline_event

@router.post("/cases/{case_id}/timeline/attachments", response_model=CaseTimelineResponse, status_code=status.HTTP_201_CREATED)
def upload_case_attachment(case_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload a file attachment to the case timeline.
    """
    db_case = db.query(WelfareCase).filter(WelfareCase.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Welfare case not found.")

    # Create uploads directory if it doesn't exist
    upload_dir = "uploads"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)

    # Secure the file name to prevent directory traversal
    filename = f"{uuid.uuid4().hex}_{os.path.basename(file.filename)}"
    file_path = os.path.join(upload_dir, filename)

    # Write the file locally
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.error(f"Failed to save file: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    attachment_url = f"/uploads/{filename}"

    timeline_event = CaseTimeline(
        case_id=case_id,
        event_type="ATTACHMENT",
        description=f"File uploaded: {file.filename}.",
        attachment_url=attachment_url,
        attachment_name=file.filename
    )
    db.add(timeline_event)
    db.commit()
    db.refresh(timeline_event)
    return timeline_event

@router.get("/cases/{case_id}/timeline", response_model=List[CaseTimelineResponse])
def get_case_timeline(case_id: int, db: Session = Depends(get_db)):
    """
    Fetch all timeline events for a welfare case.
    """
    return db.query(CaseTimeline).filter(CaseTimeline.case_id == case_id).order_by(CaseTimeline.id.desc()).all()
