from datetime import datetime

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Session as UserSession
from .models import User
from .security import hash_token


class AuthContext:
    def __init__(self, user: User, session: UserSession):
        self.user = user
        self.session = session


def get_client_ip(request: Request) -> str:
    settings = get_settings()
    forwarded = request.headers.get('x-forwarded-for')
    if settings.trust_x_forwarded_for and forwarded:
        return forwarded.split(',')[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return 'unknown'


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    settings = get_settings()
    now = datetime.utcnow()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')

    token_hash = hash_token(token)
    session = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid session')
    if session.expires_at < now:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Session expired')
    if (now - session.last_seen_at).total_seconds() > settings.session_idle_timeout_seconds:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Session expired due to inactivity')

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid session user')

    session.last_seen_at = now
    db.add(session)
    db.commit()

    return AuthContext(user=user, session=session)


def require_admin(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.user.role != 'administrator':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin role required')
    if ctx.user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Password change required')
    return ctx


def allow_admin_with_password_change(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.user.role != 'administrator':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin role required')
    return ctx


def validate_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    settings = get_settings()
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    if not cookie_token or not x_csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Missing CSRF token')
    if cookie_token != x_csrf_token or ctx.session.csrf_token != x_csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Invalid CSRF token')
