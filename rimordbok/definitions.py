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
    }
  }
}
"""


def _init_cache(db_path: Path) -> None:
    """Create cache table if it doesn't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS definisjoner (
            ord TEXT PRIMARY KEY,
            definisjon TEXT,
            ordklasse TEXT,
            hentet_dato TEXT
        )
    """)
    conn.commit()
    conn.close()


def _get_cached(word: str, db_path: Path) -> Optional[dict]:
    """Check cache for a definition."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT definisjon, ordklasse FROM definisjoner WHERE ord = ?",
        (word.lower(),),
    ).fetchone()
    conn.close()
    if row is not None:
        return {"definisjon": row[0], "ordklasse": row[1]}
    return None


def _set_cached(word: str, definisjon: Optional[str], ordklasse: Optional[str], db_path: Path) -> None:
    """Store a definition in cache."""
    _init_cache(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO definisjoner (ord, definisjon, ordklasse, hentet_dato) VALUES (?, ?, ?, datetime('now'))",
        (word.lower(), definisjon, ordklasse),
    )
    conn.commit()
    conn.close()


def _pick_best_definition(articles: list) -> tuple[Optional[str], Optional[str]]:
    """Pick the most relevant definition from articles.

    Strategy: choose the article with the most definitions (most common meaning),
    then take its first definition text.
    """
    best_article = None
    best_count = 0

    for art in articles:
        defs = art.get("definitions", [])
        count = len(defs)
        if count > best_count:
            best_count = count
            best_article = art

    if not best_article:
        return None, None

    ordklasse = best_article.get("wordClass")
    for d in best_article.get("definitions", []):
        for c in d.get("content", []):
            text = c.get("textContent", "").strip()
            if text and len(text) > 3:
                return text, ordklasse

    return None, ordklasse


def hent_definisjon(
    ord: str, cache_db: Optional[Path] = None
) -> dict:
    """Hent definisjon for et norsk ord.

    Returns dict with keys: definisjon (str|None), ordklasse (str|None).
    Never raises — returns empty on failure.
    """
    db_path = cache_db or CACHE_DB

    # Check cache first
    cached = _get_cached(ord, db_path)
    if cached is not None:
        return cached

    # No httpx = can't fetch
    if not _HAS_HTTPX:
        return {"definisjon": None, "ordklasse": None}

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
            _set_cached(ord, None, None, db_path)
            return {"definisjon": None, "ordklasse": None}

        articles = word_data.get("articles", [])
        definisjon, ordklasse = _pick_best_definition(articles)

        _set_cached(ord, definisjon, ordklasse, db_path)
        return {"definisjon": definisjon, "ordklasse": ordklasse}

    except Exception:
        # Timeout, network error, etc. — don't cache failures
        return {"definisjon": None, "ordklasse": None}
