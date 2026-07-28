import hmac
import time
from collections import OrderedDict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW_SECONDS = 300
LOGIN_ATTEMPT_CACHE_SIZE = 256
_login_attempts: OrderedDict[str, deque[float]] = OrderedDict()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


def require_authenticated(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    settings = get_settings()
    token = request.cookies.get(settings.auth_cookie_name)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        subject = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    if subject != settings.admin_username:
        raise HTTPException(status_code=401, detail="Invalid session subject")
    return subject


def authenticate(username: str, password: str) -> str:
    settings = get_settings()
    password_hash = settings.admin_password_hash
    valid_username = bool(
        settings.admin_username and hmac.compare_digest(username, settings.admin_username)
    )
    valid_password = bool(password_hash and verify_password(password, password_hash))
    if not valid_username or not valid_password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return create_access_token(settings.admin_username)


def _client_address(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _recent_attempts(address: str, now: float) -> deque[float]:
    attempts = _login_attempts.get(address, deque())
    while attempts and now - attempts[0] >= LOGIN_ATTEMPT_WINDOW_SECONDS:
        attempts.popleft()
    if attempts:
        _login_attempts[address] = attempts
        _login_attempts.move_to_end(address)
    else:
        _login_attempts.pop(address, None)
    return attempts


def _reject_if_rate_limited(request: Request) -> None:
    if len(_recent_attempts(_client_address(request), time.monotonic())) >= LOGIN_ATTEMPT_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login attempts")


def _record_failed_attempt(request: Request) -> None:
    address = _client_address(request)
    now = time.monotonic()
    attempts = _recent_attempts(address, now)
    if address not in _login_attempts:
        while len(_login_attempts) >= LOGIN_ATTEMPT_CACHE_SIZE:
            _login_attempts.popitem(last=False)
        _login_attempts[address] = attempts
    attempts.append(now)
    _login_attempts.move_to_end(address)


def _clear_failed_attempts(request: Request) -> None:
    _login_attempts.pop(_client_address(request), None)


def reset_login_attempt_limiter() -> None:
    """Reset the process-local limiter; production replicas do not share this state."""
    _login_attempts.clear()


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    _reject_if_rate_limited(request)
    try:
        token = authenticate(payload.username, payload.password)
    except HTTPException:
        _record_failed_attempt(request)
        raise
    _clear_failed_attempts(request)
    set_session_cookie(response, token)
    return {"accessToken": token, "username": payload.username}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/session")
def session(username: str = Depends(require_authenticated)) -> dict:
    return {"authenticated": True, "username": username}
