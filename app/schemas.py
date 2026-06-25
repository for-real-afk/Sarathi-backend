from pydantic import BaseModel, field_validator
from typing import List, Dict, Any, Optional
from datetime import datetime

class SurveyCreate(BaseModel):
    # Section A - Identity
    firstName: str
    middleName: Optional[str] = None
    lastName: str
    primaryMobile: str
    alternateMobile: Optional[str] = None
    dob: str
    age: Optional[str] = None
    aadhaarConsent: Optional[str] = None
    aadhaarNumber: Optional[str] = None
    gender: str
    maritalStatus: str
    religion: str
    socialCategory: str
    subCaste: Optional[str] = None
    residentialStatus: str
    houseNo: Optional[str] = None
    street: Optional[str] = None
    village: str
    mandal: Optional[str] = None
    district: str
    state: str
    pincode: Optional[str] = None
    durationAtAddress: Optional[str] = None

    # Section B - Household
    adults: Optional[str] = "0"
    childrenCount: Optional[str] = "0"
    seniors: Optional[str] = "0"
    familyStructure: str
    familyMembers: List[Dict[str, Any]] = []

    # Section C - Employment
    mainOccupation: str
    employmentNature: str
    secondaryIncome: List[str] = []
    empChallenges: List[str] = []

    # Section D - Income
    monthlyIncomeRange: str
    annualIncome: str
    bankAccount: str
    liquidSavings: Optional[str] = None
    insuranceCoverage: List[str] = []
    householdDebt: Dict[str, Any] = {}
    debtReasons: List[str] = []

    # Section E - Assets & Amenities
    housingType: str
    housingOwnership: str
    agriLand: str
    livestock: str
    twoWheelers: Optional[str] = "0"
    fourWheelers: Optional[str] = "0"
    smartphones: Optional[str] = "0"
    
    # Amenities (Part of Section E)
    amenity_electricity: Optional[str] = None
    amenity_drinkingWater: Optional[str] = None
    amenity_toilet: Optional[str] = None
    amenity_lpgGas: Optional[str] = None
    amenity_internet: Optional[str] = None

    # Section F - Education
    eduMembers: List[Dict[str, Any]] = []
    dropoutReasons: List[str] = []

    # Section G - Health
    chronicConditions: List[Dict[str, Any]] = []
    disabilities: List[Dict[str, Any]] = []
    healthcareAccess: List[str] = []
    healthChallenges: List[str] = []

    # Section H - Welfare
    currentSchemes: List[Dict[str, Any]] = []
    applicableSchemes: List[str] = []
    benefitsNotReceived: List[str] = []
    benefitsMostNeeded: List[str] = []

    # Section I - Digital Access & Docs
    hasSmartphone: str
    digitalAbility: Optional[str] = None
    doc_aadhaar_available: Optional[str] = None
    doc_aadhaar_valid: Optional[str] = None
    doc_pan_available: Optional[str] = None
    doc_pan_valid: Optional[str] = None
    doc_rationCard_available: Optional[str] = None
    doc_rationCard_valid: Optional[str] = None
    doc_incomeCert_available: Optional[str] = None
    doc_incomeCert_valid: Optional[str] = None
    doc_casteCert_available: Optional[str] = None
    doc_casteCert_valid: Optional[str] = None
    doc_disabilityCert_available: Optional[str] = None
    doc_disabilityCert_valid: Optional[str] = None
    doc_voterId_available: Optional[str] = None
    doc_voterId_valid: Optional[str] = None
    doc_bankPassbook_available: Optional[str] = None
    doc_bankPassbook_valid: Optional[str] = None

    # Section J - Community
    altContactName: Optional[str] = None
    altRelationship: Optional[str] = None
    altMobile: Optional[str] = None
    altOccupation: Optional[str] = None
    communityRole: List[str] = []
    willingToReceiveInfo: Optional[str] = None
    preferredComm: List[str] = []

    # Section K - Consent
    consentStatus: str
    signatureName: str
    consentDate: str
    surveyorName: str
    surveyorId: str
    surveyLocation: str
    additionalRemarks: Optional[str] = None

    # Survey Metadata (sent in payload)
    survey_language: Optional[str] = "en"
    submitted_at: Optional[str] = None
    sections_visited: List[str] = []


class SurveyUpdate(BaseModel):
    # Allow updating individual searchable columns or the entire payload
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    primaryMobile: Optional[str] = None
    dob: Optional[str] = None
    surveyorName: Optional[str] = None
    surveyorId: Optional[str] = None
    survey_language: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class SurveyResponse(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    primary_mobile: Optional[str] = None
    dob: Optional[str] = None
    surveyor_name: Optional[str] = None
    surveyor_id: Optional[str] = None
    survey_language: Optional[str] = None
    submitted_at: Optional[datetime] = None
    data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- RAG & Welfare Scheme schemas ---

class RawTextIngest(BaseModel):
    title: str
    content: str
    verification_level: Optional[str] = "COMMUNITY_SOURCE"

class UrlIngest(BaseModel):
    title: str
    url: str
    verification_level: Optional[str] = "COMMUNITY_SOURCE"

class SchemeCreate(BaseModel):
    scheme_name: str
    state: str
    department: Optional[str] = None
    category: str
    description: str
    benefits: Dict[str, Any]
    eligibility_rules: Dict[str, Any]
    required_documents: List[str]
    application_process: str
    source_page: Optional[int] = 1
    source_urls: Optional[List[str]] = None
    verification_status: Optional[str] = "UNVERIFIED"
    verification_level: Optional[str] = "COMMUNITY_SOURCE"

class SchemeUpdate(BaseModel):
    scheme_name: Optional[str] = None
    state: Optional[str] = None
    department: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    benefits: Optional[Dict[str, Any]] = None
    eligibility_rules: Optional[Dict[str, Any]] = None
    required_documents: Optional[List[str]] = None
    application_process: Optional[str] = None
    source_page: Optional[int] = None
    source_urls: Optional[List[str]] = None
    verification_status: Optional[str] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    version_source: Optional[str] = None
    change_summary: Optional[str] = None
    verification_level: Optional[str] = None

class SchemeResponse(BaseModel):
    id: Any
    document_id: Optional[Any] = None
    scheme_name: str
    state: str
    department: Optional[str] = None
    category: str
    description: str
    benefits: Dict[str, Any]
    eligibility_rules: Dict[str, Any]
    required_documents: List[str]
    application_process: str
    source_page: Optional[int] = None
    source_urls: Optional[List[str]] = None
    verification_status: str
    is_active: bool
    is_archived: bool
    version: int
    verification_level: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SchemeVersionHistoryResponse(BaseModel):
    id: Any
    scheme_id: Any
    version: int
    scheme_name: str
    state: str
    department: Optional[str] = None
    category: str
    description: str
    benefits: Dict[str, Any]
    eligibility_rules: Dict[str, Any]
    required_documents: List[str]
    application_process: str
    source_urls: Optional[List[str]] = None
    verification_level: str
    version_source: Optional[str] = None
    change_summary: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    profile: Dict[str, Any]
    question: str
    history: Optional[List[ChatMessage]] = []

class EligibleSchemeRecommendation(BaseModel):
    scheme_name: str
    eligibility_status: str
    eligibility_score: int
    why_recommended: str
    missing_documents: List[str]
    next_steps: str
    source_page: int
    verification_status: str

class ChatResponse(BaseModel):
    response: str
    recommendations: List[EligibleSchemeRecommendation]
    retrieved_sources: List[Dict[str, Any]]

class ChatFeedbackRequest(BaseModel):
    rating: str

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: str) -> str:
        valid_ratings = {"HELPFUL", "NOT_HELPFUL"}
        if value not in valid_ratings:
            raise ValueError(f"Feedback rating must be one of {valid_ratings}")
        return value

class BenchmarkLogResponse(BaseModel):
    id: Any
    session_id: Optional[str] = None
    citizen_profile: Optional[Dict[str, Any]] = None
    question: str
    retrieved_chunks: List[Dict[str, Any]]
    llm_response: str
    latency_ms: int
    feedback: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# --- Citizen CRM Schemas ---

class CitizenTimelineCreate(BaseModel):
    event_type: str
    description: Optional[str] = None
    event_date: Optional[datetime] = None

class CitizenTimelineResponse(BaseModel):
    id: int
    citizen_id: int
    event_type: str
    description: Optional[str] = None
    event_date: datetime
    created_at: datetime

    class Config:
        from_attributes = True

class HouseholdProfileCreate(BaseModel):
    income: Optional[str] = None
    housing_status: Optional[str] = None
    land_ownership: Optional[str] = None
    occupation: Optional[str] = None
    poverty_classification: Optional[str] = None
    family_members: List[Dict[str, Any]] = []

class HouseholdProfileUpdate(BaseModel):
    income: Optional[str] = None
    housing_status: Optional[str] = None
    land_ownership: Optional[str] = None
    occupation: Optional[str] = None
    poverty_classification: Optional[str] = None
    family_members: Optional[List[Dict[str, Any]]] = None

class HouseholdProfileResponse(BaseModel):
    id: int
    income: Optional[str] = None
    housing_status: Optional[str] = None
    land_ownership: Optional[str] = None
    occupation: Optional[str] = None
    poverty_classification: Optional[str] = None
    family_members: List[Dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CitizenProfileCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    aadhaar_reference: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    address: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    household_id: Optional[int] = None
    household: Optional[HouseholdProfileCreate] = None

class CitizenProfileUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    aadhaar_reference: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    address: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    household_id: Optional[int] = None
    household: Optional[HouseholdProfileUpdate] = None

class CitizenProfileResponse(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    aadhaar_reference: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    address: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    household_id: Optional[int] = None
    household: Optional[HouseholdProfileResponse] = None
    timeline: List[CitizenTimelineResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Volunteer & Hub Operations Schemas ---

class HubCreate(BaseModel):
    name: str
    hub_type: str  # "CENTRAL" or "LOCAL"
    district: str
    parent_hub_id: Optional[int] = None

class HubResponse(BaseModel):
    id: int
    name: str
    hub_type: str
    district: str
    parent_hub_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True

class VolunteerProfileCreate(BaseModel):
    user_id: int
    contact_phone: Optional[str] = None
    district: str
    availability: Optional[bool] = True
    hub_id: Optional[int] = None

class VolunteerProfileResponse(BaseModel):
    id: int
    user_id: int
    contact_phone: Optional[str] = None
    district: str
    availability: bool
    hub_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True

class CaseTimelineNoteCreate(BaseModel):
    note: str

class CaseTimelineResponse(BaseModel):
    id: int
    case_id: int
    event_type: str
    description: str
    note: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class WelfareCaseCreate(BaseModel):
    citizen_id: int
    volunteer_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    status: Optional[str] = "OPEN"
    upcoming_visit_date: Optional[datetime] = None
    follow_up_tasks: List[Dict[str, Any]] = []

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        valid_statuses = {"OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED"}
        if value is not None and value not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return value

class WelfareCaseUpdate(BaseModel):
    volunteer_id: Optional[int] = None
    status: Optional[str] = None
    upcoming_visit_date: Optional[datetime] = None
    follow_up_tasks: Optional[List[Dict[str, Any]]] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        valid_statuses = {"OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED"}
        if value is not None and value not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return value

class WelfareCaseResponse(BaseModel):
    id: int
    citizen_id: int
    citizen: CitizenProfileResponse
    volunteer_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    status: str
    upcoming_visit_date: Optional[datetime] = None
    follow_up_tasks: List[Dict[str, Any]] = []
    timeline: List[CaseTimelineResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True



