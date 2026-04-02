from __future__ import annotations

"""Database access for rimordbok.

Supports dialect-aware queries via the `dialekt` parameter.
Default dialect is 'øst' (Østnorsk), which uses the main `ord` table.
Other dialects (nord, midt, vest, sørvest) use the `ord_dialekter` table
for words that differ from østnorsk, falling back to `ord` for the rest.
"""

import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"

GYLDIGE_DIALEKTER = {"øst", "nord", "midt", "vest", "sørvest"}

# Thread-local persistent connections with WAL + tuning
_local = threading.local()


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = str(db_path or DEFAULT_DB)
    cache_key = f"conn_{path}"
    conn = getattr(_local, cache_key, None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass  # Connection closed, recreate
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA synchronous=NORMAL")
    setattr(_local, cache_key, conn)
    return conn


def hent_rim(
    ord: str,
    db_path: Optional[Path] = None,
    maks: int = 50,
    samme_tonelag: bool = False,
) -> list[dict]:
    """Find words that rhyme with the given word.

    Returns list of dicts with keys: ord, rimsuffiks, tonelag, stavelser.
    """
    conn = _connect(db_path)
    try:
        # Look up the source word's rhyme suffix
        row = conn.execute(
            "SELECT rimsuffiks, tonelag FROM ord WHERE ord = ? LIMIT 1",
            (ord,),
        ).fetchone()

        if row is None:
            return []

        suffix = row["rimsuffiks"]
        tonelag = row["tonelag"]

        if samme_tonelag and tonelag is not None:
            cur = conn.execute(
                "SELECT DISTINCT ord, rimsuffiks, tonelag, stavelser "
                "FROM ord WHERE rimsuffiks = ? AND tonelag = ? AND ord != ? "
                "ORDER BY ord LIMIT ?",
                (suffix, tonelag, ord, maks),
            )
        else:
            cur = conn.execute(
                "SELECT DISTINCT ord, rimsuffiks, tonelag, stavelser "
                "FROM ord WHERE rimsuffiks = ? AND ord != ? "
                "ORDER BY ord LIMIT ?",
                (suffix, ord, maks),
            )

        return [dict(r) for r in cur]
    finally:
        pass  # Connection reused via thread-local pool


def hent_fonetikk(ord: str, db_path: Optional[Path] = None) -> list[dict]:
    """Get phonetic info for a word. Returns all entries (may have multiple POS)."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT ord, pos, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser "
            "FROM ord WHERE ord = ?",
            (ord,),
        )
        return [dict(r) for r in cur]
    finally:
        pass  # Connection reused via thread-local pool


def hent_fonetikk_dialekt(
    ord: str, dialekt: str, db_path: Optional[Path] = None
) -> Optional[dict]:
    """Get dialect-specific phonetic info for a word.

    If the word has a dialect-specific entry, returns it.
    Otherwise falls back to østnorsk from the main ord table.
    """
    conn = _connect(db_path)
    try:
        if dialekt != "øst":
            row = conn.execute(
                "SELECT ord, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser "
                "FROM ord_dialekter WHERE ord = ? AND dialekt = ? LIMIT 1",
                (ord, dialekt),
            ).fetchone()
            if row:
                return dict(row)

        # Fallback to østnorsk
        row = conn.execute(
            "SELECT ord, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser "
            "FROM ord WHERE ord = ? LIMIT 1",
            (ord,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        pass  # Connection reused via thread-local pool


def hent_rim_dialekt(
    suffix: str,
    dialekt: str,
    ord_lower: str,
    db_path: Optional[Path] = None,
    maks: int = 1000,
    samme_tonelag: bool = False,
    tonelag_val: Optional[int] = None,
) -> list[dict]:
    """Find rhyming words for a given suffix in a specific dialect.

    For non-øst dialects: queries ord_dialekter for words with different
    suffixes in that dialect, UNION with ord table entries that have no
    dialect override (meaning they're the same as østnorsk).
    """
    conn = _connect(db_path)
    try:
        if dialekt == "øst":
            # Group by LOWER(ord) to deduplicate Sol/sol and same-word POS variants
            if samme_tonelag and tonelag_val is not None:
                cur = conn.execute(
                    "SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
                    "MAX(stavelser) as stavelser, MAX(frekvens) as frekvens "
                    "FROM ord WHERE rimsuffiks = ? AND tonelag = ? "
                    "AND LOWER(ord) != ? "
                    "GROUP BY LOWER(ord) ORDER BY frekvens DESC LIMIT ?",
                    (suffix, tonelag_val, ord_lower, maks),
                )
            else:
                cur = conn.execute(
                    "SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
                    "MAX(stavelser) as stavelser, MAX(frekvens) as frekvens "
                    "FROM ord WHERE rimsuffiks = ? "
                    "AND LOWER(ord) != ? "
                    "GROUP BY LOWER(ord) ORDER BY frekvens DESC LIMIT ?",
                    (suffix, ord_lower, maks),
                )
            return [dict(r) for r in cur]

        # Non-øst dialect: union of dialect-specific + øst fallback
        # Words in ord_dialekter for this dialect with matching suffix
        # PLUS words in ord that DON'T have an override in ord_dialekter
        tonelag_clause = "AND tonelag = ?" if (samme_tonelag and tonelag_val is not None) else ""
        params_dialect = [suffix, dialekt, ord_lower]
        params_fallback = [suffix, ord_lower, dialekt]
        if tonelag_clause:
            params_dialect.append(tonelag_val)
            params_fallback.append(tonelag_val)

        query = f"""
            SELECT LOWER(ord) as ord, rimsuffiks, tonelag, stavelser, 0.0 as frekvens
            FROM ord_dialekter
            WHERE rimsuffiks = ? AND dialekt = ? AND LOWER(ord) != ? {tonelag_clause}
            GROUP BY LOWER(ord)

            UNION

            SELECT LOWER(o.ord) as ord, o.rimsuffiks, o.tonelag,
                   MAX(o.stavelser) as stavelser, MAX(o.frekvens) as frekvens
            FROM ord o
            WHERE o.rimsuffiks = ? AND LOWER(o.ord) != ?
            AND NOT EXISTS (
                SELECT 1 FROM ord_dialekter d
                WHERE d.ord = o.ord AND d.dialekt = ?
            )
            {tonelag_clause}
            GROUP BY LOWER(o.ord)

            ORDER BY frekvens DESC
            LIMIT ?
        """
        params = params_dialect + params_fallback + [maks]
        cur = conn.execute(query, params)
        return [dict(r) for r in cur]
    finally:
        pass  # Connection reused via thread-local pool


def hent_varianter(ord: str, db_path: Optional[Path] = None) -> list[dict]:
    """Find all distinct pronunciation variants for a word (homograph detection).

    Groups by rimsuffiks to detect words with different rhyme behavior.
    Only variants with genuinely different rimsuffikser are returned —
    words that are spelled the same but pronounced differently for rhyme
    purposes (e.g. "stolt" as verb /uːlt/ vs adjective /ɔlt/).

    Returns list of dicts: rimsuffiks, ipa_ren, pos, tonelag, stavelser, frekvens.
    Sorted by frequency descending (most common variant first).

    If only one unique rimsuffiks exists, returns a single entry.
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT rimsuffiks, ipa_ren, pos, tonelag, stavelser, "
            "MAX(frekvens) as frekvens "
            "FROM ord WHERE LOWER(ord) = ? "
            "GROUP BY rimsuffiks "
            "ORDER BY frekvens DESC",
            (ord.lower(),),
        )
        return [dict(r) for r in cur]
    finally:
        pass


def hent_rim_for_suffiks(
    suffiks: str,
    ord_lower: str,
    db_path: Optional[Path] = None,
    maks: int = 200,
    samme_tonelag: bool = False,
    tonelag_val: Optional[int] = None,
    ekskluder_propn: bool = True,
) -> list[dict]:
    """Find rhyming words for a specific suffix (used after disambiguation).

    Returns list of dicts: ord, rimsuffiks, tonelag, stavelser, frekvens, pos.
    Sorted by frequency descending.
    If ekskluder_propn=True, filters out proper nouns (PM).
    """
    conn = _connect(db_path)
    try:
        propn_clause = "AND pos NOT LIKE 'PM%'" if ekskluder_propn else ""
        tonelag_clause = "AND tonelag = ?" if (samme_tonelag and tonelag_val is not None) else ""

        params: list = [suffiks, ord_lower]
        if tonelag_clause:
            params.append(tonelag_val)
        params.append(maks)

        cur = conn.execute(
            f"SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
            f"MAX(stavelser) as stavelser, MAX(frekvens) as frekvens, pos "
            f"FROM ord WHERE rimsuffiks = ? AND LOWER(ord) != ? "
            f"{propn_clause} {tonelag_clause} "
            f"GROUP BY LOWER(ord) ORDER BY frekvens DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in cur]
    finally:
        pass


def hent_ord_for_halvrim(
    suffikser: list[str],
    ord_lower: str,
    db_path: Optional[Path] = None,
    maks: int = 500,
    ekskluder_propn: bool = True,
    stavelser_eq: Optional[int] = None,
    stavelser_gte: Optional[int] = None,
) -> list[dict]:
    """Get words matching any of the given suffixes, with IPA data.

    Used by the halvrim engine to fetch candidates for depth-based scoring.
    Can filter by syllable count: stavelser_eq for exact, stavelser_gte for minimum.

    Returns list of dicts: ord, rimsuffiks, tonelag, stavelser, frekvens, ipa_ren, pos.
    Deduplicates by LOWER(ord), keeping highest-frequency entry.
    """
    if not suffikser:
        return []
    conn = _connect(db_path)
    try:
        propn_clause = "AND pos NOT LIKE 'PM%'" if ekskluder_propn else ""

        syl_clause = ""
        syl_params: list = []
        if stavelser_eq is not None:
            syl_clause = "AND stavelser = ?"
            syl_params = [stavelser_eq]
        elif stavelser_gte is not None:
            syl_clause = "AND stavelser >= ?"
            syl_params = [stavelser_gte]

        placeholders = ",".join("?" for _ in suffikser)
        params: list = list(suffikser) + [ord_lower] + syl_params + [maks]

        cur = conn.execute(
            f"SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
            f"stavelser, frekvens, ipa_ren, pos "
            f"FROM ord WHERE rimsuffiks IN ({placeholders}) "
            f"AND LOWER(ord) != ? "
            f"{propn_clause} {syl_clause} "
            f"ORDER BY frekvens DESC LIMIT ?",
            params,
        )
        # Deduplicate by word, keeping highest frequency entry
        seen: dict[str, dict] = {}
        for r in cur:
            d = dict(r)
            key = d["ord"]
            if key not in seen or (d["frekvens"] or 0) > (seen[key]["frekvens"] or 0):
                seen[key] = d
        return list(seen.values())
    finally:
        pass


def hent_rim_med_ipa(
    suffiks: str,
    ord_lower: str,
    db_path: Optional[Path] = None,
    maks: int = 500,
    ekskluder_propn: bool = True,
    samme_tonelag: bool = False,
    tonelag_val: Optional[int] = None,
) -> list[dict]:
    """Get rhyme candidates with IPA data for syllable-depth filtering.

    Like hent_rim_for_suffiks but also returns ipa_ren, needed for
    computing multi-syllable suffix matches. Deduplicates by LOWER(ord),
    keeping the highest-frequency entry.

    Returns list of dicts: ord, rimsuffiks, tonelag, stavelser, frekvens, ipa_ren, pos.
    """
    conn = _connect(db_path)
    try:
        propn_clause = "AND pos NOT LIKE 'PM%'" if ekskluder_propn else ""
        tonelag_clause = "AND tonelag = ?" if (samme_tonelag and tonelag_val is not None) else ""

        params: list = [suffiks, ord_lower]
        if tonelag_clause:
            params.append(tonelag_val)
        params.append(maks)

        cur = conn.execute(
            f"SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
            f"stavelser, frekvens, ipa_ren, pos "
            f"FROM ord WHERE rimsuffiks = ? AND LOWER(ord) != ? "
            f"{propn_clause} {tonelag_clause} "
            f"ORDER BY frekvens DESC LIMIT ?",
            params,
        )
        # Deduplicate by word, keeping highest frequency entry
        seen: dict[str, dict] = {}
        for r in cur:
            d = dict(r)
            key = d["ord"]
            if key not in seen or (d["frekvens"] or 0) > (seen[key]["frekvens"] or 0):
                seen[key] = d
        return list(seen.values())
    finally:
        pass


def sok_ord(
    prefiks: str, db_path: Optional[Path] = None, maks: int = 20
) -> list[str]:
    """Autocomplete: find words starting with the given prefix."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT DISTINCT ord FROM ord WHERE ord >= ? AND ord < ? ORDER BY ord LIMIT ?",
            (prefiks, prefiks + "\uffff", maks),
        )
        return [r["ord"] for r in cur]
    finally:
        pass  # Connection reused via thread-local pool
