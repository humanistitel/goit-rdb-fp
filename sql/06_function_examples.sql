-- Обидві функції використано в одному запиті до нормалізованих даних.
-- number_rabies має тип numeric; обмеження таблиці відкидає NaN/Infinity.
-- Вибір лише непорожніх чисел задовольняє умову для функції кількості.
-- Дільники 12 / 4 / 2 означають місяць / квартал / півріччя відповідно.

SELECT
    stats.observation_id,
    entity.entity,
    entity.code,
    stats.year,
    pandemic.years_since(stats.year) AS years_elapsed,
    stats.number_rabies AS annual_number_rabies,
    pandemic.period_average(stats.number_rabies, 12::numeric) AS monthly_average,
    pandemic.period_average(stats.number_rabies, 4::numeric) AS quarterly_average,
    pandemic.period_average(stats.number_rabies, 2::numeric) AS half_year_average
FROM pandemic.case_stats AS stats
JOIN pandemic.entities AS entity USING (entity_id)
WHERE stats.number_rabies IS NOT NULL
ORDER BY entity.entity COLLATE "C", entity.code COLLATE "C" NULLS LAST,
         stats.year, stats.observation_id;
