"""Portable PostgreSQL checks with an independent CSV/Decimal reference.

``check_project(run)`` checks an already loaded ProjectRun, returns a JSON-safe
summary, and raises ProjectCheckError with that summary if any check fails.
The checks need only the standard library and the existing database connection.
All mutation probes roll back; explicit IDs also preserve identity sequences.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
import csv
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import io
from pathlib import Path


SOURCE_SHA256 = "226a0ff1916de44182d881b00d21cd59c1d58ae2ff6ec47d7a8042d7bc03f289"
SOURCE_COLUMNS = (
    "Entity", "Code", "Year", "Number_yaws", "polio_cases",
    "cases_guinea_worm", "Number_rabies", "Number_malaria", "Number_hiv",
    "Number_tuberculosis", "Number_smallpox", "Number_cholera_cases",
)
MEASURES = tuple(column.lower() for column in SOURCE_COLUMNS[3:])
SQL_COLUMNS = tuple(column.lower() for column in SOURCE_COLUMNS)
RELATIVE_TOLERANCE = Decimal("1e-16")


class ProjectCheckError(AssertionError):
    def __init__(self, summary):
        self.summary = summary
        failed = [item["name"] for item in summary["checks"] if not item["passed"]]
        super().__init__("Project checks failed: " + ", ".join(failed))


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _rows(run, sql, params=None):
    with run.conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _close_decimal(actual, expected, label):
    if expected is None:
        _require(actual is None, f"{label}: expected NULL, got {actual!r}")
        return
    _require(isinstance(actual, Decimal) and actual.is_finite(),
             f"{label}: expected finite NUMERIC/Decimal, got {actual!r}")
    with localcontext() as context:
        context.prec = 60
        tolerance = abs(expected) * RELATIVE_TOLERANCE
        _require(abs(actual - expected) <= tolerance,
                 f"{label}: {actual} differs from {expected}; tolerance {tolerance}")


def _elapsed_years(year, reference):
    """Signed completed anniversaries; independent of SQL AGE."""
    if year is None:
        return None
    anchor = date(year, 1, 1)
    earlier, later = sorted((anchor, reference))
    count = later.year - earlier.year - ((later.month, later.day) < (earlier.month, earlier.day))
    return count if reference >= anchor else -count


def _source_reference(path):
    payload = Path(path).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    _require(digest == SOURCE_SHA256, "Source CSV SHA-256 mismatch")
    reader = csv.reader(io.StringIO(payload.decode("utf-8"), newline=""), strict=True)
    _require(tuple(next(reader)) == SOURCE_COLUMNS, "Source CSV header mismatch")
    rows, grouped = [], defaultdict(list)
    for source_id, row in enumerate(reader, 1):
        _require(len(row) == 12, f"CSV row {source_id}: wrong width")
        values = tuple(None if text == "" else Decimal(text) for text in row[3:])
        _require(all(value is None or (value.is_finite() and value >= 0) for value in values),
                 f"CSV row {source_id}: unexpected non-finite or negative measure")
        typed = (source_id, row[0], row[1] or None, int(row[2]), *values)
        rows.append(typed)
        grouped[(typed[1], typed[2])].append(typed)
    _require(len(rows) == 10521 and len(grouped) == 245, "Source dimensions differ")
    groups = {}
    with localcontext() as context:
        context.prec = 60
        for key, observations in grouped.items():
            values = [row[7] for row in observations if row[7] is not None]
            total = sum(values, Decimal(0)) if values else None
            groups[key] = {
                "rows": len(observations), "count": len(values),
                "avg": total / len(values) if values else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None, "sum": total,
            }
        ranked = sorted(groups, key=lambda key: (
            groups[key]["avg"] is None,
            -groups[key]["avg"] if groups[key]["avg"] is not None else Decimal(0),
            key[0], key[1] is None, key[1] or "",
        ))
    return {"sha256": digest, "rows": rows, "groups": groups, "ranked": ranked}


@contextmanager
def _rollback(run):
    """Preserve a caller's transaction, or use a new rolled-back transaction."""
    own_transaction = run.conn.get_transaction_status() == 0
    with run.conn.cursor() as cursor:
        cursor.execute("BEGIN" if own_transaction else "SAVEPOINT fp_check_rollback")
        try:
            yield cursor
        finally:
            if own_transaction:
                cursor.execute("ROLLBACK")
            else:
                cursor.execute("ROLLBACK TO SAVEPOINT fp_check_rollback")
                cursor.execute("RELEASE SAVEPOINT fp_check_rollback")


def _expect_sqlstate(run, sql, params, state, constraint=None):
    caught = None
    with _rollback(run) as cursor:
        try:
            cursor.execute(sql, params)
        except Exception as error:
            caught = error
    _require(caught is not None, f"Expected SQLSTATE {state}, statement succeeded")
    _require(getattr(caught, "pgcode", None) == state,
             f"Expected SQLSTATE {state}, got {getattr(caught, 'pgcode', None)}: {caught}")
    if constraint:
        _require(caught.diag.constraint_name == constraint,
                 f"Expected constraint {constraint}, got {caught.diag.constraint_name}")


def check_project(run):
    """Verify real database state and functions without changing project data."""
    root = Path(run.root)
    reference = _source_reference(root / "data" / "infectious_cases.csv")
    summary = {"passed": False, "checks_passed": 0, "total_checks": 0,
               "source_sha256": reference["sha256"], "checks": []}
    initial_transaction_status = run.conn.get_transaction_status()
    initial_counts = tuple(run.scalar(f"SELECT count(*) FROM pandemic.{table}")
                           for table in ("infectious_cases", "entities", "case_stats"))
    sequence_sql = "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname='pandemic' ORDER BY sequencename"
    initial_sequences = _rows(run, sequence_sql)
    current_date = run.scalar("SELECT CURRENT_DATE")
    summary["database_date"] = current_date.isoformat()
    summary["database_version"] = run.scalar("SHOW server_version")

    def record(name, action):
        try:
            details = action()
        except Exception as error:
            summary["checks"].append({"name": name, "passed": False,
                                      "error": f"{type(error).__name__}: {error}"})
        else:
            item = {"name": name, "passed": True}
            if details is not None:
                item["details"] = details
            summary["checks"].append(item)

    def row_counts():
        _require(initial_counts == (10521, 245, 10521), f"Wrong row counts: {initial_counts}")
        return dict(zip(("raw", "entities", "facts"), initial_counts))
    record("exact_row_counts", row_counts)

    def exact_import():
        observed = _rows(run, "SELECT source_row_id, " + ", ".join(SQL_COLUMNS)
                         + " FROM pandemic.infectious_cases ORDER BY source_row_id")
        _require(observed == reference["rows"], "Imported rows differ from original CSV values/order")
        return {"rows": len(observed), "source_fields_per_row": 12, "all_values_equal": True}
    record("all_csv_fields_exact", exact_import)

    def numeric_storage():
        metadata = _rows(run, """SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
            FROM information_schema.columns WHERE table_schema='pandemic'
            AND table_name IN ('infectious_cases', 'case_stats') AND column_name = ANY(%s)""", (list(MEASURES),))
        _require(len(metadata) == 18, "Expected nine measure columns in each of two tables")
        _require(all(row[2:] == ("numeric", None, None) for row in metadata),
                 "Measure columns must be unconstrained NUMERIC")
        numeric = [row[7] for row in reference["rows"] if row[7] is not None]
        _require(sum(value != value.to_integral_value() for value in numeric) == 6780,
                 "Expected 6780 fractional rabies values")
        _require(max(-value.as_tuple().exponent for value in numeric) == 12,
                 "Expected source precision through twelve decimal places")
        _require(run.scalar("SELECT count(*) FROM pandemic.case_stats WHERE number_rabies <> trunc(number_rabies)") == 6780,
                 "Fractional rabies data was rounded")
        fraction = Decimal("123.123456789012345678901234567890")
        with _rollback(run) as cursor:
            cursor.execute("INSERT INTO pandemic.infectious_cases (source_row_id,entity,year,number_rabies) VALUES (-900001,'Precision fixture',9999,%s) RETURNING number_rabies", (fraction,))
            _require(cursor.fetchone()[0] == fraction, "Raw NUMERIC truncates fractional fixture")
            cursor.execute("INSERT INTO pandemic.case_stats (observation_id,entity_id,year,number_rabies) SELECT -900001,min(entity_id),9999,%s FROM pandemic.entities RETURNING number_rabies", (fraction,))
            _require(cursor.fetchone()[0] == fraction, "Normalized NUMERIC truncates fractional fixture")
        return {"unconstrained_numeric_columns": 18, "fractional_rabies_rows": 6780,
                "source_max_decimal_places": 12, "stored_fixture_decimal_places": 30}
    record("numeric_fraction_preservation", numeric_storage)

    def null_codes():
        counts = _rows(run, """SELECT (SELECT count(*) FROM pandemic.entities WHERE code IS NULL),
            (SELECT count(*) FROM pandemic.infectious_cases WHERE code IS NULL),
            (SELECT count(*) FROM pandemic.case_stats JOIN pandemic.entities USING(entity_id) WHERE code IS NULL)""")[0]
        _require(counts == (34, 1128, 1128), f"NULL Code identity/rows lost: {counts}")
        return {"distinct_entities": counts[0], "raw_rows": counts[1], "fact_rows": counts[2]}
    record("null_code_entities_preserved", null_codes)

    def lossless():
        result = run.query((root / "sql" / "07_validation.sql").read_text(encoding="utf-8"))
        row = result.iloc[0]
        _require(int(row["source_only_rows"]) == int(row["reconstructed_only_rows"]) == 0,
                 "EXCEPT ALL found lost, changed, or additional rows")
        _require(int(row["rabies_numeric_rows"]) == 6780 and int(row["rabies_missing_rows"]) == 3741,
                 "Rabies NULL/number counts differ")
        return {"source_only_rows": 0, "reconstructed_only_rows": 0,
                "comparison": "both directions EXCEPT ALL; source id and all 12 source fields"}
    record("lossless_except_all", lossless)

    def constraints():
        entity_id, entity, code = _rows(run, "SELECT entity_id,entity,code FROM pandemic.entities WHERE code IS NOT NULL ORDER BY entity_id LIMIT 1")[0]
        null_entity = _rows(run, "SELECT entity FROM pandemic.entities WHERE code IS NULL ORDER BY entity_id LIMIT 1")[0][0]
        observation_id, fact_entity, year = _rows(run, "SELECT observation_id,entity_id,year FROM pandemic.case_stats ORDER BY observation_id LIMIT 1")[0]
        probes = [
            ("raw_primary_key", "INSERT INTO pandemic.infectious_cases(source_row_id,entity,year) VALUES (1,'PK fixture',9999)", None, "23505", "infectious_cases_pkey"),
            ("entity_primary_key", "INSERT INTO pandemic.entities(entity_id,entity,code) VALUES (%s,'PK fixture','fixture')", (entity_id,), "23505", "entities_pkey"),
            ("fact_primary_key", "INSERT INTO pandemic.case_stats(observation_id,entity_id,year) VALUES (%s,%s,9999)", (observation_id, fact_entity), "23505", "case_stats_pkey"),
            ("nonnull_pair_unique", "INSERT INTO pandemic.entities(entity_id,entity,code) VALUES (-900001,%s,%s)", (entity, code), "23505", "entities_entity_code_key"),
            ("null_pair_unique", "INSERT INTO pandemic.entities(entity_id,entity,code) VALUES (-900001,%s,NULL)", (null_entity,), "23505", "entities_entity_code_key"),
            ("entity_year_unique", "INSERT INTO pandemic.case_stats(observation_id,entity_id,year) VALUES (-900001,%s,%s)", (fact_entity, year), "23505", "case_stats_entity_year_key"),
            ("fact_foreign_key", "INSERT INTO pandemic.case_stats(observation_id,entity_id,year) VALUES (-900001,-900001,9999)", None, "23503", "case_stats_entity_id_fkey"),
        ]
        for label, sql, params, state, constraint in probes:
            _expect_sqlstate(run, sql, params, state, constraint)
        _require(run.scalar("""SELECT i.indnullsnotdistinct FROM pg_index i
            JOIN pg_constraint c ON c.conindid=i.indexrelid
            WHERE c.conrelid='pandemic.entities'::regclass AND c.conname='entities_entity_code_key'""") is True,
                 "Entity pair uniqueness does not use NULLS NOT DISTINCT")
        with _rollback(run) as cursor:
            cursor.execute("INSERT INTO pandemic.entities(entity_id,entity,code) VALUES (-900001,'Independent null fixture A',NULL),(-900002,'Independent null fixture B',NULL),(-900003,'Independent null fixture A','OTHER')")
        return {"rejected_real_inserts": [probe[0] for probe in probes],
                "different_null_entities_and_second_code_allowed": True, "all_probes_rolled_back": True}
    record("keys_and_uniqueness_real_mutations", constraints)

    aggregate_sql = """SELECT e.entity_id,e.entity,e.code,count(*) AS rows,
        count(s.number_rabies) AS observed_years,avg(s.number_rabies) AS avg_number_rabies,
        min(s.number_rabies) AS min_number_rabies,max(s.number_rabies) AS max_number_rabies,
        sum(s.number_rabies) AS sum_number_rabies FROM pandemic.entities e
        JOIN pandemic.case_stats s USING(entity_id) GROUP BY e.entity_id,e.entity,e.code
        ORDER BY avg_number_rabies DESC NULLS LAST,e.entity COLLATE "C",e.code COLLATE "C" NULLS LAST,e.entity_id"""

    def aggregates():
        observed = _rows(run, aggregate_sql)
        _require(len(observed) == 245, "Expected 245 aggregate groups")
        _require({(row[1], row[2]) for row in observed} == set(reference["groups"]), "Group identities differ")
        for row in observed:
            key = (row[1], row[2])
            expected = reference["groups"][key]
            _require(row[3] == expected["rows"] and row[4] == expected["count"], f"Wrong group counts: {key}")
            _close_decimal(row[5], expected["avg"], f"AVG {key}")
            _require(row[6:9] == (expected["min"], expected["max"], expected["sum"]), f"MIN/MAX/SUM mismatch: {key}")
        return {"groups": 245, "exact_min_max_sum": True, "avg_relative_tolerance": str(RELATIVE_TOLERANCE)}
    record("all_245_rabies_aggregates_vs_raw_decimal", aggregates)

    def ranking():
        observed = _rows(run, aggregate_sql)
        _require([(row[1], row[2]) for row in observed] == reference["ranked"], "Full ranking differs from CSV Decimal ordering")
        null_tail = [row for row in observed if row[5] is None]
        _require(len(null_tail) == 19 and all(row[5] is None for row in observed[-19:]), "All-NULL groups are not the final 19 groups")
        return {"ordered_groups": 245, "null_average_groups_at_end": 19}
    record("rank_order_and_nulls_last", ranking)

    analysis_sql = (root / "sql" / "03_analysis.sql").read_text(encoding="utf-8")

    def top_ten():
        observed = run.query(analysis_sql).to_dict(orient="records")
        _require(len(observed) == 10, "Analysis SQL did not return exactly ten rows")
        identities = [(row["entity"], row["code"]) for row in observed]
        _require(identities == reference["ranked"][:10], "Analysis SQL top-ten identity/order mismatch")
        for row, key in zip(observed, identities):
            expected = reference["groups"][key]
            _require(int(row["observed_years"]) == expected["count"], f"Top-ten numeric count: {key}")
            _close_decimal(row["avg_number_rabies"], expected["avg"], f"top-ten AVG {key}")
            for column, metric in (("min_number_rabies", "min"), ("max_number_rabies", "max"), ("sum_number_rabies", "sum")):
                _require(row[column] == expected[metric], f"Top-ten {metric}: {key}")
        return {"rows": 10, "entities_in_order": [key[0] for key in identities]}
    record("actual_analysis_sql_top10", top_ten)

    def ranking_fixture():
        # Run the delivered query itself against small controlled relations.
        fixture_sql = analysis_sql.replace("pandemic.entities", "pg_temp.fp_check_entities").replace("pandemic.case_stats", "pg_temp.fp_check_stats")
        with _rollback(run) as cursor:
            cursor.execute("CREATE TEMP TABLE fp_check_entities(entity_id bigint,entity text,code text)")
            cursor.execute("CREATE TEMP TABLE fp_check_stats(entity_id bigint,number_rabies numeric)")
            pairs = [(1, "All NULL", None), (2, "Alpha", None), (3, "Alpha", "B"),
                     (4, "Alpha", "A"), (5, "Beta", "B")]
            pairs += [(index, f"Tail {index:02d}", None) for index in range(6, 15)]
            cursor.executemany("INSERT INTO fp_check_entities VALUES (%s,%s,%s)", pairs)
            values = [(1, None), (2, Decimal("2.5")), (2, None), (3, Decimal("2.5")),
                      (4, Decimal("2.5")), (5, Decimal("0"))]
            values += [(index, Decimal("1") / index) for index in range(6, 15)]
            cursor.executemany("INSERT INTO fp_check_stats VALUES (%s,%s)", values)
            cursor.execute(fixture_sql)
            observed = cursor.fetchall()
            _require(len(observed) == 10, "Fixture did not honor LIMIT 10")
            _require([row[0] for row in observed] == [4, 3, 2, 6, 7, 8, 9, 10, 11, 12],
                     "Tie breaking, Code NULL order, average ordering or NULLS LAST failed")
            _require(observed[0][4:8] == (Decimal("2.5"),) * 4, "Fixture aggregates incorrectly include missing values")
        return {"fixture_groups": 14, "rows_returned": 10, "ties_and_null_codes_checked": True}
    record("analysis_sql_tie_and_null_fixture", ranking_fixture)

    def date_query():
        observed = _rows(run, (root / "sql" / "04_dates.sql").read_text(encoding="utf-8"))
        _require(len(observed) == len(reference["rows"]), "Date SQL lost observations")
        for result, source in zip(observed, reference["rows"]):
            _require(result[:4] == source[:4], f"Date row identity mismatch: {source[0]}")
            _require(result[4:] == (date(source[3], 1, 1), current_date, _elapsed_years(source[3], current_date)),
                     f"Built-in date result mismatch: {source[0]}")
        return {"rows": len(observed), "reference_date": current_date.isoformat()}
    record("actual_dates_sql_all_observations", date_query)

    def date_fixtures():
        fixtures = [(1996, "2024-01-01", 28), (1996, "2024-02-29", 28),
                    (1996, "2023-12-31", 27), (2024, "2024-01-01", 0),
                    (2024, "2023-12-31", 0), (2024, "2023-01-01", -1),
                    (2025, "2023-12-31", -1), (2000, "2000-02-29", 0)]
        for year, reference_date, expected in fixtures:
            parsed = date.fromisoformat(reference_date)
            _require(_elapsed_years(year, parsed) == expected, "Independent date fixture is inconsistent")
            value = run.scalar("SELECT extract(year FROM age(%s::date,make_date(%s,1,1)))::integer", (reference_date, year))
            _require(value == expected, f"Date fixture {year}/{reference_date}: {value}, expected {expected}")
        return {"fixtures": len(fixtures), "leap_day_future_and_anniversary_cases": True}
    record("builtin_date_leap_and_future_fixtures", date_fixtures)

    def year_function():
        years = sorted({row[3] for row in reference["rows"]} | {1996, 2000, 2024, current_date.year, current_date.year + 1, current_date.year + 2})
        for year in years + [None]:
            result = _rows(run, "SELECT pandemic.years_since(%s::integer),extract(year FROM age(CURRENT_DATE,make_date(%s::integer,1,1)))::integer", (year, year))[0]
            expected = _elapsed_years(year, current_date)
            _require(result == (expected, expected), f"years_since({year}): {result}, expected {expected}")
        return {"distinct_years_plus_null": len(years) + 1, "future_years": [current_date.year + 1, current_date.year + 2],
                "assignment_example_1996": _elapsed_years(1996, current_date)}
    record("year_function_vs_builtin_and_python", year_function)

    def function_contract():
        for signature, result, volatility in (("pandemic.years_since(integer)", "integer", "s"),
                                                ("pandemic.period_average(numeric,numeric)", "numeric", "i")):
            row = _rows(run, "SELECT prorettype::regtype::text,provolatile,proisstrict FROM pg_proc WHERE oid=to_regprocedure(%s)", (signature,))
            _require(row == [(result, volatility, True)], f"Function signature/strictness/volatility mismatch: {signature}: {row}")
        return {"years_since": "integer -> integer; STABLE STRICT", "period_average": "numeric,numeric -> numeric; IMMUTABLE STRICT"}
    record("function_catalog_contract", function_contract)

    def period_valid():
        fixtures = [("100", "12"), ("100", "4"), ("100", "2"),
                    ("120.75", "12"), ("0", "12"), ("100", "0.5"),
                    ("-8", "2"), ("120.123456789012", "12"),
                    ("1.000000000001", "2"), ("123.123456789012345678901234567890", "0.5"),
                    (None, "12"), ("100", None), (None, "0"), ("NaN", None), (None, "NaN")]
        with localcontext() as context:
            context.prec = 60
            for annual, divisor in fixtures:
                expected = None if annual is None or divisor is None else Decimal(annual) / Decimal(divisor)
                observed = run.scalar("SELECT pandemic.period_average(%s::numeric,%s::numeric)", (annual, divisor))
                _close_decimal(observed, expected, f"period_average({annual},{divisor})")
                if expected is not None and divisor in ("2", "4", "0.5"):
                    _require(observed == expected, "Terminating period fraction lost precision")
        return {"fixtures": len(fixtures), "required_divisors": [12, 4, 2], "strict_null_before_invalid_argument": True,
                "negative_finite_annual_allowed": True, "fractional_positive_divisor": True}
    record("period_function_valid_null_and_precision_fixtures", period_valid)

    def period_invalid():
        fixtures = [("100", "0"), ("100", "-2")]
        fixtures += [(value, "12") for value in ("NaN", "Infinity", "-Infinity")]
        fixtures += [("100", value) for value in ("NaN", "Infinity", "-Infinity")]
        for annual, divisor in fixtures:
            _expect_sqlstate(run, "SELECT pandemic.period_average(%s::numeric,%s::numeric)", (annual, divisor), "22023")
        return {"rejected_real_calls": len(fixtures), "expected_sqlstate": "22023", "nonfinite_checked_in_both_arguments": True}
    record("period_function_invalid_sqlstates", period_invalid)

    def period_data():
        observed = _rows(run, (root / "sql" / "06_function_examples.sql").read_text(encoding="utf-8"))
        source_by_id = {row[0]: row for row in reference["rows"] if row[7] is not None}
        _require(len(observed) == len(source_by_id) == 6780, "Function examples must use exactly the 6780 numeric rabies rows")
        _require({row[0] for row in observed} == set(source_by_id), "Function examples lost or duplicated numeric observations")
        with localcontext() as context:
            context.prec = 60
            for row in observed:
                source = source_by_id[row[0]]
                _require(row[:4] == source[:4] and row[4] == _elapsed_years(source[3], current_date) and row[5] == source[7],
                         f"Function example source/date mismatch: {row[0]}")
                for actual, divisor in zip(row[6:9], (12, 4, 2)):
                    _close_decimal(actual, source[7] / divisor, f"period data {row[0]}/{divisor}")
        return {"numeric_observations": 6780, "period_results_checked": 20340, "null_rabies_excluded": 3741}
    record("actual_function_examples_all_numeric_rows", period_data)

    def unchanged():
        final_counts = tuple(run.scalar(f"SELECT count(*) FROM pandemic.{table}")
                             for table in ("infectious_cases", "entities", "case_stats"))
        _require(final_counts == initial_counts, "Mutation tests changed project row counts")
        _require(_rows(run, sequence_sql) == initial_sequences, "Mutation tests advanced identity sequences")
        _require(_rows(run, "SELECT source_row_id, " + ", ".join(SQL_COLUMNS)
                       + " FROM pandemic.infectious_cases ORDER BY source_row_id") == reference["rows"],
                 "Mutation tests changed source values")
        _require(run.conn.get_transaction_status() == initial_transaction_status,
                 "Checks changed the caller's transaction status")
        return {"row_counts_unchanged": True, "source_values_unchanged": True, "identity_sequences_unchanged": True}
    record("rollback_and_repeat_safety", unchanged)

    summary["total_checks"] = len(summary["checks"])
    summary["checks_passed"] = sum(check["passed"] for check in summary["checks"])
    summary["passed"] = summary["checks_passed"] == summary["total_checks"]
    if not summary["passed"]:
        raise ProjectCheckError(summary)
    return summary
