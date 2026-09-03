"""Create all DB tables in the configured backend (PostgreSQL) and verify."""

import os

from sqlalchemy import text

from bist_bot.db.database import Base, DatabaseManager


def main() -> None:
    print("DATABASE_URL =", os.environ.get("DATABASE_URL"))
    print("DB_PATH      =", os.environ.get("DB_PATH"))
    mgr = DatabaseManager()
    print("engine url   =", mgr.engine.url)
    Base.metadata.create_all(mgr.engine)
    print("create_all done")
    with mgr.engine.connect() as conn:
        if mgr.engine.dialect.name == "postgresql":
            rows = conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            ).all()
        else:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            ).all()
    print("tables:", [r[0] for r in rows])


if __name__ == "__main__":
    main()
