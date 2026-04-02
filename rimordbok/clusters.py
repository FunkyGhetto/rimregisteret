from __future__ import annotations

"""Rimklynge-generering for freestyle-trening.

Bruker rim-motoren (finn_perfekte_rim / finn_halvrim) slik at alle
filtre (morfologisk, stavelsevekt, egennavn) gjelder automatisk.

Fire moduser:
- PAR:  Rimpar (2 ord per klynge) fra ulike tilfeldige rimfamilier.
- BRED: Brede klynger (4 ord per klynge) fra tilfeldige rimfamilier.
- DYP:  Mange ord fra én rimfamilie, sortert etter frekvens.
- STI:  Rimstier — gli mellom rimfamilier via vokalskift.

Klyngene kan inneholde helrim, halvrim eller begge, styrt av `rimtype`.
"""

import random
import sqlite3
from pathlib import Path
from typing import Optional

from rimordbok.rhyme import finn_perfekte_rim, finn_halvrim, finn_rimsti

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"

_CLUSTER_SIZE = {"par": 2, "bred": 4}


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _velg_tilfeldig_ord(
    stavelser: Optional[int] = None,
    min_frekvens: float = 5.0,
    db_path: Optional[Path] = None,
) -> Optional[str]:
    """Velg et tilfeldig, vanlig ord fra databasen.

    Filtrerer på frekvens og ordlengde for å unngå obskure ord.
    """
    conn = _connect(db_path)
    where = [
        "frekvens >= ?",
        "length(ord) BETWEEN 3 AND 10",
        "pos NOT LIKE 'PM%'",       # ikke egennavn
        "ord NOT LIKE '%-%'",        # ikke bindestrek-ord
    ]
    params: list = [min_frekvens]

    if stavelser is not None:
        where.append("stavelser = ?")
        params.append(stavelser)

    # Hent et tilfeldig ord — ORDER BY RANDOM() med LIMIT
    query = (
        f"SELECT LOWER(ord) as ord FROM ord "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY LOWER(ord) "
        f"ORDER BY RANDOM() LIMIT 1"
    )
    row = conn.execute(query, params).fetchone()
    return row["ord"] if row else None


def _hent_rim_for_ord(
    ord: str,
    maks: int,
    rimtype: str = "helrim",
    terskel: float = 0.5,
    dialekt: str = "øst",
    db_path: Optional[Path] = None,
) -> tuple[list[str], str | None]:
    """Hent rim for et ord via rim-motoren.

    Args:
        rimtype: "helrim", "halvrim", eller "begge"

    Returns:
        (liste med rimord, rimsuffiks) — rimord sortert etter relevans.
    """
    resultater = []
    rimsuffiks = None

    if rimtype in ("helrim", "begge"):
        helrim = finn_perfekte_rim(
            ord, maks=maks, dialekt=dialekt, grupper=False,
            db_path=db_path, ekskluder_propn=True,
        )
        rimsuffiks = rimsuffiks or helrim.get("rimsuffiks")
        for r in helrim.get("resultater", []):
            if r["ord"] not in resultater:
                resultater.append(r["ord"])

    if rimtype in ("halvrim", "begge"):
        halvrim = finn_halvrim(
            ord, maks=maks, terskel=terskel, dialekt=dialekt,
            db_path=db_path, ekskluder_propn=True,
        )
        rimsuffiks = rimsuffiks or halvrim.get("rimsuffiks")
        for r in halvrim.get("resultater", []):
            if r["ord"] not in resultater:
                resultater.append(r["ord"])

    return resultater, rimsuffiks


def generer_rimklynger(
    modus: str = "par",
    antall: int = 10,
    stavelser: Optional[int] = None,
    min_frekvens: float = 1.0,
    dialekt: str = "øst",
    ord: Optional[str] = None,
    rimtype: str = "begge",
    terskel: float = 0.5,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Generer rimklynger for freestyle-trening.

    Bruker rim-motoren (finn_perfekte_rim / finn_halvrim) for å
    finne rim, slik at alle filtre gjelder automatisk.

    Args:
        modus: "par" (2 ord), "bred" (4 ord), eller "dyp" (mange ord).
        antall: Antall klynger å generere (ignoreres for "dyp").
        stavelser: Filtrer på antall stavelser (None = alle).
        min_frekvens: Minimum ordfrekvens for seed-ord.
        dialekt: Dialektregion (default "øst").
        ord: Valgfritt startord — bruk dette i stedet for tilfeldig.
        rimtype: "helrim", "halvrim" eller "begge" (default "helrim").
        terskel: Minimum likhetsscore for halvrim (default 0.5).
        db_path: Database-sti (None = default).

    Returns:
        Liste med klynge-dicts: {startord, rimtype, ord: [str, ...]}
        For "dyp": alltid én klynge med mange ord.
    """
    if modus not in ("par", "bred", "dyp", "sti"):
        raise ValueError(f"Ugyldig modus: {modus!r}. Bruk 'par', 'bred', 'dyp' eller 'sti'.")

    if modus == "dyp":
        return _klynge_dyp(
            ord=ord, stavelser=stavelser, min_frekvens=min_frekvens,
            dialekt=dialekt, rimtype=rimtype, terskel=terskel,
            db_path=db_path,
        )

    if modus == "sti":
        raise ValueError("Bruk generer_rimstier() for sti-modus.")

    return _klynger_par_bred(
        modus=modus, antall=antall, ord=ord,
        stavelser=stavelser, min_frekvens=min_frekvens,
        dialekt=dialekt, rimtype=rimtype, terskel=terskel,
        db_path=db_path,
    )


def _klynge_dyp(
    ord: Optional[str],
    stavelser: Optional[int],
    min_frekvens: float,
    dialekt: str,
    rimtype: str,
    terskel: float,
    db_path: Optional[Path],
) -> list[dict]:
    """Dyp modus: mange rim fra ett ord."""
    startord = ord or _velg_tilfeldig_ord(
        stavelser=stavelser, min_frekvens=max(min_frekvens, 5.0),
        db_path=db_path,
    )
    if not startord:
        return []

    rim, rimsuffiks = _hent_rim_for_ord(
        startord, maks=200, rimtype=rimtype,
        terskel=terskel, dialekt=dialekt, db_path=db_path,
    )
    if not rim:
        return []

    return [{
        "startord": startord,
        "rimsuffiks": rimsuffiks,
        "rimtype": rimtype,
        "ord": rim,
    }]


def _klynger_par_bred(
    modus: str,
    antall: int,
    ord: Optional[str],
    stavelser: Optional[int],
    min_frekvens: float,
    dialekt: str,
    rimtype: str,
    terskel: float,
    db_path: Optional[Path],
) -> list[dict]:
    """Par/bred modus: flere klynger med 2 eller 4 ord."""
    cluster_size = _CLUSTER_SIZE[modus]
    klynger = []

    if ord:
        # Brukeren ga et startord — bygg klynger fra det ordets rim
        rim, rimsuffiks = _hent_rim_for_ord(
            ord, maks=cluster_size * antall,
            rimtype=rimtype, terskel=terskel,
            dialekt=dialekt, db_path=db_path,
        )
        random.shuffle(rim)
        for i in range(0, len(rim) - cluster_size + 1, cluster_size):
            klynger.append({
                "startord": ord,
                "rimsuffiks": rimsuffiks,
                "rimtype": rimtype,
                "ord": rim[i:i + cluster_size],
            })
            if len(klynger) >= antall:
                break
    else:
        # Velg tilfeldige startord, ett per klynge
        forsok = 0
        while len(klynger) < antall and forsok < antall * 3:
            forsok += 1
            startord = _velg_tilfeldig_ord(
                stavelser=stavelser,
                min_frekvens=max(min_frekvens, 5.0),
                db_path=db_path,
            )
            if not startord:
                continue

            rim, rimsuffiks = _hent_rim_for_ord(
                startord, maks=cluster_size * 2,
                rimtype=rimtype, terskel=terskel,
                dialekt=dialekt, db_path=db_path,
            )
            if len(rim) < cluster_size:
                continue

            # Velg tilfeldige ord fra rimene
            valgte = random.sample(rim, cluster_size)
            klynger.append({
                "startord": startord,
                "rimsuffiks": rimsuffiks,
                "rimtype": rimtype,
                "ord": valgte,
            })

    return klynger


def generer_rimstier(
    antall_stier: int = 3,
    maks_steg: int = 8,
    min_familiestr: int = 3,
    min_frekvens: float = 1.0,
    dialekt: str = "øst",
    ord: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Generer rimstier for freestyle-trening.

    Hver rimsti er en vandring gjennom vokalrommet med fast
    konsonantskjelett — hvert steg er en rimfamilie med gradvis
    vokalforskyvning.

    Args:
        antall_stier: Antall rimstier å generere.
        maks_steg: Maks antall steg (rimfamilier) per sti.
        min_familiestr: Minimum ord per rimfamilie.
        min_frekvens: Minimum ordfrekvens for seed-ord.
        dialekt: Dialektregion (default "øst").
        ord: Valgfritt startord. Hvis None, velges tilfeldige ord.
        db_path: Database-sti (None = default).

    Returns:
        Liste med sti-dicts, hver med: ord, rimsuffiks,
        konsonantskjelett, steg[], antall_steg.
    """
    stier = []

    if ord:
        # Brukeren ga et startord — generer én sti fra det
        sti = finn_rimsti(
            ord, maks_steg=maks_steg, min_familiestr=min_familiestr,
            min_frekvens=min_frekvens, dialekt=dialekt, db_path=db_path,
        )
        if sti.get("steg"):
            stier.append(sti)
    else:
        # Generer tilfeldige rimstier
        forsok = 0
        while len(stier) < antall_stier and forsok < antall_stier * 5:
            forsok += 1
            startord = _velg_tilfeldig_ord(
                min_frekvens=max(min_frekvens, 5.0),
                db_path=db_path,
            )
            if not startord:
                continue

            sti = finn_rimsti(
                startord, maks_steg=maks_steg,
                min_familiestr=min_familiestr,
                min_frekvens=min_frekvens, dialekt=dialekt,
                db_path=db_path,
            )
            if sti.get("steg") and len(sti["steg"]) >= 3:
                stier.append(sti)

    return stier
