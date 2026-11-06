# Обработка полученных замечаний

6 ноября 2026 коллега [WhyNot-png](https://github.com/WhyNot-png)
оставил два замечания к PR №1 и одно к PR №3. Все три замечания приняты.

## PR №1: первые прогнозы и список заявок

[Исходный комментарий](https://github.com/troublegale/research-graph/pull/1#issuecomment-6685393315).

1. **Гонка регистрации версии модели.** Проверка наличия и вставка заменены
   атомарным `INSERT ... ON CONFLICT DO NOTHING` для PostgreSQL и SQLite.
   Затем оба запроса читают одну зарегистрированную версию.
   Тест `assert_concurrent_first_predictions` синхронизирует две отдельные
   сессии непосредственно перед INSERT и проверяет одну версию и две оценки.
   Проверка выполняется на SQLite и в PostgreSQL-интеграции.
2. **Заявки после сотой недоступны в интерфейсе.** Добавлена кнопка
   «Показать ещё заявки»; уже открытые страницы сохраняются при выборе
   и обновлении заявки. API-тест проверяет разбиение 101 записи на страницы,
   браузерный сценарий — загрузку и открытие самой старой заявки.

[Коммит исправления](https://github.com/troublegale/research-graph/commit/0f80bcfe069765fbb6d636a6e69b72108859db7d).
Браузерная проверка находится в PR №3, где подключён Playwright.

## PR №3: нормализация цены при CSV-предсказании

[Исходный комментарий](https://github.com/troublegale/research-graph/pull/3#issuecomment-6685404643).

Разбор целевой цены через `float` заменён общей функцией `number`, используемой
при импорте. Добавлены шесть API-проверок: исходный/подготовленный CSV ×
обычные пробелы/неразрывные пробелы/десятичная запятая. Проверяются успешный
ответ и метрики по нормализованной цене. Отсутствующая цена по-прежнему
означает прогноз без метрик, некорректная — ошибку валидации.

[Коммит исправления CSV и браузерной проверки](https://github.com/troublegale/research-graph/commit/88d97cf2eba601867a0981a8f3f9bb3f2a2ac8d5).

## Ответы автора и проверка исправлений

- [Ответ на замечания PR №1](https://github.com/troublegale/research-graph/pull/1#issuecomment-6685596915).
- [Ответ на замечание PR №3](https://github.com/troublegale/research-graph/pull/3#issuecomment-6685648622).

После исправлений 6 ноября 2026 выполнен полный набор проверок с SQLite
и отдельной PostgreSQL: **115 тестов прошли, покрытие — 99,49%**.
Ruff, проверка форматирования и mypy завершились успешно. В Chromium проверены
загрузка второй страницы заявок и открытие 101-й записи; тот же сценарий
выполнен в обновлённом Docker-приложении. Проверки включены в GitHub Actions.

## Слияние

Все три PR последовательно слиты в `main` **6 ноября 2026** с сохранением
истории. После смены базовых веток они обновлены из `main`; коллега
`WhyNot-png` подтвердил итоговые версии через GitHub Approve.

| PR | Итоговое одобрение | Коммит слияния | Время слияния, Москва |
|---|---|---|---|
| [№1](https://github.com/troublegale/research-graph/pull/1) | [Approve](https://github.com/troublegale/research-graph/pull/1#pullrequestreview-5800624649) | `154ba6a4364a58a7aede42db0959230363abdfea` | 16:21:19 |
| [№2](https://github.com/troublegale/research-graph/pull/2) | [Approve](https://github.com/troublegale/research-graph/pull/2#pullrequestreview-5800724625) | `99dd2b256aefa1ccb96cb1956d716de5f74e1a0a` | 16:29:45 |
| [№3](https://github.com/troublegale/research-graph/pull/3) | [Approve](https://github.com/troublegale/research-graph/pull/3#pullrequestreview-5800790991) | `cfa49ec36068b2b1af51c3d5677b04ea6912ee09` | 16:35:41 |

Получены формальные одобрения на все три PR. В самих комментариях коллеги
содержатся два замечания к №1 и одно к №3; в отчёте они не выдаются за
три замечания на каждый PR. Защита `main` при слиянии сохранялась.
