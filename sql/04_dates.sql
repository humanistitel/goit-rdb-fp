-- Завдання 4. Повні календарні роки від 1 січня року спостереження.
-- CURRENT_DATE визначається датою початку поточної транзакції.

SELECT
    stats.observation_id,
    entity.entity,
    entity.code,
    stats.year,
    make_date(stats.year, 1, 1) AS year_start,
    CURRENT_DATE AS current_date,
    extract(year FROM age(CURRENT_DATE, make_date(stats.year, 1, 1)))::integer
        AS years_elapsed
FROM pandemic.case_stats AS stats
JOIN pandemic.entities AS entity USING (entity_id)
ORDER BY stats.observation_id;
