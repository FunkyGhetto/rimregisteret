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

# --- In-memory preloaded indexes (built once at import time) ---
# suffix → list of word dicts (sorted by frequency desc)
_SUFFIX_INDEX: dict[str, list[dict]] = {}
# lowercase word → list of phonetics dicts
_WORD_INDEX: dict[str, list[dict]] = {}
_PRELOADED = False


def _ensure_preloaded():
    """Load entire ord table into memory for O(1) lookups. Called lazily on first use."""
    global _SUFFIX_INDEX, _WORD_INDEX, _PRELOADED
    if _PRELOADED:
        return
    import logging
    import time as _time
    logger = logging.getLogger("rimordbok.db")
    t0 = _time.time()

    conn = _connect()
    cur = conn.execute(
        "SELECT ord, LOWER(ord) as ord_lower, pos, fonemer, ipa_ren, "
        "rimsuffiks, tonelag, stavelser, frekvens "
        "FROM ord ORDER BY frekvens DESC"
    )

    suffix_idx: dict[str, dict[str, dict]] = {}
    word_idx: dict[str, list[dict]] = {}

    for row in cur:
        d = dict(row)
        word_lower = d["ord_lower"]
        suffix = d["rimsuffiks"]

        if word_lower not in word_idx:
            word_idx[word_lower] = []
        word_idx[word_lower].append({
            "ord": d["ord"], "pos": d["pos"], "fonemer": d["fonemer"],
            "ipa_ren": d["ipa_ren"], "rimsuffiks": suffix,
            "tonelag": d["tonelag"], "stavelser": d["stavelser"],
        })

        if suffix not in suffix_idx:
            suffix_idx[suffix] = {}
        if word_lower not in suffix_idx[suffix]:
            suffix_idx[suffix][word_lower] = {
                "ord": word_lower, "rimsuffiks": suffix,
                "tonelag": d["tonelag"], "stavelser": d["stavelser"],
                "frekvens": d["frekvens"] or 0, "ipa_ren": d["ipa_ren"],
                "pos": d["pos"],
            }

    _SUFFIX_INDEX = {
        sfx: sorted(words.values(), key=lambda w: -(w["frekvens"] or 0))
        for sfx, words in suffix_idx.items()
    }
    _WORD_INDEX = word_idx
    _PRELOADED = True

    elapsed = _time.time() - t0
    logger.info(
        "Preloaded %d suffixes, %d words in %.1fs",
        len(_SUFFIX_INDEX), len(_WORD_INDEX), elapsed,
    )


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
    if db_path is None:
        _ensure_preloaded()
        if _PRELOADED:
            entries = _WORD_INDEX.get(ord, []) or _WORD_INDEX.get(ord.lower(), [])
            return [dict(e) for e in entries]
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT ord, pos, fonemer, ipa_ren, rimsuffiks, tonelag, stavelser "
            "FROM ord WHERE ord = ?",
            (ord,),
        )
        return [dict(r) for r in cur]
    finally:
        pass


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
    Only variants with genuinely different rimsuffikser are returned.
    """
    if db_path is None:
        _ensure_preloaded()
        if _PRELOADED:
            entries = _WORD_INDEX.get(ord.lower(), [])
            seen: dict[str, dict] = {}
            for e in entries:
                sfx = e["rimsuffiks"]
                if sfx not in seen:
                    seen[sfx] = dict(e)
            return sorted(seen.values(), key=lambda v: -(v.get("frekvens", 0) or 0))
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
    """Find rhyming words for a specific suffix."""
    if db_path is None:
        _ensure_preloaded()
        if _PRELOADED:
            words = _SUFFIX_INDEX.get(suffiks, [])
            result = []
            for w in words:
                if w["ord"] == ord_lower:
                    continue
                if ekskluder_propn and w.get("pos", "").startswith("PM"):
                    continue
                if samme_tonelag and tonelag_val is not None and w.get("tonelag") != tonelag_val:
                    continue
                result.append(dict(w))
                if len(result) >= maks:
                    break
            return result
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
    """Get words matching any of the given suffixes, with IPA data."""
    if not suffikser:
        return []
    if db_path is None:
        _ensure_preloaded()
        if _PRELOADED:
            seen: dict[str, dict] = {}
            for sfx in suffikser:
                for w in _SUFFIX_INDEX.get(sfx, []):
                    if w["ord"] == ord_lower:
                        continue
                    if ekskluder_propn and w.get("pos", "").startswith("PM"):
                        continue
                    syl = w.get("stavelser", 1) or 1
                    if stavelser_eq is not None and syl != stavelser_eq:
                        continue
                    if stavelser_gte is not None and syl < stavelser_gte:
                        continue
                    key = w["ord"]
                    if key not in seen:
                        seen[key] = dict(w)
                    if len(seen) >= maks:
                        break
                if len(seen) >= maks:
                    break
            return list(seen.values())
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
        seen2: dict[str, dict] = {}
        for r in cur:
            d = dict(r)
            key = d["ord"]
            if key not in seen2 or (d["frekvens"] or 0) > (seen2[key]["frekvens"] or 0):
                seen2[key] = d
        return list(seen2.values())
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
    """Get rhyme candidates with IPA data for syllable-depth filtering."""
    if db_path is None:
        _ensure_preloaded()
        if _PRELOADED:
            return hent_rim_for_suffiks(
                suffiks, ord_lower, db_path=None, maks=maks,
                samme_tonelag=samme_tonelag, tonelag_val=tonelag_val,
                ekskluder_propn=ekskluder_propn,
            )
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
