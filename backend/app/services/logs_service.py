import tarfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import LogBundle
from .liveu_config import get_liveu_identity


def _slug_filename_component(value: str) -> str:
    cleaned = ''.join(ch if ch.isalnum() else '-' for ch in value.strip())
    collapsed = '-'.join(part for part in cleaned.split('-') if part)
    return collapsed.lower() or 'unknown'


def _get_server_license_for_filename(identity: dict) -> str:
    license_value = str(identity.get('server_license') or '').strip()
    if license_value:
        return _slug_filename_component(license_value)

    return 'unknown'


def gather_logs_archive(db: Session, username: str) -> dict:
    cleanup_expired_log_bundles(db)

    settings = get_settings()
    source_dir = settings.host_logs_dir
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f'Logs directory not found: {source_dir}')

    bundle_id = uuid.uuid4().hex
    identity = get_liveu_identity()
    server_type = _slug_filename_component(str(identity.get('server_type') or 'unknown'))
    server_license = _get_server_license_for_filename(identity)
    timestamp = datetime.utcnow().strftime('%Y-%m-%d--%H:%M:%S')
    filename = f'liveu-{server_type}-logs-{timestamp}-{server_license}.tar.gz'
    file_path = settings.log_bundle_dir / filename

    with tarfile.open(file_path, mode='w:gz') as tar:
        tar.add(source_dir, arcname='logs')

    bundle = LogBundle(
        bundle_id=bundle_id,
        filename=filename,
        file_path=str(file_path),
        created_by=username,
    )
    db.add(bundle)
    db.commit()

    return {'bundle_id': bundle_id, 'filename': filename}


def get_bundle_file_path(db: Session, bundle_id: str) -> tuple[Path, str]:
    cleanup_expired_log_bundles(db)

    bundle = db.query(LogBundle).filter(LogBundle.bundle_id == bundle_id).first()
    if not bundle:
        raise FileNotFoundError('Bundle not found')

    path = Path(bundle.file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError('Bundle file missing')

    return path, bundle.filename


def cleanup_expired_log_bundles(db: Session) -> int:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(seconds=settings.log_bundle_ttl_seconds)
    expired_bundles = db.query(LogBundle).filter(LogBundle.created_at < cutoff).all()

    deleted_count = 0
    for bundle in expired_bundles:
        file_path = Path(bundle.file_path)
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass
        db.delete(bundle)
        deleted_count += 1

    if deleted_count:
        db.commit()

    return deleted_count
