from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from bist_bot.db.database import ConfigRecord, DatabaseManager


class ConfigRepository:
    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    def save_config(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self.manager.session_scope() as session:
            record = session.get(ConfigRecord, key)
            if record is None:
                session.add(ConfigRecord(key=key, value=payload, updated_at=self.manager.now_iso()))
            else:
                record.value = payload
                record.updated_at = self.manager.now_iso()

    def get_config(self, key: str, default: Any = None) -> Any:
        with self.manager.session_scope() as session:
            record = session.scalar(select(ConfigRecord).where(ConfigRecord.key == key).limit(1))
        if record is None:
            return default
        try:
            return json.loads(record.value)
        except json.JSONDecodeError:
            return default

    def delete_config(self, key: str) -> None:
        with self.manager.session_scope() as session:
            record = session.get(ConfigRecord, key)
            if record is not None:
                session.delete(record)
