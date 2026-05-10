from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    f'sqlite:///{settings.db_path}',
    connect_args={'check_same_thread': False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def ensure_schema_migrations() -> None:
    # Lightweight SQLite-safe migration for newly added metric fields.
    expected_columns: dict[str, str] = {
        'network_interface': 'TEXT',
        'rx_bytes_total': 'INTEGER',
        'tx_bytes_total': 'INTEGER',
        'rx_mbps': 'REAL',
        'tx_mbps': 'REAL',
    }

    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='metric_samples'")
        ).fetchone()
        if not table_exists:
            return

        rows = conn.execute(text('PRAGMA table_info(metric_samples)')).fetchall()
        existing = {row[1] for row in rows}
        for column_name, column_type in expected_columns.items():
            if column_name in existing:
                continue
            conn.execute(text(f'ALTER TABLE metric_samples ADD COLUMN {column_name} {column_type}'))

        session_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        ).fetchone()
        if session_exists:
            session_rows = conn.execute(text('PRAGMA table_info(sessions)')).fetchall()
            session_cols = {row[1] for row in session_rows}
            if 'last_reauth_at' not in session_cols:
                conn.execute(text('ALTER TABLE sessions ADD COLUMN last_reauth_at DATETIME'))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
