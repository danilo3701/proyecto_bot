import asyncio
import copy
import json
import os
import tempfile
from typing import Callable


class MyWordsRepository:
    def __init__(self, data_path: str, backup_path: str):
        self._data_path = data_path
        self._backup_path = backup_path
        self._lock = asyncio.Lock()

    def _atomic_json_dump(self, path: str, data: dict) -> None:
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def _build_default(self) -> dict:
        return {"users": {}}

    def _normalize_word(self, raw_word: object) -> tuple[dict | None, bool]:
        changed = False
        if not isinstance(raw_word, dict):
            return None, True

        wid = raw_word.get("id")
        es = raw_word.get("es")
        ru = raw_word.get("ru")
        learned = raw_word.get("learned")

        if not isinstance(wid, str):
            wid = ""
            changed = True
        if not isinstance(es, str):
            es = ""
            changed = True
        if not isinstance(ru, str):
            ru = ""
            changed = True
        if not isinstance(learned, bool):
            learned = bool(learned)
            changed = True

        return {"id": wid, "es": es, "ru": ru, "learned": learned}, changed

    def _normalize(self, data: object) -> tuple[dict, bool]:
        changed = False
        if not isinstance(data, dict):
            return self._build_default(), True

        users = data.get("users")
        if not isinstance(users, dict):
            users = {}
            changed = True

        normalized_users: dict[str, dict] = {}
        for uid, user in users.items():
            uid_str = str(uid)
            if uid_str != uid:
                changed = True

            if not isinstance(user, dict):
                normalized_users[uid_str] = {"settings": {"session_words": 5}, "categories": {}}
                changed = True
                continue

            settings = user.get("settings")
            if not isinstance(settings, dict):
                settings = {}
                changed = True
            session_words = settings.get("session_words", 5)
            try:
                session_words = int(session_words)
            except Exception:
                session_words = 5
                changed = True
            session_words = max(1, min(session_words, 30))
            n_settings = {"session_words": session_words}

            categories = user.get("categories")
            if not isinstance(categories, dict):
                categories = {}
                changed = True

            n_categories: dict[str, list[dict]] = {}
            for cat_name, words in categories.items():
                cat_name_str = str(cat_name)
                if cat_name_str != cat_name:
                    changed = True

                if not isinstance(words, list):
                    n_categories[cat_name_str] = []
                    changed = True
                    continue

                n_words = []
                for w in words:
                    normalized_word, word_changed = self._normalize_word(w)
                    if normalized_word is None:
                        changed = True
                        continue
                    changed = changed or word_changed
                    n_words.append(normalized_word)

                n_categories[cat_name_str] = n_words

            normalized_users[uid_str] = {
                "settings": n_settings,
                "categories": n_categories,
            }

        return {"users": normalized_users}, changed

    def _read_raw(self) -> dict:
        if not os.path.exists(self._data_path):
            if os.path.exists(self._backup_path):
                try:
                    with open(self._backup_path, "r", encoding="utf-8") as f:
                        backup_data = json.load(f)
                    data, _ = self._normalize(backup_data)
                    self._atomic_json_dump(self._data_path, data)
                    return data
                except Exception:
                    pass
            data = self._build_default()
            self._atomic_json_dump(self._data_path, data)
            self._atomic_json_dump(self._backup_path, data)
            return data

        try:
            with open(self._data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            if os.path.exists(self._backup_path):
                try:
                    with open(self._backup_path, "r", encoding="utf-8") as f:
                        backup_data = json.load(f)
                    data, _ = self._normalize(backup_data)
                    self._atomic_json_dump(self._data_path, data)
                    return data
                except Exception:
                    pass
            data = self._build_default()
            self._atomic_json_dump(self._data_path, data)
            self._atomic_json_dump(self._backup_path, data)
            return data

    async def _load_locked(self) -> dict:
        raw = self._read_raw()
        data, changed = self._normalize(raw)
        if changed:
            self._atomic_json_dump(self._data_path, data)
            self._atomic_json_dump(self._backup_path, data)
        return data

    async def read(self, reader: Callable[[dict], object]):
        async with self._lock:
            data = await self._load_locked()
            return reader(data)

    async def mutate(self, mutator: Callable[[dict], object], save: bool = True):
        async with self._lock:
            data = await self._load_locked()
            result = mutator(data)
            if save:
                self._atomic_json_dump(self._data_path, data)
                self._atomic_json_dump(self._backup_path, data)
            return result

    async def load_copy(self) -> dict:
        return await self.read(lambda data: copy.deepcopy(data))

    async def save(self, data: dict) -> None:
        normalized, _ = self._normalize(copy.deepcopy(data))
        async with self._lock:
            self._atomic_json_dump(self._data_path, normalized)
            self._atomic_json_dump(self._backup_path, normalized)

    @staticmethod
    def ensure_user(data: dict, user_id: str) -> dict:
        users = data.setdefault("users", {})
        user = users.setdefault(user_id, {})
        settings = user.setdefault("settings", {})
        settings["session_words"] = max(1, min(int(settings.get("session_words", 5) or 5), 30))
        user.setdefault("categories", {})
        return user
