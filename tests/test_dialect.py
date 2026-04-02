"""Tests for dialect-based rhyming.

Verifies that the dialect system correctly handles phonetic differences
across Norwegian dialect regions (øst, nord, midt, vest, sørvest).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from rimordbok.phonetics import slaa_opp
from rimordbok.rhyme import finn_perfekte_rim, finn_rim_alle_dialekter
from rimordbok.db import GYLDIGE_DIALEKTER

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"
SEM_DB = Path(__file__).resolve().parent.parent / "data/db/semantics.db"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="database not built yet",
)

client = TestClient(app)


# ===================================================================
# 1. Rimsuffikser varierer mellom dialekter
# ===================================================================


class TestDialektSuffikser:
    """Verify that rhyme suffixes differ across dialects for retroflex words."""

    RETROFLEX_ORD = [
        # (ord, øst-suffiks, vest-suffiks)
        ("barn", "ɑːɳ", "ɑːrn"),
        ("fort", "ʊʈ", "ʊrt"),
        ("ferdig", "æ.ɖɪ", "ær.dɪ"),
    ]

    @pytest.mark.parametrize("ord,øst_suffiks,vest_suffiks", RETROFLEX_ORD)
    def test_suffiks_øst_vs_vest(self, ord, øst_suffiks, vest_suffiks):
        info_øst = slaa_opp(ord, dialekt="øst")
        info_vest = slaa_opp(ord, dialekt="vest")
        assert info_øst["rimsuffiks"] == øst_suffiks
        assert info_vest["rimsuffiks"] == vest_suffiks
        assert info_øst["rimsuffiks"] != info_vest["rimsuffiks"]

    def test_sol_same_across_dialects(self):
        """Words without retroflexes should have the same suffix everywhere."""
        for d in GYLDIGE_DIALEKTER:
            info = slaa_opp("sol", dialekt=d)
            assert info["rimsuffiks"] == "uːl", f"sol suffix in {d}: {info['rimsuffiks']}"

    def test_skjorte_øst_vs_vest(self):
        """skjorte: retroflexed ʈ in øst, r+t cluster in vest (across syllable)."""
        øst = slaa_opp("skjorte", dialekt="øst")
        vest = slaa_opp("skjorte", dialekt="vest")
        assert "ʈ" in øst["rimsuffiks"]
        # vest has r.t across syllable boundary: ʊr.tɑ
        assert "r" in vest["rimsuffiks"] and "t" in vest["rimsuffiks"]
        assert øst["rimsuffiks"] != vest["rimsuffiks"]


# ===================================================================
# 2. Rimpar som fungerer i én dialekt men ikke en annen
# ===================================================================


class TestDialektRimpar:
    """Test rhyme pairs that work in one dialect but not another."""

    def test_skjorte_borte_rimer_i_øst(self):
        """skjorte/borte: both have suffix ʊ.ʈə in østnorsk → perfect rhyme."""
        rim = finn_perfekte_rim("skjorte", dialekt="øst", maks=200)
        words = {r["ord"] for r in rim}
        assert "borte" in words

    def test_skjorte_borte_rimer_ikke_i_vest(self):
        """skjorte/borte: different vowels in vest (ʊr.tɑ vs ʊr.tə) → NOT a rhyme."""
        rim = finn_perfekte_rim("skjorte", dialekt="vest", maks=200)
        words = {r["ord"] for r in rim}
        assert "borte" not in words

    def test_hjerne_lanterne_rimer_i_øst(self):
        """hjerne/lanterne: both have suffix æː.ɳə in øst → perfect rhyme."""
        rim = finn_perfekte_rim("hjerne", dialekt="øst", maks=200)
        words = {r["ord"] for r in rim}
        assert "lanterne" in words

    def test_hjerne_lanterne_rimer_ikke_i_vest(self):
        """hjerne/lanterne: different vowels in vest (æːr.nə vs æːr.nɑ) → NOT a rhyme."""
        rim = finn_perfekte_rim("hjerne", dialekt="vest", maks=200)
        words = {r["ord"] for r in rim}
        assert "lanterne" not in words


# ===================================================================
# 3. Standard østnorsk er default
# ===================================================================


class TestDefaultDialekt:
    """Verify that default behavior is østnorsk (backward compatible)."""

    def test_default_is_øst(self):
        """Calling without dialekt param should use østnorsk."""
        result_default = finn_perfekte_rim("sol")
        result_øst = finn_perfekte_rim("sol", dialekt="øst")
        default_words = {r["ord"] for r in result_default}
        øst_words = {r["ord"] for r in result_øst}
        assert default_words == øst_words

    def test_api_default_dialekt(self):
        """API without ?dialekt should return østnorsk results."""
        r = client.get("/api/v1/rim/sol")
        assert r.status_code == 200
        data = r.json()
        assert data.get("dialekt", "øst") == "øst"

    def test_stol_in_sol_default(self):
        """Classic test: stol rhymes with sol (default = øst)."""
        rim = finn_perfekte_rim("sol")
        words = {r["ord"] for r in rim}
        assert "stol" in words


# ===================================================================
# 4. finn_rim_alle_dialekter
# ===================================================================


class TestRimAllDialekter:
    """Test the cross-dialect rhyme lookup."""

    def test_barn_has_all_dialects(self):
        """barn should have suffix entries for all 5 dialects."""
        result = finn_rim_alle_dialekter("barn", maks=50)
        assert set(result["dialektsuffikser"].keys()) == GYLDIGE_DIALEKTER

    def test_barn_øst_vs_vest_suffix_differs(self):
        """barn: øst=ɑːɳ (retroflex) vs vest=ɑːrn (cluster)."""
        result = finn_rim_alle_dialekter("barn")
        assert result["dialektsuffikser"]["øst"] != result["dialektsuffikser"]["vest"]

    def test_sol_same_in_all(self):
        """sol: same suffix uːl in all dialects."""
        result = finn_rim_alle_dialekter("sol")
        suffixes = set(result["dialektsuffikser"].values())
        assert len(suffixes) == 1
        assert "uːl" in suffixes

    def test_rimpar_have_dialekter_field(self):
        """Each rhyme pair should list which dialects it works in."""
        result = finn_rim_alle_dialekter("barn", maks=5)
        for rp in result["rimpar"]:
            assert "ord" in rp
            assert "dialekter" in rp
            assert len(rp["dialekter"]) > 0


# ===================================================================
# 5. API dialekt-parameter
# ===================================================================


class TestAPIDialekt:
    def test_rim_with_dialekt_param(self):
        r = client.get("/api/v1/rim/barn?dialekt=vest")
        assert r.status_code == 200
        data = r.json()
        assert data["dialekt"] == "vest"
        assert data["antall"] > 0

    def test_rim_dialekter_endpoint(self):
        r = client.get("/api/v1/rim/barn/dialekter")
        assert r.status_code == 200
        data = r.json()
        assert "dialektsuffikser" in data
        assert "rimpar" in data
        assert "soketid_ms" in data

    def test_invalid_dialekt_rejected(self):
        r = client.get("/api/v1/rim/sol?dialekt=bergen")
        assert r.status_code == 400
        assert "Ugyldig dialekt" in r.json()["feil"]

    def test_halvrim_with_dialekt(self):
        r = client.get("/api/v1/halvrim/dag?dialekt=vest")
        assert r.status_code == 200
        assert r.json()["dialekt"] == "vest"

    def test_info_with_dialekt(self):
        r = client.get("/api/v1/info/barn?dialekt=vest")
        assert r.status_code == 200
        data = r.json()
        assert data["dialekt"] == "vest"


# ===================================================================
# 6. Dialektgruppering: øst/nord/midt vs vest/sørvest
# ===================================================================


class TestDialektGruppering:
    """Verify that øst/nord/midt share retroflexes, vest/sørvest don't."""

    def test_øst_nord_midt_same_for_barn(self):
        """øst, nord, and midt all use retroflex ɳ for 'barn'."""
        suffixes = {}
        for d in ["øst", "nord", "midt"]:
            info = slaa_opp("barn", dialekt=d)
            suffixes[d] = info["rimsuffiks"]
        assert suffixes["øst"] == suffixes["nord"] == suffixes["midt"]
        assert "ɳ" in suffixes["øst"]

    def test_vest_sørvest_same_for_barn(self):
        """vest and sørvest both use rn cluster for 'barn'."""
        vest = slaa_opp("barn", dialekt="vest")
        sørvest = slaa_opp("barn", dialekt="sørvest")
        assert vest["rimsuffiks"] == sørvest["rimsuffiks"]
        assert "rn" in vest["rimsuffiks"]

    def test_sørvest_different_unstressed_vowels(self):
        """sørvest uses ɑ where vest/øst use ə in unstressed syllables."""
        # skjorte: vest=ʊr.tɑ, sørvest=ʊr.tɑ (both ɑ in sørvest)
        # vs øst=ʊ.ʈə (ə in unstressed)
        sv = slaa_opp("skjorte", dialekt="sørvest")
        øst = slaa_opp("skjorte", dialekt="øst")
        assert sv["rimsuffiks"] != øst["rimsuffiks"]


# ===================================================================
# 7. Performance
# ===================================================================


class TestDialektYtelse:
    def test_dialect_lookup_under_200ms(self):
        """Dialect rhyme lookup should be fast enough for interactive use."""
        import time
        # Warm up
        finn_perfekte_rim("sol", dialekt="vest")
        # Measure
        start = time.perf_counter()
        finn_perfekte_rim("sol", dialekt="vest")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 200, f"Dialect lookup took {elapsed_ms:.1f}ms"

    def test_all_dialects_under_500ms(self):
        """Cross-dialect lookup should complete within 500ms."""
        import time
        finn_rim_alle_dialekter("sol", maks=10)
        start = time.perf_counter()
        finn_rim_alle_dialekter("sol", maks=10)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"All-dialects lookup took {elapsed_ms:.1f}ms"
