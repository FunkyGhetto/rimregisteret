"""Build rimsti (rhyme path) index: precompute consonant skeletons for all suffixes.

Reads all distinct rimsuffiks from rimindeks.db, computes the consonant
skeleton for each, counts family size, and stores top 5 examples.
"""

import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "data/db/rimindeks.db"

# Import from the rhyme module
sys.path.insert(0, str(PROJECT_ROOT))
from rimordbok.rhyme import _consonant_skeleton


def main():
    if not DB_FILE.exists():
        print(f"ERROR: {DB_FILE} not found", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row

    # Create table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rimsti_indeks (
            rimsuffiks TEXT NOT NULL,
            konsonantskjelett TEXT NOT NULL,
            familiestr INTEGER DEFAULT 0,
            eksempler TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_rimsti_skjelett ON rimsti_indeks(konsonantskjelett);
    """)

    # Clear old data
    conn.execute("DELETE FROM rimsti_indeks")

    # Get all distinct suffixes
    cur = conn.execute("SELECT DISTINCT rimsuffiks FROM ord")
    suffixes = [row["rimsuffiks"] for row in cur]
    print(f"Distinct suffixes: {len(suffixes):,}")

    # Process each suffix
    batch = []
    skeleton_counter = Counter()

    for sfx in suffixes:
        skeleton = _consonant_skeleton(sfx)
        skeleton_str = ".".join(skeleton) if skeleton else ""
        skeleton_counter[skeleton_str] += 1

        # Count qualifying words
        row = conn.execute(
            "SELECT COUNT(*) as n FROM ("
            "  SELECT LOWER(ord) FROM ord "
            "  WHERE rimsuffiks = ? AND frekvens >= 1.0 "
            "  AND length(ord) >= 2 AND length(ord) <= 15 "
            "  GROUP BY LOWER(ord)"
            ")",
            (sfx,),
        ).fetchone()
        familiestr = row["n"]

        # Top 5 examples
        cur2 = conn.execute(
            "SELECT LOWER(ord) as ord FROM ord "
            "WHERE rimsuffiks = ? AND frekvens >= 1.0 "
            "AND length(ord) >= 2 AND length(ord) <= 15 "
            "GROUP BY LOWER(ord) ORDER BY MAX(frekvens) DESC LIMIT 5",
            (sfx,),
        )
        eksempler = ",".join(r["ord"] for r in cur2)

        batch.append((sfx, skeleton_str, familiestr, eksempler))

        if len(batch) % 10000 == 0:
            print(f"  ...{len(batch):,} suffixes processed")

    # Insert
    conn.executemany(
        "INSERT INTO rimsti_indeks (rimsuffiks, konsonantskjelett, familiestr, eksempler) "
        "VALUES (?, ?, ?, ?)",
        batch,
    )

    # Create unique index after insert (faster)
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rimsti_suffiks ON rimsti_indeks(rimsuffiks)")
    except sqlite3.IntegrityError:
        pass

    conn.commit()

    # Statistics
    distinct_skeletons = len(skeleton_counter)
    avg_variants = len(suffixes) / distinct_skeletons if distinct_skeletons else 0

    print(f"\n=== Statistics ===")
    print(f"Suffixes processed:       {len(batch):>10,}")
    print(f"Distinct skeletons:       {distinct_skeletons:>10,}")
    print(f"Avg variants/skeleton:    {avg_variants:>10.1f}")

    print(f"\n=== Top 10 skeletons (most vowel variants) ===")
    for skel, count in skeleton_counter.most_common(10):
        # Get example suffixes for this skeleton
        examples = conn.execute(
            "SELECT rimsuffiks, familiestr, eksempler FROM rimsti_indeks "
            "WHERE konsonantskjelett = ? AND familiestr >= 3 ORDER BY familiestr DESC LIMIT 3",
            (skel,),
        ).fetchall()
        ex_str = " | ".join(f"/{r['rimsuffiks']}/ ({r['familiestr']})" for r in examples)
        print(f"  /{skel or '(tom)':12} {count:>4} variants  {ex_str}")

    # Spot checks
    print(f"\n=== Spot checks ===")
    for word in ["sang", "natt", "sol", "hjerte"]:
        row = conn.execute(
            "SELECT r.rimsuffiks, ri.konsonantskjelett, ri.familiestr "
            "FROM ord o JOIN rimsti_indeks ri ON o.rimsuffiks = ri.rimsuffiks "
            "LEFT JOIN rimsti_indeks r ON r.rimsuffiks = o.rimsuffiks "
            "WHERE LOWER(o.ord) = ? LIMIT 1",
            (word,),
        ).fetchone()
        if row:
            # Count siblings
            siblings = conn.execute(
                "SELECT COUNT(*) as n FROM rimsti_indeks WHERE konsonantskjelett = ? AND familiestr >= 3",
                (row["konsonantskjelett"],),
            ).fetchone()["n"]
            print(f"  {word:10} /{row['rimsuffiks']}/  skeleton=/{row['konsonantskjelett']}/  "
                  f"family={row['familiestr']}  steg={siblings}")

    conn.close()
    print(f"\nDone. Table rimsti_indeks has {len(batch):,} rows.")


if __name__ == "__main__":
    main()
