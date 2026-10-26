"""Convert the prepared grammar dataset into a Cloudflare D1 SQL import."""

import argparse
import csv
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "output/cloudflare-grammar-import"


def sql_value(value):
    return "'" + value.replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=SOURCE)
    parser.add_argument("--zip", action="store_true", help="Also create a ZIP package.")
    args = parser.parse_args()
    OUTPUT = args.out.resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    schema = (PROJECT_ROOT / "schema/grammar.sql").read_text()
    if OUTPUT != SOURCE.resolve():
        (OUTPUT / "cloudflare_schema.sql").write_text(schema)

    seed = []
    imported = {}
    for table, filename in [
        ("grammar_sources", "grammar_sources.csv"),
        ("grammar_rules", "grammar_rules.csv"),
        ("grammar_examples", "grammar_examples.csv"),
        ("grammar_vocabulary", "vocabulary_template.csv"),
    ]:
        with (SOURCE / filename).open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            columns = reader.fieldnames
            rows = list(reader)
        imported[table] = rows
        seed.append(f"-- {table}: {len(rows)} records\n")
        quoted_columns = ", ".join('"' + column + '"' for column in columns)
        for row in rows:
            values = ", ".join(sql_value(row[column]) for column in columns)
            seed.append(f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({values});\n')
    seed_sql = "".join(seed)
    (OUTPUT / "cloudflare_seed.sql").write_text(seed_sql)
    combined = schema + "\n" + seed_sql
    (OUTPUT / "cloudflare_import.sql").write_text(combined)

    # Temporary in-memory verification, not a persistent local database.
    database = sqlite3.connect(":memory:")
    database.execute("PRAGMA foreign_keys = ON")
    database.executescript(combined)
    counts = {}
    for table, expected in imported.items():
        database.row_factory = sqlite3.Row
        actual = [dict(row) for row in database.execute(f'SELECT * FROM "{table}" ORDER BY id')]
        assert len(actual) == len(expected), table
        for before, after in zip(sorted(expected, key=lambda row: row["id"]), actual):
            assert all(str(after[key]) == value for key, value in before.items()), (table, before["id"])
        counts[table] = len(actual)
    assert list(database.execute("PRAGMA foreign_key_check")) == []
    assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert database.execute("SELECT count(*) FROM grammar_examples WHERE review_status = 'approved'").fetchone()[0] == 0
    assert database.execute("SELECT json_extract(forms, '$.past') FROM grammar_vocabulary WHERE id = 'go-verb'").fetchone()[0] == "went"
    database.close()

    if OUTPUT != SOURCE.resolve():
        for path in SOURCE.iterdir():
            if path.suffix in {".csv", ".jsonl"} or path.name in {"dataset_report.json", "README.md"}:
                shutil.copy2(path, OUTPUT / path.name)
    report = {
        "status": "passed_in_memory_sqlite_import_and_roundtrip",
        "row_counts": counts,
        "foreign_key_check": "passed",
        "integrity_check": "passed",
        "json_word_forms_query": "passed",
        "record_roundtrip": "passed_for_all_fields",
        "cloudflare_deployment": "not_performed",
        "note": "SQLite verification checks SQL and data integrity; live D1 import remains to be performed.",
    }
    (OUTPUT / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n")
    if args.zip:
        archive = OUTPUT.parent / "cloudflare-grammar-import.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for path in sorted(OUTPUT.iterdir()):
                if path.is_file():
                    package.write(path, Path(OUTPUT.name) / path.name)
            package.write(__file__, Path(OUTPUT.name) / "prepare_cloudflare_import.py")
        with zipfile.ZipFile(archive) as package:
            assert package.testzip() is None
        print("PACKAGE", archive.resolve())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
