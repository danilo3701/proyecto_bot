# ProyectoBot/topics/loader.py
"""
💬 Загружает темы из папки topics
Каждый JSON-файл поддерживает:
 - комментарии, начинающиеся с #
 - поля title, category
 - либо готовое поле structure, либо автоматическую сборку из vocab_links + exercises
"""

import os
import json

def load_topics():
    topics = {}
    base_path = os.path.dirname(__file__)
    for filename in os.listdir(base_path):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(base_path, filename)
        try:
            # читаем файл, убираем строковые комментарии и пустые строки
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            content = "".join(
                [l for l in lines if not l.strip().startswith("#") and l.strip()]
            )
            data = json.loads(content)

            key = filename.rsplit(".", 1)[0]

            # если нет готового списка блоков — собираем его автоматически
            if "structure" not in data:
                data["structure"] = []
                for v in data.get("vocab_links", []):
                    data["structure"].append({
                        "type": "vocab",
                        "title": v.get("title", ""),
                        "link": v.get("link", "")
                    })
                for ex in data.get("exercises", []):
                    data["structure"].append({
                        "type": "exercise",
                        "title": ex.get("title", ""),
                        "instruction": ex.get("instruction", ""),
                        "link": ex.get("link", "")
                    })

            topics[key] = data

        except Exception as e:
            print(f"⚠️ Пропускаю {filename}: {e}")
    return topics

