from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class CitizenTimeline(Base):
    __tablename__ = "citizen_timelines"

    id = Column(Integer, primary_key=True, index=True)
    citizen_id = Column(Integer, ForeignKey("citizen_profiles.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False) # Profile Creation, Eligibility Run, Case Created, Volunteer Visit, Resolution
    description = Column(String, nullable=True)
    event_date = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    citizen = relationship("CitizenProfile", back_populates="timeline")
