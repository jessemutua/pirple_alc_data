# core/deps.py
# Thin compatibility layer so existing imports (from core.deps import get_current_user_id)
# keep working while the single implementation lives in core.security.

from core.security import get_current_user_id

__all__ = ["get_current_user_id"]