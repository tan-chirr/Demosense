import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from demosense.models.audit import AuditLog


async def log_action(
    session: AsyncSession,
    *,
    actor_person_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_person_id=actor_person_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
    )
    session.add(entry)
    await session.flush()
    return entry
