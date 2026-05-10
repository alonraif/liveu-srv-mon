from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import allow_user_with_password_change, get_client_ip, validate_csrf
from ..models import Session as UserSession
from ..models import User
from ..schemas import ChangePasswordRequest, LoginRequest, LoginResponse
from ..security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    session_expiry,
    verify_password,
)
from ..services.audit import write_audit
from ..services.rate_limiter import LoginRateLimiter

router = APIRouter(prefix='/api/auth', tags=['auth'])
login_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300)


def _set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=True,
        samesite='strict',
        path='/',
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite='strict',
        path='/',
    )


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path='/')
    response.delete_cookie(settings.csrf_cookie_name, path='/')


@router.post('/login', response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    client_ip = get_client_ip(request)
    key = f'{client_ip}:{payload.username}'
    if login_rate_limiter.is_limited(key):
        write_audit(
            db,
            username=payload.username,
            action='login_blocked_rate_limit',
            details='Login blocked due to rate limiting',
            remote_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many login attempts')

    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        login_rate_limiter.register_attempt(key)
        write_audit(
            db,
            username=payload.username,
            action='login_failed',
            details='Invalid username or password',
            remote_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid username or password')

    login_rate_limiter.reset(key)
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(session_token),
        csrf_token=csrf_token,
        expires_at=session_expiry(),
    )
    db.add(session)
    db.commit()

    _set_auth_cookies(response, session_token=session_token, csrf_token=csrf_token)

    write_audit(
        db,
        username=user.username,
        action='login_success',
        details='Successful login',
        remote_ip=client_ip,
    )

    return LoginResponse(username=user.username, role=user.role, must_change_password=user.must_change_password)


@router.post('/change-password')
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    _csrf: None = Depends(validate_csrf),
    ctx=Depends(allow_user_with_password_change),
    db: Session = Depends(get_db),
):
    user = ctx.user
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Current password is incorrect')

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.updated_at = datetime.utcnow()
    db.add(user)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.commit()

    _clear_auth_cookies(response)

    write_audit(
        db,
        username=user.username,
        action='password_changed',
        details='Admin changed password and all sessions were revoked',
        remote_ip=get_client_ip(request),
    )

    return {'detail': 'Password changed successfully. Please log in again.'}


@router.post('/logout')
def logout(
    request: Request,
    response: Response,
    ctx=Depends(allow_user_with_password_change),
    _csrf: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    db.delete(ctx.session)
    db.commit()
    _clear_auth_cookies(response)

    write_audit(
        db,
        username=ctx.user.username,
        action='logout',
        details='User logged out',
        remote_ip=get_client_ip(request),
    )

    return {'detail': 'Logged out'}


@router.get('/me')
def me(ctx=Depends(allow_user_with_password_change)):
    return {'username': ctx.user.username, 'role': ctx.user.role, 'must_change_password': ctx.user.must_change_password}
