from __future__ import annotations

"""Build SQLite rhyme index from parsed phonetics JSONL.

Reads data/processed/phonetics.jsonl, computes a rhyme suffix for each word
(phonemes from the last stressed vowel to end of word), and writes everything
into data/db/rimindeks.db.

Supports dialect data: reads data/processed/phonetics_{dialekt}.jsonl files
and populates an ord_dialekter table with dialect-specific phonetics.

Rhyme suffix algorithm:
  1. Walk syllables to find the LAST syllable with stress >= 1.
  2. Within that syllable, find the first vowel phoneme.
  3. The rhyme suffix = that vowel + everything after it (remaining phonemes
     in that syllable + all subsequent syllables), joined with '.' between
     syllables.
  Fallback: if no stress info, use the last syllable's first vowel.
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data/processed/phonetics.jsonl"
DB_FILE = PROJECT_ROOT / "data/db/rimindeks.db"
NO_STRESS_LOG = PROJECT_ROOT / "data/processed/no_stress.log"

# Non-øst dialects to load into ord_dialekter
DIALECT_FILES = {
    "nord": PROJECT_ROOT / "data/processed/phonetics_nord.jsonl",
    "midt": PROJECT_ROOT / "data/processed/phonetics_midt.jsonl",
    "vest": PROJECT_ROOT / "data/processed/phonetics_vest.jsonl",
    "sørvest": PROJECT_ROOT / "data/processed/phonetics_sørvest.jsonl",
}

# Norwegian IPA vowels (base characters, without length mark)
# Includes monophthongs used in Norwegian. Diphthongs start with these.
VOWELS = frozenset({
    "ɑ", "ɛ", "ɪ", "ɔ", "ʊ", "ʉ", "ə",  # short/lax
    "æ", "œ", "ø", "ʏ",                     # front rounded / open
    "e", "i", "o", "u", "y", "a",           # cardinal
})


def is_vowel(phoneme: str) -> bool:
    """Check if a phoneme is a vowel (strip length mark and combining chars)."""
    base = phoneme.replace("ː", "").replace("\u0329", "")  # strip ː and  ̩
    # Handle diphthong-like combining characters (æ͡ɪ → base is æ)
    if "͡" in base:
        base = base.split("͡")[0]
    return base in VOWELS


def compute_rhyme_suffix(fonemer: list[list[str]], stress: list[int]) -> str | None:
    """Compute the rhyme suffix for a word.

    Returns a string of phonemes from the last stressed vowel to end of word,
    with '.' separating syllables. Returns None if no vowel found.
    """
    # Find the last syllable with stress >= 1
    stressed_syl_idx = None
    for i in range(len(stress) - 1, -1, -1):
        if stress[i] >= 1:
            stressed_syl_idx = i
            break

    # Fallback: if no stress at all, use last syllable that contains a vowel
    if stressed_syl_idx is None:
        for i in range(len(fonemer) - 1, -1, -1):
            if any(is_vowel(ph) for ph in fonemer[i]):
                stressed_syl_idx = i
                break

    if stressed_syl_idx is None:
        return None

    # Within the stressed syllable, find the first vowel
    syl = fonemer[stressed_syl_idx]
    vowel_idx = None
    for j, ph in enumerate(syl):
        if is_vowel(ph):
            vowel_idx = j
            break

    if vowel_idx is None:
        # Stressed syllable has no vowel (e.g. syllabic consonant like n̩)
        # Use the whole syllable
        vowel_idx = 0

    # Build suffix: from vowel in stressed syllable + all remaining syllables
    parts = []
    # Remainder of stressed syllable from vowel onwards
    parts.append("".join(syl[vowel_idx:]))
    # All subsequent syllables
    for k in range(stressed_syl_idx + 1, len(fonemer)):
        parts.append("".join(fonemer[k]))

    return ".".join(parts)


def build_db(input_path: Path, db_path: Path, no_stress_path: Path) -> dict:
    """Build the SQLite rhyme index.

    Returns statistics dict.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove old DB to ensure clean build
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE ord (
            id INTEGER PRIMARY KEY,
            ord TEXT NOT NULL,
            pos TEXT NOT NULL DEFAULT '',
            fonemer TEXT NOT NULL,
            ipa_ren TEXT NOT NULL DEFAULT '',
            rimsuffiks TEXT NOT NULL,
            tonelag INTEGER,
            stavelser INTEGER,
            frekvens REAL DEFAULT 0.0
        );
        CREATE INDEX idx_rimsuffiks ON ord(rimsuffiks);
        CREATE INDEX idx_ord ON ord(ord);
        CREATE INDEX idx_rimsuffiks_tonelag ON ord(rimsuffiks, tonelag);

        CREATE TABLE ord_dialekter (
            id INTEGER PRIMARY KEY,
            ord TEXT NOT NULL,
            dialekt TEXT NOT NULL,
            fonemer TEXT NOT NULL,
            ipa_ren TEXT NOT NULL DEFAULT '',
            rimsuffiks TEXT NOT NULL,
            tonelag INTEGER,
            stavelser INTEGER
        );
        CREATE INDEX idx_dial_rimsuffiks ON ord_dialekter(dialekt, rimsuffiks);
        CREATE INDEX idx_dial_ord ON ord_dialekter(dialekt, ord);
        CREATE INDEX idx_dial_rimsuffiks_tonelag ON ord_dialekter(dialekt, rimsuffiks, tonelag);
    """)

    stats = {
        "read": 0,
        "inserted": 0,
        "no_suffix": 0,
        "no_stress": 0,
    }
    no_stress_words = []

    batch = []
    BATCH_SIZE = 10000

    with open(input_path, encoding="utf-8") as f:
        for line in f:
            stats["read"] += 1
            record = json.loads(line)

            fonemer = record["fonemer"]
            stress = record["stress"]
            tonelag = record.get("tonelag")
            stavelser = record["stavelser"]
            ord_text = record["ord"]
            pos = record.get("pos", "")
            ipa_ren = record.get("ipa_ren", "")

            # Track words without stress info
            if all(s == 0 for s in stress):
                stats["no_stress"] += 1
                no_stress_words.append(ord_text)

            suffix = compute_rhyme_suffix(fonemer, stress)
            if suffix is None:
                stats["no_suffix"] += 1
                continue

            # Flatten fonemer to a single string for storage
            fonemer_str = ".".join("".join(syl) for syl in fonemer)

            batch.append((
                ord_text, pos, fonemer_str, ipa_ren,
                suffix, tonelag, stavelser,
            ))

            if len(batch) >= BATCH_SIZE:
                cur.executemany(
                    "INSERT INTO ord (ord, pos, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                stats["inserted"] += len(batch)
                batch.clear()

    # Insert remaining
    if batch:
        cur.executemany(
            "INSERT INTO ord (ord, pos, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
        stats["inserted"] += len(batch)

    conn.commit()

    # Print some rhyme suffix distribution stats
    cur.execute("SELECT COUNT(DISTINCT rimsuffiks) FROM ord")
    stats["unique_suffixes"] = cur.fetchone()[0]

    cur.execute(
        "SELECT rimsuffiks, COUNT(*) as cnt FROM ord "
        "GROUP BY rimsuffiks ORDER BY cnt DESC LIMIT 10"
    )
    stats["top_suffixes"] = cur.fetchall()

    conn.close()

    # Write no-stress log
    with open(no_stress_path, "w", encoding="utf-8") as f:
        f.write(f"Words without stress info: {stats['no_stress']}\n\n")
        for w in no_stress_words:
            f.write(w + "\n")

    return stats


def build_dialects(db_path: Path) -> dict:
    """Load non-øst dialect data into ord_dialekter table.

    Only stores entries where the pronunciation differs from østnorsk,
    plus all entries for dialects with different phoneme inventories.
    Returns statistics dict.
    """
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Build lookup of østnorsk (ord, pos) -> rimsuffiks for diff detection
    øst_lookup = {}
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            fonemer = rec["fonemer"]
            stress = rec["stress"]
            suffix = compute_rhyme_suffix(fonemer, stress)
            if suffix:
                key = (rec["ord"], rec.get("pos", ""))
                øst_lookup[key] = suffix

    total_stats = {}

    for dialect_code, dialect_path in DIALECT_FILES.items():
        if not dialect_path.exists():
            print(f"  SKIP {dialect_code}: {dialect_path.name} not found")
            continue

        stats = {"read": 0, "inserted": 0, "same_as_øst": 0, "no_suffix": 0}
        batch = []
        seen = set()

        with open(dialect_path, encoding="utf-8") as f:
            for line in f:
                stats["read"] += 1
                rec = json.loads(line)

                fonemer = rec["fonemer"]
                stress = rec["stress"]
                tonelag = rec.get("tonelag")
                stavelser = rec["stavelser"]
                ord_text = rec["ord"]
                ipa_ren = rec.get("ipa_ren", "")

                suffix = compute_rhyme_suffix(fonemer, stress)
                if suffix is None:
                    stats["no_suffix"] += 1
                    continue

                # Only store if different from østnorsk
                key = (ord_text, rec.get("pos", ""))
                øst_suffix = øst_lookup.get(key)
                if øst_suffix == suffix:
                    stats["same_as_øst"] += 1
                    continue

                # Dedup within this dialect
                dedup = (ord_text, ipa_ren)
                if dedup in seen:
                    continue
                seen.add(dedup)

                fonemer_str = ".".join("".join(syl) for syl in fonemer)
                batch.append((
                    ord_text, dialect_code, fonemer_str, ipa_ren,
                    suffix, tonelag, stavelser,
                ))

                if len(batch) >= 10000:
                    cur.executemany(
                        "INSERT INTO ord_dialekter (ord, dialekt, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                    stats["inserted"] += len(batch)
                    batch.clear()

        if batch:
            cur.executemany(
                "INSERT INTO ord_dialekter (ord, dialekt, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            stats["inserted"] += len(batch)

        conn.commit()
        total_stats[dialect_code] = stats

    conn.close()
    return total_stats


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: Input not found: {INPUT_FILE}", file=sys.stderr)
        sys.exit(1)

    print(f"Building rhyme index from {INPUT_FILE.name}...")
    stats = build_db(INPUT_FILE, DB_FILE, NO_STRESS_LOG)

    print(f"\n=== Statistics ===")
    print(f"Records read:      {stats['read']:>10,}")
    print(f"Inserted to DB:    {stats['inserted']:>10,}")
    print(f"No suffix (skip):  {stats['no_suffix']:>10,}")
    print(f"No stress info:    {stats['no_stress']:>10,}")
    print(f"Unique suffixes:   {stats['unique_suffixes']:>10,}")

    print(f"\n=== Top 10 rhyme suffixes (most words) ===")
    for suffix, count in stats["top_suffixes"]:
        print(f"  {suffix:20} {count:>6,} words")

    print(f"\nDatabase: {DB_FILE}")
    print(f"No-stress log: {NO_STRESS_LOG}")

    # Build dialect data
    has_dialects = any(p.exists() for p in DIALECT_FILES.values())
    if has_dialects:
        print(f"\n=== Building dialect data ===")
        dialect_stats = build_dialects(DB_FILE)
        for code, ds in dialect_stats.items():
            print(f"  {code:8} inserted: {ds['inserted']:>8,}  "
                  f"(same as øst: {ds['same_as_øst']:,}, no suffix: {ds['no_suffix']:,})")

        # Show total dialect entries
        import sqlite3 as s
        conn = s.connect(str(DB_FILE))
        cur = conn.execute(
            "SELECT dialekt, COUNT(*) FROM ord_dialekter GROUP BY dialekt"
        )
        print(f"\n  Dialect entries in DB:")
        for row in cur:
            print(f"    {row[0]:8} {row[1]:>8,} entries")
        conn.close()

    # Demo queries
    import sqlite3 as s
    conn = s.connect(str(DB_FILE))
    print(f"\n=== Demo: words rhyming with 'sol' ===")
    cur = conn.execute(
        "SELECT o2.ord FROM ord o1 JOIN ord o2 ON o1.rimsuffiks = o2.rimsuffiks "
        "WHERE o1.ord = 'sol' AND o2.ord != 'sol' LIMIT 15"
    )
    print(", ".join(row[0] for row in cur))

    print(f"\n=== Demo: words rhyming with 'dag' ===")
    cur = conn.execute(
        "SELECT o2.ord FROM ord o1 JOIN ord o2 ON o1.rimsuffiks = o2.rimsuffiks "
        "WHERE o1.ord = 'dag' AND o2.ord != 'dag' LIMIT 15"
    )
    print(", ".join(row[0] for row in cur))

    print(f"\n=== Demo: words rhyming with 'natt' ===")
    cur = conn.execute(
        "SELECT o2.ord FROM ord o1 JOIN ord o2 ON o1.rimsuffiks = o2.rimsuffiks "
        "WHERE o1.ord = 'natt' AND o2.ord != 'natt' LIMIT 15"
    )
    print(", ".join(row[0] for row in cur))

    conn.close()


if __name__ == "__main__":
    main()
