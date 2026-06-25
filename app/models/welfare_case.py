from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class WelfareCase(Base):
    __tablename__ = "welfare_cases"

    id = Column(Integer, primary_key=True, index=True)
    citizen_id = Column(Integer, ForeignKey("citizen_profiles.id", ondelete="CASCADE"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("volunteer_profiles.id", ondelete="SET NULL"), nullable=True)
    
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, default="OPEN", nullable=False) # OPEN, ASSIGNED, IN_PROGRESS, RESOLVED
    
    upcoming_visit_date = Column(DateTime(timezone=True), nullable=True)
    follow_up_tasks = Column(JSON, default=[], nullable=False) # e.g. [{"task_name": "Aadhaar verification", "completed": False}]

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    citizen = relationship("CitizenProfile")
    volunteer = relationship("VolunteerProfile", back_populates="cases")
    timeline = relationship("CaseTimeline", back_populates="case", cascade="all, delete-orphan", order_by="CaseTimeline.id.desc()")
