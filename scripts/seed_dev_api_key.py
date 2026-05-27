"""Bootstrap a development API key. Run once after migrations."""

import asyncio
import hashlib
import uuid

from emerald.db.session import session_factory
from emerald.models.api_key import ApiKey
from emerald.models.entity import Entity


async def main():
    async with session_factory.session() as session:
        # Create dev entity
        entity = Entity(
            external_id="dev_user",
            type="user",
            name="Development User",
        )
        session.add(entity)
        await session.flush()

        # Create dev API key
        raw_key = "em_dev_test_key_001"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = ApiKey(
            entity_id=entity.id,
            key_hash=key_hash,
            key_prefix=raw_key[:8],
            permissions=["read", "write", "admin"],
            is_active=True,
        )
        session.add(api_key)
        await session.commit()

        print(f"Dev API key created: {raw_key}")
        print(f"Entity ID: {entity.id}")


if __name__ == "__main__":
    asyncio.run(main())
