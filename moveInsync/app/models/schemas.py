"""
Pydantic schemas for API request/response bodies.
These are NOT the DB models — they are the wire format.
"""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = None   # None → new conversation


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    status: str                              # mirrors RequestStatus or "chat"
    request_id: Optional[str] = None


class ManagerDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    note: Optional[str] = None


class TokenRequest(BaseModel):
    company_id: str
    employee_id: str
    role: str = "employee"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
