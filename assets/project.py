"""PostgreSQL execution helpers for the infectious-cases project."""
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile

import pandas as pd
import psycopg2

from runtime_bootstrap import get_local_server

DATA_SHA256 = "226a0ff1916de44182d881b00d21cd59c1d58ae2ff6ec47d7a8042d7bc03f289"
SOURCE_COLUMNS = ["Entity", "Code", "Year", "Number_yaws", "polio_cases",
                  "cases_guinea_worm", "Number_rabies", "Number_malaria",
                  "Number_hiv", "Number_tuberculosis", "Number_smallpox",
                  "Number_cholera_cases"]
SQL_COLUMNS = [name.lower() for name in SOURCE_COLUMNS]


class ProjectRun:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.temporary = tempfile.TemporaryDirectory(prefix="rdb-fp-")
        self.server = None
        self.conn = None
        self.closed = False
        try:
            self.server = get_local_server(Path(self.temporary.name) / "pgdata", cleanup_mode="stop")
            self.conn = psycopg2.connect(self.server.get_uri())
            self.conn.autocommit = True
            self.execute("SET TIME ZONE 'UTC'")
            version = self.query("SELECT version() AS postgresql, CURRENT_DATE AS run_date, current_setting('TimeZone') AS time_zone")
            if self.scalar("SELECT current_setting('server_version_num')::integer") // 10000 != 16:
                raise RuntimeError("This project requires PostgreSQL 16.")
            self.environment = version
        except BaseException:
            self.close()
            raise

    def execute(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

    def query(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

    def scalar(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]

    def script(self, name):
        source = (self.root / "sql" / name).read_text(encoding="utf-8")
        self.execute(source)
        return source

    def import_csv(self):
        data = (self.root / "data" / "infectious_cases.csv").read_bytes()
        if hashlib.sha256(data).hexdigest() != DATA_SHA256:
            raise ValueError("The infectious_cases.csv checksum does not match the original source.")
        text = data.decode("utf-8")
        reader = csv.reader(io.StringIO(text, newline=""))
        if next(reader) != SOURCE_COLUMNS:
            raise ValueError("Unexpected source CSV header.")
        rows = list(reader)
        if len(rows) != 10521 or any(len(row) != 12 for row in rows):
            raise ValueError("Unexpected source CSV dimensions.")
        self.execute("TRUNCATE pandemic.infectious_cases RESTART IDENTITY")
        columns = ", ".join(SQL_COLUMNS)
        with self.conn.cursor() as cur:
            cur.copy_expert("COPY pandemic.infectious_cases (" + columns + ") FROM STDIN WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')", io.StringIO(text, newline=""))
        count = self.scalar("SELECT count(*) FROM pandemic.infectious_cases")
        if count != len(rows):
            raise AssertionError("COPY row count differs from the source.")
        return count

    def save_results(self, name, frame):
        out = self.root / "results"
        out.mkdir(exist_ok=True)
        frame.to_csv(out / (name + ".csv"), index=False)

    def close(self):
        if self.closed:
            return
        if self.conn is not None and not self.conn.closed:
            self.conn.close()
        if self.server is not None:
            self.server.cleanup()
        self.temporary.cleanup()
        self.closed = True

