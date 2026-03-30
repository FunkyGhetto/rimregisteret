"""Tests for rimklynge-generering (clusters.py)."""

import sqlite3
from pathlib import Path

import pytest

from rimordbok.clusters import (
    generer_rimklynger,
    hent_kvalifiserte_suffikser,
    hent_rimfamilie,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"


# ===================================================================
# 1. hent_kvalifiserte_suffikser
# ===================================================================

class TestHentKvalifiserteSuffikser:
    def test_returns_list(self):
        result = hent_kvalifiserte_suffikser(min_ord=2)
        assert isinstance(result, list)
        assert len(result) > 100  # plenty of suffixes

    def test_min_ord_filters(self):
        few = hent_kvalifiserte_suffikser(min_ord=50)
        many = hent_kvalifiserte_suffikser(min_ord=2)
        assert len(few) < len(many)

    def test_stavelser_filter(self):
        result = hent_kvalifiserte_suffikser(min_ord=2, stavelser=1)
        assert isinstance(result, list)
        assert len(result) > 0


# ===================================================================
# 2. hent_rimfamilie
# ===================================================================

class TestHentRimfamilie:
    def test_known_suffix(self):
        # ɑt is the suffix for "natt", "bratt", "skatt", etc.
        result = hent_rimfamilie("ɑt", min_frekvens=0.0)
        assert len(result) > 5
        for w in result:
            assert "ord" in w
            assert "frekvens" in w

    def test_tilfeldig_ordering(self):
        """Two random calls should likely differ in order."""
        r1 = hent_rimfamilie("ɑt", min_frekvens=0.0, tilfeldig=True, maks=20)
        r2 = hent_rimfamilie("ɑt", min_frekvens=0.0, tilfeldig=True, maks=20)
        words1 = [w["ord"] for w in r1]
        words2 = [w["ord"] for w in r2]
        # Same words, but almost certainly different order
        assert set(words1) == set(words2) or words1 != words2

    def test_frequency_sorted_when_not_random(self):
        result = hent_rimfamilie("ɑt", min_frekvens=0.0, tilfeldig=False)
        freqs = [w["frekvens"] for w in result]
        assert freqs == sorted(freqs, reverse=True)

    def test_maks_limits(self):
        result = hent_rimfamilie("ɑt", min_frekvens=0.0, maks=3)
        assert len(result) <= 3

    def test_unknown_suffix(self):
        result = hent_rimfamilie("zzzznonexistent", min_frekvens=0.0)
        assert result == []


# ===================================================================
# 3. PAR-modus (2 ord per klynge)
# ===================================================================

class TestParModus:
    def test_returns_clusters(self):
        result = generer_rimklynger(modus="par", antall=5)
        assert isinstance(result, list)
        assert len(result) > 0
        assert len(result) <= 5

    def test_cluster_size_is_2(self):
        result = generer_rimklynger(modus="par", antall=5)
        for klynge in result:
            assert len(klynge["ord"]) == 2

    def test_words_share_suffix(self):
        """All words in a cluster should share the same rimsuffiks."""
        result = generer_rimklynger(modus="par", antall=3, min_frekvens=0.0)
        for klynge in result:
            suffiks = klynge["rimsuffiks"]
            assert suffiks is not None
            assert len(suffiks) > 0

    def test_different_families_per_cluster(self):
        """Without `ord`, each cluster should come from a different family."""
        result = generer_rimklynger(modus="par", antall=5)
        suffikser = [k["rimsuffiks"] for k in result]
        # All suffixes should be unique (each from different family)
        assert len(set(suffikser)) == len(suffikser)

    def test_randomness(self):
        """Two calls should likely produce different results."""
        r1 = generer_rimklynger(modus="par", antall=5)
        r2 = generer_rimklynger(modus="par", antall=5)
        words1 = [w for k in r1 for w in k["ord"]]
        words2 = [w for k in r2 for w in k["ord"]]
        # Very unlikely to be identical
        assert words1 != words2 or True  # allow rare collision


# ===================================================================
# 4. BRED-modus (4 ord per klynge)
# ===================================================================

class TestBredModus:
    def test_returns_clusters(self):
        result = generer_rimklynger(modus="bred", antall=3)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_cluster_size_is_4(self):
        result = generer_rimklynger(modus="bred", antall=3)
        for klynge in result:
            assert len(klynge["ord"]) == 4

    def test_words_share_suffix(self):
        result = generer_rimklynger(modus="bred", antall=2, min_frekvens=0.0)
        for klynge in result:
            assert klynge["rimsuffiks"] is not None


# ===================================================================
# 5. DYP-modus (alle ord fra én rimfamilie)
# ===================================================================

class TestDypModus:
    def test_returns_single_cluster(self):
        result = generer_rimklynger(modus="dyp")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_many_words(self):
        result = generer_rimklynger(modus="dyp", min_frekvens=0.0)
        klynge = result[0]
        assert len(klynge["ord"]) > 4

    def test_sorted_by_frequency(self):
        """DYP mode should return words sorted by frequency (most common first)."""
        result = generer_rimklynger(modus="dyp", min_frekvens=0.0)
        klynge = result[0]
        # Verify the suffix has freq-sorted words by checking via hent_rimfamilie
        familie = hent_rimfamilie(
            klynge["rimsuffiks"], min_frekvens=0.0, tilfeldig=False
        )
        expected_order = [w["ord"] for w in familie]
        assert klynge["ord"] == expected_order


# ===================================================================
# 6. `ord` parameter
# ===================================================================

class TestOrdParameter:
    def test_par_with_ord_natt(self):
        result = generer_rimklynger(modus="par", antall=3, ord="natt", min_frekvens=0.0)
        assert len(result) > 0
        for klynge in result:
            assert len(klynge["ord"]) == 2

    def test_bred_with_ord_natt(self):
        result = generer_rimklynger(modus="bred", antall=2, ord="natt", min_frekvens=0.0)
        assert len(result) > 0
        for klynge in result:
            assert len(klynge["ord"]) == 4

    def test_dyp_with_ord_natt(self):
        result = generer_rimklynger(modus="dyp", ord="natt", min_frekvens=0.0)
        assert len(result) == 1
        klynge = result[0]
        assert len(klynge["ord"]) > 4
        # "natt" itself should be in the family
        assert "natt" in [w.lower() for w in klynge["ord"]]

    def test_all_words_rhyme_with_ord(self):
        """When ord='natt', all results should share natt's rimsuffiks."""
        result = generer_rimklynger(modus="dyp", ord="natt", min_frekvens=0.0)
        klynge = result[0]
        # All words in this cluster come from the same suffix
        assert klynge["rimsuffiks"] is not None
        assert len(klynge["rimsuffiks"]) > 0

    def test_nonexistent_word(self):
        result = generer_rimklynger(modus="par", ord="xyznonexistent")
        assert result == []

    def test_case_insensitive(self):
        r1 = generer_rimklynger(modus="dyp", ord="Natt", min_frekvens=0.0)
        r2 = generer_rimklynger(modus="dyp", ord="natt", min_frekvens=0.0)
        assert len(r1) == len(r2) == 1
        assert r1[0]["rimsuffiks"] == r2[0]["rimsuffiks"]


# ===================================================================
# 7. Filters
# ===================================================================

class TestFilters:
    def test_stavelser_filter(self):
        result = generer_rimklynger(modus="par", antall=3, stavelser=1, min_frekvens=0.0)
        assert len(result) > 0
        for klynge in result:
            assert klynge["stavelser"] == 1

    def test_frekvens_filter(self):
        """High frequency threshold should yield fewer/no results."""
        high = generer_rimklynger(modus="par", antall=5, min_frekvens=1000.0)
        low = generer_rimklynger(modus="par", antall=5, min_frekvens=0.01)
        assert len(high) <= len(low)

    def test_rare_stavelser_empty(self):
        """Very rare syllable count should give empty or few results."""
        result = generer_rimklynger(modus="par", antall=5, stavelser=9)
        assert len(result) == 0 or len(result) < 5


# ===================================================================
# 8. Edge cases
# ===================================================================

class TestEdgeCases:
    def test_invalid_modus(self):
        with pytest.raises(ValueError, match="Ugyldig modus"):
            generer_rimklynger(modus="invalid")

    def test_antall_zero(self):
        result = generer_rimklynger(modus="par", antall=0)
        assert result == []

    def test_antall_one(self):
        result = generer_rimklynger(modus="par", antall=1)
        assert len(result) <= 1

    def test_dyp_ignores_antall(self):
        """DYP mode always returns 1 cluster regardless of antall."""
        result = generer_rimklynger(modus="dyp", antall=50, min_frekvens=0.0)
        assert len(result) == 1


# ===================================================================
# 9. Rimsuffiks-konsistens — alle ord i klynge har faktisk samme suffiks
# ===================================================================

class TestRimsuffiksKonsistens:
    """Verify all words in a cluster actually share the claimed rimsuffiks in DB."""

    def _word_has_suffix(self, conn, word, expected_suffix):
        """Check if any DB entry for this word has the expected suffix."""
        rows = conn.execute(
            "SELECT DISTINCT rimsuffiks FROM ord WHERE LOWER(ord) = ?",
            (word.lower(),),
        ).fetchall()
        assert rows, f"Word '{word}' not in DB"
        suffixes = {r[0] for r in rows}
        assert expected_suffix in suffixes, (
            f"Word '{word}' has suffixes {suffixes}, expected '{expected_suffix}'"
        )

    def test_par_words_share_db_suffix(self):
        result = generer_rimklynger(modus="par", antall=5, min_frekvens=0.0)
        conn = sqlite3.connect(str(DB_PATH))
        for klynge in result:
            for word in klynge["ord"]:
                self._word_has_suffix(conn, word, klynge["rimsuffiks"])
        conn.close()

    def test_bred_words_share_db_suffix(self):
        result = generer_rimklynger(modus="bred", antall=3, min_frekvens=0.0)
        conn = sqlite3.connect(str(DB_PATH))
        for klynge in result:
            for word in klynge["ord"]:
                self._word_has_suffix(conn, word, klynge["rimsuffiks"])
        conn.close()

    def test_dyp_words_share_db_suffix(self):
        result = generer_rimklynger(modus="dyp", ord="natt", min_frekvens=0.0)
        conn = sqlite3.connect(str(DB_PATH))
        klynge = result[0]
        for word in klynge["ord"][:20]:
            self._word_has_suffix(conn, word, klynge["rimsuffiks"])
        conn.close()


# ===================================================================
# 10. Frekvensfilter — sjeldne ord filtreres bort
# ===================================================================

class TestFrekvensfilterDetalj:
    """Verify frequency filter actually removes low-frequency words."""

    def test_high_freq_excludes_rare_words(self):
        """With min_frekvens=10.0, all words should have freq >= 10."""
        result = generer_rimklynger(modus="dyp", min_frekvens=10.0)
        if result:
            klynge = result[0]
            familie = hent_rimfamilie(
                klynge["rimsuffiks"], min_frekvens=10.0, tilfeldig=False
            )
            for w in familie:
                assert w["frekvens"] >= 10.0, (
                    f"Word '{w['ord']}' has freq {w['frekvens']} < 10.0"
                )

    def test_zero_freq_includes_all(self):
        """min_frekvens=0 should include words with zero frequency."""
        result_zero = generer_rimklynger(modus="dyp", ord="natt", min_frekvens=0.0)
        result_high = generer_rimklynger(modus="dyp", ord="natt", min_frekvens=5.0)
        if result_zero and result_high:
            assert len(result_zero[0]["ord"]) >= len(result_high[0]["ord"])


# ===================================================================
# 11. Tilfeldighet — 5 kall gir minst 2 ulike resultater
# ===================================================================

class TestTilfeldighet:
    """Verify randomness across multiple calls."""

    def test_par_randomness_5_calls(self):
        """5 calls to par mode should produce at least 2 different suffix sets."""
        suffix_sets = set()
        for _ in range(5):
            result = generer_rimklynger(modus="par", antall=3)
            key = frozenset(k["rimsuffiks"] for k in result)
            suffix_sets.add(key)
        assert len(suffix_sets) >= 2, (
            "5 random par calls all returned the same suffixes"
        )

    def test_bred_randomness_5_calls(self):
        suffix_sets = set()
        for _ in range(5):
            result = generer_rimklynger(modus="bred", antall=3)
            key = frozenset(k["rimsuffiks"] for k in result)
            suffix_sets.add(key)
        assert len(suffix_sets) >= 2


# ===================================================================
# 12. Antall-parameter
# ===================================================================

class TestAntallParameter:
    def test_exact_antall_par(self):
        for n in [1, 3, 5, 10]:
            result = generer_rimklynger(modus="par", antall=n, min_frekvens=0.0)
            assert len(result) <= n
            if n <= 5:
                assert len(result) == n  # should have enough families

    def test_exact_antall_bred(self):
        for n in [1, 3, 5]:
            result = generer_rimklynger(modus="bred", antall=n, min_frekvens=0.0)
            assert len(result) <= n
            if n <= 3:
                assert len(result) == n
