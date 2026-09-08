"""Server-side credential provisioning. No bot token is required."""
import argparse
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from backend.auth import ROLES, token_hash
from database.crm_models import ApiCredential


async def run(args):
    from database.session import async_session_maker, engine
    try:
        async with async_session_maker() as session:
            if args.command == "revoke":
                result = await session.execute(update(ApiCredential).where(
                    ApiCredential.id == args.id,
                ).values(revoked=True))
                await session.commit()
                print(f"Revoked: {result.rowcount}")
                return
            token = secrets.token_urlsafe(48)
            row = ApiCredential(guild_id=args.guild, user_id=args.user, name=args.name,
                                role=args.role, token_hash=token_hash(token),
                                expires_at=datetime.now(timezone.utc) + timedelta(days=args.days))
            session.add(row)
            await session.commit()
            print(f"Credential ID: {row.id}\nToken (shown once): {token}")
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("issue")
    create.add_argument("--guild", type=int, required=True)
    create.add_argument("--user", type=int, required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=sorted(ROLES), required=True)
    create.add_argument("--days", type=int, default=90)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("id")
    args = parser.parse_args()
    if args.command == "issue" and (not 1 <= args.days <= 3650 or args.guild <= 0 or args.user <= 0 or not 1 <= len(args.name) <= 100):
        parser.error("Use positive Discord IDs, a name of 1–100 characters, and --days from 1 to 3650")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
