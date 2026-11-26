"""Dev-only endpoint to mint JWTs without a real IdP."""
from fastapi import APIRouter
from app.models.schemas import TokenRequest, TokenResponse
from app.core.security import create_token

router = APIRouter()


@router.post("/token", response_model=TokenResponse)
def get_token(body: TokenRequest):
    """
    Mint a JWT for testing.
    In production, tokens come from your IdP (Auth0, Okta, etc.).
    Never call this from production without at least a shared secret guard.
    """
    token = create_token(body.company_id, body.employee_id, body.role)
    return TokenResponse(access_token=token)
