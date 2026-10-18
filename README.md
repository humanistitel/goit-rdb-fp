# Інфекційні захворювання: фінальний проєкт

PostgreSQL 16: імпорт CSV у схему `pandemic`, нормалізація до 3НФ, десять найбільших середніх `Number_rabies`, календарна різниця років і дві незалежні функції.

[Відкрити у Google Colab](https://colab.research.google.com/github/humanistitel/goit-rdb-fp/blob/main/Diuryk_final_project.ipynb) або завантажити `Diuryk_final_project.ipynb` через меню **File → Upload notebook**. Оберіть середовище з CPU та натисніть **Runtime → Run all**. Notebook містить CSV, SQL і допоміжні модулі; перша клітинка встановлює відсутні залежності та створює окрему базу. Сумісні бібліотеки Colab зберігаються. Завершальна клітинка закриває сервер. Повторний Run all створює нову базу.

Локально потрібен Python 3.9–3.12. У порожньому середовищі встановіть `python -m pip install -r requirements.txt`, відкрийте notebook у Jupyter і виконайте всі клітинки. Для відкриття notebook можна окремо встановити JupyterLab: `python -m pip install jupyterlab`.

Дані: [infectious_cases.csv з LMS](https://drive.google.com/file/d/1dQf-uVXzYPYYGgXsG1y4Q1qDdhP2miZl/view?usp=drive_link), 540 895 байтів, 10 521 рядок, 12 колонок, 245 пар Entity/Code, 1920–2023 роки. SHA-256 незміненого файла: `226a0ff1916de44182d881b00d21cd59c1d58ae2ff6ec47d7a8042d7bc03f289`.

Порожні поля імпортуються як `NULL`, нулі зберігаються, дробові показники мають тип `NUMERIC` без округлення. Ідентичність визначає пара Entity/Code; 34 сутності без Code не об’єднуються. `entities` зберігає описи сутностей, `case_stats` — показники за ключем `(entity_id, year)`. Вихідна таблиця залишається для зіставлення відновлених даних через `EXCEPT ALL` в обох напрямах.

Статистика ігнорує відсутні значення й сортує середні `DESC NULLS LAST`. Entity включає World, регіони та інші групи, що можуть перетинатися; їхні показники не підсумовуються як незалежні країни. Одиниці вимірювання не встановлено з самого CSV. `CURRENT_DATE` обчислюється під час запуску в UTC. `years_since` повертає повні роки від 1 січня; `period_average` ділить річне число на додатний дільник. Приклади містять 12, 4, 2 і 7; це рівномірні середні за період. `NULL` повертає `NULL`; недодатний дільник і нескінченні або NaN-аргументи відхиляються.

Файли: `Diuryk_final_project.ipynb` — notebook; `sql/` — сім SQL-файлів; `data/` — оригінальний CSV; `assets/` — модулі запуску; `results/` — CSV-результати; `screenshots/` — таблиці, запити й результати.

[Завдання LMS](https://www.edu.goit.global/uk/learn/43680627/52381036/53957424/homework). Назва репозиторію для подання — `goit-rdb-fp`; адреса: [github.com/humanistitel/goit-rdb-fp](https://github.com/humanistitel/goit-rdb-fp). Архів для LMS — `ФП_Diuryk_Anton.zip`; умови задають шаблон назви `ФП_ПІБ`.
