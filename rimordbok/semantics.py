from __future__ import annotations

"""Semantic relations: synonyms, antonyms, and related words.

Combines two data sources:
- Norwegian WordNet Bokmål (CC BY 4.0): synset-based semantic relations
- norwegian-synonyms (CC BY-NC-SA 4.0): direct synonym lists
  NOTE: The synonym list is licensed for academic/non-commercial use only.

All lookups go through the pre-built semantics.db (built by scripts/parse_wordnet.py).
"""

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data/db/semantics.db"
RHYME_DB = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _get_frequencies_batch(words: list, rhyme_db: Optional[Path] = None) -> dict:
    """Look up word frequencies in batch from the rhyme index DB."""
    path = rhyme_db or RHYME_DB
    if not path.exists() or not words:
        return {}
    conn = sqlite3.connect(str(path))
    # Use a single query with IN clause for batch lookup
    placeholders = ",".join("?" for _ in words)
    lower_words = [w.lower() for w in words]
    cur = conn.execute(
        f"SELECT LOWER(ord) as word_lower, MAX(frekvens) as freq "
        f"FROM ord WHERE LOWER(ord) IN ({placeholders}) GROUP BY LOWER(ord)",
        lower_words,
    )
    result = {}
    for row in cur:
        result[row[0]] = row[1] if row[1] else 0.0
    pass
    return result


def _query_relations(
    word: str,
    relation: str,
    db_path: Optional[Path] = None,
    rhyme_db: Optional[Path] = None,
    maks: int = 50,
) -> list[dict]:
    """Query word relations, sorted by frequency."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT DISTINCT related_word, source FROM word_relations "
            "WHERE LOWER(word) = ? AND relation = ?",
            (word.lower(), relation),
        )
        rows = [(row["related_word"], row["source"]) for row in cur]

        # Batch frequency lookup
        freq_map = _get_frequencies_batch(
            [r[0] for r in rows], rhyme_db
        )

        results = []
        for related, source in rows:
            results.append({
                "ord": related,
                "relasjon": relation,
                "kilde": source,
                "frekvens": freq_map.get(related.lower(), 0.0),
            })

        # Sort by frequency descending (common words first)
        results.sort(key=lambda r: -r["frekvens"])
        return results[:maks]
    finally:
        pass


def _bokmaalsordboka_fallback(ord: str, relation: str, rhyme_db: Optional[Path] = None) -> list[dict]:
    """Fallback to Bokmålsordboka via ordbokapi.org for synonyms/antonyms."""
    try:
        from rimordbok.definitions import hent_definisjon
        defn = hent_definisjon(ord)
        words = defn.get("synonymer" if relation == "synonym" else "antonymer", [])
        if not words:
            return []
        freq_map = _get_frequencies_batch(words, rhyme_db)
        results = [{
            "ord": w,
            "relasjon": relation,
            "kilde": "bokmaalsordboka",
            "frekvens": freq_map.get(w.lower(), 0.0),
        } for w in words]
        results.sort(key=lambda r: -r["frekvens"])
        return results
    except Exception:
        return []


def finn_synonymer(
    ord: str,
    db_path: Optional[Path] = None,
    rhyme_db: Optional[Path] = None,
    maks: int = 50,
) -> list[dict]:
    """Find synonyms for a word.

    Combines WordNet + synonym list + Bokmålsordboka fallback.
    Results sorted by word frequency (most common first).

    Returns list of dicts: ord, relasjon, kilde, frekvens.
    """
    results = _query_relations(ord, "synonym", db_path, rhyme_db, maks)
    # Always merge with Bokmålsordboka
    bm = _bokmaalsordboka_fallback(ord, "synonym", rhyme_db)
    existing = {r["ord"].lower() for r in results}
    for r in bm:
        if r["ord"].lower() not in existing:
            results.append(r)
            existing.add(r["ord"].lower())
    results.sort(key=lambda r: -r["frekvens"])
    return results[:maks]


def finn_antonymer(
    ord: str,
    db_path: Optional[Path] = None,
    rhyme_db: Optional[Path] = None,
    maks: int = 50,
) -> list[dict]:
    """Find antonyms for a word.

    Combines WordNet + Bokmålsordboka.
    Returns list of dicts: ord, relasjon, kilde, frekvens.
    """
    results = _query_relations(ord, "antonym", db_path, rhyme_db, maks)
    bm = _bokmaalsordboka_fallback(ord, "antonym", rhyme_db)
    existing = {r["ord"].lower() for r in results}
    for r in bm:
        if r["ord"].lower() not in existing:
            results.append(r)
            existing.add(r["ord"].lower())
    results.sort(key=lambda r: -r["frekvens"])
    return results[:maks]


def finn_relaterte(
    ord: str,
    db_path: Optional[Path] = None,
    rhyme_db: Optional[Path] = None,
    maks: int = 50,
) -> list[dict]:
    """Find related words (hypernyms + hyponyms + related).

    Returns list of dicts: ord, relasjon, kilde, frekvens.
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT DISTINCT related_word, relation, source FROM word_relations "
            "WHERE LOWER(word) = ? AND relation IN ('hypernym', 'hyponym', 'related')",
            (ord.lower(),),
        )
        rows = [(row["related_word"], row["relation"], row["source"]) for row in cur]

        freq_map = _get_frequencies_batch([r[0] for r in rows], rhyme_db)

        results = []
        for related, relation, source in rows:
            results.append({
                "ord": related,
                "relasjon": relation,
                "kilde": source,
                "frekvens": freq_map.get(related.lower(), 0.0),
            })

        results.sort(key=lambda r: -r["frekvens"])
        return results[:maks]
    finally:
        pass


def finn_meronymer(
    ord: str,
    db_path: Optional[Path] = None,
    rhyme_db: Optional[Path] = None,
    maks: int = 50,
) -> list[dict]:
    """Find meronyms (parts of the given word).

    Returns list of dicts: ord, relasjon, kilde, frekvens.
    """
    return _query_relations(ord, "meronym", db_path, rhyme_db, maks)


def finn_holonymer(
    ord: str,
    db_path: Optional[Path] = None,
    rhyme_db: Optional[Path] = None,
    maks: int = 50,
) -> list[dict]:
    """Find holonyms (wholes that the given word is part of).

    Returns list of dicts: ord, relasjon, kilde, frekvens.
    """
    return _query_relations(ord, "holonym", db_path, rhyme_db, maks)
