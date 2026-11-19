from fastapi import APIRouter

from app.api.v1.endpoints import ai, audit_logs, auth, compliance, dashboard, documents, invoices, payments, reconciliation

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(invoices.router)
api_router.include_router(payments.router)
api_router.include_router(reconciliation.router)
api_router.include_router(dashboard.router)
api_router.include_router(documents.router)
api_router.include_router(ai.router)
api_router.include_router(compliance.router)
api_router.include_router(audit_logs.router)
