"""Build morphological antonym pairs from rimindeks.db.

Finds word pairs like:
  u- prefix: vanlig/uvanlig, mulig/umulig, heldig/uheldig
  mis- prefix: bruk/misbruk, tillit/mistillit
  van- prefix: ære/vanære, styre/vanstyre
  -løs suffix: håp/håpløs, hjelp/hjelpeløs
  -fri suffix: smerte/smertefri, barne/barnefri

Stores in semantics.db → word_relations with source='morfologisk'.
Only adds pairs not already in the database.
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RIMINDEKS_DB = PROJECT_ROOT / "data/db/rimindeks.db"
SEMANTICS_DB = PROJECT_ROOT / "data/db/semantics.db"

# Known false positives to exclude (u+word gives unrelated meaning)
FALSE_POSITIVES = {
    ("land", "uland"),
    ("ke", "uke"),
    ("ll", "ull"),
    ("ng", "ung"),
    ("nder", "under"),
    ("te", "ute"),
    ("ten", "uten"),
    ("t", "ut"),
    ("r", "ur"),
}

MIN_FREQ = 0.1  # per million words
MIN_WORD_LEN = 3  # minimum length for base word


def main():
    if not RIMINDEKS_DB.exists():
        print(f"ERROR: {RIMINDEKS_DB} not found", file=sys.stderr)
        sys.exit(1)

    # Load all words with frequency from rimindeks
    conn = sqlite3.connect(str(RIMINDEKS_DB))
    cur = conn.execute(
        "SELECT LOWER(ord) as ord, MAX(frekvens) as freq "
        "FROM ord WHERE length(ord) >= 2 "
        "GROUP BY LOWER(ord)"
    )
    word_freq = {}
    for row in cur:
        word_freq[row[0]] = row[1] if row[1] else 0.0
    conn.close()

    all_words = set(word_freq.keys())
    print(f"Loaded {len(all_words):,} unique words")

    # Load existing antonym pairs from semantics.db
    sem = sqlite3.connect(str(SEMANTICS_DB))
    existing = set()
    try:
        cur = sem.execute(
            "SELECT LOWER(word), LOWER(related_word) FROM word_relations WHERE relation = 'antonym'"
        )
        for row in cur:
            existing.add((row[0], row[1]))
            existing.add((row[1], row[0]))
    except sqlite3.OperationalError:
        pass

    print(f"Existing antonym pairs: {len(existing) // 2}")

    # Add confidence column if missing
    try:
        sem.execute("ALTER TABLE word_relations ADD COLUMN confidence REAL DEFAULT 1.0")
        sem.commit()
        print("Added confidence column")
    except sqlite3.OperationalError:
        pass  # Already exists

    pairs = []

    def add_pair(word1, word2):
        """Add an antonym pair if both words qualify."""
        w1, w2 = word1.lower(), word2.lower()
        if w1 == w2:
            return
        if (w1, w2) in FALSE_POSITIVES or (w2, w1) in FALSE_POSITIVES:
            return
        if len(w1) < MIN_WORD_LEN or len(w2) < MIN_WORD_LEN:
            return
        f1 = word_freq.get(w1, 0.0)
        f2 = word_freq.get(w2, 0.0)
        if f1 < MIN_FREQ or f2 < MIN_FREQ:
            return
        if (w1, w2) in existing or (w2, w1) in existing:
            return
        pairs.append((w1, w2, min(f1, f2)))

    # --- PREFIX PATTERNS ---

    # u- prefix (most productive Norwegian negation prefix)
    for word in all_words:
        if len(word) >= MIN_WORD_LEN:
            negated = "u" + word
            if negated in all_words:
                add_pair(word, negated)

    # Words starting with u- → check if base exists
    for word in all_words:
        if word.startswith("u") and len(word) >= MIN_WORD_LEN + 1:
            base = word[1:]
            if base in all_words:
                add_pair(base, word)

    # mis- prefix
    for word in all_words:
        if len(word) >= MIN_WORD_LEN:
            negated = "mis" + word
            if negated in all_words:
                add_pair(word, negated)

    for word in all_words:
        if word.startswith("mis") and len(word) >= MIN_WORD_LEN + 3:
            base = word[3:]
            if base in all_words:
                add_pair(base, word)

    # van- prefix
    for word in all_words:
        if len(word) >= MIN_WORD_LEN:
            negated = "van" + word
            if negated in all_words:
                add_pair(word, negated)

    for word in all_words:
        if word.startswith("van") and len(word) >= MIN_WORD_LEN + 3:
            base = word[3:]
            if base in all_words:
                add_pair(base, word)

    # --- SUFFIX PATTERNS ---

    # -løs suffix (håpløs, hjelpeløs, tankeløs)
    for word in all_words:
        if word.endswith("løs") and len(word) >= MIN_WORD_LEN + 3:
            base = word[:-3]  # håpløs → håp
            if base in all_words:
                add_pair(base, word)
            # Try with -e- link vowel: hjelpeløs → hjelp
            if base.endswith("e") and base[:-1] in all_words:
                add_pair(base[:-1], word)

    # -fri suffix (smertefri, barnefri, bilfri)
    for word in all_words:
        if word.endswith("fri") and len(word) >= MIN_WORD_LEN + 3:
            base = word[:-3]
            if base in all_words:
                add_pair(base, word)
            if base.endswith("e") and base[:-1] in all_words:
                add_pair(base[:-1], word)

    # Deduplicate pairs
    seen = set()
    unique_pairs = []
    for w1, w2, freq in pairs:
        key = tuple(sorted([w1, w2]))
        if key not in seen:
            seen.add(key)
            unique_pairs.append((w1, w2, freq))

    unique_pairs.sort(key=lambda x: -x[2])

    print(f"\nFound {len(unique_pairs)} new morphological antonym pairs")

    # Insert into semantics.db (both directions)
    batch = []
    for w1, w2, freq in unique_pairs:
        batch.append((w1, "antonym", w2, "morfologisk", 1.0))
        batch.append((w2, "antonym", w1, "morfologisk", 1.0))

    sem.executemany(
        "INSERT OR IGNORE INTO word_relations (word, relation, related_word, source, confidence) "
        "VALUES (?, ?, ?, ?, ?)",
        batch,
    )
    sem.commit()

    print(f"Inserted {len(batch)} rows (both directions)")

    # Show top 20 most frequent pairs
    print(f"\n=== Top 20 most frequent antonym pairs ===")
    for w1, w2, freq in unique_pairs[:20]:
        f1 = word_freq.get(w1, 0)
        f2 = word_freq.get(w2, 0)
        print(f"  {w1:20} ↔ {w2:20} (freq: {f1:.1f} / {f2:.1f})")

    # Stats by pattern
    prefixes = {"u": 0, "mis": 0, "van": 0}
    suffixes = {"løs": 0, "fri": 0}
    for w1, w2, _ in unique_pairs:
        if w2.startswith("u") and w2[1:] == w1:
            prefixes["u"] += 1
        elif w1.startswith("u") and w1[1:] == w2:
            prefixes["u"] += 1
        elif "mis" in (w2[:3], w1[:3]):
            prefixes["mis"] += 1
        elif "van" in (w2[:3], w1[:3]):
            prefixes["van"] += 1
        elif w2.endswith("løs") or w1.endswith("løs"):
            suffixes["løs"] += 1
        elif w2.endswith("fri") or w1.endswith("fri"):
            suffixes["fri"] += 1

    print(f"\n=== Breakdown by pattern ===")
    for p, n in prefixes.items():
        print(f"  {p}-: {n} pairs")
    for s, n in suffixes.items():
        print(f"  -{s}: {n} pairs")

    sem.close()


if __name__ == "__main__":
    main()
