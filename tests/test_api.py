"""Tests for the REST API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app

DB_PATH = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"
SEM_DB = Path(__file__).resolve().parent.parent / "data/db/semantics.db"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists() or not SEM_DB.exists(),
    reason="databases not built yet",
)

client = TestClient(app)


# --- Root ---


class TestRoot:
    def test_root(self):
        r = client.get("/")
        assert r.status_code == 200
        # Root serves the frontend HTML
        assert "Rimregisteret" in r.text


# --- Rim ---


class TestRim:
    def test_sol(self):
        r = client.get("/api/v1/rim/sol")
        assert r.status_code == 200
        data = r.json()
        assert data["ord"] == "sol"
        assert data["antall"] > 0
        assert "soketid_ms" in data
        words = {item["ord"] for item in data["resultater"]}
        assert "stol" in words

    def test_response_format(self):
        r = client.get("/api/v1/rim/sol")
        data = r.json()
        item = data["resultater"][0]
        assert "ord" in item
        assert "score" in item
        assert "stavelser" in item
        assert "tonelag" in item
        assert item["score"] == 1.0

    def test_maks_parameter(self):
        r = client.get("/api/v1/rim/sol?maks=5")
        data = r.json()
        assert len(data["resultater"]) <= 5

    def test_stavelser_filter(self):
        r = client.get("/api/v1/rim/sol?stavelser=1")
        data = r.json()
        for item in data["resultater"]:
            assert item["stavelser"] == 1

    def test_tonelag_filter(self):
        r = client.get("/api/v1/rim/sol?tonelag=1")
        data = r.json()
        for item in data["resultater"]:
            assert item["tonelag"] == 1

    def test_samme_tonelag(self):
        r = client.get("/api/v1/rim/sol?samme_tonelag=true")
        data = r.json()
        for item in data["resultater"]:
            assert item["tonelag"] == 1

    def test_unknown_word(self):
        r = client.get("/api/v1/rim/xyznonexistent")
        assert r.status_code == 200
        assert r.json()["antall"] == 0

    def test_performance(self):
        r = client.get("/api/v1/rim/sol")
        data = r.json()
        assert data["soketid_ms"] < 100


# --- Halvrim ---


class TestHalvrim:
    def test_dag(self):
        r = client.get("/api/v1/halvrim/dag")
        assert r.status_code == 200
        data = r.json()
        assert data["antall"] > 0
        words = {item["ord"] for item in data["resultater"]}
        assert "tak" in words

    def test_terskel(self):
        r = client.get("/api/v1/halvrim/dag?terskel=0.8")
        data = r.json()
        for item in data["resultater"]:
            assert item["score"] >= 0.8


# --- Synonymer ---


class TestSynonymer:
    def test_glad(self):
        r = client.get("/api/v1/synonymer/glad")
        assert r.status_code == 200
        data = r.json()
        words = {item["ord"] for item in data["resultater"]}
        assert "lykkelig" in words
        assert "fornøyd" in words

    def test_response_format(self):
        r = client.get("/api/v1/synonymer/glad")
        data = r.json()
        item = data["resultater"][0]
        assert "ord" in item
        assert "relasjon" in item
        assert "kilde" in item
        assert item["relasjon"] == "synonym"


# --- Relaterte ---


class TestRelaterte:
    def test_hund(self):
        r = client.get("/api/v1/relaterte/hund")
        assert r.status_code == 200
        data = r.json()
        assert data["antall"] > 0


# --- Konsonanter ---


class TestKonsonanter:
    def test_returns_list(self):
        r = client.get("/api/v1/konsonanter/sol")
        assert r.status_code == 200
        assert isinstance(r.json()["resultater"], list)


# --- Info ---


class TestInfo:
    def test_sol(self):
        r = client.get("/api/v1/info/sol")
        assert r.status_code == 200
        data = r.json()
        assert data["ord"] == "sol"
        assert "fonetikk" in data
        assert data["fonetikk"]["ipa_ren"] == "suːl"
        assert data["fonetikk"]["tonelag"] == 1
        assert "rim" in data
        assert "synonymer" in data
        assert "soketid_ms" in data

    def test_leksikon_entries(self):
        r = client.get("/api/v1/info/sol")
        data = r.json()
        assert len(data["leksikon"]) >= 1


# --- Søk / Autocomplete ---


class TestSok:
    def test_prefix(self):
        r = client.get("/api/v1/sok?q=sol")
        assert r.status_code == 200
        data = r.json()
        assert data["prefiks"] == "sol"
        assert "sol" in data["resultater"]
        assert all(w.startswith("sol") for w in data["resultater"])

    def test_maks(self):
        r = client.get("/api/v1/sok?q=s&maks=5")
        data = r.json()
        assert len(data["resultater"]) <= 5

    def test_empty_result(self):
        r = client.get("/api/v1/sok?q=zzzzz")
        data = r.json()
        assert data["antall"] == 0


# --- Rimklynger ---


class TestRimklyngerPar:
    def test_basic(self):
        r = client.get("/api/v1/rimklynger/par?antall=5")
        assert r.status_code == 200
        data = r.json()
        assert data["modus"] == "par"
        assert len(data["klynger"]) <= 5
        assert data["antall"] == len(data["klynger"])
        assert "soketid_ms" in data

    def test_cluster_size(self):
        r = client.get("/api/v1/rimklynger/par?antall=3")
        for klynge in r.json()["klynger"]:
            assert len(klynge["ord"]) == 2

    def test_with_ord(self):
        r = client.get("/api/v1/rimklynger/par?ord=sol&antall=3&min_frekvens=0")
        data = r.json()
        assert data["filter"]["ord"] == "sol"
        assert len(data["klynger"]) > 0
        # All clusters should share sol's suffix
        suffixes = {k["rimsuffiks"] for k in data["klynger"]}
        assert len(suffixes) == 1

    def test_response_format(self):
        r = client.get("/api/v1/rimklynger/par?antall=1")
        data = r.json()
        assert "filter" in data
        assert "stavelser" in data["filter"]
        assert "min_frekvens" in data["filter"]
        assert "dialekt" in data["filter"]


class TestRimklyngerBred:
    def test_basic(self):
        r = client.get("/api/v1/rimklynger/bred?antall=3")
        assert r.status_code == 200
        data = r.json()
        assert data["modus"] == "bred"

    def test_cluster_size(self):
        r = client.get("/api/v1/rimklynger/bred?antall=2")
        for klynge in r.json()["klynger"]:
            assert len(klynge["ord"]) == 4

    def test_stavelser_filter(self):
        r = client.get("/api/v1/rimklynger/bred?stavelser=2&antall=3&min_frekvens=0")
        data = r.json()
        assert data["filter"]["stavelser"] == 2


class TestRimklyngerDyp:
    def test_basic(self):
        r = client.get("/api/v1/rimklynger/dyp?min_frekvens=0")
        assert r.status_code == 200
        data = r.json()
        assert data["modus"] == "dyp"
        assert len(data["klynger"]) == 1

    def test_with_ord_natt(self):
        r = client.get("/api/v1/rimklynger/dyp?ord=natt&min_frekvens=0")
        data = r.json()
        assert len(data["klynger"]) == 1
        klynge = data["klynger"][0]
        assert len(klynge["ord"]) > 4
        assert "natt" in [w.lower() for w in klynge["ord"]]
        assert data["filter"]["ord"] == "natt"

    def test_without_ord(self):
        r = client.get("/api/v1/rimklynger/dyp?min_frekvens=0")
        data = r.json()
        assert len(data["klynger"]) == 1
        assert data["filter"]["ord"] is None

    def test_invalid_dialekt(self):
        r = client.get("/api/v1/rimklynger/dyp?dialekt=invalid")
        assert r.status_code == 400
        assert "Ugyldig dialekt" in r.json()["feil"]


class TestRimklyngerFiltre:
    def test_stavelser_filter_par(self):
        r = client.get("/api/v1/rimklynger/par?stavelser=1&antall=3&min_frekvens=0")
        data = r.json()
        assert data["filter"]["stavelser"] == 1
        assert len(data["klynger"]) > 0

    def test_stavelser_filter_dyp(self):
        r = client.get("/api/v1/rimklynger/dyp?stavelser=1&min_frekvens=0")
        data = r.json()
        assert data["filter"]["stavelser"] == 1

    def test_dialekt_filter(self):
        r = client.get("/api/v1/rimklynger/par?dialekt=%C3%B8st&antall=3")
        data = r.json()
        assert r.status_code == 200
        assert data["filter"]["dialekt"] == "øst"

    def test_nonexistent_ord(self):
        r = client.get("/api/v1/rimklynger/par?ord=xyznonexistent")
        data = r.json()
        assert data["klynger"] == []

    def test_impossible_filter(self):
        r = client.get("/api/v1/rimklynger/par?stavelser=99&antall=5")
        data = r.json()
        assert data["klynger"] == []


class TestRimklyngerResponstid:
    # Random cluster generation requires GROUP BY on 684K rows — allow 500ms
    # Ord-specific lookups are much faster (<100ms)
    ENDPOINTS_FAST = [
        "/api/v1/rimklynger/dyp?ord=natt&min_frekvens=0",
        "/api/v1/rimklynger/par?ord=sol&antall=5&min_frekvens=0",
    ]
    ENDPOINTS_RANDOM = [
        "/api/v1/rimklynger/par?antall=10",
        "/api/v1/rimklynger/bred?antall=5",
        "/api/v1/rimklynger/dyp?min_frekvens=0",
    ]

    @pytest.mark.parametrize("endpoint", ENDPOINTS_FAST)
    def test_ord_specific_under_150ms(self, endpoint):
        import time
        client.get(endpoint)
        start = time.perf_counter()
        r = client.get(endpoint)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert r.status_code == 200
        assert elapsed_ms < 150, f"{endpoint} took {elapsed_ms:.1f}ms"

    @pytest.mark.parametrize("endpoint", ENDPOINTS_RANDOM)
    def test_random_under_500ms(self, endpoint):
        import time
        client.get(endpoint)
        start = time.perf_counter()
        r = client.get(endpoint)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert r.status_code == 200
        assert elapsed_ms < 500, f"{endpoint} took {elapsed_ms:.1f}ms"


# --- Edge cases ---


class TestEdgeCases:
    def test_unicode_word(self):
        r = client.get("/api/v1/rim/blå")
        assert r.status_code == 200

    def test_uppercase_word(self):
        r = client.get("/api/v1/rim/Sol")
        assert r.status_code == 200

    def test_maks_high_accepted(self):
        """Rim/halvrim accept high maks values (no limit for frontend)."""
        r = client.get("/api/v1/rim/sol?maks=5000")
        assert r.status_code == 200

    def test_maks_too_high_for_synonymer(self):
        """Synonymer still has le=1000 validation."""
        r = client.get("/api/v1/synonymer/glad?maks=5000")
        assert r.status_code == 422

    def test_cors_header(self):
        r = client.get("/api/v1/rim/sol", headers={"Origin": "http://localhost:3000"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_production(self):
        r = client.get("/api/v1/rim/sol", headers={"Origin": "https://rimregisteret.no"})
        assert r.headers.get("access-control-allow-origin") == "https://rimregisteret.no"
