from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Session as UserSession
from ..models import User
from ..security import hash_password
from .audit import write_audit


def ensure_default_users(db: Session) -> None:
    settings = get_settings()
    admin = db.query(User).filter(User.username == settings.default_admin_username).first()
    monitor = db.query(User).filter(User.username == settings.default_monitor_username).first()
    if admin and monitor:
        return

    initial_admin = (settings.initial_admin_password or '').strip()
    initial_monitor = (settings.initial_monitor_password or '').strip()
    if len(initial_admin) < 12 or len(initial_monitor) < 12:
        raise RuntimeError(
            'Initial user passwords are required on first startup. '
            'Set INITIAL_ADMIN_PASSWORD and INITIAL_MONITOR_PASSWORD (minimum 12 characters each).'
        )

    if not admin:
        db.add(
            User(
                username=settings.default_admin_username,
                password_hash=hash_password(initial_admin),
                role='administrator',
                must_change_password=True,
            )
        )
    if not monitor:
        db.add(
            User(
                username=settings.default_monitor_username,
                password_hash=hash_password(initial_monitor),
                role='monitor',
                must_change_password=True,
            )
        )
    db.commit()


def apply_admin_password_reset_if_requested(db: Session) -> bool:
    settings = get_settings()
    reset = settings.reset_admin_password
    if not reset:
        return False

    admin = db.query(User).filter(User.username == settings.default_admin_username).first()
    if not admin:
        admin = User(
            username=settings.default_admin_username,
            password_hash=hash_password(reset),
            role='administrator',
            must_change_password=True,
        )
        db.add(admin)
    else:
        admin.password_hash = hash_password(reset)
        admin.must_change_password = True
        admin.updated_at = datetime.utcnow()
        db.add(admin)

    db.query(UserSession).filter(UserSession.user_id == admin.id).delete()
    db.commit()

    write_audit(
        db,
        username=settings.default_admin_username,
        action='admin_password_reset',
        details='Admin password reset from RESET_ADMIN_PASSWORD env var at startup. Remove this env var after use.',
        remote_ip='local-startup',
    )
    return True


def cleanup_expired_sessions(db: Session) -> None:
    settings = get_settings()
    now = datetime.utcnow()
    idle_cutoff = now - timedelta(seconds=settings.session_idle_timeout_seconds)
    db.query(UserSession).filter(
        (UserSession.expires_at < now) | (UserSession.last_seen_at < idle_cutoff)
    ).delete()
    db.commit()
