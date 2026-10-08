# Рекомендации для участников

Спасибо за интерес к этому проекту! Вот как вы можете помочь.

## Отправка issues

- **Ошибки**: опишите шаги для воспроизведения, окружение (Python, ОС), и вывод ошибок
- **Предложения**: объясните задачу и почему она нужна
- Используйте соответствующий шаблон

## Отправка pull requests

1. **Fork** и **clone** репозиторий
2. Создайте **новую branch**: `git checkout -b feature/description`
3. Внесите изменения, соблюдая стиль кода
4. Тестируйте локально:
   ```bash
   pip install -e ".[dev]"
   python -m pytest
   ruff check . && ruff format --check .
   ```
5. Создайте **commit** с понятным сообщением
6. **Push** в свой fork
7. Откройте **Pull Request** с описанием

## Стиль кода

- Python 3.10+
- `ruff check` и `ruff format` (настройки в `pyproject.toml`)
- Тип-хинты (type hints)
- Комментарии на русском, если нужны объяснения

## Добавление новых инструментов

1. Добавьте функцию в `yandex_tracker_mcp.py`:
   - читающий инструмент — `@mcp.tool(annotations=_READ)`;
   - пишущий — `@_write_tool()` (или `@_write_tool(destructive=True)`), и `write=True` в `_request`.
2. Docstring на русском — его видит модель.
3. Значения из аргументов, которые попадают в путь URL, пропускайте через `_segment()`.
4. Списки получайте через `_request_list()`, постраничные — оборачивайте в `_paged()`.
5. Результат сериализуйте `_out()`; не возвращайте лишние поля.
6. Добавьте тест в `tests/test_server.py` и строку в README.

Пример:

```python
@_write_tool()
async def new_tool(issue_key: str, text: str) -> str:
    """Описание инструмента."""
    result = await _request(
        "POST", f"/issues/{_segment(issue_key, 'ключ задачи')}/something", body={"text": text}, write=True
    )
    return _out(result)
```

## Безопасность

- ⚠️ **Никогда** не коммитьте `.env` с токенами
- Все переменные окружения в `.env.example` должны иметь плейсхолдеры
- Не логируйте токены или конфиденциальные данные

## Использование Claude Code

При разработке используйте Claude Code с этим сервером:

```bash
claude mcp add yandex-tracker-dev --scope user \
  -e TRACKER_TOKEN=<test_token> \
  -e TRACKER_ORG_ID=<test_org> \
  -- python /path/to/server.py
```

Смотрите [CLAUDE.md](CLAUDE.md) для быстрого старта разработки.

## Лицензия

Внося код, вы соглашаетесь лицензировать его под MIT (смотрите [LICENSE](LICENSE)).
