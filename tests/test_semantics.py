"""Tests for the semantics engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from rimordbok.semantics import (
    finn_synonymer,
    finn_antonymer,
    finn_relaterte,
    finn_meronymer,
    finn_holonymer,
)

SEM_DB = Path(__file__).resolve().parent.parent / "data/db/semantics.db"
RHYME_DB = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"

pytestmark = pytest.mark.skipif(
    not SEM_DB.exists(), reason="semantics.db not built yet"
)


class TestFinnSynonymer:
    def test_glad_includes_lykkelig(self):
        results = finn_synonymer("glad", db_path=SEM_DB, rhyme_db=RHYME_DB)
        words = {r["ord"] for r in results}
        assert "lykkelig" in words

    def test_glad_includes_fornøyd(self):
        results = finn_synonymer("glad", db_path=SEM_DB, rhyme_db=RHYME_DB)
        words = {r["ord"] for r in results}
        assert "fornøyd" in words

    def test_result_format(self):
        results = finn_synonymer("glad", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert len(results) > 0
        r = results[0]
        assert "ord" in r
        assert "relasjon" in r
        assert r["relasjon"] == "synonym"
        assert "kilde" in r
        assert "frekvens" in r

    def test_sorted_by_frequency(self):
        """Results should be sorted by frequency descending."""
        results = finn_synonymer("glad", db_path=SEM_DB, rhyme_db=RHYME_DB)
        freqs = [r["frekvens"] for r in results]
        assert freqs == sorted(freqs, reverse=True)

    def test_unknown_word(self):
        results = finn_synonymer("xyznonexistent", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert results == []

    def test_case_insensitive(self):
        r1 = finn_synonymer("Glad", db_path=SEM_DB, rhyme_db=RHYME_DB)
        r2 = finn_synonymer("glad", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert {r["ord"] for r in r1} == {r["ord"] for r in r2}

    def test_stor_has_synonyms(self):
        results = finn_synonymer("stor", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert len(results) > 0


class TestFinnAntonymer:
    def test_returns_list(self):
        results = finn_antonymer("glad", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert isinstance(results, list)

    def test_unknown_word(self):
        results = finn_antonymer("xyznonexistent", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert results == []


class TestFinnRelaterte:
    def test_hund_has_related(self):
        """'hund' should have hypernyms like 'rovdyr' or 'dyr'."""
        results = finn_relaterte("hund", db_path=SEM_DB, rhyme_db=RHYME_DB)
        words = {r["ord"] for r in results}
        assert len(words) > 0

    def test_result_has_relasjon_type(self):
        results = finn_relaterte("hund", db_path=SEM_DB, rhyme_db=RHYME_DB)
        if results:
            rels = {r["relasjon"] for r in results}
            assert rels <= {"hypernym", "hyponym", "related"}

    def test_unknown_word(self):
        results = finn_relaterte("xyznonexistent", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert results == []


class TestFinnMeronymer:
    def test_returns_list(self):
        results = finn_meronymer("bil", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert isinstance(results, list)


class TestFinnHolonymer:
    def test_returns_list(self):
        results = finn_holonymer("hjul", db_path=SEM_DB, rhyme_db=RHYME_DB)
        assert isinstance(results, list)


class TestDatabaseIntegrity:
    def test_synonym_count(self):
        """Should have substantial synonym coverage."""
        import sqlite3
        conn = sqlite3.connect(str(SEM_DB))
        cur = conn.execute(
            "SELECT COUNT(DISTINCT word) FROM word_relations WHERE relation = 'synonym'"
        )
        count = cur.fetchone()[0]
        conn.close()
        assert count > 10_000

    def test_relation_types(self):
        """Should have all expected relation types."""
        import sqlite3
        conn = sqlite3.connect(str(SEM_DB))
        cur = conn.execute("SELECT DISTINCT relation FROM word_relations")
        rels = {row[0] for row in cur}
        conn.close()
        assert "synonym" in rels
        assert "antonym" in rels
        assert "hypernym" in rels
        assert "hyponym" in rels
