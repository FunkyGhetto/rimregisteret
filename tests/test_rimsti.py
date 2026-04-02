"""Tests for rimsti (rhyme path) functionality."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from rimordbok.rhyme import _consonant_skeleton, finn_rimsti

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="database not built yet",
)

client = TestClient(app)


# ===================================================================
# 1. _consonant_skeleton
# ===================================================================


class TestConsonantSkeletonBasic:
    def test_same_skeleton_ng_r(self):
        """ɛŋ.ər, ɑŋ.ər, ɪŋ.ər all share skeleton (ŋ, r)."""
        s1 = _consonant_skeleton("ɛŋ.ər")
        s2 = _consonant_skeleton("ɑŋ.ər")
        s3 = _consonant_skeleton("ɪŋ.ər")
        assert s1 == s2 == s3

    def test_same_skeleton_kst(self):
        """ɛkst, ɑkst, ɔkst all share skeleton."""
        s1 = _consonant_skeleton("ɛkst")
        s2 = _consonant_skeleton("ɑkst")
        s3 = _consonant_skeleton("ɔkst")
        assert s1 == s2 == s3

    def test_same_skeleton_l(self):
        """ɑːl and ɛl both have skeleton (l,)."""
        assert _consonant_skeleton("ɑːl") == _consonant_skeleton("ɛl")

    def test_same_skeleton_r(self):
        """eːr and ɑːr both have skeleton (r,)."""
        assert _consonant_skeleton("eːr") == _consonant_skeleton("ɑːr")

    def test_different_skeletons(self):
        """ɛŋ.ər and ɛkst have different skeletons."""
        assert _consonant_skeleton("ɛŋ.ər") != _consonant_skeleton("ɛkst")


class TestConsonantSkeletonEdgeCases:
    def test_vowel_only(self):
        """Suffix with only a vowel gives skeleton with just V."""
        assert _consonant_skeleton("ɑː") == ("V",)

    def test_diphthong_collapses(self):
        """Diphthong + consonant: vowels collapse to one V."""
        assert _consonant_skeleton("æ͡ɪs") == ("V", "s")
        assert _consonant_skeleton("æ͡ɪ.ən") == ("V", "n")

    def test_long_short_vowel_same(self):
        """Long and short vowel give same skeleton."""
        assert _consonant_skeleton("ɑːl") == _consonant_skeleton("ɑl")

    def test_preserves_syllable_structure(self):
        """Monosyllabic and polysyllabic suffixes get different skeletons."""
        mono = _consonant_skeleton("ʉːs")  # hus
        poly = _consonant_skeleton("øː.sə")  # løse
        assert mono == ("V", "s")
        assert poly == ("V", "s", "V")
        assert mono != poly

    def test_specific_values(self):
        """Verify exact skeleton values for key suffixes."""
        assert _consonant_skeleton("ɛŋ.ər") == ("V", "ŋ", "V", "r")
        assert _consonant_skeleton("ɑ.sə") == ("V", "s", "V")
        assert _consonant_skeleton("ɑːl") == ("V", "l")


# ===================================================================
# 2. finn_rimsti
# ===================================================================


class TestFinnRimsti:
    def test_known_word(self):
        """finn_rimsti('sang') returns steg with matching suffixes."""
        result = finn_rimsti("sang", min_familiestr=3, maks_steg=20)
        assert result["ord"] == "sang"
        assert result["rimsuffiks"] is not None
        assert result["konsonantskjelett"] is not None
        assert result["antall_steg"] > 0

        suffixes = {s["rimsuffiks"] for s in result["steg"]}
        # sang has suffix ɑŋ, should find other ŋ-families
        assert "ɑŋ" in suffixes

    def test_active_step(self):
        """The input word's own family is marked aktiv."""
        result = finn_rimsti("sang", min_familiestr=3)
        active = [s for s in result["steg"] if s["aktiv"]]
        assert len(active) == 1
        assert active[0]["rimsuffiks"] == result["rimsuffiks"]

    def test_family_size_filter(self):
        """All steg have familiestr >= min_familiestr."""
        result = finn_rimsti("sang", min_familiestr=5)
        for s in result["steg"]:
            assert s["familiestr"] >= 5

    def test_maks_steg(self):
        """maks_steg limits the number of results."""
        result = finn_rimsti("sang", maks_steg=3)
        assert result["antall_steg"] <= 3

    def test_eksempler_present(self):
        """Each steg has at least one eksempel."""
        result = finn_rimsti("sang", min_familiestr=3)
        for s in result["steg"]:
            assert len(s["eksempler"]) > 0

    def test_unknown_word(self):
        """Unknown word returns empty steg."""
        result = finn_rimsti("xyznonexistent")
        assert result["antall_steg"] == 0

    def test_sorted_by_vowel_distance(self):
        """Steg are sorted by avstand (vowel distance) ascending."""
        result = finn_rimsti("sang", min_familiestr=3)
        distances = [s["avstand"] for s in result["steg"]]
        assert distances == sorted(distances)

    def test_active_step_has_zero_distance(self):
        """The active step should have avstand 0.0."""
        result = finn_rimsti("sang", min_familiestr=3)
        active = [s for s in result["steg"] if s["aktiv"]]
        assert len(active) == 1
        assert active[0]["avstand"] == 0.0


# ===================================================================
# 3. API endpoint
# ===================================================================


class TestAPIRimsti:
    def test_basic(self):
        r = client.get("/api/v1/rimsti/sang")
        assert r.status_code == 200
        data = r.json()
        assert "steg" in data
        assert "konsonantskjelett" in data
        assert "soketid_ms" in data
        assert data["antall_steg"] > 0

    def test_parameters(self):
        r = client.get("/api/v1/rimsti/sang?maks_steg=3&min_familiestr=5")
        data = r.json()
        assert len(data["steg"]) <= 3
        for s in data["steg"]:
            assert s["familiestr"] >= 5

    def test_invalid_dialekt(self):
        r = client.get("/api/v1/rimsti/sang?dialekt=invalid")
        assert r.status_code == 400

    def test_unknown_word(self):
        r = client.get("/api/v1/rimsti/xyznonexistent")
        assert r.status_code == 200
        assert r.json()["antall_steg"] == 0

    def test_response_format(self):
        r = client.get("/api/v1/rimsti/sol")
        data = r.json()
        assert data["ord"] == "sol"
        if data["steg"]:
            s = data["steg"][0]
            assert "rimsuffiks" in s
            assert "eksempler" in s
            assert "familiestr" in s
            assert "aktiv" in s
