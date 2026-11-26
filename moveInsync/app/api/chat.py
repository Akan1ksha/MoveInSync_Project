"""
FastAPI route handlers — chat and manager-decision endpoints.
"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_identity
from app.models.schemas import ChatMessage, ChatResponse, ManagerDecisionRequest
from app.models.database import get_db
from app.models.db import ShiftChangeRequest, RequestStatus, ConversationState
from app.agent.graph import GRAPH, GraphState
from app.agent.state_store import save_state, load_state

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatMessage,
    identity: dict = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """
    Main chat endpoint.
    - Loads or creates conversation state.
    - Appends the user message.
    - Runs the LangGraph agent.
    - Saves state and returns the reply.
    """
    company_id = identity["company_id"]
    employee_id = identity["sub"]

    # Resolve or create conversation
    conversation_id = body.conversation_id or str(uuid.uuid4())

    # Load existing state (enforces company isolation inside load_state)
    existing = load_state(db, conversation_id, company_id) if body.conversation_id else None

    if existing:
        state: GraphState = existing  # type: ignore
    else:
        state: GraphState = {
            "company_id": company_id,
            "employee_id": employee_id,
            "conversation_id": conversation_id,
            "messages": [],
            "intent": None,
            "requested_time": None,
            "roster_entry_id": None,
            "chosen_cab_id": None,
            "request_id": None,
            "llm_calls": 0,
            "next_action": "",
            "pending_manager": False,
            "manager_decision": None,
            "reply": "",
        }

    # Guard: conversation belongs to the right employee
    if state.get("employee_id") and state["employee_id"] != employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation not yours.")

    # Guard: paused for manager — tell the user instead of running the graph
    if state.get("pending_manager"):
        return ChatResponse(
            conversation_id=conversation_id,
            reply=(
                "Your request is still waiting for manager approval. "
                "You'll receive a notification once a decision is made."
            ),
            status=RequestStatus.PENDING_APPROVAL,
            request_id=state.get("request_id"),
        )

    # Append user message
    state["messages"] = state.get("messages", []) + [
        {"role": "user", "content": body.message}
    ]
    state["llm_calls"] = 0  # reset per-turn counter

    # Run graph
    try:
        result: GraphState = GRAPH.invoke(state)  # type: ignore
    except Exception as exc:
        # Never show a stack trace; always give a plain error message
        reply = (
            "Something went wrong on our end. Please try again in a moment, "
            "or contact the transport desk if the issue persists."
        )
        save_state(db, conversation_id, company_id, employee_id, state)
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            status="failed",
        )

    # Append assistant reply to history
    result["messages"] = result.get("messages", []) + [
        {"role": "assistant", "content": result.get("reply", "")}
    ]

    save_state(db, conversation_id, company_id, employee_id, dict(result))

    return ChatResponse(
        conversation_id=conversation_id,
        reply=result.get("reply", "I'm not sure how to help with that. Could you rephrase?"),
        status="pending_approval" if result.get("pending_manager") else "chat",
        request_id=result.get("request_id"),
    )


@router.post("/requests/{request_id}/decision")
def manager_decision(
    request_id: str,
    body: ManagerDecisionRequest,
    identity: dict = Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """
    Manager-only endpoint to approve or reject a paused request.
    After writing the decision, resumes the paused conversation graph.
    """
    if identity.get("role") != "manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager role required.")

    company_id = identity["company_id"]

    # Find the request — must belong to the manager's company
    req = db.query(ShiftChangeRequest).filter_by(
        id=request_id, company_id=company_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    if req.status != RequestStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"Request is already in state: {req.status}.")

    # Write decision
    req.manager_decision = body.decision
    req.manager_note = body.note
    req.status = RequestStatus.APPROVED if body.decision == "approved" else RequestStatus.REJECTED
    db.commit()

    # Resume the paused conversation
    conv_state = load_state(db, req.conversation_id, company_id)
    if not conv_state:
        return {"status": "decision_recorded", "note": "Conversation state not found; cannot resume."}

    conv_state["manager_decision"] = body.decision
    conv_state["pending_manager"] = False
    conv_state["next_action"] = "resume"

    # Re-enter graph at resume node
    try:
        result: GraphState = GRAPH.invoke(conv_state)  # type: ignore
        result["messages"] = result.get("messages", []) + [
            {"role": "assistant", "content": result.get("reply", "")}
        ]
        save_state(db, req.conversation_id, company_id, req.employee_id, dict(result))
    except Exception:
        pass  # Decision is recorded; graph resume failure is non-fatal here

    return {
        "status": "ok",
        "decision": body.decision,
        "request_id": request_id,
        "employee_message": conv_state.get("reply", ""),
    }
