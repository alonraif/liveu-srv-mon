from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_ip, require_admin, validate_csrf
from ..schemas import AdminPasswordConfirm, RebootRequest, SpeedtestResultResponse
from ..security import verify_password
from ..services.admin_actions import AdminActionError, reboot_server, restart_liveu_service, run_speedtest
from ..services.audit import write_audit

router = APIRouter(prefix='/api/admin', tags=['admin'])


@router.post('/restart-liveu')
def restart_liveu(
    payload: AdminPasswordConfirm,
    request: Request,
    _csrf: None = Depends(validate_csrf),
    ctx=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.password, ctx.user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Password confirmation failed')

    try:
        output = restart_liveu_service()
    except AdminActionError as exc:
        write_audit(
            db,
            username=ctx.user.username,
            action='restart_liveu_failed',
            details=str(exc),
            remote_ip=get_client_ip(request),
        )
        raise HTTPException(status_code=500, detail=f'Failed to restart LiveU service: {exc}') from exc

    write_audit(
        db,
        username=ctx.user.username,
        action='restart_liveu',
        details=f'LiveU service restart triggered: {output}',
        remote_ip=get_client_ip(request),
    )
    return {'detail': f'LiveU service restart result: {output}', 'output': output}


@router.post('/reboot')
def reboot(
    payload: RebootRequest,
    request: Request,
    _csrf: None = Depends(validate_csrf),
    ctx=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.confirmation != 'REBOOT':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation text must be exactly 'REBOOT'")
    if not verify_password(payload.password, ctx.user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Password confirmation failed')

    try:
        output = reboot_server()
    except AdminActionError as exc:
        write_audit(
            db,
            username=ctx.user.username,
            action='reboot_failed',
            details=str(exc),
            remote_ip=get_client_ip(request),
        )
        raise HTTPException(status_code=500, detail=f'Failed to reboot server: {exc}') from exc

    write_audit(
        db,
        username=ctx.user.username,
        action='reboot_server',
        details=f'Server reboot triggered: {output}',
        remote_ip=get_client_ip(request),
    )
    return {'detail': 'Server reboot command executed'}


@router.post('/speedtest', response_model=SpeedtestResultResponse)
def speedtest(
    request: Request,
    _csrf: None = Depends(validate_csrf),
    ctx=Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        result = run_speedtest()
    except AdminActionError as exc:
        write_audit(
            db,
            username=ctx.user.username,
            action='speedtest_failed',
            details=str(exc),
            remote_ip=get_client_ip(request),
        )
        raise HTTPException(status_code=500, detail=f'Failed to run speedtest: {exc}') from exc

    write_audit(
        db,
        username=ctx.user.username,
        action='speedtest_run',
        details=(
            f"Speedtest result: download={result['download_mbps']} Mbps, "
            f"upload={result['upload_mbps']} Mbps, ping={result['ping_ms']} ms, "
            f"server={result['server_name']} ({result['server_sponsor']})"
        ),
        remote_ip=get_client_ip(request),
    )
    return SpeedtestResultResponse(**result)
