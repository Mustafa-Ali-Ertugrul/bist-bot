import sys
from pathlib import Path

# Add src to path
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bist_bot.config import settings
from bist_bot.db.database import DatabaseManager
from bist_bot.auth.passwords import verify_and_rehash_password
from sqlalchemy import text


def check_admin():
    import os

    if os.environ.get("BIST_BOT_DEBUG", "").lower() not in {"1", "true"}:
        print("BIST_BOT_DEBUG=1 required to run this script")
        return
    db_manager = DatabaseManager()
    print(f"Checking user: {settings.ADMIN_BOOTSTRAP_EMAIL}")

    with db_manager.engine.connect() as conn:
        result = conn.execute(
            text("SELECT email, password_hash FROM users WHERE email = :email"),
            {"email": settings.ADMIN_BOOTSTRAP_EMAIL},
        ).fetchone()

        if result:
            email, pwd_hash = result
            print(f"Found user: {email}")
            print(f"Hash in DB: {pwd_hash}")

            # Verify against admin123
            is_valid, _ = verify_and_rehash_password("admin123", pwd_hash)
            print(f"Password 'admin123' valid: {is_valid}")

            # Verify against the one in .env
            env_hash = settings.ADMIN_BOOTSTRAP_PASSWORD_HASH
            print(f"Hash in .env: {env_hash}")
            is_env_valid, _ = verify_and_rehash_password("admin123", env_hash)
            print(f"Password 'admin123' valid against .env hash: {is_env_valid}")
        else:
            print("Admin user NOT FOUND in database!")


if __name__ == "__main__":
    check_admin()
