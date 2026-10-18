-- Збереження значень перевіряється в обох напрямках із EXCEPT ALL.
-- ALL враховує кратність рядків; до порівняння включено всі дев'ять показників.

WITH reconstructed AS (
    SELECT
        stats.observation_id AS source_row_id,
        entity.entity, entity.code, stats.year,
        stats.number_yaws, stats.polio_cases, stats.cases_guinea_worm,
        stats.number_rabies, stats.number_malaria, stats.number_hiv,
        stats.number_tuberculosis, stats.number_smallpox,
        stats.number_cholera_cases
    FROM pandemic.case_stats AS stats
    JOIN pandemic.entities AS entity USING (entity_id)
), source_only AS (
    SELECT * FROM pandemic.infectious_cases
    EXCEPT ALL
    SELECT * FROM reconstructed
), reconstructed_only AS (
    SELECT * FROM reconstructed
    EXCEPT ALL
    SELECT * FROM pandemic.infectious_cases
)
SELECT
    (SELECT count(*) FROM pandemic.infectious_cases) AS source_rows,
    (SELECT count(*) FROM pandemic.entities) AS entity_rows,
    (SELECT count(*) FROM pandemic.case_stats) AS normalized_rows,
    (SELECT count(*) FROM pandemic.entities WHERE code IS NULL) AS entities_without_code,
    (SELECT count(*) FROM pandemic.infectious_cases WHERE code IS NULL) AS source_rows_without_code,
    (SELECT count(*) FROM reconstructed WHERE code IS NULL) AS normalized_rows_without_code,
    (SELECT count(*) FROM source_only) AS source_only_rows,
    (SELECT count(*) FROM reconstructed_only) AS reconstructed_only_rows,
    (SELECT count(number_rabies) FROM pandemic.case_stats) AS rabies_numeric_rows,
    (SELECT count(*) FROM pandemic.case_stats WHERE number_rabies IS NULL) AS rabies_missing_rows,
    (SELECT min(year) FROM pandemic.case_stats) AS first_year,
    (SELECT max(year) FROM pandemic.case_stats) AS last_year;
