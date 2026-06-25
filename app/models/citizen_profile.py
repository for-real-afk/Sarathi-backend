from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class CitizenProfile(Base):
    __tablename__ = "citizen_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    phone = Column(String, index=True, nullable=True)
    aadhaar_reference = Column(String, index=True, nullable=True)
    gender = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    address = Column(String, nullable=True)
    state = Column(String, nullable=True)
    district = Column(String, nullable=True)
    mandal = Column(String, nullable=True)
    village = Column(String, nullable=True)
    
    household_id = Column(Integer, ForeignKey("household_profiles.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    household = relationship("HouseholdProfile", back_populates="citizens")
    timeline = relationship("CitizenTimeline", back_populates="citizen", cascade="all, delete-orphan")
