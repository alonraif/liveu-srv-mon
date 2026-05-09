from sqlalchemy.orm import Session

from ..models import AuditLog


def write_audit(db: Session, username: str, action: str, details: str, remote_ip: str | None = None) -> None:
    entry = AuditLog(username=username, action=action, details=details[:4000], remote_ip=remote_ip)
    db.add(entry)
    db.commit()
