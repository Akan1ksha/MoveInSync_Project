"""
SQLAlchemy models for persistent state.
Using SQLite in dev; swap DATABASE_URL to Postgres in prod.
"""
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, Enum, Text, Integer, Boolean, ForeignKey, Float
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class RequestStatus(str, PyEnum):
    PENDING_CLARIFICATION = "pending_clarification"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class ShiftChangeRequest(Base):
    """
    One per employee message-thread that initiates a change.
    Survives restarts — LangGraph resumes from here.
    """
    __tablename__ = "shift_change_requests"

    id = Column(String, primary_key=True)             # UUID
    company_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)

    # What was asked
    original_time = Column(String)
    requested_time = Column(String)
    trip_type = Column(String)                         # "pickup" | "drop"
    roster_entry_id = Column(String)

    # Decision
    status = Column(Enum(RequestStatus), default=RequestStatus.PENDING_CLARIFICATION)
    manager_decision = Column(String)                  # "approved" | "rejected" | null
    manager_note = Column(Text)
    decided_at = Column(DateTime)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationState(Base):
    """
    Persists LangGraph checkpoint so the agent can resume after restart.
    In production you'd use langgraph's built-in Postgres checkpointer;
    this lightweight table serves the same purpose for the demo.
    """
    __tablename__ = "conversation_states"

    conversation_id = Column(String, primary_key=True)
    company_id = Column(String, nullable=False)
    employee_id = Column(String, nullable=False)
    graph_state_json = Column(Text)                   # serialised GraphState
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WaitlistEntry(Base):
    """Bonus: employees waiting for a seat to free up on a specific cab/time."""
    __tablename__ = "waitlist"

    id = Column(String, primary_key=True)
    company_id = Column(String, nullable=False)
    employee_id = Column(String, nullable=False)
    roster_entry_id = Column(String, nullable=False)
    notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
