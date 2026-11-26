"""
Mock roster store backed by JSON data files.
In production this would be a DB query or an internal REST call.

Design decision: Rules (cut-off, capacity) are enforced HERE in Python,
never inside the LLM prompt.  The model only gets back structured facts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _load(filename: str) -> dict:
    with open(DATA_DIR / filename) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Public tool functions — these are what the LangGraph agent calls via tools
# ---------------------------------------------------------------------------

def get_employee_roster(company_id: str, employee_id: str, date: Optional[str] = None) -> dict:
    """
    Returns the employee's roster entries for the given date (default: today).
    ALWAYS scoped by company_id — cross-company access is structurally impossible.
    """
    try:
        rosters = _load("rosters.json")
    except FileNotFoundError:
        return {"error": "Roster data unavailable. Please try again later."}

    # Strict company isolation
    company_rosters = rosters.get(company_id, {})
    employee_entries = company_rosters.get(employee_id, [])

    if not employee_entries:
        return {"entries": [], "message": "No roster found for today."}

    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    todays = [e for e in employee_entries if e.get("date") == target_date]
    return {"entries": todays, "date": target_date}


def get_cab_options(
    company_id: str,
    trip_type: str,
    requested_time: str,
    date: Optional[str] = None,
) -> dict:
    """
    Returns available cabs with free seats at or near the requested time.
    Only cabs belonging to the company are returned.
    """
    try:
        cabs = _load("cabs.json")
    except FileNotFoundError:
        return {"error": "Cab data unavailable. Please try again later."}

    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    company_cabs = [
        c for c in cabs
        if c["company_id"] == company_id
        and c["trip_type"] == trip_type
        and c["date"] == target_date
    ]

    # Parse requested time and find cabs within ±90 minutes
    try:
        req_dt = datetime.strptime(f"{target_date} {requested_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return {"error": f"Cannot parse time '{requested_time}'. Use HH:MM format."}

    options = []
    for cab in company_cabs:
        cab_dt = datetime.strptime(f"{target_date} {cab['time']}", "%Y-%m-%d %H:%M")
        diff_minutes = abs((cab_dt - req_dt).total_seconds() / 60)
        if diff_minutes <= 90 and cab["seats_available"] > 0:
            options.append({**cab, "minutes_diff": int(diff_minutes)})

    options.sort(key=lambda c: c["minutes_diff"])
    return {"options": options[:5]}   # return at most 5 nearest


def check_policy(company_id: str, trip_type: str, scheduled_time: str, date: Optional[str] = None) -> dict:
    """
    Checks if the current time is within the company's cut-off window.
    Returns {"allowed": bool, "reason": str, "cutoff_hours": float}.
    Rules are enforced HERE — the LLM only sees the result, never the raw rule.
    """
    try:
        policies = _load("policies.json")
    except FileNotFoundError:
        return {"error": "Policy data unavailable. Please try again later."}

    policy = policies.get(company_id)
    if not policy:
        return {"error": f"No policy found for company {company_id}."}

    cutoff_hours: float = policy.get("cutoff_hours", 2.0)
    max_seats: int = policy.get("max_seats_per_cab", 6)

    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        trip_dt = datetime.strptime(f"{target_date} {scheduled_time}", "%Y-%m-%d %H:%M")
        trip_dt = trip_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return {"error": f"Cannot parse scheduled time '{scheduled_time}'."}

    now = datetime.now(timezone.utc)
    hours_until_trip = (trip_dt - now).total_seconds() / 3600

    if hours_until_trip < cutoff_hours:
        return {
            "allowed": False,
            "reason": (
                f"Changes to this {trip_type} must be made at least {cutoff_hours} hours "
                f"before departure. The trip is {hours_until_trip:.1f} hours away."
            ),
            "cutoff_hours": cutoff_hours,
            "requires_manager_approval": True,
        }

    return {
        "allowed": True,
        "reason": "Within the allowed change window.",
        "cutoff_hours": cutoff_hours,
        "requires_manager_approval": False,
    }


def apply_shift_change(
    company_id: str,
    employee_id: str,
    roster_entry_id: str,
    new_cab_id: str,
    new_time: str,
    request_id: str,
) -> dict:
    """
    Applies the confirmed shift change.
    In production: writes to DB, calls roster service.
    Here: validates seat availability and returns a confirmation dict.
    """
    try:
        cabs = _load("cabs.json")
    except FileNotFoundError:
        return {"error": "Cannot apply change — data layer unavailable."}

    # Find the target cab and check it still has space (race-condition guard)
    target_cab = next(
        (c for c in cabs if c["cab_id"] == new_cab_id and c["company_id"] == company_id),
        None,
    )
    if not target_cab:
        return {"error": "Cab no longer available. Please choose another."}
    if target_cab["seats_available"] <= 0:
        return {
            "error": "This cab just filled up while you were deciding. Please choose another slot.",
            "suggest_retry": True,
        }

    # TODO: decrement seat count in DB (atomic update) and write audit row
    return {
        "success": True,
        "confirmation": (
            f"Your {target_cab['trip_type']} has been updated to "
            f"{new_time} on cab {target_cab['cab_id']} (route: {target_cab['route']})."
        ),
        "request_id": request_id,
    }


def raise_manager_escalation(
    company_id: str,
    employee_id: str,
    request_id: str,
    reason: str,
) -> dict:
    """
    Records an escalation and notifies the transport manager (stub).
    Returns immediately — the agent then suspends and waits.
    """
    # TODO: send real notification (email, Slack, push)
    return {
        "escalated": True,
        "request_id": request_id,
        "message": (
            "Your request has been sent to your company's transport manager for approval. "
            "You'll be notified here once a decision is made. This usually takes 1–2 hours."
        ),
    }
