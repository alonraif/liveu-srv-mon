import hashlib
import secrets
from datetime import datetime, timedelta

from passlib.context import CryptContext

from .config import get_settings

pwd_context = CryptContext(schemes=['argon2'], deprecated='auto')


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def session_expiry() -> datetime:
    settings = get_settings()
    return datetime.utcnow() + timedelta(seconds=settings.session_ttl_seconds)
