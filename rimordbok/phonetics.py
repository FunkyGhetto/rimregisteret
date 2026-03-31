from __future__ import annotations

"""Phonetics lookup with G2P fallback.

First looks up in the SQLite database (NB Uttale lexicon data).
Falls back to rule-based G2P for unknown words.
Supports dialect-specific lookups via the `dialekt` parameter.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from rimordbok.db import hent_fonetikk, hent_fonetikk_dialekt
from rimordbok.g2p import transkriber_med_stavelser

# Cached version for default db_path (most common case)
@lru_cache(maxsize=4096)
def _slaa_opp_cached(ord: str, dialekt: str) -> dict:
    return _slaa_opp_impl(ord, None, dialekt)


def slaa_opp(
    ord: str, db_path: Optional[Path] = None, dialekt: str = "øst",
) -> dict:
    """Look up phonetic information for a word."""
    if db_path is None:
        return _slaa_opp_cached(ord, dialekt)
    return _slaa_opp_impl(ord, db_path, dialekt)


def _slaa_opp_impl(
    ord: str, db_path: Optional[Path], dialekt: str,
) -> dict:
    if dialekt != "øst":
        return _slaa_opp_dialekt(ord, dialekt, db_path)

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
