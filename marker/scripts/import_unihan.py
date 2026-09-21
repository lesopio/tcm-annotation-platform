"""Import a locally supplied official Unicode Unihan.zip into the character index.

This script never downloads data. Obtain a pinned Unihan.zip from unicode.org,
then run after the backend has created the v2 tables:
    python marker/scripts/import_unihan.py path/to/Unihan.zip
"""
from __future__ import annotations

import argparse
import sqlite3
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "marker" / "data" / "bencao_vsr.sqlite3"
FIELDS = {
    "kRSUnicode": "radical",
    "kTotalStrokes": "strokes",
    "kMandarin": "readings",
    "kCantonese": "readings",
    "kDefinition": "aliases",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("unihan_zip", type=Path)
    args = parser.parse_args()
    if not args.unihan_zip.is_file():
        raise SystemExit(f"File not found: {args.unihan_zip}")
    records: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(args.unihan_zip) as archive:
        for name in archive.namelist():
            if not name.startswith("Unihan_") or not name.endswith(".txt"):
                continue
            for raw in archive.read(name).decode("utf-8").splitlines():
                if not raw or raw.startswith("#"):
                    continue
                code, field, value = raw.split("\t", 2)
                if field not in FIELDS:
                    continue
                row = records.setdefault(code, {})
                target = FIELDS[field]
                row[target] = f"{row.get(target, '')} {value}".strip()
    con = sqlite3.connect(DB_PATH)
    try:
        admin = con.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
        if not admin:
            raise SystemExit("Create an admin user before importing Unihan")
        for code, values in records.items():
            cp = int(code[2:], 16)
            exists = con.execute("SELECT 1 FROM character_entries WHERE unicode_codepoint=? AND status='global'", (code,)).fetchone()
            if exists:
                continue
            radical = values.get("radical", "").split(".", 1)[0]
            strokes_raw = values.get("strokes", "").split()[0] if values.get("strokes") else ""
            strokes = int(strokes_raw) if strokes_raw.isdigit() else None
            con.execute(
                "INSERT INTO character_entries (book_id,unicode_codepoint,character,ids,radical,strokes,readings,aliases,glyph_path,status,created_by,created_at,updated_at) VALUES (NULL,?,?,?,?,?,?,?,?, 'global',?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                (code, chr(cp), "", radical, strokes, values.get("readings", ""), values.get("aliases", ""), "", admin[0]),
            )
        con.commit()
        print(f"Imported {len(records)} Unihan records into {DB_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
