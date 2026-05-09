import asyncio
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import DiskSample, MetricSample
from .logs_service import cleanup_expired_log_bundles
from .system_status import get_cpu_memory_temperature, get_disk_usage, get_relevant_nic_counters


class MetricsCollector:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name='metrics-collector')

    async def stop(self) -> None:
        if not self._task:
            return
        self._stopping.set()
        await self._task

    async def _run(self) -> None:
        settings = get_settings()
        while not self._stopping.is_set():
            try:
                collect_and_store_metrics()
                cleanup_old_metrics()
                with SessionLocal() as db:
                    cleanup_expired_log_bundles(db)
            except Exception:
                # Keep background collection alive even if one cycle fails.
                pass
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=settings.metrics_interval_seconds)
            except asyncio.TimeoutError:
                continue


def collect_and_store_metrics() -> None:
    values = get_cpu_memory_temperature()
    disks = get_disk_usage()
    nic = get_relevant_nic_counters()

    with SessionLocal() as db:
        previous = db.query(MetricSample).order_by(MetricSample.timestamp.desc()).first()
        rx_mbps: float | None = None
        tx_mbps: float | None = None
        if (
            previous
            and previous.network_interface
            and previous.network_interface == nic.get('interface')
            and isinstance(previous.rx_bytes_total, int)
            and isinstance(previous.tx_bytes_total, int)
            and isinstance(nic.get('rx_bytes_total'), int)
            and isinstance(nic.get('tx_bytes_total'), int)
        ):
            delta_seconds = (values['timestamp'] - previous.timestamp).total_seconds()
            if delta_seconds > 0:
                delta_rx = max(0, nic['rx_bytes_total'] - previous.rx_bytes_total)
                delta_tx = max(0, nic['tx_bytes_total'] - previous.tx_bytes_total)
                rx_mbps = round((delta_rx * 8) / delta_seconds / 1_000_000, 3)
                tx_mbps = round((delta_tx * 8) / delta_seconds / 1_000_000, 3)

        sample = MetricSample(
            timestamp=values['timestamp'],
            cpu_percent=values['cpu_percent'],
            memory_percent=values['memory_percent'],
            temperature_c=values['temperature_c'],
            network_interface=nic.get('interface'),
            rx_bytes_total=nic.get('rx_bytes_total'),
            tx_bytes_total=nic.get('tx_bytes_total'),
            rx_mbps=rx_mbps,
            tx_mbps=tx_mbps,
        )
        db.add(sample)
        db.flush()

        for disk in disks:
            db.add(
                DiskSample(
                    metric_sample_id=sample.id,
                    mountpoint=disk['mountpoint'],
                    used_percent=disk['used_percent'],
                    total_bytes=disk['total_bytes'],
                    used_bytes=disk['used_bytes'],
                )
            )

        db.commit()


def cleanup_old_metrics() -> None:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(days=settings.metrics_retention_days)

    with SessionLocal() as db:
        old_ids = [
            row[0]
            for row in db.execute(
                select(MetricSample.id).where(MetricSample.timestamp < cutoff)
            ).all()
        ]
        if not old_ids:
            return
        db.execute(delete(DiskSample).where(DiskSample.metric_sample_id.in_(old_ids)))
        db.execute(delete(MetricSample).where(MetricSample.id.in_(old_ids)))
        db.commit()


def get_latest_status(db: Session) -> dict:
    sample = db.query(MetricSample).order_by(MetricSample.timestamp.desc()).first()
    if not sample:
        collect_and_store_metrics()
        sample = db.query(MetricSample).order_by(MetricSample.timestamp.desc()).first()

    disks = (
        db.query(DiskSample)
        .filter(DiskSample.metric_sample_id == sample.id)
        .order_by(DiskSample.mountpoint.asc())
        .all()
        if sample
        else []
    )

    return {
        'timestamp': sample.timestamp,
        'cpu_percent': sample.cpu_percent,
        'memory_percent': sample.memory_percent,
        'temperature_c': sample.temperature_c,
        'network_interface': sample.network_interface,
        'rx_mbps': sample.rx_mbps,
        'tx_mbps': sample.tx_mbps,
        'disks': [
            {
                'mountpoint': d.mountpoint,
                'used_percent': d.used_percent,
                'total_bytes': d.total_bytes,
                'used_bytes': d.used_bytes,
            }
            for d in disks
        ],
    }


def get_history(db: Session, days: int = 7) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    samples = (
        db.query(MetricSample)
        .filter(MetricSample.timestamp >= since)
        .order_by(MetricSample.timestamp.asc())
        .all()
    )

    return [
        {
            'timestamp': s.timestamp,
            'cpu_percent': s.cpu_percent,
            'memory_percent': s.memory_percent,
            'temperature_c': s.temperature_c,
            'network_interface': s.network_interface,
            'rx_mbps': s.rx_mbps,
            'tx_mbps': s.tx_mbps,
        }
        for s in samples
    ]
