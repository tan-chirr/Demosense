"""Bootstrap the first superuser. The public /auth/register endpoint cannot
set is_superuser (by design - fastapi-users strips it from untrusted input),
so the very first one has to be created directly against the database.

Usage:
    python scripts/create_superuser.py you@example.com "First" "Last"
(prompts for a password)
"""

import argparse
import asyncio
import getpass

from fastapi_users.password import PasswordHelper
from sqlalchemy import select

from demosense.db import SessionLocal
from demosense.models.person import Person
from demosense.winloop import use_selector_event_loop_on_windows


async def run(email: str, first_name: str, last_name: str, password: str) -> None:
    async with SessionLocal() as session:
        existing = (await session.scalars(select(Person).filter_by(email=email))).one_or_none()
        if existing is not None:
            print(f"a person with email {email!r} already exists (id={existing.id})")
            return

        person = Person(
            email=email,
            first_name=first_name,
            last_name=last_name,
            hashed_password=PasswordHelper().hash(password),
            is_superuser=True,
            is_verified=True,
        )
        session.add(person)
        await session.commit()
        print(f"created superuser {email} (id={person.id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email")
    parser.add_argument("first_name")
    parser.add_argument("last_name")
    args = parser.parse_args()
    pw = getpass.getpass("Password: ")
    use_selector_event_loop_on_windows()
    asyncio.run(run(args.email, args.first_name, args.last_name, pw))
