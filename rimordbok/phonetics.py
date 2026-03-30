from __future__ import annotations

"""Phonetics lookup with G2P fallback.

First looks up in the SQLite database (NB Uttale lexicon data).
Falls back to rule-based G2P for unknown words.
Supports dialect-specific lookups via the `dialekt` parameter.
"""

from pathlib import Path
from typing import Optional

from rimordbok.db import hent_fonetikk, hent_fonetikk_dialekt
from rimordbok.g2p import transkriber_med_stavelser


def slaa_opp(
    ord: str, db_path: Optional[Path] = None, dialekt: str = "øst",
) -> dict:
    """Look up phonetic information for a word.

    Returns a dict with keys:
        fonemer, stress, tonelag, stavelser, ipa_ren, rimsuffiks, g2p (bool)

    For non-øst dialects, checks ord_dialekter first, then falls back to øst.
    """
    if dialekt != "øst":
        return _slaa_opp_dialekt(ord, dialekt, db_path)

    # Try lexicon first (østnorsk)
    results = hent_fonetikk(ord, db_path=db_path)
    if results:
        r = results[0]
        return {
            "fonemer": r["fonemer"],
            "ipa_ren": r["ipa_ren"],
            "tonelag": r["tonelag"],
            "stavelser": r["stavelser"],
            "rimsuffiks": r["rimsuffiks"],
            "g2p": False,
        }

    # Try lowercase
    if ord != ord.lower():
        results = hent_fonetikk(ord.lower(), db_path=db_path)
        if results:
            r = results[0]
            return {
                "fonemer": r["fonemer"],
                "ipa_ren": r["ipa_ren"],
                "tonelag": r["tonelag"],
                "stavelser": r["stavelser"],
                "rimsuffiks": r["rimsuffiks"],
                "g2p": False,
            }

    # Fallback: rule-based G2P
    return transkriber_med_stavelser(ord)


def _slaa_opp_dialekt(
    ord: str, dialekt: str, db_path: Optional[Path] = None
) -> dict:
    """Look up phonetic info for a specific dialect."""
    r = hent_fonetikk_dialekt(ord, dialekt, db_path=db_path)
    if r:
        return {
            "fonemer": r["fonemer"],
            "ipa_ren": r["ipa_ren"],
            "tonelag": r["tonelag"],
            "stavelser": r["stavelser"],
            "rimsuffiks": r["rimsuffiks"],
            "g2p": False,
        }

    # Try lowercase
    if ord != ord.lower():
        r = hent_fonetikk_dialekt(ord.lower(), dialekt, db_path=db_path)
        if r:
            return {
                "fonemer": r["fonemer"],
                "ipa_ren": r["ipa_ren"],
                "tonelag": r["tonelag"],
                "stavelser": r["stavelser"],
                "rimsuffiks": r["rimsuffiks"],
                "g2p": False,
            }

    # Fallback: rule-based G2P (dialect-agnostic)
    return transkriber_med_stavelser(ord)
