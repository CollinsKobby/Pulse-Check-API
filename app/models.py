from sqlalchemy import TIMESTAMP, Column, DateTime, Integer, String, Enum as SQLEnum
from sqlalchemy.sql.expression import null
from .database import Base
import enum

class MonitorStatus(enum.Enum):
    ACTIVE = "active"
    DOWN = "down"
    PAUSED = "paused"

class Monitors(Base):
    __tablename__ = "monitors"

    id = Column(String, primary_key=True, nullable=False)
    timeout = Column(Integer, nullable=False, default=60)
    alert_email = Column(String, nullable=False)
    status = Column(SQLEnum(MonitorStatus), nullable=False, default=MonitorStatus.ACTIVE)
    expires_at = Column(DateTime, nullable=False)