"""Tests for rhyme index — verify that known rhyme pairs are found."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rimordbok.db import hent_rim, hent_fonetikk, sok_ord
from scripts.build_rhyme_index import compute_rhyme_suffix, is_vowel

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="rimindeks.db not built yet"
)


# --- Rhyme suffix unit tests ---


class TestRhymeSuffix:
    def test_sol(self):
        """sol: 1 syllable, stress on only syllable → suffix from vowel."""
        fonemer = [["s", "uː", "l"]]
        stress = [1]
        assert compute_rhyme_suffix(fonemer, stress) == "uːl"

    def test_katten(self):
        """katten: 2 syllables, stress on first → suffix includes both."""
        fonemer = [["k", "ɑ"], ["t", "n̩"]]
        stress = [1, 0]
        assert compute_rhyme_suffix(fonemer, stress) == "ɑ.tn̩"

    def test_forstaa(self):
        """forstå: stress on last syllable → suffix is just last syllable vowel+."""
        fonemer = [["f", "ɔ", "ʂ"], ["ʈ", "oː"]]
        stress = [0, 1]
        assert compute_rhyme_suffix(fonemer, stress) == "oː"

    def test_fantastisk(self):
        """fantastisk: stress on second syllable → suffix from 'ɑ' in syl 2 onwards."""
        fonemer = [["f", "ɑ", "n"], ["t", "ɑ"], ["s", "t", "ɪ"], ["s", "k"]]
        stress = [0, 1, 0, 0]
        assert compute_rhyme_suffix(fonemer, stress) == "ɑ.stɪ.sk"

    def test_menneske(self):
        """menneske: stress on first syllable."""
        fonemer = [["m", "ɛ"], ["n", "ə"], ["s", "k", "ə"]]
        stress = [1, 0, 0]
        assert compute_rhyme_suffix(fonemer, stress) == "ɛ.nə.skə"


class TestIsVowel:
    def test_monophthongs(self):
        assert is_vowel("ɑ")
        assert is_vowel("ɛ")
        assert is_vowel("ə")

    def test_long_vowels(self):
        assert is_vowel("uː")
        assert is_vowel("ɑː")

    def test_consonants(self):
        assert not is_vowel("k")
        assert not is_vowel("t")
        assert not is_vowel("ŋ")
        assert not is_vowel("ʂ")

    def test_syllabic_consonants(self):
        assert not is_vowel("n̩")
        assert not is_vowel("l̩")


# --- Database integration tests ---


class TestHentRim:
    def test_sol_rhymes(self):
        """'sol' should rhyme with 'stol', 'bol', 'fiol', etc."""
        results = hent_rim("sol", db_path=DB_PATH, maks=500)
        rhyme_words = {r["ord"] for r in results}
        assert "stol" in rhyme_words
        assert "bol" in rhyme_words
        assert "fiol" in rhyme_words

    def test_dag_rhymes(self):
        """'dag' should rhyme with 'flag', 'jag', 'fag', etc.

        'ɑːg' is a very common suffix (1000+ words), so we test
        words early in the alphabet to stay within default limits.
        """
        results = hent_rim("dag", db_path=DB_PATH, maks=500)
        rhyme_words = {r["ord"] for r in results}
        assert "flag" in rhyme_words
        assert "jag" in rhyme_words
        assert "fag" in rhyme_words

    def test_natt_rhymes(self):
        """'natt' should rhyme with 'matt', 'hatt', 'katt', etc."""
        results = hent_rim("natt", db_path=DB_PATH, maks=500)
        rhyme_words = {r["ord"] for r in results}
        assert "matt" in rhyme_words
        assert "hatt" in rhyme_words
        assert "katt" in rhyme_words

    def test_no_self_rhyme(self):
        """A word should not appear in its own rhyme list."""
        results = hent_rim("sol", db_path=DB_PATH)
        rhyme_words = {r["ord"] for r in results}
        assert "sol" not in rhyme_words

    def test_unknown_word(self):
        """Unknown word should return empty list."""
        assert hent_rim("xyznonexistent", db_path=DB_PATH) == []

    def test_bønder_bønner_tonelag(self):
        """bønder (tone 1) and bønner (tone 2) share suffix but differ in tonelag."""
        info_d = hent_fonetikk("bønder", db_path=DB_PATH)
        info_n = hent_fonetikk("bønner", db_path=DB_PATH)
        assert info_d[0]["rimsuffiks"] == info_n[0]["rimsuffiks"]
        assert info_d[0]["tonelag"] != info_n[0]["tonelag"]


class TestHentFonetikk:
    def test_known_word(self):
        results = hent_fonetikk("sol", db_path=DB_PATH)
        assert len(results) >= 1
        r = results[0]
        assert r["rimsuffiks"] == "uːl"
        assert r["tonelag"] == 1
        assert r["stavelser"] == 1

    def test_unknown_word(self):
        assert hent_fonetikk("xyznonexistent", db_path=DB_PATH) == []


class TestSokOrd:
    def test_prefix(self):
        results = sok_ord("sol", db_path=DB_PATH, maks=10)
        assert "sol" in results
        assert all(r.startswith("sol") for r in results)

    def test_empty_prefix(self):
        results = sok_ord("zzzzz", db_path=DB_PATH)
        assert results == []
