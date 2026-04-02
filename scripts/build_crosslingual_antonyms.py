"""Transfer English antonym pairs to Norwegian via Open Multilingual WordNet.

Uses NLTK WordNet + OMW-1.4 Norwegian Bokmål mappings.
Also extracts cross-lingual synonyms from shared synsets.

Input: NLTK WordNet + OMW data (downloaded via nltk.download)
Output: new rows in data/db/semantics.db
"""

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from nltk.corpus import wordnet as wn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RIMINDEKS_DB = PROJECT_ROOT / "data/db/rimindeks.db"
SEMANTICS_DB = PROJECT_ROOT / "data/db/semantics.db"

# Also try Wiktionary translations as secondary source
WIKTIONARY_FILE = PROJECT_ROOT / "data/raw/wiktionary_nb.jsonl"


def build_wiktionary_translations():
    """Build eng→nob translation dict from Wiktionary JSONL."""
    translations = defaultdict(set)
    if not WIKTIONARY_FILE.exists():
        return translations

    with open(WIKTIONARY_FILE, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            word_nb = entry.get("word", "").lower().strip()
            if not word_nb:
                continue
            # Wiktionary entries have "translations" in senses
            for sense in entry.get("senses", []):
                for tr in sense.get("translations", []):
                    if tr.get("lang_code") == "en" or tr.get("code") == "en":
                        eng = tr.get("word", "").lower().strip()
                        if eng:
                            translations[eng].add(word_nb)
    return translations


def main():
    # Load valid Norwegian words from rimindeks
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

    # Ensure confidence column
    try:
        sem.execute("ALTER TABLE word_relations ADD COLUMN confidence REAL DEFAULT 1.0")
        sem.commit()
    except sqlite3.OperationalError:
        pass

    # --- Step A: Build eng→nob mapping from OMW ---
    print("\nBuilding OMW eng→nob mapping...")
    eng_to_nob = defaultdict(set)  # eng_lemma → set of nob words
    synset_to_nob = {}  # synset_name → set of nob words

    for synset in wn.all_synsets():
        nob_lemmas = synset.lemma_names("nob")
        if nob_lemmas:
            nob_set = {w.lower().replace("_", " ") for w in nob_lemmas}
            synset_to_nob[synset.name()] = nob_set
            for lemma in synset.lemmas("eng"):
                eng_to_nob[lemma.name().lower().replace("_", " ")].update(nob_set)

    print(f"  OMW mappings: {len(eng_to_nob):,} English words → Norwegian")
    print(f"  Synsets with Norwegian: {len(synset_to_nob):,}")

    # --- Step A2: Enrich with Wiktionary translations ---
    print("\nLoading Wiktionary translations...")
    # The nb Wiktionary has Norwegian words with English translations
    # We need the reverse: English → Norwegian
    # The nb JSONL has Norwegian headwords. We can use them as-is for matching.
    wikt_trans = build_wiktionary_translations()
    if wikt_trans:
        added = 0
        for eng, nob_set in wikt_trans.items():
            for nob in nob_set:
                if nob not in eng_to_nob.get(eng, set()):
                    eng_to_nob[eng].add(nob)
                    added += 1
        print(f"  Wiktionary added {added:,} new eng→nob mappings")
    print(f"  Total eng→nob mappings: {len(eng_to_nob):,}")

    # --- Step B: Extract English antonym pairs and transfer ---
    print("\nTransferring English antonym pairs...")
    stats = {
        "eng_pairs": 0,
        "mapped_pairs": 0,
        "new_antonyms": 0,
        "new_synonyms": 0,
        "skipped_no_mapping": 0,
        "skipped_not_valid": 0,
        "skipped_duplicate": 0,
    }

    ant_batch = []
    syn_batch = []

    # Process antonyms
    seen_eng_pairs = set()
    for synset in wn.all_synsets():
        for lemma in synset.lemmas():
            for ant_lemma in lemma.antonyms():
                eng_a = lemma.name().lower().replace("_", " ")
                eng_b = ant_lemma.name().lower().replace("_", " ")
                pair = tuple(sorted([eng_a, eng_b]))
                if pair in seen_eng_pairs:
                    continue
                seen_eng_pairs.add(pair)
                stats["eng_pairs"] += 1

                nob_a = eng_to_nob.get(eng_a, set())
                nob_b = eng_to_nob.get(eng_b, set())

                if not nob_a or not nob_b:
                    stats["skipped_no_mapping"] += 1
                    continue

                stats["mapped_pairs"] += 1

                for na in nob_a:
                    for nb in nob_b:
                        if na == nb:
                            continue
                        if na not in valid_words or nb not in valid_words:
                            stats["skipped_not_valid"] += 1
                            continue

                        # Primary translation = higher confidence
                        conf = 0.85

                        if (na, nb, "antonym") in existing:
                            stats["skipped_duplicate"] += 1
                            continue

                        existing.add((na, nb, "antonym"))
                        existing.add((nb, na, "antonym"))
                        ant_batch.append((na, "antonym", nb, "wordnet_transfer", conf))
                        ant_batch.append((nb, "antonym", na, "wordnet_transfer", conf))
                        stats["new_antonyms"] += 1

    # Process synonyms from shared synsets
    print("Extracting cross-lingual synonyms from shared synsets...")
    for synset_name, nob_words in synset_to_nob.items():
        nob_list = [w for w in nob_words if w in valid_words]
        if len(nob_list) < 2:
            continue
        for i in range(len(nob_list)):
            for j in range(i + 1, len(nob_list)):
                wa, wb = nob_list[i], nob_list[j]
                if (wa, wb, "synonym") not in existing:
                    existing.add((wa, wb, "synonym"))
                    syn_batch.append((wa, "synonym", wb, "wordnet_transfer", 0.9))
                    stats["new_synonyms"] += 1

    # Insert
    sem.executemany(
        "INSERT OR IGNORE INTO word_relations (word, relation, related_word, source, confidence) "
        "VALUES (?, ?, ?, ?, ?)",
        ant_batch + syn_batch,
    )
    sem.commit()

    print(f"\n=== Statistics ===")
    print(f"English antonym pairs:     {stats['eng_pairs']:>10,}")
    print(f"Mapped to Norwegian:       {stats['mapped_pairs']:>10,}")
    print(f"New antonym pairs:         {stats['new_antonyms']:>10,}")
    print(f"New synonym pairs:         {stats['new_synonyms']:>10,}")
    print(f"Skipped (no mapping):      {stats['skipped_no_mapping']:>10,}")
    print(f"Skipped (not in rimindeks):{stats['skipped_not_valid']:>10,}")
    print(f"Skipped (duplicate):       {stats['skipped_duplicate']:>10,}")
    print(f"Inserted antonym rows:     {len(ant_batch):>10,}")
    print(f"Inserted synonym rows:     {len(syn_batch):>10,}")

    # Show examples
    print(f"\n=== Top 30 new antonym pairs ===")
    # Get frequencies for sorting
    rconn = sqlite3.connect(str(RIMINDEKS_DB))
    examples = []
    seen = set()
    for w1, rel, w2, src, conf in ant_batch:
        key = tuple(sorted([w1, w2]))
        if key in seen:
            continue
        seen.add(key)
        f1 = rconn.execute("SELECT MAX(frekvens) FROM ord WHERE LOWER(ord) = ?", (w1,)).fetchone()[0] or 0
        f2 = rconn.execute("SELECT MAX(frekvens) FROM ord WHERE LOWER(ord) = ?", (w2,)).fetchone()[0] or 0
        examples.append((w1, w2, min(f1, f2)))

    examples.sort(key=lambda x: -x[2])
    for w1, w2, freq in examples[:30]:
        print(f"  {w1:20} ↔ {w2:20} (freq: {freq:.1f})")
    rconn.close()

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
