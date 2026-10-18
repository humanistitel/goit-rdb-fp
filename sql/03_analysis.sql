-- Завдання 3. Десять найбільших середніх Number_rabies за парою Entity/Code.
-- NULL не підміняється нулем. Групи без вимірювань розташовані наприкінці.
-- Додаткові ключі забезпечують відтворюваний порядок однакових середніх.

SELECT
    entity.entity_id,
    entity.entity,
    entity.code,
    count(stats.number_rabies) AS observed_years,
    avg(stats.number_rabies) AS avg_number_rabies,
    min(stats.number_rabies) AS min_number_rabies,
    max(stats.number_rabies) AS max_number_rabies,
    sum(stats.number_rabies) AS sum_number_rabies
FROM pandemic.entities AS entity
JOIN pandemic.case_stats AS stats USING (entity_id)
GROUP BY entity.entity_id, entity.entity, entity.code
ORDER BY avg_number_rabies DESC NULLS LAST,
         entity.entity COLLATE "C",
         entity.code COLLATE "C" NULLS LAST,
         entity.entity_id
LIMIT 10;
