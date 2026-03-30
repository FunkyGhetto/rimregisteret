from __future__ import annotations

"""Update frequency column in rimindeks.db from frequencies.jsonl.

Reads data/processed/frequencies.jsonl and updates the frekvens column
in data/db/rimindeks.db for matching words.
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FREQ_FILE = PROJECT_ROOT / "data/processed/frequencies.jsonl"
DB_FILE = PROJECT_ROOT / "data/db/rimindeks.db"
LOG_FILE = PROJECT_ROOT / "data/processed/frequency_match.log"


def update_frequencies(freq_path: Path, db_path: Path, log_path: Path) -> dict:
    """Update frequency column in the database."""
    # Load frequency data
    freq_map = {}
    with open(freq_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            freq_map[r["ord"]] = r["frekvens"]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get all distinct words in the DB
    cur = conn.execute("SELECT DISTINCT ord FROM ord")
    db_words = {row["ord"] for row in cur}

    stats = {
        "db_words": len(db_words),
        "freq_words": len(freq_map),
        "matched": 0,
        "matched_lowercase": 0,
        "unmatched_db": 0,
        "unmatched_freq": 0,
    }

    # Update frequencies — try exact match, then lowercase
    batch = []
    matched_db_words = set()

    for db_word in db_words:
        freq = freq_map.get(db_word.lower())
        if freq is not None:
            batch.append((freq, db_word))
            matched_db_words.add(db_word)
            if db_word != db_word.lower():
                stats["matched_lowercase"] += 1
            else:
                stats["matched"] += 1

    # Batch update
    conn.execute("BEGIN")
    for i in range(0, len(batch), 5000):
        chunk = batch[i:i + 5000]
        conn.executemany(
            "UPDATE ord SET frekvens = ? WHERE ord = ?",
            chunk,
        )
    conn.commit()

    # Compute unmatched
    unmatched_db = db_words - matched_db_words
    stats["unmatched_db"] = len(unmatched_db)

    freq_words_lower = set(freq_map.keys())
    db_words_lower = {w.lower() for w in db_words}
    unmatched_freq = freq_words_lower - db_words_lower
    stats["unmatched_freq"] = len(unmatched_freq)

    # Verify
    cur = conn.execute("SELECT COUNT(DISTINCT ord) FROM ord WHERE frekvens > 0")
    stats["words_with_freq"] = cur.fetchone()[0]

    conn.close()

    # Write log
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"=== Frequency Update Log ===\n\n")
        f.write(f"DB words:                 {stats['db_words']:>10,}\n")
        f.write(f"Frequency list words:     {stats['freq_words']:>10,}\n")
        f.write(f"Matched (exact):          {stats['matched']:>10,}\n")
        f.write(f"Matched (via lowercase):  {stats['matched_lowercase']:>10,}\n")
        f.write(f"DB words without freq:    {stats['unmatched_db']:>10,}\n")
        f.write(f"Freq words not in DB:     {stats['unmatched_freq']:>10,}\n")
        f.write(f"Words with freq > 0:      {stats['words_with_freq']:>10,}\n")

        f.write(f"\n--- Sample DB words without frequency (first 100) ---\n")
        for w in sorted(unmatched_db)[:100]:
            f.write(f"  {w}\n")

        f.write(f"\n--- Sample freq words not in DB (top by frequency, first 100) ---\n")
        top_unmatched = sorted(unmatched_freq, key=lambda w: -freq_map[w])[:100]
        for w in top_unmatched:
            f.write(f"  {w:30} {freq_map[w]:>10.2f}\n")

    return stats


def main():
    if not FREQ_FILE.exists():
        print(f"ERROR: {FREQ_FILE} not found. Run build_frequencies.py first.",
              file=sys.stderr)
        sys.exit(1)
    if not DB_FILE.exists():
        print(f"ERROR: {DB_FILE} not found. Run build_rhyme_index.py first.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Updating frequencies in {DB_FILE.name}...")
    stats = update_frequencies(FREQ_FILE, DB_FILE, LOG_FILE)

    print(f"\n=== Results ===")
    print(f"DB words:                 {stats['db_words']:>10,}")
    print(f"Frequency list words:     {stats['freq_words']:>10,}")
    print(f"Matched (exact):          {stats['matched']:>10,}")
    print(f"Matched (via lowercase):  {stats['matched_lowercase']:>10,}")
    print(f"DB words without freq:    {stats['unmatched_db']:>10,}")
    print(f"Freq words not in DB:     {stats['unmatched_freq']:>10,}")
    print(f"Words with freq > 0:      {stats['words_with_freq']:>10,}")
    print(f"\nLog: {LOG_FILE}")

    # Demo: top rhymes for "sol" sorted by frequency
    import sqlite3 as s
    conn = s.connect(str(DB_FILE))
    print(f"\n=== Demo: top rhymes for 'sol' by frequency ===")
    cur = conn.execute(
        "SELECT o2.ord, o2.frekvens FROM ord o1 "
        "JOIN ord o2 ON o1.rimsuffiks = o2.rimsuffiks "
        "WHERE o1.ord = 'sol' AND o2.ord != 'sol' "
        "ORDER BY o2.frekvens DESC LIMIT 15"
    )
    for row in cur:
        print(f"  {row[0]:20} {row[1]:>10.2f}")
    conn.close()


if __name__ == "__main__":
    main()
