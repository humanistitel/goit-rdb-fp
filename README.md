# Інфекційні захворювання: фінальний проєкт

Імпорт і аналіз `infectious_cases.csv` у PostgreSQL 16: нормалізація до 3НФ, агрегати `Number_rabies`, календарна різниця років і дві власні функції.

[Відкрити у Google Colab](https://colab.research.google.com/github/humanistitel/goit-rdb-fp/blob/main/Diuryk_final_project.ipynb)

## Запуск

У Colab оберіть CPU та натисніть **Runtime → Run all**. Notebook містить CSV, SQL і модулі запуску. Перша клітинка готує залежності та тимчасову базу, остання закриває сервер. Кожен повний запуск створює нову базу.

Локально потрібен Python 3.9–3.12. Встановіть залежності командою `python -m pip install -r requirements.txt`, відкрийте `Diuryk_final_project.ipynb` у Jupyter і виконайте всі клітинки.

## Дані та схема

[CSV з LMS](https://drive.google.com/file/d/1dQf-uVXzYPYYGgXsG1y4Q1qDdhP2miZl/view?usp=drive_link) містить **10 521 рядок, 12 колонок і 245 пар Entity/Code** за 1920–2023 роки. SHA-256 файла: `226a0ff1916de44182d881b00d21cd59c1d58ae2ff6ec47d7a8042d7bc03f289`.

Схема `pandemic` містить вихідну `infectious_cases` і дві нормалізовані таблиці: `entities` та `case_stats`. Ключ річного спостереження — `(entity_id, year)`. Порожні значення стають `NULL`, нулі та дробові показники зберігаються в `NUMERIC`. Сутності без Code розрізняються за назвою.

## Запити й функції

Для `Number_rabies` обчислюються `AVG`, `MIN`, `MAX`, `SUM`. Десять найбільших середніх виводяться з `DESC NULLS LAST`. Entity включає країни, World та групи, що можуть перетинатися; одиниці показників у CSV не зазначені.

`years_since` повертає повні роки від 1 січня заданого року до `CURRENT_DATE` у UTC. `period_average` ділить річний показник на додатний дільник; наведено приклади для 12, 4, 2 і 7. `NULL` повертає `NULL`; недодатний дільник, NaN та нескінченні аргументи відхиляються.

## Файли

- `Diuryk_final_project.ipynb` — notebook із SQL і результатами.
- `sql/` — сім SQL-файлів.
- `data/` — вихідний CSV.
- `assets/` — модулі запуску.
- `results/` — CSV-результати та графік.
- `screenshots/` — таблиці, запити й результати.

[Завдання LMS](https://www.edu.goit.global/uk/learn/43680627/52381036/53957424/homework) · [Репозиторій](https://github.com/humanistitel/goit-rdb-fp). Архів роботи — `ФП_Diuryk_Anton.zip`.
