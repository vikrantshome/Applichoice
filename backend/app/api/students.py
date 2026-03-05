"""
Student API endpoints — onboarding, profile management, and applications.

Authentication: Phone-based JWT tokens issued after OTP verification.
"""
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, status
from typing import Annotated, List
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_database
from app.core.security import create_access_token
from app.api.deps_student import get_current_student
from app.models.student import (
    StudentOnboardRequest, StudentUpdateRequest, StudentResponse,
)
from app.models.application import (
    ApplicationCreateRequest, ApplicationResponse,
)

router = APIRouter()


def _generate_order_id() -> str:
    """Generate a unique order ID like NAV-2026-XXXX."""
    short_id = uuid.uuid4().hex[:6].upper()
    year = datetime.now().year
    return f"NAV-{year}-{short_id}"


# ─────────────────────────────────────────────
#  Onboarding (public — called after OTP verify)
# ─────────────────────────────────────────────
@router.post("/onboard")
async def onboard_student(request: StudentOnboardRequest):
    """
    Create or update a student profile and issue a JWT.

    Called right after OTP verification. If the phone already exists,
    the profile is updated (upsert). Returns a JWT for subsequent requests.
    """
    db = get_database()
    now = datetime.now(timezone.utc)

    # Check if OTP is globally completely disabled by admins
    config = await db.system_settings.find_one({"_id": "global_config"})
    is_otp_enabled = config.get("is_otp_enabled", True) if config else True

    # Verify that this phone was recently OTP-verified (if enabled)
    if is_otp_enabled:
        otp_session = await db.otp_sessions.find_one(
            {"phone": request.phone, "verified": True},
            sort=[("created_at", -1)],
        )
        if not otp_session:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Phone number not verified. Please complete OTP verification first.",
            )

    # Build the student document
    student_data = request.model_dump(exclude_none=True)
    student_data["phoneVerified"] = True
    student_data["updatedAt"] = now

    # Upsert: create if new, update if exists
    result = await db.students.update_one(
        {"phone": request.phone},
        {
            "$set": student_data,
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )

    # Fetch the full student record
    student = await db.students.find_one({"phone": request.phone})

    # Issue JWT with phone + role
    token = create_access_token(
        data={"sub": request.phone, "role": "student"},
        expires_delta=timedelta(days=30),
    )

    return {
        "success": True,
        "message": "Student profile saved",
        "token": token,
        "student": _serialize_student(student),
    }

# ─────────────────────────────────────────────
#  Dev Login (No OTP)
# ─────────────────────────────────────────────
class DevLoginRequest(BaseModel):
    phone: str

@router.post("/dev-login")
async def dev_login(request: DevLoginRequest):
    """Bypass OTP for testing. Just provide phone number to get JWT."""
    db = get_database()
    student = await db.students.find_one({"phone": request.phone})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found / not onboarded")
    
    # Generate JWT directly
    token = create_access_token(
        data={"sub": request.phone, "role": "student"},
        expires_delta=timedelta(days=30),
    )
    return {
        "success": True,
        "message": "Dev login successful",
        "token": token,
        "student": _serialize_student(student),
    }

# ─────────────────────────────────────────────
#  Profile (authenticated)
# ─────────────────────────────────────────────
@router.get("/me")
async def get_my_profile(phone: str = Depends(get_current_student)):
    """Get the current student's profile."""
    db = get_database()
    student = await db.students.find_one({"phone": phone})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return _serialize_student(student)


@router.patch("/me")
async def update_my_profile(
    request: StudentUpdateRequest,
    phone: str = Depends(get_current_student),
):
    """Update the current student's profile (partial update)."""
    db = get_database()
    update_data = request.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_data["updatedAt"] = datetime.now(timezone.utc)

    await db.students.update_one(
        {"phone": phone},
        {"$set": update_data},
    )
    student = await db.students.find_one({"phone": phone})
    return _serialize_student(student)


# ─────────────────────────────────────────────
#  Applications (authenticated)
# ─────────────────────────────────────────────
@router.post("/applications")
async def create_application(
    request: ApplicationCreateRequest,
    phone: str = Depends(get_current_student),
):
    """Create a new application (checkout)."""
    db = get_database()
    now = datetime.now(timezone.utc)

    if not request.colleges or len(request.colleges) == 0:
        raise HTTPException(status_code=400, detail="At least one college is required")

    app_doc = {
        "studentPhone": phone,
        "orderId": _generate_order_id(),
        "colleges": [c.model_dump() for c in request.colleges],
        "pricing": request.pricing.model_dump(),
        "paymentStatus": "paid",  # TODO: Revert to "pending" once Razorpay is integrated
        "paymentId": None,
        "createdAt": now,
        "updatedAt": now,
    }

    result = await db.applications.insert_one(app_doc)
    app_doc["_id"] = str(result.inserted_id)

    return {
        "success": True,
        "message": "Application created",
        "application": _serialize_application(app_doc),
    }


@router.get("/applications")
async def get_my_applications(phone: str = Depends(get_current_student)):
    """Get all applications for the current student."""
    db = get_database()
    cursor = db.applications.find(
        {"studentPhone": phone}
    ).sort("createdAt", -1)

    applications = []
    async for doc in cursor:
        applications.append(_serialize_application(doc))

    return {"applications": applications}


@router.get("/applications/{order_id}")
async def get_application(
    order_id: str,
    phone: str = Depends(get_current_student),
):
    """Get a single application by order ID."""
    db = get_database()
    app_doc = await db.applications.find_one({
        "orderId": order_id,
        "studentPhone": phone,
    })
    if not app_doc:
        raise HTTPException(status_code=404, detail="Application not found")
    return _serialize_application(app_doc)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def _serialize_student(doc: dict) -> dict:
    """Convert a MongoDB student document to a JSON-safe dict."""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    # Convert datetime objects
    for key in ("createdAt", "updatedAt"):
        if key in doc and doc[key]:
            doc[key] = doc[key].isoformat()
    return doc


def _serialize_application(doc: dict) -> dict:
    """Convert a MongoDB application document to a JSON-safe dict."""
    if doc is None:
        return None
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    for key in ("createdAt", "updatedAt"):
        if key in doc and doc[key]:
            doc[key] = doc[key].isoformat()
    return doc
