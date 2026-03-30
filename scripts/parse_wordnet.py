from __future__ import annotations

"""Parse Norwegian WordNet and synonyms into semantics.db.

Sources:
- Norwegian WordNet Bokmål (CC BY 4.0): synset-based relations
- norwegian-synonyms (CC BY-NC-SA 4.0): direct synonym lists (academic use only)

Output: data/db/semantics.db with tables for words, synsets, relations, and synonyms.
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORDNET_DIR = PROJECT_ROOT / "data/raw/wordnet_nob/dat"
SYNONYMS_FILE = PROJECT_ROOT / "data/raw/norwegian-synonyms/norwegian-synonyms.json"
DB_FILE = PROJECT_ROOT / "data/db/semantics.db"

# Relations we care about for the semantics engine
RELATION_MAP = {
    "nearSynonymOf": "synonym",
    "xposNearSynonymOf": "synonym",
    "nearAntonymOf": "antonym",
    "hyponymOf": "hypernym",     # X hyponymOf Y means Y is hypernym of X
    "concerns": "related",
    "partMeronymOf": "meronym",
    "partHolonymOf": "holonym",
    "memberMeronymOf": "meronym",
    "memberHolonymOf": "holonym",
    "madeofHolonymOf": "holonym",
    "madeofMeronymOf": "meronym",
}


def load_words(path: Path) -> dict:
    """Load words.tab → {word_id: (form, pos)}"""
    words = {}
    with open(path / "words.tab", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                words[parts[0]] = (parts[1], parts[2])
    return words


def load_wordsenses(path: Path) -> tuple:
    """Load wordsenses.tab → (word_to_synsets, synset_to_words)"""
    w2s = {}  # word_id -> [synset_id]
    s2w = {}  # synset_id -> [word_id]
    with open(path / "wordsenses.tab", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                word_id, synset_id = parts[1], parts[2]
                w2s.setdefault(word_id, []).append(synset_id)
                s2w.setdefault(synset_id, []).append(word_id)
    return w2s, s2w


def load_relations(path: Path) -> list:
    """Load relations.tab, filtering to relevant relation types."""
    rels = []
    with open(path / "relations.tab", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4:
                src_synset = parts[0]
                rel_name = parts[1]
                tgt_synset = parts[3]
                if rel_name in RELATION_MAP:
                    rels.append((src_synset, RELATION_MAP[rel_name], tgt_synset))
    return rels


def load_synonyms_json(path: Path) -> dict:
    """Load norwegian-synonyms.json → {word: [synonyms]}"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_db(wordnet_dir: Path, synonyms_path: Path, db_path: Path) -> dict:
    """Build semantics.db from WordNet data and synonym list."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    stats = {
        "words": 0,
        "synsets": 0,
        "wordsenses": 0,
        "wn_relations": 0,
        "word_relations": 0,
        "synonym_pairs": 0,
    }

    # Load WordNet data
    print("Loading WordNet data...")
    words = load_words(wordnet_dir)
    w2s, s2w = load_wordsenses(wordnet_dir)
    relations = load_relations(wordnet_dir)

    # Load synonyms
    print("Loading synonym list...")
    syn_json = load_synonyms_json(synonyms_path) if synonyms_path.exists() else {}

    # Build the database
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.executescript("""
        -- WordNet words
        CREATE TABLE wn_words (
            id INTEGER PRIMARY KEY,
            form TEXT NOT NULL,
            pos TEXT NOT NULL DEFAULT ''
        );

        -- WordNet synsets
        CREATE TABLE wn_synsets (
            id INTEGER PRIMARY KEY
        );

        -- Word-to-synset mapping
        CREATE TABLE wn_wordsenses (
            word_id INTEGER NOT NULL,
            synset_id INTEGER NOT NULL,
            UNIQUE(word_id, synset_id)
        );

        -- Synset-to-synset relations (from WordNet)
        CREATE TABLE wn_relations (
            source_synset INTEGER NOT NULL,
            relation TEXT NOT NULL,
            target_synset INTEGER NOT NULL
        );

        -- Flattened word-to-word relations (derived from synset relations)
        -- This is the main lookup table for the semantics engine
        CREATE TABLE word_relations (
            word TEXT NOT NULL,
            relation TEXT NOT NULL,
            related_word TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'wordnet'
        );

        CREATE INDEX idx_word_rel ON word_relations(word, relation);
        CREATE INDEX idx_word ON word_relations(word);
    """)

    # Insert words
    print("Inserting words...")
    batch = [(int(wid), form, pos) for wid, (form, pos) in words.items()]
    cur.executemany("INSERT OR IGNORE INTO wn_words (id, form, pos) VALUES (?, ?, ?)", batch)
    stats["words"] = len(batch)

    # Insert synsets
    synset_ids = set()
    for wid_list in s2w.values():
        pass  # just need synset keys
    for sid in s2w:
        synset_ids.add(int(sid))
    cur.executemany("INSERT OR IGNORE INTO wn_synsets (id) VALUES (?)",
                    [(sid,) for sid in synset_ids])
    stats["synsets"] = len(synset_ids)

    # Insert wordsenses
    ws_batch = []
    for wid, synsets in w2s.items():
        for sid in synsets:
            ws_batch.append((int(wid), int(sid)))
    cur.executemany("INSERT OR IGNORE INTO wn_wordsenses (word_id, synset_id) VALUES (?, ?)",
                    ws_batch)
    stats["wordsenses"] = len(ws_batch)

    # Insert synset relations
    rel_batch = [(int(src), rel, int(tgt)) for src, rel, tgt in relations]
    cur.executemany(
        "INSERT INTO wn_relations (source_synset, relation, target_synset) VALUES (?, ?, ?)",
        rel_batch
    )
    stats["wn_relations"] = len(rel_batch)

    conn.commit()

    # Flatten synset relations into word-to-word relations
    print("Flattening synset relations to word pairs...")

    # For each synset relation, expand to all word pairs
    word_rel_batch = []
    seen = set()

    # 1) Words in the same synset are synonyms
    print("  Computing synset-based synonyms...")
    for sid, word_ids in s2w.items():
        forms = set()
        for wid in word_ids:
            if wid in words:
                forms.add(words[wid][0])
        forms_list = sorted(forms)
        for i, w1 in enumerate(forms_list):
            for w2 in forms_list[i + 1:]:
                key1 = (w1, "synonym", w2)
                key2 = (w2, "synonym", w1)
                if key1 not in seen:
                    word_rel_batch.append((w1, "synonym", w2, "wordnet"))
                    word_rel_batch.append((w2, "synonym", w1, "wordnet"))
                    seen.add(key1)
                    seen.add(key2)

    # 2) Synset-to-synset relations → word pairs
    print("  Computing cross-synset word pairs...")
    for src_sid, rel, tgt_sid in relations:
        src_words = set()
        tgt_words = set()
        for wid in s2w.get(src_sid, []):
            if wid in words:
                src_words.add(words[wid][0])
        for wid in s2w.get(tgt_sid, []):
            if wid in words:
                tgt_words.add(words[wid][0])

        for w1 in src_words:
            for w2 in tgt_words:
                if w1 == w2:
                    continue
                key = (w1, rel, w2)
                if key not in seen:
                    word_rel_batch.append((w1, rel, w2, "wordnet"))
                    seen.add(key)
                    # Add reverse for symmetric relations
                    if rel in ("synonym", "antonym", "related"):
                        rev_key = (w2, rel, w1)
                        if rev_key not in seen:
                            word_rel_batch.append((w2, rel, w1, "wordnet"))
                            seen.add(rev_key)
                    elif rel == "hypernym":
                        # If X hyponymOf Y, then Y is hypernym of X
                        # Store as: X has hypernym Y, and Y has hyponym X
                        rev_key = (w2, "hyponym", w1)
                        if rev_key not in seen:
                            word_rel_batch.append((w2, "hyponym", w1, "wordnet"))
                            seen.add(rev_key)
                    elif rel == "holonym":
                        rev_key = (w2, "meronym", w1)
                        if rev_key not in seen:
                            word_rel_batch.append((w2, "meronym", w1, "wordnet"))
                            seen.add(rev_key)
                    elif rel == "meronym":
                        rev_key = (w2, "holonym", w1)
                        if rev_key not in seen:
                            word_rel_batch.append((w2, "holonym", w1, "wordnet"))
                            seen.add(rev_key)

    # 3) Norwegian synonyms JSON
    # License: CC BY-NC-SA 4.0 — academic use only
    print("  Adding synonym list entries...")
    for word, syns in syn_json.items():
        for syn in syns:
            key = (word, "synonym", syn)
            if key not in seen:
                word_rel_batch.append((word, "synonym", syn, "synonymlist"))
                seen.add(key)
            rev_key = (syn, "synonym", word)
            if rev_key not in seen:
                word_rel_batch.append((syn, "synonym", word, "synonymlist"))
                seen.add(rev_key)

    # Insert all word relations
    print(f"  Inserting {len(word_rel_batch):,} word relations...")
    for i in range(0, len(word_rel_batch), 10000):
        cur.executemany(
            "INSERT INTO word_relations (word, relation, related_word, source) "
            "VALUES (?, ?, ?, ?)",
            word_rel_batch[i:i + 10000]
        )
    conn.commit()
    stats["word_relations"] = len(word_rel_batch)
    stats["synonym_pairs"] = sum(1 for _, r, _, _ in word_rel_batch if r == "synonym")

    # Create stats
    cur.execute("SELECT relation, COUNT(*) FROM word_relations GROUP BY relation ORDER BY COUNT(*) DESC")
    stats["relation_distribution"] = cur.fetchall()

    conn.close()
    return stats


def main():
    if not WORDNET_DIR.exists():
        print(f"ERROR: WordNet not found at {WORDNET_DIR}", file=sys.stderr)
        print("Download and extract: https://www.nb.no/sbfil/leksikalske_databaser/norsk_ordvev_nob_1.1.2.zip")
        sys.exit(1)

    print(f"Building semantics DB...")
    stats = build_db(WORDNET_DIR, SYNONYMS_FILE, DB_FILE)

    print(f"\n=== Statistics ===")
    print(f"Words:             {stats['words']:>10,}")
    print(f"Synsets:           {stats['synsets']:>10,}")
    print(f"Word senses:       {stats['wordsenses']:>10,}")
    print(f"WN relations:      {stats['wn_relations']:>10,}")
    print(f"Word relations:    {stats['word_relations']:>10,}")
    print(f"Synonym pairs:     {stats['synonym_pairs']:>10,}")

    print(f"\n=== Relation distribution ===")
    for rel, count in stats["relation_distribution"]:
        print(f"  {rel:20} {count:>10,}")

    print(f"\nDatabase: {DB_FILE}")

    # Demo
    conn = sqlite3.connect(str(DB_FILE))
    print(f"\n=== Demo: synonyms for 'glad' ===")
    cur = conn.execute(
        "SELECT DISTINCT related_word, source FROM word_relations "
        "WHERE word = 'glad' AND relation = 'synonym' ORDER BY related_word"
    )
    for row in cur:
        print(f"  {row[0]:25} ({row[1]})")

    print(f"\n=== Demo: antonyms for 'glad' ===")
    cur = conn.execute(
        "SELECT DISTINCT related_word FROM word_relations "
        "WHERE word = 'glad' AND relation = 'antonym'"
    )
    for row in cur:
        print(f"  {row[0]}")

    print(f"\n=== Demo: hypernyms for 'hund' ===")
    cur = conn.execute(
        "SELECT DISTINCT related_word FROM word_relations "
        "WHERE word = 'hund' AND relation = 'hypernym' LIMIT 10"
    )
    for row in cur:
        print(f"  {row[0]}")

    conn.close()


if __name__ == "__main__":
    main()
