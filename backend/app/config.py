from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'LiveU Server Monitor'
    data_dir: Path = Field(default=Path('/app/data'))
    db_path: Path = Field(default=Path('/app/data/liveu_monitor.db'))
    cert_path: Path = Field(default=Path('/app/data/certs/server.crt'))
    key_path: Path = Field(default=Path('/app/data/certs/server.key'))
    log_bundle_dir: Path = Field(default=Path('/app/data/bundles'))

    session_cookie_name: str = 'liveu_session'
    csrf_cookie_name: str = 'liveu_csrf'
    session_ttl_seconds: int = 60 * 60 * 12
    session_idle_timeout_seconds: int = 60 * 10

    default_admin_username: str = 'admin'
    default_admin_temp_password: str = 'ChangeMeNow!123'
    reset_admin_password: str | None = None
    trust_x_forwarded_for: bool = False
    enable_api_docs: bool = False

    metrics_interval_seconds: int = 1
    metrics_retention_days: int = 7

    host_liveu_dir: Path = Field(default=Path('/host/etc/liveu'))
    host_logs_dir: Path = Field(default=Path('/host/logs'))
    log_bundle_ttl_seconds: int = 60 * 5
    host_os_release: Path = Field(default=Path('/host/etc/os-release'))
    host_proc_dir: Path = Field(default=Path('/host/proc'))
    host_sys_dir: Path = Field(default=Path('/host/sys'))
    host_root_dir: Path = Field(default=Path('/host-root'))
    host_public_ip_cache_file: Path = Field(default=Path('/host-root/tmp/liveu-public-ip.txt'))
    public_ip_override: str | None = None

    # Restrictable fixed admin command path
    admin_command_runner: str = '/usr/local/bin/liveu-admin-action'
    liveu_config_reader: str = '/usr/local/bin/liveu-config-read'


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.log_bundle_dir.mkdir(parents=True, exist_ok=True)
    settings.cert_path.parent.mkdir(parents=True, exist_ok=True)
    settings.key_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
