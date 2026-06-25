from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class CaseTimeline(Base):
    __tablename__ = "case_timeline"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("welfare_cases.id", ondelete="CASCADE"), nullable=False)
    
    event_type = Column(String, nullable=False)  # STATUS_CHANGE, NOTE, ATTACHMENT, UPDATE, CREATION
    description = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    attachment_url = Column(String, nullable=True)
    attachment_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("WelfareCase", back_populates="timeline")
