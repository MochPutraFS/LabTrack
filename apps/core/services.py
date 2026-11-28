"""Core service helpers, including centralized audit logging."""

from typing import Any

from apps.core.models import AuditLog


def log_audit(
    actor,
    action: str,
    entity_type: str,
    entity_id: Any,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Create a structured AuditLog record for a critical domain event."""
    resolved_actor = actor if (actor is not None and getattr(actor, "is_authenticated", False)) else None
    return AuditLog.objects.create(
        actor=resolved_actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        metadata=metadata or {},
    )
