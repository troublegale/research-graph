# research-graph

![CI](https://github.com/troublegale/research-graph/actions/workflows/ci.yml/badge.svg)

Учебный проект курса Python (ИТМО), который развивается в течение семестра.
Пакет `research_graph` — каркас приложения для сбора и обработки данных из
внешних источников (GitHub API и др.): в нём уже настроены конфигурация через
переменные окружения, логирование (текст или JSON) и CLI `rg`.

Цель первой лабораторной — не бизнес-логика, а инфраструктура качества:
зафиксированные зависимости, строгая типизация, линтер, тесты с покрытием,
pre-commit и CI, проверяемый на Linux и Windows. Модули под следующие ЛР
(`models`, `sources`, `storage`, `pipelines`, `api`) уже заведены как заготовки.

## Требования

- Python **3.12+** (CI проверяет 3.12 и 3.13)
- [uv](https://docs.astral.sh/uv/) **0.13+**
- git

Установка uv, если его ещё нет:

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Установка

```bash
git clone https://github.com/troublegale/research-graph.git
cd research-graph
uv sync
```

`uv sync` сам скачает нужную версию Python (из `.python-version`), создаст `.venv`
и установит пакет вместе с dev-зависимостями строго по `uv.lock`.

Опционально — локальный файл настроек:

```bash
cp .env.example .env
```

## Конфигурация

Настройки читаются из переменных окружения с префиксом `RG_` и из файла `.env`
в текущей директории. Переменные окружения имеют приоритет над `.env`.

| Переменная            | Тип          | По умолчанию | Описание                                                  |
|-----------------------|--------------|--------------|-----------------------------------------------------------|
| `RG_GITHUB_TOKEN`     | строка       | *(не задан)* | Токен GitHub API. Никогда не выводится целиком.           |
| `RG_DATA_DIR`         | путь         | `data`       | Каталог для данных проекта.                               |
| `RG_LOG_LEVEL`        | строка       | `INFO`       | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (регистр не важен). |
| `RG_LOG_FORMAT`       | `text`/`json`| `text`       | Формат логов: человекочитаемый или JSON Lines.            |
| `RG_REQUEST_TIMEOUT`  | число        | `10`         | Таймаут HTTP-запросов в секундах, диапазон `(0; 300]`.    |
| `RG_MAX_CONCURRENCY`  | целое        | `4`          | Максимум параллельных запросов, диапазон `[1; 64]`.       |

Некорректные значения приводят к ошибке валидации при запуске.

## Использование

Логи пишутся в `stderr`, полезный вывод — в `stdout`.

```bash
uv run rg --help
```

```text
 Usage: rg [OPTIONS] COMMAND [ARGS]...

 research-graph: project toolkit CLI.

╭─ Options ───────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ──────────────────────────────────────────────────────────────────╮
│ version       Show the package version.                                     │
│ check-config  Load settings, initialise logging and print a summary         │
│               (secrets are masked).                                         │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```bash
uv run rg version
```

```text
0.1.0
```

```bash
RG_GITHUB_TOKEN=ghp_supersecretvalue uv run rg check-config
```

```text
2026-10-18 22:39:33 | INFO     | research_graph.cli | Configuration loaded
Configuration summary:
  github_token    : set (ghp_****alue)
  data_dir        : data
  data_dir exists : no
  log_level       : INFO
  log_format      : text
  request_timeout : 10 s
  max_concurrency : 4
```

Флаг `--create-data-dir` создаёт каталог `RG_DATA_DIR`, если его нет:

```bash
uv run rg check-config --create-data-dir
```

Логи в формате JSON (одна строка на запись):

```bash
RG_LOG_FORMAT=json uv run rg check-config
```

```text
{"timestamp": "2026-10-18T19:39:33.123456+00:00", "level": "INFO", "logger": "research_graph.cli", "message": "Configuration loaded"}
Configuration summary:
  ...
```

При ошибке в настройках команда завершается с кодом `2`:

```bash
RG_MAX_CONCURRENCY=0 uv run rg check-config
```

```text
... | ERROR    | research_graph.cli | Invalid configuration: 1 error(s)
RG_MAX_CONCURRENCY: Input should be greater than or equal to 1
```

> В Windows PowerShell переменные задаются так: `$env:RG_LOG_FORMAT="json"; uv run rg check-config`.

Также доступен запуск модулем: `uv run python -m research_graph version`.

## Разработка

```bash
uv run pytest                      # тесты + покрытие (порог 90 %)
uv run ruff check .                # линтер
uv run ruff format .               # форматирование (--check — только проверка)
uv run mypy                        # строгая проверка типов src/ и tests/
uv run pre-commit install          # хуки перед каждым коммитом
uv run pre-commit run --all-files  # прогнать все хуки вручную
```

Добавление зависимостей — только через uv, чтобы обновился `uv.lock`:

```bash
uv add <package>                # рабочая зависимость
uv add --group dev <package>    # dev-зависимость
```

CI (`.github/workflows/ci.yml`) на каждый push и pull request запускает
ruff, проверку форматирования и mypy, а затем тесты в матрице
`ubuntu-latest`/`windows-latest` × Python `3.12`/`3.13` с порогом покрытия 90 %
и smoke-тест CLI.

## Структура проекта

```text
research-graph/
├── .github/workflows/ci.yml   # CI: линт, типы, тесты в матрице ОС × Python
├── docs/
│   └── lab1_report.md         # отчёт по ЛР1
├── src/research_graph/        # устанавливаемый пакет (src-layout)
│   ├── __init__.py            # версия пакета
│   ├── __main__.py            # python -m research_graph
│   ├── cli.py                 # Typer-приложение: команды version, check-config
│   ├── config.py              # Settings (pydantic-settings), маскирование секретов
│   ├── logging_setup.py       # setup_logging(), JsonFormatter
│   ├── py.typed               # маркер PEP 561: пакет типизирован
│   ├── api/                   # заготовка: HTTP API
│   ├── models/                # заготовка: доменные модели
│   ├── pipelines/             # заготовка: пайплайны обработки
│   ├── sources/               # заготовка: источники данных
│   └── storage/               # заготовка: слой хранения
├── tests/
│   ├── conftest.py            # изоляция от .env и RG_* окружения
│   ├── test_cli.py
│   ├── test_config.py
│   └── test_logging_setup.py
├── .env.example               # шаблон настроек (безопасные значения)
├── .gitattributes             # LF-переносы строк на всех ОС
├── .gitignore
├── .pre-commit-config.yaml    # ruff, ruff-format, mypy, базовые проверки
├── .python-version            # версия Python для uv
├── pyproject.toml             # метаданные, зависимости, настройки инструментов
└── uv.lock                    # зафиксированные версии зависимостей
```
