from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import AuditLog

router = APIRouter(prefix='/api/audit', tags=['audit'])


@router.get('')
def list_audit(
    limit: int = Query(default=200, ge=1, le=1000),
    _ctx=Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return {
        'entries': [
            {
                'timestamp': row.timestamp,
                'username': row.username,
                'action': row.action,
                'details': row.details,
                'remote_ip': row.remote_ip,
            }
            for row in rows
        ]
    }
