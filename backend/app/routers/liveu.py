from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_monitor_or_admin
from ..schemas import IdentityResponse, LiveuConfigResponse
from ..services.liveu_config import get_liveu_config, get_liveu_identity

router = APIRouter(prefix='/api/liveu', tags=['liveu'])


@router.get('/identity', response_model=IdentityResponse)
def identity(_ctx=Depends(require_monitor_or_admin)):
    try:
        return IdentityResponse(**get_liveu_identity())
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get('/config', response_model=LiveuConfigResponse)
def config(_ctx=Depends(require_monitor_or_admin)):
    try:
        return LiveuConfigResponse(**get_liveu_config())
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
