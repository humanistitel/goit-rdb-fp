-- Завдання 5. Дві незалежні функції, доступні зі звичайного SQL-запиту.
-- years_since: повні календарні роки; NULL -> NULL; поточна дата -> STABLE.

CREATE OR REPLACE FUNCTION pandemic.years_since(source_year integer)
RETURNS integer
LANGUAGE sql
STABLE
STRICT
RETURN extract(
    year FROM pg_catalog.age(CURRENT_DATE, pg_catalog.make_date(source_year, 1, 1))
)::integer;

-- period_average: рівномірне середнє за частину року, а не окреме вимірювання.
-- Дільник повинен бути додатним; 0 та від'ємні значення викликають помилку.
-- NaN та нескінченності в обох аргументах також викликають помилку.
-- NULL в будь-якому аргументі -> NULL завдяки STRICT.
-- numeric / numeric зберігає дробову частину результату.
CREATE OR REPLACE FUNCTION pandemic.period_average(
    annual_cases numeric,
    divisor numeric
)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $function$
BEGIN
    IF annual_cases IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
       OR divisor IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) THEN
        RAISE EXCEPTION 'Аргументи повинні бути скінченними числами'
            USING ERRCODE = '22023';
    END IF;
    IF divisor <= 0 THEN
        RAISE EXCEPTION 'Дільник повинен бути додатним: %', divisor
            USING ERRCODE = '22023';
    END IF;
    RETURN annual_cases / divisor;
END;
$function$;
