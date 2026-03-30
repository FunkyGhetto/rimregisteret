"""Tests for the rhyme engine."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from rimordbok.rhyme import (
    finn_perfekte_rim,
    finn_nesten_rim,
    finn_homofoner,
    match_konsonanter,
    _score_near_rhyme,
    _parse_suffix_phonemes,
    _segment_phonemes,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="rimindeks.db not built yet"
)


# --- Unit tests for internal helpers ---


class TestSegmentPhonemes:
    def test_simple(self):
        assert _segment_phonemes("suːl") == ["s", "uː", "l"]

    def test_diphthong(self):
        assert _segment_phonemes("stæ͡ɪn") == ["s", "t", "æ͡ɪ", "n"]

    def test_retroflex(self):
        assert _segment_phonemes("ʈə") == ["ʈ", "ə"]


class TestParseSuffixPhonemes:
    def test_single_syllable(self):
        assert _parse_suffix_phonemes("uːl") == ["uː", "l"]

    def test_multi_syllable(self):
        phs = _parse_suffix_phonemes("æ.ʈə")
        assert phs == ["æ", "ʈ", "ə"]


class TestNearRhymeScoring:
    def test_identical_suffix(self):
        assert _score_near_rhyme("ɑːg", "ɑːg") == 1.0

    def test_dag_tak_near_rhyme(self):
        """dag (ɑːg) vs tak (ɑːk): same vowel, g/k equivalence → high score."""
        score = _score_near_rhyme("ɑːg", "ɑːk")
        assert score >= 0.5, f"Expected near-rhyme score >= 0.5, got {score}"

    def test_completely_different(self):
        score = _score_near_rhyme("uːl", "ɪŋ")
        assert score < 0.5


# --- Integration tests ---


class TestFinnPerfekteRim:
    def test_sol_includes_stol(self):
        """'sol' should perfectly rhyme with 'stol'."""
        results = finn_perfekte_rim("sol", db_path=DB_PATH)
        words = {r["ord"] for r in results}
        assert "stol" in words

    def test_hjerte_includes_smerte(self):
        """'hjerte' should perfectly rhyme with 'smerte'."""
        results = finn_perfekte_rim("hjerte", db_path=DB_PATH)
        words = {r["ord"] for r in results}
        assert "smerte" in words

    def test_result_format(self):
        results = finn_perfekte_rim("sol", db_path=DB_PATH)
        assert len(results) > 0
        r = results[0]
        assert "ord" in r
        assert "rimsuffiks" in r
        assert "tonelag" in r
        assert "stavelser" in r
        assert "score" in r
        assert r["score"] == 1.0

    def test_no_self_rhyme(self):
        results = finn_perfekte_rim("sol", db_path=DB_PATH)
        words = {r["ord"] for r in results}
        assert "sol" not in words

    def test_unknown_word(self):
        results = finn_perfekte_rim("xyznonexistent", db_path=DB_PATH)
        assert results == []

    def test_performance(self):
        """Perfect rhyme lookup should be fast (<50ms)."""
        start = time.perf_counter()
        finn_perfekte_rim("sol", db_path=DB_PATH)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05, f"Took {elapsed:.3f}s, expected < 0.05s"

    def test_samme_tonelag(self):
        """With samme_tonelag=True, all results should share tonelag."""
        results = finn_perfekte_rim("sol", db_path=DB_PATH, samme_tonelag=True)
        for r in results:
            assert r["tonelag"] == 1


class TestFinnNestenRim:
    def test_dag_finds_tak(self):
        """dag (ɑːg) → near-rhyme 'tak' (ɑːk) via g/k equivalence."""
        results = finn_nesten_rim("dag", db_path=DB_PATH, terskel=0.5)
        words = {r["ord"] for r in results}
        assert "tak" in words

    def test_score_range(self):
        results = finn_nesten_rim("dag", db_path=DB_PATH, terskel=0.5)
        for r in results:
            assert 0.0 <= r["score"] <= 1.5  # max 1.0 + 0.1 tonelag bonus

    def test_excludes_exact_matches(self):
        """Near-rhyme should not include perfect rhymes (same suffix)."""
        exact = finn_perfekte_rim("dag", db_path=DB_PATH, maks=500)
        exact_words = {r["ord"] for r in exact}

        near = finn_nesten_rim("dag", db_path=DB_PATH, terskel=0.5)
        near_words = {r["ord"] for r in near}

        # Near-rhymes should not overlap with perfect rhymes
        overlap = exact_words & near_words
        assert len(overlap) == 0, f"Overlap: {overlap}"


class TestFinnHomofoner:
    def test_returns_list(self):
        results = finn_homofoner("sol", db_path=DB_PATH)
        assert isinstance(results, list)

    def test_no_self(self):
        results = finn_homofoner("sol", db_path=DB_PATH)
        words = {r["ord"] for r in results}
        assert "sol" not in words


class TestMatchKonsonanter:
    def test_returns_list(self):
        results = match_konsonanter("sol", db_path=DB_PATH)
        assert isinstance(results, list)

    def test_no_self(self):
        results = match_konsonanter("sol", db_path=DB_PATH)
        words = {r["ord"] for r in results}
        assert "sol" not in words
