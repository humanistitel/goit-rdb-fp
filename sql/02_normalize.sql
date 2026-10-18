-- Завдання 2. Нормалізація до 3НФ без втрати рядків і показників.
-- entities: entity_id -> (entity, code).
-- case_stats: observation_id та (entity_id, year) -> дев'ять показників.
-- Пара entity/code зберігається один раз; у фактах залишається зовнішній ключ.

SET search_path TO pandemic;

TRUNCATE TABLE pandemic.case_stats, pandemic.entities RESTART IDENTITY;

INSERT INTO pandemic.entities (entity, code)
SELECT entity, code
FROM (
    SELECT DISTINCT entity, code
    FROM pandemic.infectious_cases
) AS unique_pairs
ORDER BY entity COLLATE "C", code COLLATE "C" NULLS LAST;

INSERT INTO pandemic.case_stats (
    observation_id, entity_id, year,
    number_yaws, polio_cases, cases_guinea_worm, number_rabies,
    number_malaria, number_hiv, number_tuberculosis,
    number_smallpox, number_cholera_cases
)
SELECT
    source.source_row_id, entity.entity_id, source.year,
    source.number_yaws, source.polio_cases, source.cases_guinea_worm,
    source.number_rabies, source.number_malaria, source.number_hiv,
    source.number_tuberculosis, source.number_smallpox,
    source.number_cholera_cases
FROM pandemic.infectious_cases AS source
JOIN pandemic.entities AS entity
  ON entity.entity IS NOT DISTINCT FROM source.entity
 AND entity.code IS NOT DISTINCT FROM source.code
ORDER BY source.source_row_id;

-- IS NOT DISTINCT FROM зіставляє також дві відсутні мітки Code.
-- Це зберігає 34 різні сутності з порожнім кодом, а не зливає їх в одну.
ANALYZE pandemic.entities;
ANALYZE pandemic.case_stats;
