from __future__ import annotations

"""Hent orddefinisjoner fra ordbokapi.org (Bokmålsordboka).

Cacher resultater i SQLite for å unngå gjentatte API-kall.
Timeout: 2 sekunder. Manglende definisjon er ikke en feil.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

GRAPHQL_URL = "https://api.ordbokapi.org/graphql"
CACHE_DB = Path(__file__).resolve().parent.parent / "data/db/definisjoner.db"
_TIMEOUT = 2.0

QUERY = """
query($word: String!) {
  word(word: $word, dictionaries: [Bokmaalsordboka]) {
    articles {
      wordClass
      definitions {
        content {
          textContent
        }
      }
      relationships {
        __typename
        ... on SynonymArticleRelationship {
          article { lemmas { lemma } }
        }
        ... on AntonymArticleRelationship {
          article { lemmas { lemma } }
        }
      }
    }
  }
}
"""


def _init_cache(db_path: Path) -> None:
    """Create cache tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS definisjoner (
            ord TEXT PRIMARY KEY,
            definisjon TEXT,
            ordklasse TEXT,
            synonymer TEXT,
            antonymer TEXT,
            hentet_dato TEXT
        )
    """)
    # Add columns if they don't exist (migration for existing DBs)
    try:
        conn.execute("ALTER TABLE definisjoner ADD COLUMN synonymer TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE definisjoner ADD COLUMN antonymer TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def _get_cached(word: str, db_path: Path) -> Optional[dict]:
    """Check cache for a definition."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT definisjon, ordklasse, synonymer, antonymer FROM definisjoner WHERE ord = ?",
        (word.lower(),),
    ).fetchone()
    conn.close()
    if row is not None:
        return {
            "definisjon": row[0],
            "ordklasse": row[1],
            "synonymer": json.loads(row[2]) if row[2] else [],
            "antonymer": json.loads(row[3]) if row[3] else [],
        }
    return None


def _set_cached(word: str, definisjon: Optional[str], ordklasse: Optional[str],
                synonymer: list, antonymer: list, db_path: Path) -> None:
    """Store definition + synonyms/antonyms in cache."""
    _init_cache(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO definisjoner (ord, definisjon, ordklasse, synonymer, antonymer, hentet_dato) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (word.lower(), definisjon, ordklasse,
         json.dumps(synonymer, ensure_ascii=False) if synonymer else None,
         json.dumps(antonymer, ensure_ascii=False) if antonymer else None),
    )
    conn.commit()
    conn.close()


def _pick_best_definition(articles: list) -> tuple[Optional[str], Optional[str], list, list]:
    """Pick the most relevant definition and extract synonyms/antonyms.

    Strategy: choose the article with the most definitions (most common meaning),
    then take its first definition text. Collect synonyms/antonyms from ALL articles.
    """
    best_article = None
    best_count = 0
    all_synonymer = []
    all_antonymer = []

    for art in articles:
        defs = art.get("definitions", [])
        count = len(defs)
        if count > best_count:
            best_count = count
            best_article = art

        # Collect synonyms/antonyms from relationships
        for rel in art.get("relationships", []):
            typename = rel.get("__typename", "")
            article = rel.get("article", {})
            lemmas = [l["lemma"] for l in article.get("lemmas", [])] if article else []
            if typename == "SynonymArticleRelationship":
                all_synonymer.extend(lemmas)
            elif typename == "AntonymArticleRelationship":
                all_antonymer.extend(lemmas)

    if not best_article:
        return None, None, all_synonymer, all_antonymer

    ordklasse = best_article.get("wordClass")
    for d in best_article.get("definitions", []):
        for c in d.get("content", []):
            text = c.get("textContent", "").strip()
            if text and len(text) > 3:
                return text, ordklasse, all_synonymer, all_antonymer

    return None, ordklasse, all_synonymer, all_antonymer


def hent_definisjon(
    ord: str, cache_db: Optional[Path] = None
) -> dict:
    """Hent definisjon, synonymer og antonymer for et norsk ord.

    Returns dict with keys: definisjon, ordklasse, synonymer, antonymer.
    Never raises — returns empty on failure.
    """
    db_path = cache_db or CACHE_DB

    # Check cache first
    cached = _get_cached(ord, db_path)
    if cached is not None:
        return cached

    empty = {"definisjon": None, "ordklasse": None, "synonymer": [], "antonymer": []}

    # No httpx = can't fetch
    if not _HAS_HTTPX:
        return empty

    # Fetch from API
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.post(
                GRAPHQL_URL,
                json={"query": QUERY, "variables": {"word": ord.lower()}},
            )
            r.raise_for_status()
            data = r.json()

        word_data = data.get("data", {}).get("word")
        if not word_data:
            _set_cached(ord, None, None, [], [], db_path)
            return empty

        articles = word_data.get("articles", [])
        definisjon, ordklasse, synonymer, antonymer = _pick_best_definition(articles)

        # Deduplicate and remove self
        synonymer = list(dict.fromkeys(s for s in synonymer if s.lower() != ord.lower()))
        antonymer = list(dict.fromkeys(a for a in antonymer if a.lower() != ord.lower()))

        _set_cached(ord, definisjon, ordklasse, synonymer, antonymer, db_path)
        return {"definisjon": definisjon, "ordklasse": ordklasse,
                "synonymer": synonymer, "antonymer": antonymer}

    except Exception:
        # Timeout, network error, etc. — don't cache failures
        return empty
