"""Tests for parse_phonetics.py — verify known words parse correctly."""

import pytest

from scripts.parse_phonetics import parse_ipa, parse_nofabet_stress, should_skip


class TestParseIPA:
    def test_sol(self):
        """sol: 'suːl — tone 1, 1 syllable, primary stress."""
        result = parse_ipa("'suːl")
        assert result["tonelag"] == 1
        assert result["stavelser"] == 1
        assert result["stress"] == [1]
        assert result["ipa_ren"] == "suːl"
        assert result["fonemer"] == [["s", "uː", "l"]]

    def test_katten(self):
        """katten: "kɑ.tn̩ — tone 2, 2 syllables."""
        result = parse_ipa('"kɑ.tn̩')
        assert result["tonelag"] == 2
        assert result["stavelser"] == 2
        assert result["stress"] == [1, 0]
        assert result["ipa_ren"] == "kɑ.tn̩"

    def test_hjerte(self):
        """hjerte: "jæ.ʈə — tone 2, 2 syllables, retroflex."""
        result = parse_ipa('"jæ.ʈə')
        assert result["tonelag"] == 2
        assert result["stavelser"] == 2
        assert result["fonemer"][1] == ["ʈ", "ə"]

    def test_bønder(self):
        """bønder: 'bœ.nər — tone 1, 2 syllables."""
        result = parse_ipa("'bœ.nər")
        assert result["tonelag"] == 1
        assert result["stavelser"] == 2
        assert result["stress"] == [1, 0]
        assert result["ipa_ren"] == "bœ.nər"

    def test_bønner(self):
        """bønner: "bœ.nər — tone 2, 2 syllables.
        Same phonemes as bønder but different tonelag!
        """
        result = parse_ipa('"bœ.nər')
        assert result["tonelag"] == 2
        assert result["stavelser"] == 2
        assert result["ipa_ren"] == "bœ.nər"


class TestParseNofabetStress:
    def test_sol(self):
        result = parse_nofabet_stress("S OO1 L")
        assert result == [1]

    def test_katten(self):
        result = parse_nofabet_stress("K AH2 T NX0")
        assert result == [2, 0]

    def test_empty(self):
        assert parse_nofabet_stress("") is None


class TestShouldSkip:
    def test_suffix(self):
        assert should_skip("-abel", "JJ") is True

    def test_multiword(self):
        assert should_skip("A-B_Klinikken", "NN") is True

    def test_normal(self):
        assert should_skip("hus", "NN") is False

    def test_digit(self):
        assert should_skip("123", "RG") is True
