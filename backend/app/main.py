from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import engine

settings = get_settings()

app = FastAPI(
    title="TradeFlow AI API",
    version="0.1.0",
    description="Cross-border trade operations: invoices, payments, reconciliation, document intelligence.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    """Turn business-rule failures into structured JSON errors: {"detail": "..."}."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/health", tags=["system"])
@app.get("/api/v1/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness plus database connectivity check."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
