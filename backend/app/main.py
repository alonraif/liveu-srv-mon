import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import Base, SessionLocal, engine, ensure_schema_migrations
from .routers import admin, audit, auth, liveu, logs, network, status as status_router
from .services.auth_service import apply_admin_password_reset_if_requested, cleanup_expired_sessions, ensure_admin_user
from .services.logs_service import cleanup_expired_log_bundles
from .services.metrics_service import MetricsCollector, collect_and_store_metrics

logger = logging.getLogger('liveu-monitor')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
metrics_collector = MetricsCollector()
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations()

    with SessionLocal() as db:
        ensure_admin_user(db)
        cleanup_expired_sessions(db)
        cleanup_expired_log_bundles(db)
        reset_applied = apply_admin_password_reset_if_requested(db)
        if reset_applied:
            logger.warning('RESET_ADMIN_PASSWORD was applied. Remove it from runtime configuration after first startup.')

    collect_and_store_metrics()
    await metrics_collector.start()
    logger.info('Application started. Data dir: %s', settings.data_dir)
    try:
        yield
    finally:
        await metrics_collector.stop()
        logger.info('Application stopped')


app = FastAPI(
    title='LiveU Server Monitor',
    version='0.1.0',
    lifespan=lifespan,
    docs_url='/docs' if settings.enable_api_docs else None,
    redoc_url='/redoc' if settings.enable_api_docs else None,
    openapi_url='/openapi.json' if settings.enable_api_docs else None,
)


@app.middleware('http')
async def set_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self';"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logger.exception('Unhandled exception: %s', exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={'detail': 'Internal server error'},
    )


app.include_router(auth.router)
app.include_router(status_router.router)
app.include_router(network.router)
app.include_router(liveu.router)
app.include_router(logs.router)
app.include_router(admin.router)
app.include_router(audit.router)

static_dir = Path(__file__).resolve().parent / 'static'
assets_dir = static_dir / 'assets'
if assets_dir.exists():
    app.mount('/assets', StaticFiles(directory=assets_dir), name='assets')


@app.get('/healthz')
def health_check():
    return {'status': 'ok'}


@app.get('/favicon.png')
def serve_favicon():
    favicon_path = static_dir / 'favicon.png'
    if not favicon_path.exists():
        raise HTTPException(status_code=404, detail='Favicon not found')
    return FileResponse(favicon_path, media_type='image/png')


@app.get('/{full_path:path}')
def serve_spa(full_path: str):
    if full_path.startswith('api/'):
        raise HTTPException(status_code=404, detail='Not found')
    index_path = static_dir / 'index.html'
    if not index_path.exists():
        return JSONResponse(
            status_code=503,
            content={'detail': 'Frontend build is missing. Build frontend assets first.'},
        )
    return FileResponse(index_path)
