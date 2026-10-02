# CLAUDE.md — Coinbot-Yuriy

Мониторинг нумизматических площадок (Мешок, Аукцион, Авито) с фильтрацией по ключевым словам,
LLM-проверкой и алертами в Telegram. Разработчик — CC (Claude Code). Клиент — Юрий Дерябин.

---

## Правила репозитория

- Репо: `Coinbot-Yuriy` (публичный, аккаунт Романа)
- **НИКОГДА не указывать Claude / Claude Code в качестве соавтора коммитов.** Единственный автор — аккаунт Романа.
- Ветка по умолчанию: `main`

---

## Стек

| Компонент | Решение |
|---|---|
| Язык | Python 3.10+ (проверь `python3 --version` на VPS) |
| Telegram-бот | aiogram 3.x |
| HTTP-запросы | requests + BeautifulSoup4 (основной парсинг) |
| База данных | SQLite в WAL-режиме (`PRAGMA journal_mode=WAL`) |
| LLM | OpenAI GPT-4o-mini (`openai` SDK) |
| Зависимости | pip + `requirements.txt` + `.venv` в корне |
| Расписание | **cron на Beget VPS** (не APScheduler) |
| Деплой | Beget VPS; бот — systemd-сервис; скрапер — cron |
| Конфиг секретов | `.env` + `python-dotenv` |
| Конфиг источников | `config.yaml` (ключевые слова, URL каталогов, интервалы) |

---

## Архитектура (два процесса, одна БД)

```
┌─────────────────────────────────────────────────────────────────┐
│  cron (каждые 30 мин для Мешка, каждый час для Аукциона/Авито) │
│                                                                 │
│  scraper_run.py                                                 │
│    └── для каждого source в config.yaml:                        │
│          1. Scraper.fetch_new_lots(since=last_run_at)           │
│          2. keyword_filter(lots, keywords)  →  candidates       │
│          3. llm_check(candidates)           →  confirmed        │
│          4. dedup(confirmed)                →  new_finds        │
│          5. Bot API send_message(new_finds) →  Telegram-алерт   │
│          6. Сохранить в found_lots + обновить last_run_at       │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  systemd-сервис (persistent, 24/7)                               │
│                                                                  │
│  bot_service.py (aiogram)                                        │
│    /start  →  приветствие                                        │
│    /logs   →  последние 20 находок из found_lots (из SQLite)     │
└──────────────────────────────────────────────────────────────────┘

              Общая база: coinbot.db (SQLite WAL)
```

> **Ключевое разделение:** скрапер шлёт алерты напрямую через Bot API (`requests.post`),
> aiogram нужен только боту — они **не зависят друг от друга** в рантайме.

---

## Структура проекта

```
Coinbot-Yuriy/
├── .env                        # секреты (не в git — добавь в .gitignore)
├── .gitignore
├── config.yaml                 # ключевые слова, URL каталогов
├── requirements.txt
├── coinbot.db                  # SQLite (создаётся при первом запуске, не в git)
│
├── scraper_run.py              # точка входа для cron
├── bot_service.py              # точка входа для systemd (aiogram)
│
├── scrapers/
│   ├── base.py                 # BaseScraper (ABC)
│   ├── meshok.py               # Мешок (браки + юбилейка разделы)
│   ├── auction.py              # Аукцион (auction.ru)
│   └── avito.py                # Авито — ЗАГЛУШКА на первом этапе
│
├── pipeline/
│   ├── keyword_filter.py       # фильтр по ключевым словам
│   ├── llm_checker.py          # GPT-4o-mini проверка
│   └── dedup.py                # дедупликация по lot_id
│
├── bot/
│   ├── setup.py                # инициализация aiogram Bot + Dispatcher
│   └── handlers.py             # /start, /logs
│
├── db/
│   └── database.py             # SQLite схема + CRUD-функции
│
└── utils/
    ├── notifier.py             # send_alert() через requests → Bot API
    └── logger.py               # настройка logging
```

---

## База данных (coinbot.db)

```sql
-- Все обработанные лоты (дедупликация)
CREATE TABLE IF NOT EXISTS seen_lots (
    lot_id      TEXT NOT NULL,
    source      TEXT NOT NULL,          -- 'meshok_braki', 'meshok_yubileyka', 'auction', 'avito'
    first_seen  TIMESTAMP DEFAULT (datetime('now')),
    PRIMARY KEY (lot_id, source)
);

-- Подтверждённые совпадения (для /logs и истории)
CREATE TABLE IF NOT EXISTS found_lots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id      TEXT NOT NULL,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT,
    price       TEXT,
    photo_url   TEXT,
    summary     TEXT,                   -- краткое саммари от LLM
    found_at    TIMESTAMP DEFAULT (datetime('now'))
);

-- Состояние последнего прогона (точка отсчёта "новизны" лотов)
CREATE TABLE IF NOT EXISTS run_state (
    source          TEXT PRIMARY KEY,
    last_run_at     TIMESTAMP
);
```

---

## Источники (порядок разработки)

### Этап 1 — Мешок (делаем первым)

| Источник | URL | Примечания |
|---|---|---|
| Браки | `https://meshok.net/listing?good=15190` | Приоритет #1 |
| Юбилейные (общий) | `https://meshok.net/good/15401` | |
| Юбилейные + тиражные | `https://meshok.net/listing?good=14723` | |
| СССР — 1 рубль | TBD (уточнить good-id у Юрия) | |
| Россия 1991–1996, 1 руб + Разное | TBD | |
| Россия с 1997, 10 руб | TBD | |

Сортировка по дате: исследуй URL-параметр на сайте (скорее всего `?sort=date_desc` или аналог).
Парсинг: requests + BeautifulSoup4. Извлекать: lot_id (из ссылки), title, price, photo_url, дата публикации.

### Этап 2 — Аукцион (auction.ru)

| Источник | URL |
|---|---|
| Россия после 1991 | `https://auction.ru/listing/offer/rossija_posle_1991_goda-78259` |
| Памятные и юбилейные | `https://auction.ru/listing/offer/pamjatnye_i_jubilejnye_monety-75693` |
| 1 рубль | `https://auction.ru/listing/offer/1_rubl-74407` |

Исследуй возможность добавления каталогов 3р/50р/100р — в `config.yaml` добавить пустой список `extra_auction_urls: []`.

### Этап 3 — Авито (Final Boss, не сейчас)

`avito.py` — только заглушка с `raise NotImplementedError("Avito scraper — этап 3")`.

Стратегия будет определена отдельно. Из опыта проекта Radar Rynka:
- Авито агрессивно блокирует по IP
- Разделять collect и enrich запуски на несколько часов
- Малые батчи, паузы между запросами
- НЕ использовать простой requests без дополнительной защиты

---

## Пайплайн (шаг за шагом)

### 1. keyword_filter

Принимает список лотов, возвращает только те, у которых хотя бы одно ключевое слово
найдено в `title.lower()` или `description.lower()` (если description доступен).

Ключевые слова — из `config.yaml` (список `keywords`). Сейчас 29 слов, будет расти.
**Список — конфигурация, не хардкод в коде.**

### 2. llm_checker

После keyword_filter для каждого кандидата делает запрос к GPT-4o-mini:

```python
SYSTEM_PROMPT = """Ты — фильтр нумизматических объявлений. 
Ответь ТОЛЬКО "YES" или "NO".
Объявление РЕЛЕВАНТНО, если оно касается монеты СССР или России с браком чеканки,
разновидностью, перепуткой, смещением или другим нумизматическим дефектом/особенностью."""

USER_PROMPT = f"Заголовок: {title}\nОписание: {description[:400]}"
```

Если LLM вернул "YES" → лот подтверждён. Если "NO" или ошибка → отклонён.
Обрабатывай `openai.RateLimitError` и сетевые ошибки с retry (3 попытки, exponential backoff).

### 3. dedup

Проверяет `seen_lots` по `(lot_id, source)`. 
Новый лот → добавить в `seen_lots`, продолжить.
Уже видели → пропустить (не алертить).

### 4. notifier (send_alert)

Прямой POST к Bot API (не aiogram):

```python
import requests

def send_alert(lot: dict, bot_token: str, chat_id: str):
    text = f"🔍 *{lot['source_label']}*\n\n{lot['title']}\n💰 {lot['price']}\n\n{lot['url']}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    
    if lot.get("photo_url"):
        # sendPhoto + caption вместо sendMessage
        ...
    
    requests.post(url, json=payload, timeout=10)
```

Формат алерта в Telegram:
```
🔍 Мешок — Браки

Монета 1 рубль 1961 БРАК смещение
💰 1 500 ₽

https://meshok.net/item/...
```

---

## Telegram-бот (bot_service.py)

- Token: `BOT_TOKEN` из `.env`
- Admin chat: `CHAT_ID=5063672599` (Юрий Дерябин) из `.env`
- Команды:
  - `/start` → приветствие
  - `/logs` или `/logs 10` → последние N записей из `found_lots` (default 20)

Формат `/logs`:
```
📋 Последние находки (3):

1. Мешок-Браки | 29.09 14:32
   1 руб 1961 БРАК | 1 500 ₽
   https://meshok.net/item/...

2. ...
```

Бот НЕ является точкой входа для скрапера — только для ответов пользователю.

---

## .env (шаблон — не коммитить)

```
OPENAI_API_KEY=sk-...
BOT_TOKEN=...        # получить у BotFather
CHAT_ID=5063672599
DB_PATH=coinbot.db
```

---

## config.yaml (шаблон)

```yaml
# Интервалы (минуты) — для документации, реальный контроль через cron
intervals:
  meshok: 30
  auction: 60
  avito: 60   # этап 3

# Ключевые слова для фильтрации (дополняются без изменения кода)
keywords:
  - заготовка
  - гашеная
  - муляж
  - мул
  - ошибка
  - брак
  - проба
  - оттиск
  - выкус
  - двойной выкус
  - тройной выкус
  - разновидность
  - перепутка
  - без гуртовой надписи
  - двойная накатка гуртовой надписи
  - смещение
  - щель
  - без краски
  - поворот
  - несоостность
  - полный раскол
  - чечевица
  - непрочекан
  - соударение
  - фальшивка
  - образец
  - легкая
  - тяжелая
  - инкуз
  - перечекан
  - лунка
  - вне кольца

# Источники Мешок
meshok_sources:
  - id: meshok_braki
    label: "Мешок — Браки"
    url: "https://meshok.net/listing?good=15190"
  - id: meshok_yub_main
    label: "Мешок — Юбилейка"
    url: "https://meshok.net/good/15401"
  - id: meshok_yub_tir
    label: "Мешок — Юбилейка+Тиражные"
    url: "https://meshok.net/listing?good=14723"
  # Добавить good-id для доп. разделов когда уточним у Юрия:
  # - id: meshok_ussr_1rub
  #   label: "Мешок — СССР 1 рубль"
  #   url: "https://meshok.net/listing?good=XXXXX"

# Источники Аукцион
auction_sources:
  - id: auction_post1991
    label: "Аукцион — Россия после 1991"
    url: "https://auction.ru/listing/offer/rossija_posle_1991_goda-78259"
  - id: auction_yub
    label: "Аукцион — Юбилейные"
    url: "https://auction.ru/listing/offer/pamjatnye_i_jubilejnye_monety-75693"
  - id: auction_1rub
    label: "Аукцион — 1 рубль"
    url: "https://auction.ru/listing/offer/1_rubl-74407"
  # extra_auction_urls: []  # место для 3р/50р/100р когда добавим

# Авито — этап 3
avito_sources: []
```

---

## Cron на Beget VPS

```bash
# Мешок — каждые 30 минут
*/30 * * * * /home/user/Coinbot-Yuriy/.venv/bin/python /home/user/Coinbot-Yuriy/scraper_run.py --source meshok >> /home/user/Coinbot-Yuriy/logs/scraper.log 2>&1

# Аукцион — каждый час
0 * * * * /home/user/Coinbot-Yuriy/.venv/bin/python /home/user/Coinbot-Yuriy/scraper_run.py --source auction >> /home/user/Coinbot-Yuriy/logs/scraper.log 2>&1
```

`scraper_run.py` принимает `--source meshok | auction | avito | all`.

---

## Systemd-сервис для бота

```ini
# /etc/systemd/system/coinbot.service
[Unit]
Description=Coinbot Yuriy Telegram Bot
After=network.target

[Service]
User=<user>
WorkingDirectory=/home/user/Coinbot-Yuriy
ExecStart=/home/user/Coinbot-Yuriy/.venv/bin/python bot_service.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable coinbot
sudo systemctl start coinbot
```

---

## Порядок разработки (CC делает в таком порядке)

1. `db/database.py` — инициализация SQLite, все таблицы, CRUD
2. `scrapers/base.py` — абстрактный класс BaseScraper
3. `scrapers/meshok.py` — парсер Мешка (исследуй структуру HTML, найди сортировку по дате)
4. `pipeline/keyword_filter.py`
5. `pipeline/llm_checker.py` (GPT-4o-mini)
6. `pipeline/dedup.py`
7. `utils/notifier.py` — send_alert() через Bot API
8. `scraper_run.py` — собирает пайплайн, CLI `--source`
9. `bot/handlers.py` + `bot_service.py` — aiogram, /logs
10. `scrapers/auction.py` — аналогично Мешку
11. Тесты на реальных данных, коррекция keyword_filter
12. `scrapers/avito.py` — заглушка `NotImplementedError`
13. Деплой: venv, cron, systemd
14. Авито — отдельно (этап 3)

---

## Важные ограничения и граблей

- **Мешок / Аукцион**: стандартный HTML, requests + BS4 должны работать. Проверь наличие rate limiting и добавь `time.sleep(1-2)` между запросами к одному домену.
- **SQLite WAL**: обязательно `PRAGMA journal_mode=WAL` — иначе конфликт между ботом и скрапером при одновременном доступе.
- **Логирование**: пиши в `/logs/scraper.log` и `/logs/bot.log`. Ротация — logrotate или `RotatingFileHandler`.
- **Авито — не сейчас.** `avito.py` — только `raise NotImplementedError`.
- **Ключевые слова — только из config.yaml.** Не хардкодить. При изменении keywords перезапускать только cron-скрипт (бот не надо).
- **LLM-затраты**: вызывать GPT-4o-mini только после keyword_filter. Логировать кол-во вызовов и токены для последующей оптимизации.
- **Не коммить .env и coinbot.db** (в .gitignore).
