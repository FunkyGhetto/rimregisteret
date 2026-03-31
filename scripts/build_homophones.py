"""Build homophone table from rimindeks.db.

Groups words with identical IPA transcription but different spelling.
Stores in semantics.db → homofoner table.
"""

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RIMINDEKS_DB = PROJECT_ROOT / "data/db/rimindeks.db"
SEMANTICS_DB = PROJECT_ROOT / "data/db/semantics.db"


def main():
    if not RIMINDEKS_DB.exists():
        print(f"ERROR: {RIMINDEKS_DB} not found", file=sys.stderr)
        sys.exit(1)

    # Read all (word, ipa) pairs from rimindeks, grouped by IPA
    conn = sqlite3.connect(str(RIMINDEKS_DB))
    cur = conn.execute(
        "SELECT LOWER(ord) as ord, ipa_ren FROM ord WHERE ipa_ren != '' GROUP BY LOWER(ord), ipa_ren"
    )

    ipa_groups = defaultdict(set)
    for row in cur:
        word, ipa = row
        if word and ipa:
            ipa_groups[ipa].add(word)
    conn.close()

    # Filter to groups with 2+ different spellings
    homophone_groups = {ipa: words for ipa, words in ipa_groups.items() if len(words) >= 2}

    print(f"Total IPA transcriptions: {len(ipa_groups):,}")
    print(f"Homophone groups (2+ words): {len(homophone_groups):,}")
    total_words = sum(len(w) for w in homophone_groups.values())
    print(f"Total words with homophones: {total_words:,}")

    # Write to semantics.db
    sem = sqlite3.connect(str(SEMANTICS_DB))
    sem.execute("""
        CREATE TABLE IF NOT EXISTS homofoner (
            ipa TEXT NOT NULL,
            ord TEXT NOT NULL,
            PRIMARY KEY (ipa, ord)
        )
    """)
    sem.execute("CREATE INDEX IF NOT EXISTS idx_homofoner_ord ON homofoner(ord)")

    # Clear old data
    sem.execute("DELETE FROM homofoner")

    batch = []
    for ipa, words in homophone_groups.items():
        for word in words:
            batch.append((ipa, word))

    sem.executemany("INSERT OR IGNORE INTO homofoner (ipa, ord) VALUES (?, ?)", batch)
    sem.commit()

    print(f"\nInserted {len(batch):,} rows into homofoner table")

    # Show examples
    print(f"\n=== Top 10 homophone groups (most members) ===")
    sorted_groups = sorted(homophone_groups.items(), key=lambda x: -len(x[1]))
    for ipa, words in sorted_groups[:10]:
        print(f"  /{ipa}/ → {', '.join(sorted(words))}")

    sem.close()


if __name__ == "__main__":
    main()
