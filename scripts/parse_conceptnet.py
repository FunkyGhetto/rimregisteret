"""Extract Norwegian Bokmål synonym/antonym pairs from ConceptNet 5.7.

Streams through gzipped CSV without decompressing to disk.
Input: data/raw/conceptnet.csv.gz
Output: new rows in data/db/semantics.db → word_relations table

ConceptNet CSV format (tab-separated):
  col 0: URI (/a/[/r/Synonym/,/c/no/glad/,/c/no/lykkelig/])
  col 1: relation (/r/Synonym, /r/Antonym)
  col 2: start (/c/no/glad or /c/no/glad/a)
  col 3: end (/c/no/lykkelig)
  col 4: JSON metadata (contains "weight")
"""

import gzip
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data/raw/conceptnet.csv.gz"
RIMINDEKS_DB = PROJECT_ROOT / "data/db/rimindeks.db"
SEMANTICS_DB = PROJECT_ROOT / "data/db/semantics.db"

RELATIONS = {
    "/r/Synonym": "synonym",
    "/r/Antonym": "antonym",
}


def extract_word(uri: str):
    """Extract word from ConceptNet URI like /c/no/glad/a → glad."""
    parts = uri.split("/")
    if len(parts) >= 4 and parts[1] == "c" and parts[2] == "no":
        return parts[3].lower().replace("_", " ")
    return None


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    # Load valid words
    conn = sqlite3.connect(str(RIMINDEKS_DB))
    cur = conn.execute("SELECT DISTINCT LOWER(ord) FROM ord")
    valid_words = {row[0] for row in cur}
    conn.close()
    print(f"Valid words in rimindeks: {len(valid_words):,}")

    # Load existing pairs
    sem = sqlite3.connect(str(SEMANTICS_DB))
    existing = set()
    try:
        cur = sem.execute(
            "SELECT LOWER(word), LOWER(related_word), relation FROM word_relations"
        )
        for row in cur:
            existing.add((row[0], row[1], row[2]))
    except sqlite3.OperationalError:
        pass
    print(f"Existing relations: {len(existing):,}")

    # Add confidence column if missing
    try:
        sem.execute("ALTER TABLE word_relations ADD COLUMN confidence REAL DEFAULT 1.0")
        sem.commit()
    except sqlite3.OperationalError:
        pass

    stats = {
        "total_lines": 0,
        "nb_assertions": 0,
        "nb_synonyms": 0,
        "nb_antonyms": 0,
        "new_synonyms": 0,
        "new_antonyms": 0,
        "skipped_not_valid": 0,
        "skipped_duplicate": 0,
    }

    batch = []

    print("Streaming through conceptnet.csv.gz...")
    with gzip.open(str(INPUT_FILE), "rt", encoding="utf-8") as f:
        for line in f:
            stats["total_lines"] += 1

            if stats["total_lines"] % 5_000_000 == 0:
                print(f"  ...{stats['total_lines']:,} lines, {stats['nb_assertions']:,} nb assertions")

            parts = line.strip().split("\t")
            if len(parts) < 5:
                continue

            relation_uri = parts[1]
            if relation_uri not in RELATIONS:
                continue

            start_uri = parts[2]
            end_uri = parts[3]

            # Filter: both must be Norwegian Bokmål
            if not start_uri.startswith("/c/no/") or not end_uri.startswith("/c/no/"):
                continue

            stats["nb_assertions"] += 1
            relation = RELATIONS[relation_uri]

            word1 = extract_word(start_uri)
            word2 = extract_word(end_uri)

            if not word1 or not word2 or word1 == word2:
                continue

            if relation == "synonym":
                stats["nb_synonyms"] += 1
            else:
                stats["nb_antonyms"] += 1

            # Validate both words exist in rimindeks
            if word1 not in valid_words or word2 not in valid_words:
                stats["skipped_not_valid"] += 1
                continue

            # Parse weight from metadata
            try:
                meta = json.loads(parts[4])
                weight = meta.get("weight", 1.0)
            except (json.JSONDecodeError, IndexError):
                weight = 1.0

            confidence = min(weight / 10.0, 1.0)

            # Check duplicates
            if (word1, word2, relation) in existing:
                stats["skipped_duplicate"] += 1
                continue

            existing.add((word1, word2, relation))
            batch.append((word1, relation, word2, "conceptnet", confidence))

            if relation == "synonym":
                stats["new_synonyms"] += 1
            else:
                stats["new_antonyms"] += 1
                # Add reverse direction for antonyms
                if (word2, word1, relation) not in existing:
                    existing.add((word2, word1, relation))
                    batch.append((word2, relation, word1, "conceptnet", confidence))

    # Insert
    sem.executemany(
        "INSERT OR IGNORE INTO word_relations (word, relation, related_word, source, confidence) "
        "VALUES (?, ?, ?, ?, ?)",
        batch,
    )
    sem.commit()

    print(f"\n=== Statistics ===")
    print(f"Total lines scanned:       {stats['total_lines']:>12,}")
    print(f"Norwegian nb assertions:   {stats['nb_assertions']:>12,}")
    print(f"  - synonyms:              {stats['nb_synonyms']:>12,}")
    print(f"  - antonyms:              {stats['nb_antonyms']:>12,}")
    print(f"New synonyms added:        {stats['new_synonyms']:>12,}")
    print(f"New antonyms added:        {stats['new_antonyms']:>12,}")
    print(f"Skipped (not in rimindeks):{stats['skipped_not_valid']:>12,}")
    print(f"Skipped (duplicate):       {stats['skipped_duplicate']:>12,}")
    print(f"Total rows inserted:       {len(batch):>12,}")

    # Show examples
    print(f"\n=== New antonym examples ===")
    ant_examples = [(w1, w3) for w1, rel, w3, src, conf in batch if rel == "antonym"]
    seen = set()
    for w1, w2 in ant_examples[:40]:
        key = tuple(sorted([w1, w2]))
        if key not in seen:
            seen.add(key)
            print(f"  {w1:20} ↔ {w2}")
        if len(seen) >= 20:
            break

    print(f"\n=== New synonym examples ===")
    for w1, rel, w2, src, conf in batch[:20]:
        if rel == "synonym":
            print(f"  {w1:20} → {w2}")

    # Breakdown
    cur = sem.execute(
        "SELECT relation, source, COUNT(*) FROM word_relations GROUP BY relation, source ORDER BY relation, source"
    )
    print(f"\n=== Total word_relations breakdown ===")
    for row in cur:
        print(f"  {row[0]:12} {row[1]:20} {row[2]:>8,}")

    sem.close()


if __name__ == "__main__":
    main()
