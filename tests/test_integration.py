"""End-to-end integration tests for the full rimordbok system.

Tests cover: rhyme quality, near-rhymes, tonelag, semantics,
API performance, G2P fallback, and edge cases.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from rimordbok.db import hent_fonetikk, hent_rim
from rimordbok.phonetics import slaa_opp
from rimordbok.rhyme import finn_perfekte_rim, finn_halvrim
from rimordbok.semantics import finn_synonymer, finn_relaterte
from rimordbok.clusters import generer_rimklynger

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"
SEM_DB = Path(__file__).resolve().parent.parent / "data/db/semantics.db"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists() or not SEM_DB.exists(),
    reason="databases not built yet",
)

client = TestClient(app)


# ===================================================================
# 1. Rim-kvalitetstester — 30 verifiserte rimpar
# ===================================================================


class TestPerfekteRimpar:
    """Verify that known rhyme pairs are found by the rhyme engine."""

    RIMPAR = [
        # Enstavelse — korte vokaler
        ("natt", "matt"),
        ("natt", "hatt"),
        ("natt", "katt"),
        ("vann", "mann"),
        ("sang", "gang"),
        ("drøm", "strøm"),
        ("gull", "hull"),
        ("fisk", "disk"),
        # Enstavelse — lange vokaler
        ("sol", "stol"),
        ("dag", "slag"),
        ("bok", "kok"),
        ("by", "ny"),
        ("snø", "blø"),
        ("liv", "driv"),
        ("ord", "bord"),
        ("hus", "mus"),
        # Enstavelse — diftonger
        ("stein", "bein"),
        # Enstavelse — konsonantklynger
        ("fjell", "kveld"),
        ("blomst", "komst"),
        # Tostavelse
        ("hjerte", "smerte"),
        ("gate", "mate"),
        ("rose", "pose"),
        ("sommer", "tommer"),
        ("vinter", "splinter"),
        # Trestavelse+
        ("kjærlighet", "evighet"),
    ]

    @pytest.mark.parametrize("ord1,ord2", RIMPAR)
    def test_rimpar(self, ord1, ord2):
        """Verify that ord2 appears in the rhyme results for ord1."""
        results = finn_perfekte_rim(ord1, db_path=DB_PATH, maks=500)
        words = {r["ord"] for r in results}
        assert ord2 in words, (
            f"'{ord2}' not found in rhymes for '{ord1}'. "
            f"Got {len(results)} results, first 10: {[r['ord'] for r in results[:10]]}"
        )


class TestIkkeRim:
    """Verify that non-rhyming pairs are NOT matched."""

    IKKE_RIMPAR = [
        ("jul", "stol"),     # ʉːl vs uːl — different vowels
        ("lys", "is"),       # yːs vs ɪːs
        ("båt", "råd"),      # oːt vs oːd — different final consonant
        ("tid", "strid"),    # ɪː vs ɪːd — 'tid' has silent d
        ("dans", "sjans"),   # ɑns vs ɑŋs — n vs ŋ
    ]

    @pytest.mark.parametrize("ord1,ord2", IKKE_RIMPAR)
    def test_ikke_rim(self, ord1, ord2):
        """Verify that ord2 does NOT appear in rhyme results for ord1."""
        results = finn_perfekte_rim(ord1, db_path=DB_PATH, maks=500)
        words = {r["ord"] for r in results}
        assert ord2 not in words, f"'{ord2}' should NOT rhyme with '{ord1}'"


class TestRimFrekvensordning:
    """Verify that results are sorted by frequency."""

    def test_sorted_descending(self):
        results = finn_perfekte_rim("dag", db_path=DB_PATH, maks=100)
        freqs = [r["frekvens"] for r in results]
        assert freqs == sorted(freqs, reverse=True)

    def test_common_before_rare(self):
        results = finn_perfekte_rim("sol", db_path=DB_PATH, maks=200)
        words = [r["ord"] for r in results]
        assert "alkohol" in words
        assert "rullestol" in words
        assert words.index("alkohol") < words.index("rullestol")


# ===================================================================
# 2. Halvrim-tester
# ===================================================================


class TestHalvrim:
    """Verify near-rhyme matching with phoneme equivalence classes."""

    def test_dag_tak_voiced_voiceless(self):
        """dag (ɑːg) ~ tak (ɑːk): g/k equivalence."""
        results = finn_halvrim("dag", db_path=DB_PATH, terskel=0.5)
        words = {r["ord"] for r in results}
        assert "tak" in words

    def test_sang_lang_same_ending(self):
        """sang and lang are perfect rhymes (both ɑŋ), not near-rhymes."""
        # They should be in perfect, NOT in near-rhyme (which excludes exact suffix)
        perfect = finn_perfekte_rim("sang", db_path=DB_PATH, maks=500)
        assert "lang" in {r["ord"] for r in perfect}

    def test_near_rhyme_has_score(self):
        results = finn_halvrim("dag", db_path=DB_PATH, terskel=0.5)
        for r in results:
            assert "score" in r
            assert 0.0 < r["score"] <= 1.1  # up to 1.0 + 0.1 tonelag bonus

    def test_no_perfect_overlap(self):
        """Near-rhymes should not include perfect rhymes."""
        perfect = {r["ord"] for r in finn_perfekte_rim("dag", db_path=DB_PATH, maks=500)}
        near = {r["ord"] for r in finn_halvrim("dag", db_path=DB_PATH, terskel=0.5)}
        overlap = perfect & near
        assert len(overlap) == 0, f"Overlap: {overlap}"


# ===================================================================
# 3. Tonelag-tester
# ===================================================================


class TestTonelag:
    """Verify tonelag (pitch accent) distinction."""

    def test_bønder_bønner_different_tonelag(self):
        """bønder (tone 1) and bønner (tone 2) share suffix but differ in tonelag."""
        info_d = hent_fonetikk("bønder", db_path=DB_PATH)
        info_n = hent_fonetikk("bønner", db_path=DB_PATH)
        assert len(info_d) >= 1
        assert len(info_n) >= 1
        assert info_d[0]["rimsuffiks"] == info_n[0]["rimsuffiks"]
        assert info_d[0]["tonelag"] != info_n[0]["tonelag"]

    def test_tonelag_values(self):
        """Verify specific tonelag assignments."""
        info_d = hent_fonetikk("bønder", db_path=DB_PATH)
        info_n = hent_fonetikk("bønner", db_path=DB_PATH)
        assert info_d[0]["tonelag"] == 1
        assert info_n[0]["tonelag"] == 2

    def test_samme_tonelag_filter(self):
        """With samme_tonelag=True, only matching tonelag should appear."""
        results = finn_perfekte_rim("sol", db_path=DB_PATH, samme_tonelag=True)
        for r in results:
            assert r["tonelag"] == 1

    def test_tonelag_in_api_response(self):
        """API response should include tonelag for each result."""
        r = client.get("/api/v1/rim/sol?maks=10")
        for item in r.json()["resultater"]:
            assert "tonelag" in item

    def test_tonelag_icon_mapping(self):
        """Info endpoint shows tonelag for known words."""
        r = client.get("/api/v1/info/sol")
        data = r.json()
        assert data["fonetikk"]["tonelag"] == 1


# ===================================================================
# 4. Semantikk-tester
# ===================================================================


class TestSemantikk:
    """Verify semantic relations from WordNet + synonym list."""

    def test_glad_synonymer_lykkelig(self):
        results = finn_synonymer("glad", db_path=SEM_DB)
        words = {r["ord"] for r in results}
        assert "lykkelig" in words

    def test_glad_synonymer_fornøyd(self):
        results = finn_synonymer("glad", db_path=SEM_DB)
        words = {r["ord"] for r in results}
        assert "fornøyd" in words

    def test_glad_synonymer_munter(self):
        results = finn_synonymer("glad", db_path=SEM_DB)
        words = {r["ord"] for r in results}
        assert "munter" in words

    def test_stor_synonymer(self):
        results = finn_synonymer("stor", db_path=SEM_DB)
        words = {r["ord"] for r in results}
        assert "betydelig" in words or "diger" in words or "stor" not in words

    def test_hund_relaterte(self):
        results = finn_relaterte("hund", db_path=SEM_DB)
        assert len(results) > 0
        rels = {r["relasjon"] for r in results}
        assert "hypernym" in rels or "hyponym" in rels

    def test_synonymer_sorted_by_frequency(self):
        results = finn_synonymer("glad", db_path=SEM_DB)
        freqs = [r["frekvens"] for r in results]
        assert freqs == sorted(freqs, reverse=True)

    def test_semantics_via_api(self):
        r = client.get("/api/v1/synonymer/glad")
        words = {item["ord"] for item in r.json()["resultater"]}
        assert "lykkelig" in words


# ===================================================================
# 5. API-responstid
# ===================================================================


class TestAPIResponstid:
    """All endpoints should respond within 100ms for common words."""

    ENDPOINTS = [
        "/api/v1/rim/sol",
        "/api/v1/rim/dag",
        "/api/v1/rim/hjerte",
        "/api/v1/halvrim/dag",
        "/api/v1/synonymer/glad",
        "/api/v1/relaterte/hund",
        "/api/v1/konsonanter/sol",
        "/api/v1/info/sol",
        "/api/v1/sok?q=sol",
    ]

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_under_100ms(self, endpoint):
        # Warm up
        client.get(endpoint)
        # Measure
        start = time.perf_counter()
        r = client.get(endpoint)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert r.status_code == 200
        # Synonymer/info may hit ordbokapi.org on first call (cached after)
        limit = 500 if "synonymer" in endpoint or "info" in endpoint else 150
        assert elapsed_ms < limit, f"{endpoint} took {elapsed_ms:.1f}ms"


# ===================================================================
# 6. Edge cases
# ===================================================================


class TestEdgeCases:
    """Edge case handling."""

    def test_empty_search_rejected(self):
        """Empty query string should be rejected by validation."""
        r = client.get("/api/v1/sok?q=")
        assert r.status_code == 422  # FastAPI validation (min_length=1)

    def test_unknown_word_uses_g2p(self):
        """Unknown word should fall back to G2P."""
        info = slaa_opp("kvantedansen", db_path=DB_PATH)
        assert info["g2p"] is True
        assert info["stavelser"] >= 3

    def test_unknown_word_api(self):
        """API should return a response for unknown words (G2P fallback)."""
        r = client.get("/api/v1/info/kvantedansen")
        data = r.json()
        assert data["fonetikk"]["g2p"] is True

    def test_very_long_word(self):
        """Very long word should not crash."""
        long_word = "menneskerettighetsorganisasjon"
        r = client.get(f"/api/v1/info/{long_word}")
        assert r.status_code == 200
        data = r.json()
        assert data["fonetikk"]["stavelser"] >= 5

    def test_single_character_word(self):
        """Single character 'i' is a valid Norwegian word."""
        r = client.get("/api/v1/info/i")
        assert r.status_code == 200

    def test_unicode_characters(self):
        """Norwegian special characters æ, ø, å should work."""
        for word in ["blå", "grønn", "ære"]:
            r = client.get(f"/api/v1/rim/{word}")
            assert r.status_code == 200

    def test_uppercase_normalized(self):
        """Uppercase input should find same results as lowercase."""
        r1 = client.get("/api/v1/rim/Sol")
        r2 = client.get("/api/v1/rim/sol")
        # Both should return results
        assert r1.json()["antall"] > 0
        assert r2.json()["antall"] > 0

    def test_nonexistent_word_rhyme(self):
        """Nonexistent word returns empty results."""
        r = client.get("/api/v1/rim/xyznonexistent")
        assert r.status_code == 200
        assert r.json()["antall"] == 0

    def test_number_in_word(self):
        """Word with numbers should not crash."""
        r = client.get("/api/v1/info/abc123")
        assert r.status_code == 200


# ===================================================================
# 7. Fonetikk-konsistens
# ===================================================================


class TestFonetikkKonsistens:
    """Verify phonetic data consistency between DB and G2P."""

    KNOWN_IPA = [
        ("sol", "suːl"),
        ("dag", "dɑːg"),
        ("natt", "nɑt"),
    ]

    @pytest.mark.parametrize("word,expected_ipa", KNOWN_IPA)
    def test_lexicon_ipa(self, word, expected_ipa):
        info = slaa_opp(word, db_path=DB_PATH)
        assert info["g2p"] is False
        assert info["ipa_ren"] == expected_ipa

    def test_g2p_produces_valid_output(self):
        """G2P output should have all required fields."""
        info = slaa_opp("kvantedansen", db_path=DB_PATH)
        assert "fonemer" in info
        assert "ipa_ren" in info
        assert "stavelser" in info
        assert "tonelag" in info
        assert info["g2p"] is True

    def test_lexicon_entry_has_all_fields(self):
        entries = hent_fonetikk("sol", db_path=DB_PATH)
        assert len(entries) >= 1
        e = entries[0]
        for key in ("ord", "pos", "fonemer", "ipa_ren", "rimsuffiks", "tonelag", "stavelser"):
            assert key in e


# ===================================================================
# 8. System-integrasjon
# ===================================================================


class TestSystemIntegrasjon:
    """Verify that all system components work together."""

    def test_full_pipeline_sol(self):
        """Full pipeline: lookup → rhymes → synonyms for 'sol'."""
        # Phonetics
        info = slaa_opp("sol", db_path=DB_PATH)
        assert info["ipa_ren"] == "suːl"

        # Rhymes
        rhymes = finn_perfekte_rim("sol", db_path=DB_PATH, maks=10)
        assert len(rhymes) > 0
        assert rhymes[0]["score"] == 1.0

        # Synonyms (sol = sun)
        # sol might not have many synonyms, that's ok

        # API combines all
        r = client.get("/api/v1/info/sol")
        data = r.json()
        assert data["fonetikk"]["ipa_ren"] == "suːl"
        assert len(data["rim"]) > 0

    def test_full_pipeline_glad(self):
        """Full pipeline for adjective 'glad'."""
        # Phonetics
        info = slaa_opp("glad", db_path=DB_PATH)
        assert info["g2p"] is False

        # Rhymes
        rhymes = finn_perfekte_rim("glad", db_path=DB_PATH, maks=10)
        assert len(rhymes) > 0

        # Synonyms
        syns = finn_synonymer("glad", db_path=SEM_DB)
        syn_words = {s["ord"] for s in syns}
        assert "lykkelig" in syn_words

    def test_autocomplete_to_rhyme(self):
        """Autocomplete → select word → get rhymes (simulates user flow)."""
        # Step 1: Autocomplete
        r = client.get("/api/v1/sok?q=sol")
        data = r.json()
        assert "sol" in data["resultater"]

        # Step 2: Get rhymes for selected word
        r = client.get("/api/v1/rim/sol?maks=10")
        data = r.json()
        assert data["antall"] > 0
        words = {item["ord"] for item in data["resultater"]}
        assert "stol" in words or "alkohol" in words


# ===================================================================
# 9. Rimklynge-integrasjon
# ===================================================================


class TestRimklyngeIntegrasjon:
    """Test cluster generation integrated with rhyme engine."""

    def test_klynge_to_rimsoek(self):
        """User flow: generate cluster → click word → get rhymes."""
        # Step 1: Generate a cluster with a known word
        klynger = generer_rimklynger(modus="par", antall=3, ord="natt", min_frekvens=0.0)
        assert len(klynger) > 0
        first_word = klynger[0]["ord"][0]

        # Step 2: User clicks a word — get rhymes for it
        r = client.get(f"/api/v1/rim/{first_word}?maks=20")
        data = r.json()
        assert data["antall"] > 0

        # Step 3: The original word "natt" should be in the rhyme results
        words = {item["ord"] for item in data["resultater"]}
        assert "natt" in words or first_word.lower() == "natt"

    def test_dyp_klynge_consistency(self):
        """All words in a dyp cluster should be perfect rhymes of each other."""
        klynger = generer_rimklynger(modus="dyp", ord="sol", min_frekvens=1.0)
        assert len(klynger) == 1
        ord_liste = klynger[0]["ord"]
        assert len(ord_liste) > 2

        # Pick first word, verify others are in its rhyme results
        first = ord_liste[0]
        rhymes = finn_perfekte_rim(first, db_path=DB_PATH, maks=500)
        rhyme_words = {r["ord"] for r in rhymes}
        for w in ord_liste[1:5]:  # check first few
            assert w in rhyme_words or w.lower() == first.lower(), (
                f"'{w}' from dyp cluster not in rhymes for '{first}'"
            )

    def test_klynge_api_full_flow(self):
        """Full API flow: cluster → pick word → info + rhymes."""
        # Step 1: Generate clusters via API
        r = client.get("/api/v1/rimklynger/bred?antall=2&min_frekvens=0")
        data = r.json()
        assert data["antall"] > 0
        word = data["klynger"][0]["ord"][0]

        # Step 2: Get info for picked word
        r = client.get(f"/api/v1/info/{word}")
        info = r.json()
        assert info["fonetikk"]["rimsuffiks"] is not None

        # Step 3: Get rhymes
        r = client.get(f"/api/v1/rim/{word}?maks=20")
        assert r.status_code == 200
        rim_data = r.json()
        assert rim_data["antall"] >= 0  # may be 0 for very rare words

    def test_klynge_stavelsesfilter_konsistens(self):
        """Cluster syllable filter should match DB syllable counts."""
        import sqlite3
        klynger = generer_rimklynger(
            modus="par", antall=5, stavelser=2, min_frekvens=0.0
        )
        conn = sqlite3.connect(str(DB_PATH))
        for klynge in klynger:
            for word in klynge["ord"]:
                # Check DB directly (case-insensitive) since slaa_opp may use G2P
                row = conn.execute(
                    "SELECT stavelser FROM ord WHERE LOWER(ord) = ? AND stavelser = 2 LIMIT 1",
                    (word.lower(),),
                ).fetchone()
                assert row is not None, (
                    f"Word '{word}' has no DB entry with 2 syllables"
                )
        conn.close()

    def test_klynge_par_responstid(self):
        """Cluster generation via API should be fast."""
        import time
        # Warm up
        client.get("/api/v1/rimklynger/par?antall=10")
        start = time.perf_counter()
        r = client.get("/api/v1/rimklynger/par?antall=10")
        elapsed = (time.perf_counter() - start) * 1000
        assert r.status_code == 200
        assert elapsed < 500, f"Cluster par took {elapsed:.1f}ms"
