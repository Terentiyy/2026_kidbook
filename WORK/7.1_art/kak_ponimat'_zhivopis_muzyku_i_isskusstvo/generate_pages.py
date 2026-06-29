import json
import os
import re
import time
import argparse
import anthropic
from pathlib import Path


CONCEPTS_FILE = Path(__file__).parent / "concepts.json"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "KIDBOOK" / "art_understanding"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SECTION_TITLE = "Как понимать живопись, музыку и литературу"

# Шаблон промпта для генерации
PROMPT_TEMPLATE = """Объясни для десятилетнего ребёнка, что такое «{concept}» в контексте искусства ({domain}).

Требования к тексту:
- Пиши просто, живо и увлекательно — как будто рассказываешь другу
- Используй 2–3 примера из известных произведений (картин, музыки, книг)
- Добавь 1–2 интересных факта, которые удивят ребёнка
- Объём: примерно 200–300 слов
- Структура ответа — строго Markdown:
  - Заголовок H1: название понятия
  - Раздел «Что это?» (2–3 предложения)
  - Раздел «Как это работает?» (3–4 предложения с примерами)
  - Раздел «Интересные факты» (2 пункта маркированного списка)
  - Раздел «Попробуй сам!» (1 простое задание для ребёнка)
- НЕ добавляй никакого текста вне этой структуры
- Пиши на русском языке
"""


def load_concepts() -> dict:
    with open(CONCEPTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_page(client: anthropic.Anthropic, concept: dict) -> str:
    prompt = PROMPT_TEMPLATE.format(
        concept=concept["title"],
        domain=concept["domain"]
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()

    # Добавляем метаданные в начало файла
    header = f"""---
concept_id: {concept['id']}
title: {concept['title']}
domain: {concept['domain']}
wikidata: https://www.wikidata.org/wiki/{concept['wikidata_id']}
section: {SECTION_TITLE}
---

"""
    return header + text


def add_crosslinks(text: str, all_concepts: list, current_id: str) -> str:
    used_links: set[str] = set()  # уже вставленные ссылки (по concept_id)

    for concept in all_concepts:
        if concept["id"] == current_id:
            continue  # не ссылаемся на самих себя

        rel_path = f"../{concept['slug']}.md"
        concept_id = concept["id"]

        if concept_id in used_links:
            continue

        keywords = sorted(concept["keywords"], key=len, reverse=True)  # длинные сначала
        for keyword in keywords:
            pattern = r'(?<!\[)(?<!\()(?<!\w)(' + re.escape(keyword) + r')(?!\w)(?!\])(?!\))'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                replacement = f"[{match.group(1)}]({rel_path})"
                text = text[:match.start()] + replacement + text[match.end():]
                used_links.add(concept_id)
                break  # только первое вхождение, только один keyword

    return text


def process_all(skip_generation: bool = False, api_key: str = None):
    data = load_concepts()
    concepts = data["concepts"]

    client = None
    if not skip_generation:
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("Укажите API-ключ через --api-key или переменную ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)

    pages: dict[str, str] = {}

    for i, concept in enumerate(concepts, 1):
        out_path = OUTPUT_DIR / f"{concept['slug']}.md"

        if skip_generation and out_path.exists():
            print(f"[{i:02d}/{len(concepts)}] ⏭  Пропуск (файл существует): {concept['title']}")
            with open(out_path, "r", encoding="utf-8") as f:
                pages[concept["id"]] = f.read()
            continue

        print(f"[{i:02d}/{len(concepts)}] 🤖 Генерация: {concept['title']}...", end=" ", flush=True)
        try:
            page_text = generate_page(client, concept)
            pages[concept["id"]] = page_text
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(page_text)
            print("✅")
            time.sleep(0.5)  # небольшая пауза между запросами
        except Exception as e:
            print(f" Ошибка: {e}")

    print("\n Расстановка перекрёстных ссылок...")
    for concept in concepts:
        out_path = OUTPUT_DIR / f"{concept['slug']}.md"
        if concept["id"] not in pages:
            continue

        original = pages[concept["id"]]
        if original.startswith("---"):
            parts = original.split("---", 2)
            yaml_part = "---" + parts[1] + "---\n"
            body = parts[2] if len(parts) > 2 else ""
        else:
            yaml_part = ""
            body = original

        linked_body = add_crosslinks(body, concepts, concept["id"])
        final_text = yaml_part + linked_body

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(final_text)

        print(f"  ✅ {concept['title']}")

    print(f"\n🎉 Готово! Файлы сохранены в: {OUTPUT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Генерация KIDBOOK-страниц")
    parser.add_argument("--api-key", help="Anthropic API key")
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="Пропустить генерацию, только перерасставить ссылки"
    )
    args = parser.parse_args()

    process_all(skip_generation=args.skip_generation, api_key=args.api_key)
