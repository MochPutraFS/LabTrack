from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model providing automatic created_at and updated_at timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditLog(TimeStampedModel):
    """System-wide immutable audit trail for critical actions."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=60, db_index=True)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=50)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="core_auditlog_created_at_idx"),
            models.Index(
                fields=["entity_type", "entity_id"],
                name="core_auditlog_entity_idx",
            ),
        ]

    def __str__(self) -> str:
        actor_label = self.actor.username if self.actor else "SYSTEM"
        return f"[{self.action}] {self.entity_type}#{self.entity_id} by {actor_label}"
