"""Parse Wiktionary JSONL (kaikki.org) for Norwegian Bokmål synonyms and antonyms.

Input: data/raw/wiktionary_nb.jsonl (from kaikki.org)
Output: new rows in data/db/semantics.db → word_relations table

Only adds pairs where both words exist in rimindeks.db.
Deduplicates against existing data.
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data/raw/wiktionary_nb.jsonl"
RIMINDEKS_DB = PROJECT_ROOT / "data/db/rimindeks.db"
SEMANTICS_DB = PROJECT_ROOT / "data/db/semantics.db"


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    # Load valid words from rimindeks.db
    conn = sqlite3.connect(str(RIMINDEKS_DB))
    cur = conn.execute("SELECT DISTINCT LOWER(ord) FROM ord")
    valid_words = {row[0] for row in cur}
    conn.close()
    print(f"Valid words in rimindeks: {len(valid_words):,}")

    # Load existing pairs from semantics.db
    sem = sqlite3.connect(str(SEMANTICS_DB))
    existing_syn = set()
    existing_ant = set()
    try:
        cur = sem.execute(
            "SELECT LOWER(word), LOWER(related_word), relation FROM word_relations"
        )
        for row in cur:
            pair = (row[0], row[1])
            if row[2] == "synonym":
                existing_syn.add(pair)
            elif row[2] == "antonym":
                existing_ant.add(pair)
    except sqlite3.OperationalError:
        pass

    print(f"Existing synonyms: {len(existing_syn):,}")
    print(f"Existing antonyms: {len(existing_ant):,}")

    # Add confidence column if missing
    try:
        sem.execute("ALTER TABLE word_relations ADD COLUMN confidence REAL DEFAULT 1.0")
        sem.commit()
    except sqlite3.OperationalError:
        pass

    # Parse Wiktionary JSONL
    stats = {
        "total_entries": 0,
        "with_synonyms": 0,
        "with_antonyms": 0,
        "new_syn_pairs": 0,
        "new_ant_pairs": 0,
        "skipped_not_in_db": 0,
        "skipped_duplicate": 0,
    }

    syn_batch = []
    ant_batch = []

    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            stats["total_entries"] += 1
            entry = json.loads(line)
            word = entry.get("word", "").lower().strip()

            if not word or word not in valid_words:
                continue

            senses = entry.get("senses", [])

            for sense in senses:
                # Synonyms
                for syn_entry in sense.get("synonyms", []):
                    syn_word = syn_entry.get("word", "").lower().strip()
                    if not syn_word or syn_word == word:
                        continue
                    if syn_word not in valid_words:
                        stats["skipped_not_in_db"] += 1
                        continue
                    pair = (word, syn_word)
                    if pair in existing_syn:
                        stats["skipped_duplicate"] += 1
                        continue
                    existing_syn.add(pair)
                    syn_batch.append((word, "synonym", syn_word, "wiktionary", 1.0))
                    stats["new_syn_pairs"] += 1

                # Antonyms (both directions)
                for ant_entry in sense.get("antonyms", []):
                    ant_word = ant_entry.get("word", "").lower().strip()
                    if not ant_word or ant_word == word:
                        continue
                    if ant_word not in valid_words:
                        stats["skipped_not_in_db"] += 1
                        continue
                    pair_fwd = (word, ant_word)
                    pair_rev = (ant_word, word)
                    if pair_fwd in existing_ant:
                        stats["skipped_duplicate"] += 1
                        continue
                    existing_ant.add(pair_fwd)
                    existing_ant.add(pair_rev)
                    ant_batch.append((word, "antonym", ant_word, "wiktionary", 1.0))
                    ant_batch.append((ant_word, "antonym", word, "wiktionary", 1.0))
                    stats["new_ant_pairs"] += 1

            if entry.get("senses") and any(s.get("synonyms") for s in senses):
                stats["with_synonyms"] += 1
            if entry.get("senses") and any(s.get("antonyms") for s in senses):
                stats["with_antonyms"] += 1

    # Insert
    sem.executemany(
        "INSERT OR IGNORE INTO word_relations (word, relation, related_word, source, confidence) "
        "VALUES (?, ?, ?, ?, ?)",
        syn_batch,
    )
    sem.executemany(
        "INSERT OR IGNORE INTO word_relations (word, relation, related_word, source, confidence) "
        "VALUES (?, ?, ?, ?, ?)",
        ant_batch,
    )
    sem.commit()

    print(f"\n=== Statistics ===")
    print(f"Total entries in JSONL:    {stats['total_entries']:>10,}")
    print(f"Entries with synonyms:     {stats['with_synonyms']:>10,}")
    print(f"Entries with antonyms:     {stats['with_antonyms']:>10,}")
    print(f"New synonym pairs added:   {stats['new_syn_pairs']:>10,}")
    print(f"New antonym pairs added:   {stats['new_ant_pairs']:>10,}")
    print(f"Skipped (not in rimindeks):{stats['skipped_not_in_db']:>10,}")
    print(f"Skipped (duplicate):       {stats['skipped_duplicate']:>10,}")
    print(f"Inserted syn rows:         {len(syn_batch):>10,}")
    print(f"Inserted ant rows:         {len(ant_batch):>10,} (both directions)")

    # Show examples
    print(f"\n=== Top 20 new antonym pairs ===")
    # Get frequency for sorting
    rconn = sqlite3.connect(str(RIMINDEKS_DB))
    shown = set()
    for w1, rel, w2, src, conf in ant_batch:
        key = tuple(sorted([w1, w2]))
        if key in shown:
            continue
        shown.add(key)
        f1 = rconn.execute("SELECT MAX(frekvens) FROM ord WHERE LOWER(ord) = ?", (w1,)).fetchone()[0] or 0
        f2 = rconn.execute("SELECT MAX(frekvens) FROM ord WHERE LOWER(ord) = ?", (w2,)).fetchone()[0] or 0
        if len(shown) <= 20:
            print(f"  {w1:20} ↔ {w2:20} (freq: {f1:.1f} / {f2:.1f})")
    rconn.close()

    print(f"\n=== Sample new synonyms ===")
    for w1, rel, w2, src, conf in syn_batch[:20]:
        print(f"  {w1:20} → {w2}")

    # Total counts
    cur = sem.execute("SELECT relation, source, COUNT(*) FROM word_relations GROUP BY relation, source ORDER BY relation, source")
    print(f"\n=== Total word_relations breakdown ===")
    for row in cur:
        print(f"  {row[0]:12} {row[1]:20} {row[2]:>8,}")

    sem.close()


if __name__ == "__main__":
    main()
