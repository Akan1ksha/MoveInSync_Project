"""
Conversation state persistence.
Saves/loads the LangGraph GraphState to/from the DB so the agent
can resume after a process restart without a full LangGraph checkpoint backend.
"""
from __future__ import annotations

import json
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.db import ConversationState


def save_state(db: Session, conversation_id: str, company_id: str, employee_id: str, state: dict):
    """Upsert the conversation state."""
    record = db.query(ConversationState).filter_by(conversation_id=conversation_id).first()
    if record:
        record.graph_state_json = json.dumps(state)
        record.updated_at = datetime.utcnow()
    else:
        record = ConversationState(
            conversation_id=conversation_id,
            company_id=company_id,
            employee_id=employee_id,
            graph_state_json=json.dumps(state),
        )
        db.add(record)
    db.commit()


def load_state(db: Session, conversation_id: str, company_id: str) -> dict | None:
    """
    Load state, enforcing that it belongs to the caller's company.
    Returns None if not found or if company_id doesn't match (isolation).
    """
    record = db.query(ConversationState).filter_by(conversation_id=conversation_id).first()
    if not record:
        return None
    # Company isolation check
    if record.company_id != company_id:
        return None
    return json.loads(record.graph_state_json)
