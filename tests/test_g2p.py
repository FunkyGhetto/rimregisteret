"""Tests for rule-based G2P and phonetics lookup with fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from rimordbok.g2p import transkriber, transkriber_ipa, transkriber_med_stavelser

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"


class TestTranskriber:
    """Test basic grapheme-to-phoneme conversion."""

    def test_hus(self):
        assert transkriber_ipa("hus") == "hʉːs"

    def test_sol(self):
        assert transkriber_ipa("sol") == "suːl"

    def test_dag(self):
        assert transkriber_ipa("dag") == "dɑːg"

    def test_natt(self):
        assert transkriber_ipa("natt") == "nɑt"

    def test_sang(self):
        assert transkriber_ipa("sang") == "sɑŋ"

    def test_ring(self):
        assert transkriber_ipa("ring") == "rɪŋ"

    def test_land(self):
        """Silent d in -nd."""
        assert transkriber_ipa("land") == "lɑn"

    def test_barn(self):
        """Long vowel before rn, retroflex."""
        assert transkriber_ipa("barn") == "bɑːɳ"

    def test_kjøtt(self):
        """kj → ç, double t → single."""
        assert transkriber_ipa("kjøtt") == "çœt"

    def test_skje(self):
        """skj → ʃ."""
        assert transkriber_ipa("skje") == "ʃeː"

    def test_case_insensitive(self):
        assert transkriber_ipa("Oslo") == transkriber_ipa("oslo")


class TestG2PTargetWords:
    """Test the 3 specified G2P target words."""

    def test_datamaskin_structure(self):
        r = transkriber_med_stavelser("datamaskin")
        assert r["g2p"] is True
        assert r["stavelser"] == 4
        assert r["tonelag"] is None  # G2P cannot predict tonelag
        # Should end with ʃiːn (sk before i → ʃ)
        assert r["ipa_ren"].endswith("ʃiːn")

    def test_programmering_structure(self):
        r = transkriber_med_stavelser("programmering")
        assert r["g2p"] is True
        assert r["stavelser"] == 4
        # Should end with rɪŋ
        assert r["ipa_ren"].endswith("rɪŋ")

    def test_sjokolade_structure(self):
        r = transkriber_med_stavelser("sjokolade")
        assert r["g2p"] is True
        assert r["stavelser"] == 4
        # Should start with ʃ (sj → ʃ)
        assert r["ipa_ren"].startswith("ʃ")
        # Should end with schwa
        assert r["ipa_ren"].endswith("də")


class TestRetroflexRules:
    """Verify East Norwegian retroflex assimilation."""

    def test_rt(self):
        phonemes = transkriber("kort")
        assert "ʈ" in phonemes

    def test_rd(self):
        phonemes = transkriber("gard")
        assert "ɖ" in phonemes

    def test_rn(self):
        phonemes = transkriber("barn")
        assert "ɳ" in phonemes

    def test_rl(self):
        phonemes = transkriber("karl")
        assert "ɭ" in phonemes

    def test_rs(self):
        phonemes = transkriber("norsk")
        assert "ʂ" in phonemes


class TestDiphthongs:
    def test_ei(self):
        assert "æ͡ɪ" in transkriber("stein")

    def test_øy(self):
        assert "œ͡ʏ" in transkriber("øye")

    def test_au(self):
        assert "æ͡ʉ" in transkriber("sau")


class TestSyllabification:
    def test_monosyllable(self):
        r = transkriber_med_stavelser("hus")
        assert r["stavelser"] == 1

    def test_disyllable(self):
        r = transkriber_med_stavelser("gate")
        assert r["stavelser"] == 2

    def test_trisyllable(self):
        r = transkriber_med_stavelser("telefon")
        assert r["stavelser"] == 3


class TestFallbackLookup:
    """Test phonetics.slaa_opp with lexicon + G2P fallback."""

    pytestmark = pytest.mark.skipif(
        not DB_PATH.exists(), reason="rimindeks.db not built yet"
    )

    def test_known_word_from_lexicon(self):
        from rimordbok.phonetics import slaa_opp
        r = slaa_opp("sol", db_path=DB_PATH)
        assert r["g2p"] is False
        assert r["tonelag"] == 1
        assert r["ipa_ren"] == "suːl"

    def test_unknown_word_uses_g2p(self):
        from rimordbok.phonetics import slaa_opp
        r = slaa_opp("kvantedansen", db_path=DB_PATH)
        assert r["g2p"] is True
        assert r["stavelser"] >= 3

    def test_case_fallback(self):
        """Uppercase word should find lowercase lexicon entry."""
        from rimordbok.phonetics import slaa_opp
        r = slaa_opp("Sol", db_path=DB_PATH)
        # Should find "Sol" (proper noun) or "sol" (common noun) from lexicon
        assert r["g2p"] is False
