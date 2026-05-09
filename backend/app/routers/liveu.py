from fastapi import APIRouter, Depends

from ..deps import require_admin
from ..schemas import IdentityResponse
from ..services.liveu_config import get_liveu_config, get_liveu_identity

router = APIRouter(prefix='/api/liveu', tags=['liveu'])


@router.get('/identity', response_model=IdentityResponse)
def identity(_ctx=Depends(require_admin)):
    return IdentityResponse(**get_liveu_identity())


@router.get('/config')
def config(_ctx=Depends(require_admin)):
    return get_liveu_config()
