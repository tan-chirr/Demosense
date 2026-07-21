"""Seed the position_type controlled vocabulary. Idempotent - safe to re-run."""

import asyncio

from sqlalchemy import select

from demosense.db import SessionLocal
from demosense.models.person import PositionType
from demosense.winloop import use_selector_event_loop_on_windows

POSITIONS = [
    ("president", "President", True, 10),
    ("vice_president", "Vice President", True, 20),
    ("secretary", "Secretary", True, 30),
    ("treasurer", "Treasurer", True, 40),
    ("member_at_large", "Member at Large", True, 50),
    ("member", "Member", False, 100),
]


async def run() -> None:
    async with SessionLocal() as session:
        existing = {p.code for p in await session.scalars(select(PositionType))}
        added = 0
        for code, label, is_officer, sort_order in POSITIONS:
            if code in existing:
                continue
            session.add(
                PositionType(code=code, label=label, is_officer=is_officer, sort_order=sort_order)
            )
            added += 1
        await session.commit()
        print(f"added {added} position types ({len(POSITIONS) - added} already existed)")


if __name__ == "__main__":
    use_selector_event_loop_on_windows()
    asyncio.run(run())
