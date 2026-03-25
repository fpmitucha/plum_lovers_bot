"""
Парсер переписки из Telegram HTML экспорта.
Извлекает заявки (approved/denied) и записывает данные в restore_data.py

Запуск:
    python scripts/parse_chat_history.py
"""

import re
import sys
from pathlib import Path
from html.parser import HTMLParser


HTML_FILE = Path(__file__).parent.parent / "messages.html"
OUTPUT_FILE = Path(__file__).parent / "restore_data.py"


class MessageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.messages = []
        self._current_text = []
        self._in_text_div = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'div' and 'text' in attrs_dict.get('class', ''):
            self._in_text_div = True
            self._depth = 0
            self._current_text = []
        elif self._in_text_div and tag == 'div':
            self._depth += 1

    def handle_endtag(self, tag):
        if self._in_text_div and tag == 'div':
            if self._depth == 0:
                self._in_text_div = False
                text = ''.join(self._current_text).strip()
                if text:
                    self.messages.append(text)
            else:
                self._depth -= 1

    def handle_data(self, data):
        if self._in_text_div:
            self._current_text.append(data)

    def handle_entityref(self, name):
        if self._in_text_div:
            entities = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}
            self._current_text.append(entities.get(name, ''))

    def handle_charref(self, name):
        if self._in_text_div:
            try:
                if name.startswith('x'):
                    self._current_text.append(chr(int(name[1:], 16)))
                else:
                    self._current_text.append(chr(int(name)))
            except Exception:
                pass


def parse_applications(messages):
    """Ищем сообщения с заявками по паттернам бота."""
    # Паттерн сообщения о заявке
    # Slug: xxx
    # Пользователь: @xxx
    # Telegram ID: xxx
    # ID заявки: xxx
    # RESULT: APPROVED / DENIED / AUTO-APPROVED

    applications = []

    for msg in messages:
        # Проверяем, что это сообщение о заявке
        if 'Slug:' not in msg or ('APPROVED' not in msg and 'DENIED' not in msg and 'REJECTED' not in msg and 'ОТКЛОН' not in msg):
            continue

        slug_m = re.search(r'Slug:\s*([A-Za-z0-9_.\-]+)', msg)
        user_m = re.search(r'Пользователь:\s*@([A-Za-z0-9_]+)', msg)
        tid_m = re.search(r'Telegram ID:\s*(\d+)', msg)

        # Определяем статус
        if 'AUTO-APPROVED' in msg:
            status = 'done'
        elif 'APPROVED' in msg:
            status = 'done'
        elif 'DENIED' in msg or 'REJECTED' in msg or 'ОТКЛОН' in msg.upper():
            status = 'rejected'
        else:
            status = 'done'

        if slug_m and user_m and tid_m:
            applications.append({
                'slug': slug_m.group(1).strip(),
                'username': user_m.group(1).strip(),
                'user_id': int(tid_m.group(1)),
                'status': status,
            })
        else:
            # Частичные данные — выведем предупреждение
            print(f"[WARN] Неполная заявка в сообщении: {msg[:200]}", file=sys.stderr)

    return applications


def generate_restore_script(applications, karma_overrides):
    approved = [a for a in applications if a['status'] in ('done', 'approved')]
    rejected = [a for a in applications if a['status'] == 'rejected']

    lines = [
        '"""',
        'Скрипт восстановления данных из переписки с ботом.',
        '',
        'Запуск:',
        '    cd ~/plum_lovers_bot',
        '    source .venv/bin/activate',
        '    python scripts/restore_data.py',
        '"""',
        '',
        'import asyncio',
        'import sys',
        'from pathlib import Path',
        '',
        'sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))',
        '',
        'from dotenv import load_dotenv',
        'load_dotenv()',
        '',
        'from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession',
        'from bot.config import settings',
        'from bot.models.models import Application, Roster, Profile, Base',
        '',
        '',
        '# ─── ОДОБРЕННЫЕ ЗАЯВКИ ───────────────────────────────────────────────────────',
        '# (telegram_id, "username", "slug", "status")',
        'APPROVED_USERS = [',
    ]

    for a in approved:
        lines.append(f'    ({a["user_id"]}, "{a["username"]}", "{a["slug"]}", "{a["status"]}"),')

    lines += [
        ']',
        '',
        '# ─── ОТКЛОНЁННЫЕ ЗАЯВКИ (только для истории, НЕ добавляются в roster/profiles) ──',
        'REJECTED_USERS = [',
    ]

    for a in rejected:
        lines.append(f'    ({a["user_id"]}, "{a["username"]}", "{a["slug"]}"),')

    lines += [
        ']',
        '',
        '# ─── КАРМА ───────────────────────────────────────────────────────────────────',
        '# username -> points (переопределение для тех кто есть в APPROVED_USERS)',
        'KARMA_OVERRIDES = {',
    ]

    for uname, pts in karma_overrides.items():
        lines.append(f'    "{uname}": {pts},')

    lines += [
        '}',
        '',
        '',
        'async def restore(session: AsyncSession) -> None:',
        '    restored_apps = 0',
        '    restored_roster = 0',
        '    restored_profiles = 0',
        '    restored_rejected = 0',
        '',
        '    seen_slugs = set()',
        '    seen_profiles = set()',
        '',
        '    for telegram_id, username, slug, status in APPROVED_USERS:',
        '        app = Application(user_id=telegram_id, username=username, slug=slug, status=status)',
        '        session.add(app)',
        '        restored_apps += 1',
        '',
        '        if slug not in seen_slugs:',
        '            session.add(Roster(slug=slug))',
        '            seen_slugs.add(slug)',
        '            restored_roster += 1',
        '',
        '        if telegram_id not in seen_profiles:',
        '            karma = KARMA_OVERRIDES.get(username.lower(), 10)',
        '            session.add(Profile(user_id=telegram_id, username=username, points=karma))',
        '            seen_profiles.add(telegram_id)',
        '            restored_profiles += 1',
        '',
        '    for telegram_id, username, slug in REJECTED_USERS:',
        '        app = Application(user_id=telegram_id, username=username, slug=slug, status="rejected")',
        '        session.add(app)',
        '        restored_rejected += 1',
        '',
        '    await session.commit()',
        '    print("✅ Восстановлено:")',
        '    print(f"   Одобренные заявки: {restored_apps}")',
        '    print(f"   Отклонённые заявки: {restored_rejected}")',
        '    print(f"   Реестр (roster):    {restored_roster}")',
        '    print(f"   Профили:            {restored_profiles}")',
        '',
        '',
        'async def main() -> None:',
        '    engine = create_async_engine(settings.DATABASE_URL, echo=False)',
        '    async with engine.begin() as conn:',
        '        await conn.run_sync(Base.metadata.create_all)',
        '    session_maker = async_sessionmaker(engine, expire_on_commit=False)',
        '    async with session_maker() as session:',
        '        await restore(session)',
        '    await engine.dispose()',
        '',
        '',
        'if __name__ == "__main__":',
        '    asyncio.run(main())',
    ]

    return '\n'.join(lines)


def main():
    print(f"Читаем {HTML_FILE}...")
    html = HTML_FILE.read_text(encoding='utf-8')

    # Простой regex-парсинг — быстрее и надёжнее для этого формата
    # Ищем блоки с заявками прямо в тексте
    all_texts = re.findall(r'<div class="text">(.*?)</div>', html, re.DOTALL)
    # Заменяем <br> на новую строку ПЕРЕД удалением тегов
    clean = []
    for t in all_texts:
        t = re.sub(r'<br\s*/?>', '\n', t, flags=re.IGNORECASE)
        t = re.sub(r'<[^>]+>', '', t)
        t = t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#x27;', "'")
        clean.append(t.strip())

    applications = parse_applications(clean)

    print(f"Найдено заявок: {len(applications)}")
    approved = [a for a in applications if a['status'] != 'rejected']
    rejected = [a for a in applications if a['status'] == 'rejected']
    print(f"  Одобренных: {len(approved)}")
    print(f"  Отклонённых: {len(rejected)}")

    for a in applications:
        print(f"  [{a['status'].upper():8}] @{a['username']:20} | {a['slug']}")

    karma_overrides = {
        "qq_tyomshik": 241,
        "akazadira": 70,
        "chugun_nya": 60,
        "avbaf": 52,
        "velzebubin": 32,
        "ekir98": 30,
        "anonymous1510": 27,
        "gefest0v": 23,
        "kk0sta": 23,
        "ch1ya": 22,
    }

    script = generate_restore_script(applications, karma_overrides)
    OUTPUT_FILE.write_text(script, encoding='utf-8')
    print(f"\nDone! restore_data.py updated: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
