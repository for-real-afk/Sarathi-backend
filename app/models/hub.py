from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class Hub(Base):
    __tablename__ = "hubs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    hub_type = Column(String, nullable=False) # "CENTRAL" or "LOCAL"
    district = Column(String, nullable=False)
    
    parent_hub_id = Column(Integer, ForeignKey("hubs.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    parent_hub = relationship("Hub", remote_side=[id], backref="child_hubs")
    volunteers = relationship("VolunteerProfile", back_populates="hub")
