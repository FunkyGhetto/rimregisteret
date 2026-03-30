from __future__ import annotations

"""Rimklynge-generering for freestyle-trening.

Tre moduser:
- PAR:  Rimpar (2 ord per klynge) fra tilfeldige eller angitte rimfamilier.
- BRED: Brede klynger (4 ord per klynge) fra tilfeldige eller angitte rimfamilier.
- DYP:  Alle ord fra én rimfamilie, sortert etter frekvens.
"""

import random
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"

# Minimum family sizes per mode
_MIN_FAMILY = {"par": 2, "bred": 4, "dyp": 8}
_CLUSTER_SIZE = {"par": 2, "bred": 4}


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def hent_kvalifiserte_suffikser(
    min_ord: int,
    stavelser: Optional[int] = None,
    min_frekvens: float = 1.0,
    dialekt: str = "øst",
    db_path: Optional[Path] = None,
) -> list[str]:
    """Return rhyme suffixes that have at least `min_ord` qualifying words."""
    conn = _connect(db_path)
    try:
        where = ["frekvens >= ?", "length(ord) >= 2", "length(ord) <= 15"]
        params: list = [min_frekvens]

        if stavelser is not None:
            where.append("stavelser = ?")
            params.append(stavelser)

        having_param = min_ord
        query = (
            f"SELECT rimsuffiks FROM ord "
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY rimsuffiks HAVING COUNT(*) >= ? "
            f"ORDER BY rimsuffiks"
        )
        params.append(having_param)

        cur = conn.execute(query, params)
        return [row["rimsuffiks"] for row in cur]
    finally:
        conn.close()


def hent_rimfamilie(
    rimsuffiks: str,
    min_frekvens: float = 1.0,
    stavelser: Optional[int] = None,
    dialekt: str = "øst",
    maks: Optional[int] = None,
    tilfeldig: bool = False,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Get qualifying words for a given rhyme suffix.

    Args:
        tilfeldig: If True, use ORDER BY RANDOM() (for par/bred).
                   If False, ORDER BY frekvens DESC (for dyp).
        maks: Max words to return. None = all.
    """
    conn = _connect(db_path)
    try:
        where = [
            "rimsuffiks = ?",
            "frekvens >= ?",
            "length(ord) >= 2",
            "length(ord) <= 15",
        ]
        params: list = [rimsuffiks, min_frekvens]

        if stavelser is not None:
            where.append("stavelser = ?")
            params.append(stavelser)

        order = "RANDOM()" if tilfeldig else "frekvens DESC"
        limit_clause = f"LIMIT {int(maks)}" if maks else ""

        query = (
            f"SELECT DISTINCT ord, stavelser, tonelag, frekvens "
            f"FROM ord WHERE {' AND '.join(where)} "
            f"ORDER BY {order} {limit_clause}"
        )

        cur = conn.execute(query, params)
        return [dict(row) for row in cur]
    finally:
        conn.close()


def generer_rimklynger(
    modus: str = "par",
    antall: int = 10,
    stavelser: Optional[int] = None,
    min_frekvens: float = 1.0,
    dialekt: str = "øst",
    ord: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Generate rhyme clusters for freestyle training.

    Args:
        modus: "par" (2 words), "bred" (4 words), or "dyp" (all words).
        antall: Number of clusters to generate (ignored for "dyp").
        stavelser: Filter on syllable count (None = all).
        min_frekvens: Minimum word frequency per million.
        dialekt: Dialect region (default "øst").
        ord: Optional seed word — use its rhyme family instead of random.
        db_path: Optional database path override.

    Returns:
        List of cluster dicts: {rimsuffiks, stavelser, ord: [str, ...]}
        For "dyp", always returns a single-element list.
    """
    if modus not in ("par", "bred", "dyp"):
        raise ValueError(f"Ugyldig modus: {modus!r}. Bruk 'par', 'bred' eller 'dyp'.")

    if ord is not None:
        return _klynger_med_ord(
            modus=modus,
            startord=ord,
            antall=antall,
            stavelser=stavelser,
            min_frekvens=min_frekvens,
            dialekt=dialekt,
            db_path=db_path,
        )

    return _klynger_tilfeldig(
        modus=modus,
        antall=antall,
        stavelser=stavelser,
        min_frekvens=min_frekvens,
        dialekt=dialekt,
        db_path=db_path,
    )


def _klynger_med_ord(
    modus: str,
    startord: str,
    antall: int,
    stavelser: Optional[int],
    min_frekvens: float,
    dialekt: str,
    db_path: Optional[Path],
) -> list[dict]:
    """Generate clusters using a specific word's rhyme family."""
    # Look up the word's rhyme suffix
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT rimsuffiks FROM ord WHERE LOWER(ord) = ? LIMIT 1",
            (startord.lower(),),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return []

    suffiks = row["rimsuffiks"]

    if modus == "dyp":
        familie = hent_rimfamilie(
            suffiks,
            min_frekvens=min_frekvens,
            stavelser=stavelser,
            dialekt=dialekt,
            tilfeldig=False,
            db_path=db_path,
        )
        return [{
            "rimsuffiks": suffiks,
            "stavelser": stavelser,
            "ord": [w["ord"] for w in familie],
        }]

    # par or bred
    cluster_size = _CLUSTER_SIZE[modus]
    familie = hent_rimfamilie(
        suffiks,
        min_frekvens=min_frekvens,
        stavelser=stavelser,
        dialekt=dialekt,
        tilfeldig=True,
        db_path=db_path,
    )

    ord_liste = [w["ord"] for w in familie]
    if len(ord_liste) < cluster_size:
        return []

    klynger = []
    # Shuffle and deal out clusters
    random.shuffle(ord_liste)

    for i in range(antall):
        start = i * cluster_size
        end = start + cluster_size
        if end > len(ord_liste):
            break
        klynger.append({
            "rimsuffiks": suffiks,
            "stavelser": stavelser,
            "ord": ord_liste[start:end],
        })

    return klynger


def _klynger_tilfeldig(
    modus: str,
    antall: int,
    stavelser: Optional[int],
    min_frekvens: float,
    dialekt: str,
    db_path: Optional[Path],
) -> list[dict]:
    """Generate clusters from random rhyme families."""
    min_family_size = _MIN_FAMILY[modus]

    suffikser = hent_kvalifiserte_suffikser(
        min_ord=min_family_size,
        stavelser=stavelser,
        min_frekvens=min_frekvens,
        dialekt=dialekt,
        db_path=db_path,
    )

    if not suffikser:
        return []

    if modus == "dyp":
        # Pick one suffix with many words (prefer large families)
        # Sample from top 20% by selecting a random large family
        valgt = random.choice(suffikser)
        familie = hent_rimfamilie(
            valgt,
            min_frekvens=min_frekvens,
            stavelser=stavelser,
            dialekt=dialekt,
            tilfeldig=False,
            db_path=db_path,
        )
        return [{
            "rimsuffiks": valgt,
            "stavelser": stavelser,
            "ord": [w["ord"] for w in familie],
        }]

    # par or bred
    cluster_size = _CLUSTER_SIZE[modus]
    valgte = random.sample(suffikser, min(antall, len(suffikser)))

    klynger = []
    for suffiks in valgte:
        familie = hent_rimfamilie(
            suffiks,
            min_frekvens=min_frekvens,
            stavelser=stavelser,
            dialekt=dialekt,
            tilfeldig=True,
            maks=cluster_size,
            db_path=db_path,
        )
        ord_liste = [w["ord"] for w in familie]
        if len(ord_liste) >= cluster_size:
            klynger.append({
                "rimsuffiks": suffiks,
                "stavelser": stavelser,
                "ord": ord_liste[:cluster_size],
            })

    return klynger
