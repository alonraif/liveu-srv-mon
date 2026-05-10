from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_ip, require_monitor_or_admin, validate_csrf
from ..schemas import GatherLogsResponse
from ..services.audit import write_audit
from ..services.logs_service import gather_logs_archive, get_bundle_file_path

router = APIRouter(prefix='/api/logs', tags=['logs'])


@router.post('/gather', response_model=GatherLogsResponse)
def gather_logs(
    request: Request,
    _csrf: None = Depends(validate_csrf),
    ctx=Depends(require_monitor_or_admin),
    db: Session = Depends(get_db),
):
    try:
        result = gather_logs_archive(db, username=ctx.user.username)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    write_audit(
        db,
        username=ctx.user.username,
        action='logs_gather',
        details=f"Created logs bundle {result['filename']}",
        remote_ip=get_client_ip(request),
    )
    return GatherLogsResponse(**result)


@router.get('/download/{bundle_id}')
def download_logs(bundle_id: str, request: Request, ctx=Depends(require_monitor_or_admin), db: Session = Depends(get_db)):
    try:
        path, filename = get_bundle_file_path(db, bundle_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    write_audit(
        db,
        username=ctx.user.username,
        action='logs_download',
        details=f'Downloaded logs bundle {filename}',
        remote_ip=get_client_ip(request),
    )

    return FileResponse(path=path, filename=filename, media_type='application/gzip')
