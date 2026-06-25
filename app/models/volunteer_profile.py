from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class VolunteerProfile(Base):
    __tablename__ = "volunteer_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    contact_phone = Column(String, index=True, nullable=True)
    district = Column(String, index=True, nullable=False)
    availability = Column(Boolean, default=True, nullable=False)

    hub_id = Column(Integer, ForeignKey("hubs.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    hub = relationship("Hub", back_populates="volunteers")
    cases = relationship("WelfareCase", back_populates="volunteer")
