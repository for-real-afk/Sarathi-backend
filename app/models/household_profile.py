from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class HouseholdProfile(Base):
    __tablename__ = "household_profiles"

    id = Column(Integer, primary_key=True, index=True)
    income = Column(String, nullable=True)
    housing_status = Column(String, nullable=True)
    land_ownership = Column(String, nullable=True)
    occupation = Column(String, nullable=True)
    poverty_classification = Column(String, nullable=True)
    family_members = Column(JSON, default=[], nullable=False) # List of dicts with: age, education, occupation, disability, relationship

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    citizens = relationship("CitizenProfile", back_populates="household", cascade="all, delete-orphan")
