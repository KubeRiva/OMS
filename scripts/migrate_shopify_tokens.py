"""
Migrate existing plaintext Shopify access tokens to Fernet-encrypted values.

Usage:
    DATABASE_URL=postgresql+asyncpg://oms_user:oms_pass@localhost:5433/oms_db \
        python scripts/migrate_shopify_tokens.py

The script is idempotent: rows whose access_token already starts with 'gAAAAA'
(Fernet ciphertext prefix) are skipped without modification.

Requirements:
    - The DATABASE_URL env var must be set and must use the asyncpg driver
      (postgresql+asyncpg://...).
    - SECRET_KEY must be set (or available via app.config.settings) so that the
      Fernet key can be derived — the same key used by the running application.
    - Run from the d:/OMS directory so that the `app` package is on sys.path.
"""

import asyncio
import json
import os
import sys

# Make `app` importable when the script is run from the project root.
sys.path.insert(0, ".")

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

# Import after sys.path is set.
from app.services.connectors.shopify_crypto import encrypt_access_token


async def migrate() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    engine = create_async_engine(database_url, echo=False)

    total = 0
    encrypted_count = 0
    already_encrypted_count = 0
    skipped_count = 0

    async with engine.begin() as conn:
        # Fetch all Shopify connectors.
        rows = await conn.execute(
            sa.text(
                "SELECT id, config FROM connectors WHERE connector_type = 'SHOPIFY'"
            )
        )
        shopify_rows = rows.fetchall()

    print(f"Found {len(shopify_rows)} SHOPIFY connector row(s).")

    for row in shopify_rows:
        connector_id = row[0]
        config_raw = row[1]

        total += 1

        # config may be stored as a dict (if the driver deserialises JSONB) or
        # as a JSON string — handle both.
        if isinstance(config_raw, str):
            try:
                config: dict = json.loads(config_raw)
            except Exception:
                print(f"  [{connector_id}] SKIP — could not parse config JSON")
                skipped_count += 1
                continue
        elif isinstance(config_raw, dict):
            config = config_raw
        else:
            print(f"  [{connector_id}] SKIP — unexpected config type: {type(config_raw)}")
            skipped_count += 1
            continue

        access_token: str = config.get("access_token", "")

        if not access_token:
            print(f"  [{connector_id}] SKIP — no access_token in config")
            skipped_count += 1
            continue

        # Fernet ciphertexts always start with this base64-encoded prefix.
        if access_token.startswith("gAAAAA"):
            print(f"  [{connector_id}] already encrypted — skipping")
            already_encrypted_count += 1
            continue

        # Encrypt the plaintext token.
        encrypted_token = encrypt_access_token(access_token)

        # Write back using jsonb_set so we only touch the access_token key.
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE connectors "
                    "SET config = jsonb_set(config, '{access_token}', :token_json::jsonb) "
                    "WHERE id = :connector_id"
                ),
                {
                    "token_json": json.dumps(encrypted_token),
                    "connector_id": str(connector_id),
                },
            )

        print(f"  [{connector_id}] encrypted successfully")
        encrypted_count += 1

    await engine.dispose()

    print()
    print("Migration complete.")
    print(f"  Processed : {total}")
    print(f"  Encrypted : {encrypted_count}")
    print(f"  Already encrypted: {already_encrypted_count}")
    print(f"  Skipped (no token / parse error): {skipped_count}")


if __name__ == "__main__":
    asyncio.run(migrate())
