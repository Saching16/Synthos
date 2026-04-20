"""HTTP route modules (routers are included from ``app.main``)."""

from app.routes import documents as documents
from app.routes import upload as upload

__all__ = ["documents", "upload"]
