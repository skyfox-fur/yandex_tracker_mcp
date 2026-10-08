# Yandex Tracker MCP

MCP-сервер для Яндекс Трекера (API v3), позволяющий Claude и другим MCP-клиентам читать и изменять задачи, выполнять поиск, добавлять комментарии, переводить по статусам, создавать связи и списывать время.

## Возможности

- **12 инструментов чтения**: задачи, комментарии, переходы, связи, очереди, пользователи, поля
- **6 инструментов записи**: создание, изменение, комментарии, переходы, связи, списание времени
- **Поддержка OAuth и IAM** для разных типов организаций
- **Режим только для чтения** для ограничения доступа
- **Полная интеграция с Claude Code** и другими MCP-клиентами

## Быстрый старт

### Linux/macOS

```bash
git clone https://github.com/skyfox-fur/yandex_tracker_mcp.git
cd yandex_tracker_mcp
./setup.sh
```

### Windows

```powershell
git clone https://github.com/skyfox-fur/yandex_tracker_mcp.git
cd yandex_tracker_mcp
.\setup.ps1
```

### Альтернатива: использование uvx

Без клонирования — сразу подключить к Claude Code (нужен [uv](https://docs.astral.sh/uv/)):

```bash
claude mcp add yandex-tracker --scope user -e TRACKER_TOKEN=<ваш_токен> -e TRACKER_ORG_ID=<ваш_id> -- uvx --from git+https://github.com/skyfox-fur/yandex_tracker_mcp yandex-tracker-mcp
```

## Настройка

### 1. Получение OAuth-токена

1. Перейдите на https://oauth.yandex.ru/
2. Создайте приложение:
   - Установите **Scopes**: `tracker:read` и `tracker:write`
   - Установите **Redirect URI**: `https://oauth.yandex.ru/verification_code`
   - **Примечание**: Client Secret не требуется для получения токена
3. Получите **Client ID**
4. Перейдите по ссылке (замените `<ClientID>`):
   ```
   https://oauth.yandex.ru/authorize?response_type=token&client_id=<ClientID>
   ```
5. Разрешите доступ — вас перенаправит на страницу с токеном в URL
6. Скопируйте токен и сохраните в `.env` как `TRACKER_TOKEN`

### 2. Получение ID организации

В **Яндекс Трекер** перейдите в **Администрирование** → **Организации**:

- **Для Яндекс 360**: используйте числовой ID организации → `TRACKER_ORG_ID`
- **Для Yandex Cloud**: используйте ID Cloud организации → `TRACKER_CLOUD_ORG_ID`

### 3. IAM-аутентификация (для Yandex Cloud)

Если используете `TRACKER_CLOUD_ORG_ID`:

```bash
# Получить IAM-токен
yc iam create-token

# Установить в .env
TRACKER_AUTH_TYPE=iam
TRACKER_TOKEN=<iam_token>
TRACKER_CLOUD_ORG_ID=<cloud_org_id>
```

**Примечание**: IAM-токены действуют 12 часов.

### 4. Создание .env

```bash
cp .env.example .env
# Отредактируйте .env с вашими значениями
```

Обязательные переменные:
- `TRACKER_TOKEN` — OAuth или IAM токен
- `TRACKER_ORG_ID` ИЛИ `TRACKER_CLOUD_ORG_ID` — ID организации

Опциональные:
- `TRACKER_AUTH_TYPE` — `oauth` (по умолчанию) или `iam`
- `TRACKER_READ_ONLY` — `1`/`true`/`yes`/`on` для режима только чтения (непонятное значение — ошибка при старте)
- `TRACKER_API_URL` — базовый URL API, только `https://` (по умолчанию `https://api.tracker.yandex.net/v3`)
- `TRACKER_ENV_FILE` — путь к `.env`, если он лежит не рядом с `yandex_tracker_mcp.py`

`.env` читается только рядом с `yandex_tracker_mcp.py` (или из `TRACKER_ENV_FILE`) — не из текущей папки,
чтобы чужой `.env` не мог перенаправить токен. Переменные окружения важнее значений из `.env`.
При установке через `uvx`/`pip install` модуль лежит в site-packages — передавайте переменные через
`claude mcp add -e ...` или укажите путь к своему файлу в `TRACKER_ENV_FILE`.
Ошибки конфигурации выводятся в stderr сразу при запуске.

## Инструменты

### Чтение (12)

| Инструмент | Описание |
|-----------|---------|
| `whoami` | Текущий пользователь |
| `get_issue` | Получить задачу по ключу (например, `PROJ-123`) |
| `search_issues` | Поиск задач по запросу, очереди или фильтру |
| `count_issues` | Количество задач по запросу |
| `get_comments` | Комментарии к задаче |
| `get_transitions` | Доступные переходы по статусам |
| `get_links` | Связи с другими задачами |
| `get_worklog` | Записи о затраченном времени |
| `list_queues` | Список всех очередей |
| `get_queue` | Информация об очереди (типы, приоритеты) |
| `list_users` | Пользователи организации |
| `list_fields` | Глобальные поля задач |

### Запись (6)

| Инструмент | Описание |
|-----------|---------|
| `create_issue` | Создать новую задачу |
| `update_issue` | Изменить поля задачи |
| `add_comment` | Добавить комментарий с поддержкой YFM |
| `transition_issue` | Перевести задачу в другой статус |
| `link_issues` | Создать связь между задачами |
| `add_worklog` | Списать время по задаче |

**Примечания**:
- при `TRACKER_READ_ONLY=1` инструменты записи вообще не регистрируются — клиент их не видит;
- списки (`search_issues`, `list_queues`, `list_users`) возвращают `{"items", "page", "total", "has_more"}` —
  следующая страница запрашивается через `page`; `get_comments` листается курсором `after_id`;
- ключи задач и очередей проверяются (`[A-Za-z0-9_-]`), чтобы из них нельзя было собрать путь к другому методу API;
- у инструментов есть MCP-аннотации `readOnlyHint` / `destructiveHint`.

## Использование с Claude Code

### Добавление MCP-сервера

Способ 1: с venv (локальная установка)

```bash
# После ./setup.sh или установки pyproject.toml:
claude mcp add yandex-tracker --scope user \
  -e TRACKER_TOKEN=<ваш_токен> \
  -e TRACKER_ORG_ID=<ваш_id> \
  -- <путь_к_проекту>/.venv/Scripts/python.exe <путь_к_проекту>/server.py
```

Способ 2: с uvx (рекомендуется)

```bash
claude mcp add yandex-tracker --scope user \
  -e TRACKER_TOKEN=<ваш_токен> \
  -e TRACKER_ORG_ID=<ваш_id> \
  -- uvx --from git+https://github.com/skyfox-fur/yandex_tracker_mcp yandex-tracker-mcp
```

### Использование в Claude Desktop

Откройте файл конфигурации Claude Desktop (Settings → Developer → Edit Config): `%APPDATA%\Claude\claude_desktop_config.json` на Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` на macOS:

```json
{
  "mcpServers": {
    "yandex-tracker": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/skyfox-fur/yandex_tracker_mcp",
        "yandex-tracker-mcp"
      ],
      "env": {
        "TRACKER_TOKEN": "your_token_here",
        "TRACKER_ORG_ID": "your_org_id",
        "TRACKER_AUTH_TYPE": "oauth"
      }
    }
  }
}
```

Или с локальной установкой:

```json
{
  "mcpServers": {
    "yandex-tracker": {
      "command": "<путь_к_проекту>/.venv/Scripts/python.exe",
      "args": ["<путь_к_проекту>/server.py"],
      "env": {
        "TRACKER_TOKEN": "your_token_here",
        "TRACKER_ORG_ID": "your_org_id"
      }
    }
  }
}
```

## Примеры использования

```python
# Получить текущего пользователя
whoami()

# Получить задачу
get_issue("PROJ-123")

# Поиск задач
search_issues(query="Queue: PROJ AND Assignee: me()")

# Создать задачу
create_issue(queue="PROJ", summary="Новая задача", description="Описание", assignee="john.doe")

# Добавить комментарий
add_comment("PROJ-123", "Готово!")

# Списать время
add_worklog("PROJ-123", "PT2H30M")
```

## Безопасность

⚠️ **Важно**: никогда не коммитьте файл `.env` с настоящими токенами в репозиторий!

`.env` добавлен в `.gitignore` и не будет случайно закоммичен.

При работе с Claude Code передавайте токен через флаги `-e`:
```bash
claude mcp add yandex-tracker -e TRACKER_TOKEN=<токен> ...
```

## Разработка

Смотрите [CONTRIBUTING.md](CONTRIBUTING.md) и [CLAUDE.md](CLAUDE.md).

Для разработки требуется Python 3.10+:

```bash
pip install -e ".[dev]"   # Зависимости + pytest и ruff
python -m pytest          # Тесты (без обращения к настоящему API)
ruff check . && ruff format --check .
```

## Поддержка

- **Документация Яндекс Трекера**: https://yandex.cloud/ru/docs/tracker/
- **API v3 Трекера**: https://yandex.cloud/ru/docs/tracker/api-reference/
- **MCP**: https://modelcontextprotocol.io/

## Лицензия

MIT — см. [LICENSE](LICENSE)

## Автор

[skyfox-fur](https://github.com/skyfox-fur)
