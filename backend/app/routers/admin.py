from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_ip, require_admin, validate_csrf
from ..config import get_settings
from ..schemas import AdminPasswordConfirm, RebootRequest, SpeedtestRequest, SpeedtestResultResponse
from ..security import verify_password
from ..services.admin_actions import AdminActionError, reboot_server, restart_liveu_service, run_speedtest
from ..services.audit import write_audit
from ..services.rate_limiter import SlidingWindowRateLimiter

router = APIRouter(prefix='/api/admin', tags=['admin'])
admin_action_limiter = SlidingWindowRateLimiter(max_attempts=20, window_seconds=60)
critical_action_limiter = SlidingWindowRateLimiter(max_attempts=5, window_seconds=300)


@router.post('/restart-liveu')
def restart_liveu(
    payload: AdminPasswordConfirm,
    request: Request,
    _csrf: None = Depends(validate_csrf),
    ctx=Depends(require_admin),
    db: Session = Depends(get_db),
):
    client_ip = get_client_ip(request)
    if critical_action_limiter.is_limited(f'restart-liveu:{client_ip}:{ctx.user.username}'):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many restart attempts')

    if not verify_password(payload.password, ctx.user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Password confirmation failed')
    critical_action_limiter.register_attempt(f'restart-liveu:{client_ip}:{ctx.user.username}')
    ctx.session.last_reauth_at = datetime.utcnow()
    db.add(ctx.session)
    db.commit()

    try:
        output = restart_liveu_service()
    except AdminActionError as exc:
        write_audit(
            db,
            username=ctx.user.username,
            action='restart_liveu_failed',
            details=str(exc),
            remote_ip=client_ip,
        )
        raise HTTPException(status_code=500, detail=f'Failed to restart LiveU service: {exc}') from exc

    write_audit(
        db,
        username=ctx.user.username,
        action='restart_liveu',
        details=f'LiveU service restart triggered: {output}',
        remote_ip=client_ip,
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
    client_ip = get_client_ip(request)
    if critical_action_limiter.is_limited(f'reboot:{client_ip}:{ctx.user.username}'):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many reboot attempts')

    if payload.confirmation != 'REBOOT':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation text must be exactly 'REBOOT'")
    if not verify_password(payload.password, ctx.user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Password confirmation failed')
    critical_action_limiter.register_attempt(f'reboot:{client_ip}:{ctx.user.username}')
    ctx.session.last_reauth_at = datetime.utcnow()
    db.add(ctx.session)
    db.commit()

    try:
        output = reboot_server()
    except AdminActionError as exc:
        write_audit(
            db,
            username=ctx.user.username,
            action='reboot_failed',
            details=str(exc),
            remote_ip=client_ip,
        )
        raise HTTPException(status_code=500, detail=f'Failed to reboot server: {exc}') from exc

    write_audit(
        db,
        username=ctx.user.username,
        action='reboot_server',
        details=f'Server reboot triggered: {output}',
        remote_ip=client_ip,
    )
    return {'detail': 'Server reboot command executed'}


@router.post('/speedtest', response_model=SpeedtestResultResponse)
def speedtest(
    payload: SpeedtestRequest,
    request: Request,
    _csrf: None = Depends(validate_csrf),
    ctx=Depends(require_admin),
    db: Session = Depends(get_db),
):
    client_ip = get_client_ip(request)
    if admin_action_limiter.is_limited(f'speedtest:{client_ip}:{ctx.user.username}'):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many speedtest requests')
    admin_action_limiter.register_attempt(f'speedtest:{client_ip}:{ctx.user.username}')

    if payload.password:
        if not verify_password(payload.password, ctx.user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Password confirmation failed')
        ctx.session.last_reauth_at = datetime.utcnow()
        db.add(ctx.session)
        db.commit()
    else:
        settings = get_settings()
        if not ctx.session.last_reauth_at:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Recent password re-authentication required')
        if (datetime.utcnow() - ctx.session.last_reauth_at).total_seconds() > settings.admin_reauth_window_seconds:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Re-authentication window expired')

    try:
        result = run_speedtest()
    except AdminActionError as exc:
        write_audit(
            db,
            username=ctx.user.username,
            action='speedtest_failed',
            details=str(exc),
            remote_ip=client_ip,
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
        remote_ip=client_ip,
    )
    return SpeedtestResultResponse(**result)
