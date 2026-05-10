from fastapi import APIRouter, Depends

from ..deps import require_monitor_or_admin
from ..schemas import NetworkResponse
from ..services.system_status import get_network_info

router = APIRouter(prefix='/api/network', tags=['network'])


@router.get('', response_model=NetworkResponse)
def network_info(_ctx=Depends(require_monitor_or_admin)):
    return NetworkResponse(**get_network_info())
