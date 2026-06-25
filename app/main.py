import datetime
import os
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, engine, Base, SessionLocal
from app.models import Survey, KnowledgeDocument, SchemeRegistry, SchemeChunk, ChatLog
from app.schemas import SurveyCreate, SurveyUpdate, SurveyResponse
from app.api.routes import router as api_router

# Import auth services and routers
from app.services.auth import seed_database
from app.api.auth import router as auth_router
from app.api.protected_routes import router as protected_router
from app.api.crm import router as crm_router
from app.services.crm_sync import sync_survey_to_crm
from app.api.volunteer_ops import router as volunteer_ops_router



import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse

# Automatically bootstrap database tables on startup
Base.metadata.create_all(bind=engine)

# Seed database with roles, permissions, and default accounts
db = SessionLocal()
try:
    seed_database(db)
finally:
    db.close()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for storing and managing Household Welfare Surveys."
)

if not os.path.exists("uploads"):
    os.makedirs("uploads")

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Custom Authorization Middleware for RBAC
class AuthorizationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Bypass OPTIONS requests for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        required_roles = None

        # Check path prefixes for required roles
        if path.startswith("/admin") or path.startswith("/api/admin"):
            required_roles = ["ADMIN"]
        elif path.startswith("/volunteers") or path.startswith("/api/volunteers"):
            required_roles = ["ADMIN", "CENTRAL_HUB", "LOCAL_HUB"]
        elif path.startswith("/citizens") or path.startswith("/api/citizens") or path.startswith("/api/volunteer-ops"):
            required_roles = ["ADMIN", "CENTRAL_HUB", "LOCAL_HUB", "VOLUNTEER"]

        elif path.startswith("/cases") or path.startswith("/api/cases"):
            required_roles = ["ADMIN", "CENTRAL_HUB", "LOCAL_HUB", "VOLUNTEER", "CITIZEN"]

        if required_roles is not None:
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid authorization credentials."}
                )
            
            token = auth_header.split(" ")[1]
            try:
                payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                user_id = payload.get("sub")
                roles = payload.get("roles", [])
                
                # Check if user has at least one of the required roles
                if not any(role in required_roles for role in roles):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": f"Forbidden: Access denied. Required roles: {required_roles}."}
                    )
                
                # Expose user context on request.state
                request.state.user_id = user_id
                request.state.roles = roles

            except jwt.ExpiredSignatureError:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token has expired."}
                )
            except jwt.PyJWTError:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid token."}
                )

        return await call_next(request)

# Add Middleware
app.add_middleware(AuthorizationMiddleware)

# Register Routers
app.include_router(auth_router)
app.include_router(protected_router)
app.include_router(api_router, tags=["RAG & Welfare Intelligence"])
app.include_router(crm_router)
app.include_router(volunteer_ops_router)




# CORS middleware configuration
origins = settings.CORS_ORIGINS
if isinstance(origins, str):
    origins = [origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def map_schema_to_model_fields(payload: SurveyCreate) -> dict:
    """
    Maps incoming Pydantic payload data into model attributes and parses date timestamps.
    """
    submitted_at_dt = None
    if payload.submitted_at:
        try:
            # standard ISO format parsing (e.g. 2026-06-12T05:45:12.123Z)
            iso_str = payload.submitted_at.replace("Z", "+00:00")
            submitted_at_dt = datetime.datetime.fromisoformat(iso_str)
        except Exception:
            submitted_at_dt = datetime.datetime.utcnow()
    else:
        submitted_at_dt = datetime.datetime.utcnow()

    return {
        "first_name": payload.firstName,
        "last_name": payload.lastName,
        "primary_mobile": payload.primaryMobile,
        "dob": payload.dob,
        "surveyor_name": payload.surveyorName,
        "surveyor_id": payload.surveyorId,
        "survey_language": payload.survey_language,
        "submitted_at": submitted_at_dt,
        "data": payload.model_dump(),  # Convert entire validated payload to dict for JSONB
    }

# ── API ROUTES ──────────────────────────────────────────────────────────────

@app.post("/submit", response_model=SurveyResponse, status_code=status.HTTP_201_CREATED)
@app.post("/api/surveys", response_model=SurveyResponse, status_code=status.HTTP_201_CREATED)
def submit_survey(payload: SurveyCreate, db: Session = Depends(get_db)):
    """
    Submits a survey response. Validates JSON payload, indexes key columns, and
    saves complete document in JSONB column.
    """
    try:
        db_fields = map_schema_to_model_fields(payload)
        db_survey = Survey(**db_fields)
        db.add(db_survey)
        db.commit()
        db.refresh(db_survey)
        
        # Synchronize survey with NGO Citizen Registry CRM
        try:
            sync_survey_to_crm(db, db_survey)
        except Exception as sync_err:
            import logging
            logger = logging.getLogger("uvicorn.error")
            logger.error(f"Failed to auto-sync survey to CRM: {sync_err}")

        return db_survey
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while saving the survey: {str(e)}"
        )

@app.get("/records", response_model=List[SurveyResponse])
@app.get("/api/surveys", response_model=List[SurveyResponse])
def get_records(
    first_name: Optional[str] = None,
    primary_mobile: Optional[str] = None,
    surveyor_id: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
    db: Session = Depends(get_db)
):
    """
    Retrieves survey responses from the database. Supports search filtering on top-level columns.
    """
    query = db.query(Survey)
    if first_name:
        query = query.filter(Survey.first_name.ilike(f"%{first_name}%"))
    if primary_mobile:
        query = query.filter(Survey.primary_mobile == primary_mobile)
    if surveyor_id:
        query = query.filter(Survey.surveyor_id == surveyor_id)
        
    records = query.order_by(Survey.submitted_at.desc()).offset(skip).limit(limit).all()
    return records

@app.get("/records/{record_id}", response_model=SurveyResponse)
def get_record(record_id: int, db: Session = Depends(get_db)):
    """
    Retrieves a single survey record by ID.
    """
    record = db.query(Survey).filter(Survey.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Survey record with ID {record_id} not found"
        )
    return record

@app.put("/records/{record_id}", response_model=SurveyResponse)
def update_record(record_id: int, payload: SurveyUpdate, db: Session = Depends(get_db)):
    """
    Updates an existing survey record.
    """
    db_record = db.query(Survey).filter(Survey.id == record_id).first()
    if not db_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Survey record with ID {record_id} not found"
        )
    
    # Update individual indexed columns if provided
    if payload.firstName is not None:
        db_record.first_name = payload.firstName
    if payload.lastName is not None:
        db_record.last_name = payload.lastName
    if payload.primaryMobile is not None:
        db_record.primary_mobile = payload.primaryMobile
    if payload.dob is not None:
        db_record.dob = payload.dob
    if payload.surveyorName is not None:
        db_record.surveyor_name = payload.surveyorName
    if payload.surveyorId is not None:
        db_record.surveyor_id = payload.surveyorId
    if payload.survey_language is not None:
        db_record.survey_language = payload.survey_language
        
    # Update entire JSON document if provided
    if payload.data is not None:
        db_record.data = payload.data
        
    try:
        db.commit()
        db.refresh(db_record)
        return db_record
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while updating the survey: {str(e)}"
        )

@app.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_record(record_id: int, db: Session = Depends(get_db)):
    """
    Deletes a survey record by ID.
    """
    db_record = db.query(Survey).filter(Survey.id == record_id).first()
    if not db_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Survey record with ID {record_id} not found"
        )
    try:
        db.delete(db_record)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while deleting the survey: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
