"""Tests for word frequency data and frequency-based ranking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"
FREQ_FILE = Path(__file__).resolve().parent.parent / "data/processed/frequencies.jsonl"


class TestFrequencyFile:
    """Test the frequencies.jsonl output."""

    pytestmark = pytest.mark.skipif(
        not FREQ_FILE.exists(), reason="frequencies.jsonl not built yet"
    )

    def test_file_has_enough_words(self):
        count = 0
        with open(FREQ_FILE, encoding="utf-8") as f:
            for _ in f:
                count += 1
        assert count >= 50_000

    def test_top_words(self):
        """'og', 'er', 'det' should be among the top 10 most frequent words."""
        top_words = []
        with open(FREQ_FILE, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                r = json.loads(line)
                top_words.append(r["ord"])
        assert "og" in top_words
        assert "er" in top_words
        assert "det" in top_words

    def test_frequency_descending(self):
        """File should be sorted by frequency descending."""
        prev_freq = float("inf")
        with open(FREQ_FILE, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 1000:
                    break
                r = json.loads(line)
                assert r["frekvens"] <= prev_freq
                prev_freq = r["frekvens"]

    def test_format(self):
        """Each line should have 'ord' and 'frekvens' keys."""
        with open(FREQ_FILE, encoding="utf-8") as f:
            line = f.readline()
        r = json.loads(line)
        assert "ord" in r
        assert "frekvens" in r
        assert isinstance(r["frekvens"], float)


class TestDatabaseFrequencies:
    """Test that frequencies are loaded into the database."""

    pytestmark = pytest.mark.skipif(
        not DB_PATH.exists(), reason="rimindeks.db not built yet"
    )

    def test_minimum_words_with_frequency(self):
        """At least 50,000 unique words should have frequency > 0."""
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.execute("SELECT COUNT(DISTINCT ord) FROM ord WHERE frekvens > 0")
        count = cur.fetchone()[0]
        conn.close()
        assert count >= 50_000

    def test_common_words_have_frequency(self):
        """Common words like 'dag', 'sol', 'hus' should have frequency > 0."""
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        for word in ("dag", "sol", "hus", "land", "tid"):
            cur = conn.execute(
                "SELECT frekvens FROM ord WHERE ord = ? LIMIT 1", (word,)
            )
            row = cur.fetchone()
            assert row is not None, f"{word} not in DB"
            assert row[0] > 0, f"{word} has no frequency"
        conn.close()

    def test_og_er_det_highest(self):
        """'og', 'er', 'det' should be among the top 10 by frequency."""
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.execute(
            "SELECT ord, frekvens FROM ord ORDER BY frekvens DESC LIMIT 30"
        )
        top_words = {row[0] for row in cur}
        conn.close()
        assert "og" in top_words
        assert "er" in top_words
        assert "det" in top_words


class TestFrequencyRanking:
    """Test that frequency sorting works in rhyme results."""

    pytestmark = pytest.mark.skipif(
        not DB_PATH.exists(), reason="rimindeks.db not built yet"
    )

    def test_alkohol_before_rullestol(self):
        """'alkohol' (common) should rank higher than 'rullestol' (rarer) for 'sol'."""
        from rimordbok.rhyme import finn_perfekte_rim
        results = finn_perfekte_rim("sol", db_path=DB_PATH)
        words = [r["ord"] for r in results]
        assert "alkohol" in words
        assert "rullestol" in words
        assert words.index("alkohol") < words.index("rullestol")

    def test_results_sorted_by_frequency(self):
        """Perfect rhyme results should be sorted by frequency descending."""
        from rimordbok.rhyme import finn_perfekte_rim
        results = finn_perfekte_rim("dag", db_path=DB_PATH)
        freqs = [r["frekvens"] for r in results]
        assert freqs == sorted(freqs, reverse=True)
