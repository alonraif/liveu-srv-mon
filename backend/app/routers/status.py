import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..schemas import StatusCurrentResponse, StatusHistoryResponse
from ..services.metrics_service import get_history, get_latest_status
from ..services.system_status import get_disk_usage_df, get_liveu_service_status, get_os_kernel, get_server_version

logger = logging.getLogger('liveu-monitor')

router = APIRouter(prefix='/api/status', tags=['status'])


@router.get('/current', response_model=StatusCurrentResponse)
def current_status(_ctx=Depends(require_admin), db: Session = Depends(get_db)):
    status_data = get_latest_status(db)
    status_data['disks'] = get_disk_usage_df()
    os_version, kernel_version = get_os_kernel()
    server_version = get_server_version()
    liveu_service_status = get_liveu_service_status()
    return StatusCurrentResponse(
        **status_data,
        liveu_service_status=liveu_service_status,
        os_version=os_version,
        kernel_version=kernel_version,
        server_version=server_version,
    )


@router.get('/history', response_model=StatusHistoryResponse)
def status_history(
    range_value: str = Query(default='7d', alias='range'),
    _ctx=Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        days = 7
        if range_value.endswith('d') and range_value[:-1].isdigit():
            days = max(1, min(30, int(range_value[:-1])))
        samples = get_history(db, days=days)
        return StatusHistoryResponse(samples=samples)
    except Exception as e:
        logger.error(f"Error fetching status history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch status history"
        )
