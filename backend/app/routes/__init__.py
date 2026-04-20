"""HTTP route modules (routers are included from ``app.main``)."""

from app.routes import chat
from app.routes import documents
from app.routes import upload

__all__ = ["chat", "documents", "upload"]
