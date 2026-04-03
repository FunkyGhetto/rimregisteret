from __future__ import annotations

"""REST API for Rimregisteret — norsk rimordbok med fonetikk og semantikk.

Start med:
    uvicorn api.main:app --reload

Swagger-dokumentasjon: http://localhost:8000/docs
"""

import csv
import logging
import os
import sqlite3
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rimordbok.db import hent_fonetikk, hent_varianter, sok_ord, GYLDIGE_DIALEKTER
from rimordbok.phonetics import slaa_opp
from rimordbok.rhyme import _berik_varianter_med_definisjoner
from rimordbok.rhyme import (
    finn_perfekte_rim,
    finn_halvrim,
    match_konsonanter,
    finn_rim_alle_dialekter,
)
from rimordbok.semantics import (
    finn_synonymer,
    finn_relaterte,
)
from rimordbok.definitions import hent_definisjon
from rimordbok.clusters import generer_rimklynger, generer_rimstier

# Dialect enum for API validation
DIALEKT_ENUM = list(GYLDIGE_DIALEKTER)

logger = logging.getLogger("rimordbok.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- Akustisk motor (loaded in background at startup) ---
_akustisk_lex = None
_akustisk_ready = False
_akustisk_csv_tmp = None  # temp file path for cleanup


@asynccontextmanager
async def lifespan(app):
    global _akustisk_lex, _akustisk_ready, _akustisk_csv_tmp

    csv_path = os.environ.get("AKUSTISK_LEXICON_PATH")

    if not csv_path:
        db_path = Path(__file__).resolve().parent.parent / "data/db/rimindeks.db"
        if db_path.exists():
            logger.info("Generating acoustic lexicon CSV from %s", db_path)
            conn = sqlite3.connect(str(db_path))
            cur = conn.execute(
                "SELECT ord, ipa_ren FROM ord WHERE ipa_ren IS NOT NULL AND ipa_ren != ''"
            )
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False, newline=""
            )
            csv_path = tmp.name
            _akustisk_csv_tmp = csv_path
            writer = csv.writer(tmp)
            writer.writerow(["word", "", "", "", "", "", "ipa"])
            count = 0
            for row in cur:
                writer.writerow([row[0], "", "", "", "", "", row[1]])
                count += 1
            tmp.close()
            conn.close()
            logger.info("Wrote %d words to temp CSV %s", count, csv_path)

    def _build_embeddings(path):
        global _akustisk_lex, _akustisk_ready
        try:
            from rimordbok.akustisk import Leksikon
            logger.info("Loading acoustic lexicon from %s", path)
            lex = Leksikon(path)
            logger.info("Building acoustic embeddings (%d words)...", lex.n)
            lex._ensure_embeddings()
            _akustisk_lex = lex
            _akustisk_ready = True
            logger.info("Acoustic engine ready: %d words", lex.n)
        except Exception as e:
            logger.error("Failed to initialize acoustic engine: %s", e)

    if csv_path:
        t = threading.Thread(target=_build_embeddings, args=(csv_path,), daemon=True)
        t.start()
    else:
        logger.warning("No DB or AKUSTISK_LEXICON_PATH; acoustic engine disabled")

    yield

    if _akustisk_csv_tmp:
        try:
            os.unlink(_akustisk_csv_tmp)
        except OSError:
            pass


app = FastAPI(
    title="Rimregisteret API",
    description="Rimregisteret — norsk rimordbok med fonetikk, semantikk og ordfrekvens.",
    version="0.1.0",
    lifespan=lifespan,
)

# GZip compression for large responses
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS — tillat produksjon + localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rimregisteret.no",
        "https://www.rimregisteret.no",
        "https://rimordbok.vercel.app",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Rate limiting (in-memory, per IP, 100 req/min) ---

_rate_store: dict = defaultdict(list)  # IP -> list of timestamps
_RATE_LIMIT = 100  # requests per window
_RATE_WINDOW = 60  # seconds


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # Only rate-limit /api/ paths, skip localhost/testclient
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        if ip in ("127.0.0.1", "localhost", "testclient"):
            return await call_next(request)
        now = time.time()
        # Clean old entries
        _rate_store[ip] = [t for t in _rate_store[ip] if now - t < _RATE_WINDOW]
        if len(_rate_store[ip]) >= _RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={
                    "feil": "For mange forespørsler",
                    "detaljer": f"Grense: {_RATE_LIMIT} forespørsler per {_RATE_WINDOW} sekunder.",
                },
            )
        _rate_store[ip].append(now)
    return await call_next(request)


# --- Middleware: logging og feilhåndtering ---


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s %d %.1fms",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Uventet feil: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"feil": "Intern serverfeil", "detaljer": str(exc)},
    )


# --- Hjelpefunksjoner ---


def _clamp_maks(maks: int, ceiling: int = 1000) -> int:
    return max(1, min(maks, ceiling))


def _filter_results(
    results: list[dict],
    stavelser: Optional[int],
    tonelag: Optional[int],
) -> list[dict]:
    """Apply optional syllable/tonelag filters."""
    if stavelser is not None:
        results = [r for r in results if r.get("stavelser") == stavelser]
    if tonelag is not None:
        results = [r for r in results if r.get("tonelag") == tonelag]
    return results


def _wrap(ord: str, resultater: list[dict], soketid_ms: float) -> dict:
    """Standard response wrapper."""
    return {
        "ord": ord,
        "resultater": resultater,
        "antall": len(resultater),
        "soketid_ms": round(soketid_ms, 1),
    }


# --- Endepunkter ---


@app.get("/api/v1/varianter/{ord}", summary="Finn uttalevarianter (homografer)")
def api_varianter(ord: str):
    """Finn alle uttalevarianter av et ord.

    Returnerer varianter med rimsuffiks, IPA, ordklasse og definisjon.
    Brukes til disambiguering for homografer som "stolt" (adj vs verb).
    """
    start = time.perf_counter()
    varianter = hent_varianter(ord)

    # Enrich with per-variant definitions from Bokmålsordboka
    enriched = _berik_varianter_med_definisjoner(ord, varianter)

    elapsed = (time.perf_counter() - start) * 1000
    return {
        "ord": ord,
        "varianter": enriched,
        "antall": len(enriched),
        "flertydig": len(enriched) > 1,
        "soketid_ms": round(elapsed, 1),
    }


@app.get("/api/v1/rim/{ord}", summary="Finn perfekte rim")
def api_rim(
    ord: str,
    maks: int = Query(200, ge=1, le=100000, description="Maks antall resultater (0 for ingen grense)"),
    stavelser: Optional[int] = Query(None, description="Filtrer på antall stavelser"),
    tonelag: Optional[int] = Query(None, description="Filtrer på tonelag (1 eller 2)"),
    samme_tonelag: bool = Query(False, description="Kun rim med samme tonelag"),
    dialekt: str = Query("øst", description="Dialektregion: øst, nord, midt, vest, sørvest"),
    variant: Optional[str] = Query(None, description="Rimsuffiks for disambiguering (fra /varianter/)"),
    grupper: bool = Query(False, description="Grupper resultater etter stavelser"),
    ekskluder_propn: bool = Query(True, description="Ekskluder proprium (egennavn)"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })

    start = time.perf_counter()
    result = finn_perfekte_rim(
        ord, maks=maks, samme_tonelag=samme_tonelag,
        dialekt=dialekt, rimsuffiks=variant, grupper=grupper,
        ekskluder_propn=ekskluder_propn,
    )

    # Apply post-filters if not grouped (grouped format has nested structure)
    if not grupper and stavelser is not None:
        result["resultater"] = [r for r in result["resultater"] if r.get("stavelser") == stavelser]

    elapsed = (time.perf_counter() - start) * 1000
    result["dialekt"] = dialekt
    result["antall"] = (
        sum(len(g["ord"]) for g in result["resultater"])
        if grupper else len(result["resultater"])
    )
    result["soketid_ms"] = round(elapsed, 1)
    return result


@app.get("/api/v1/halvrim/{ord}", summary="Finn halvrim")
def api_halvrim(
    ord: str,
    maks: int = Query(200, ge=1, le=100000),
    terskel: float = Query(0.75, ge=0.0, le=1.0, description="Minimum likhetsscore"),
    stavelser: Optional[int] = Query(None),
    tonelag: Optional[int] = Query(None),
    dialekt: str = Query("øst", description="Dialektregion: øst, nord, midt, vest, sørvest"),
    variant: Optional[str] = Query(None, description="Rimsuffiks for disambiguering"),
    grupper: bool = Query(False, description="Grupper resultater etter rimdybde"),
    ekskluder_propn: bool = Query(True, description="Ekskluder proprium (egennavn)"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })

    start = time.perf_counter()

    result = finn_halvrim(
        ord, maks=maks, terskel=terskel,
        dialekt=dialekt, rimsuffiks=variant, grupper=grupper,
        ekskluder_propn=ekskluder_propn,
    )

    items = result.get("resultater", [])

    # Apply post-filters if not grouped
    if not grupper and stavelser is not None:
        items = [r for r in items if r.get("stavelser") == stavelser]
        result["resultater"] = items

    elapsed = (time.perf_counter() - start) * 1000
    result["dialekt"] = dialekt
    result["antall"] = (
        sum(len(g["ord"]) for g in items)
        if grupper and items and isinstance(items[0], dict) and "ord" in items[0]
        else len(items)
    )
    result["soketid_ms"] = round(elapsed, 1)
    return result


@app.get("/api/v1/rim/{ord}/dialekter", summary="Rim i alle dialekter")
def api_rim_dialekter(
    ord: str,
    maks: int = Query(20, ge=1, le=100),
):
    """Vis hvilke dialekter et rimpar fungerer i."""
    start = time.perf_counter()
    result = finn_rim_alle_dialekter(ord, maks=maks)
    elapsed = (time.perf_counter() - start) * 1000
    result["soketid_ms"] = round(elapsed, 1)
    return result


@app.get("/api/v1/synonymer/{ord}", summary="Finn synonymer")
def api_synonymer(
    ord: str,
    maks: int = Query(50, ge=1, le=1000),
):
    start = time.perf_counter()
    results = finn_synonymer(ord, maks=_clamp_maks(maks))
    elapsed = (time.perf_counter() - start) * 1000
    return _wrap(ord, results, elapsed)


@app.get("/api/v1/relaterte/{ord}", summary="Finn relaterte ord (hypernymer, hyponymer)")
def api_relaterte(
    ord: str,
    maks: int = Query(50, ge=1, le=1000),
):
    start = time.perf_counter()
    results = finn_relaterte(ord, maks=_clamp_maks(maks))
    elapsed = (time.perf_counter() - start) * 1000
    return _wrap(ord, results, elapsed)


@app.get("/api/v1/konsonanter/{ord}", summary="Finn konsonantmatching")
def api_konsonanter(
    ord: str,
    maks: int = Query(100, ge=1, le=1000),
):
    start = time.perf_counter()
    results = match_konsonanter(ord, maks=_clamp_maks(maks))
    elapsed = (time.perf_counter() - start) * 1000
    return _wrap(ord, results, elapsed)


@app.get("/api/v1/info/{ord}", summary="All informasjon om et ord")
def api_info(
    ord: str,
    dialekt: str = Query("øst", description="Dialektregion"),
):
    """Returnerer fonetikk, rim, synonymer og relaterte ord for et ord."""
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()

    # Fonetisk info (leksikon eller G2P)
    info = slaa_opp(ord, dialekt=dialekt)

    # Fonetikk fra leksikon (kan ha flere POS)
    lex_entries = hent_fonetikk(ord)
    if not lex_entries and ord != ord.lower():
        lex_entries = hent_fonetikk(ord.lower())

    # Rim (topp 10, with variant info)
    rim_result = finn_perfekte_rim(ord, maks=10, dialekt=dialekt, grupper=False)

    # Synonymer (topp 10)
    synonymer = finn_synonymer(ord, maks=10)

    # Definisjon fra Bokmålsordboka (cached, non-blocking)
    defn = hent_definisjon(ord)

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "ord": ord,
        "dialekt": dialekt,
        "fonetikk": info,
        "definisjon": defn.get("definisjon"),
        "ordklasse": defn.get("ordklasse"),
        "leksikon": [dict(e) for e in lex_entries] if lex_entries else [],
        "rim": rim_result.get("resultater", []),
        "varianter": rim_result.get("varianter", []),
        "synonymer": synonymer,
        "soketid_ms": round(elapsed, 1),
    }


# --- Rimklynger ---


def _klynge_response(modus: str, klynger: list[dict], elapsed: float, filters: dict) -> dict:
    return {
        "modus": modus,
        "klynger": klynger,
        "antall": len(klynger),
        "filter": filters,
        "soketid_ms": round(elapsed, 1),
    }


@app.get("/api/v1/rimklynger/par", summary="Rimklynger: par-modus (2 ord)")
def api_rimklynger_par(
    antall: int = Query(10, ge=1, le=50, description="Antall rimpar"),
    stavelser: Optional[int] = Query(None, description="Filtrer på antall stavelser"),
    min_frekvens: float = Query(1.0, ge=0.0, description="Minimum ordfrekvens per million"),
    dialekt: str = Query("øst", description="Dialektregion"),
    ord: Optional[str] = Query(None, description="Startord — bruk dette ordets rimfamilie"),
    rimtype: str = Query("begge", description="helrim, halvrim eller begge"),
    terskel: float = Query(0.75, ge=0.0, le=1.0, description="Terskel for halvrim"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()
    klynger = generer_rimklynger(
        modus="par", antall=antall, stavelser=stavelser,
        min_frekvens=min_frekvens, dialekt=dialekt, ord=ord,
        rimtype=rimtype, terskel=terskel,
    )
    elapsed = (time.perf_counter() - start) * 1000
    return _klynge_response("par", klynger, elapsed, {
        "stavelser": stavelser, "min_frekvens": min_frekvens,
        "dialekt": dialekt, "ord": ord, "rimtype": rimtype,
    })


@app.get("/api/v1/rimklynger/bred", summary="Rimklynger: bred-modus (4 ord)")
def api_rimklynger_bred(
    antall: int = Query(10, ge=1, le=50, description="Antall klynger"),
    stavelser: Optional[int] = Query(None, description="Filtrer på antall stavelser"),
    min_frekvens: float = Query(1.0, ge=0.0, description="Minimum ordfrekvens per million"),
    dialekt: str = Query("øst", description="Dialektregion"),
    ord: Optional[str] = Query(None, description="Startord — bruk dette ordets rimfamilie"),
    rimtype: str = Query("begge", description="helrim, halvrim eller begge"),
    terskel: float = Query(0.75, ge=0.0, le=1.0, description="Terskel for halvrim"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()
    klynger = generer_rimklynger(
        modus="bred", antall=antall, stavelser=stavelser,
        min_frekvens=min_frekvens, dialekt=dialekt, ord=ord,
        rimtype=rimtype, terskel=terskel,
    )
    elapsed = (time.perf_counter() - start) * 1000
    return _klynge_response("bred", klynger, elapsed, {
        "stavelser": stavelser, "min_frekvens": min_frekvens,
        "dialekt": dialekt, "ord": ord, "rimtype": rimtype,
    })


@app.get("/api/v1/rimklynger/dyp", summary="Rimklynger: dyp-modus (alle ord)")
def api_rimklynger_dyp(
    ord: Optional[str] = Query(None, description="Startord (tilfeldig rimfamilie hvis utelatt)"),
    stavelser: Optional[int] = Query(None, description="Filtrer på antall stavelser"),
    min_frekvens: float = Query(1.0, ge=0.0, description="Minimum ordfrekvens per million"),
    maks: int = Query(0, ge=0, le=1000, description="Maks antall ord (0 = alle)"),
    dialekt: str = Query("øst", description="Dialektregion"),
    rimtype: str = Query("begge", description="helrim, halvrim eller begge"),
    terskel: float = Query(0.75, ge=0.0, le=1.0, description="Terskel for halvrim"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()
    klynger = generer_rimklynger(
        modus="dyp", stavelser=stavelser,
        min_frekvens=min_frekvens, dialekt=dialekt, ord=ord,
        rimtype=rimtype, terskel=terskel,
    )
    # Truncate if maks is set
    if maks > 0 and klynger and len(klynger[0]["ord"]) > maks:
        klynger[0]["ord"] = klynger[0]["ord"][:maks]
    elapsed = (time.perf_counter() - start) * 1000
    return _klynge_response("dyp", klynger, elapsed, {
        "stavelser": stavelser, "min_frekvens": min_frekvens,
        "dialekt": dialekt, "ord": ord, "rimtype": rimtype,
    })


@app.get("/api/v1/rimklynger/sti", summary="Rimklynger: sti-modus (rimstier via konsonant-drift)")
def api_rimklynger_sti(
    ord: Optional[str] = Query(None, description="Startord (tilfeldige hvis utelatt)"),
    antall_stier: int = Query(3, ge=1, le=20, description="Antall rimstier å generere"),
    maks_steg: int = Query(8, ge=3, le=30, description="Maks steg per sti"),
    min_familiestr: int = Query(3, ge=1, le=100, description="Minimum ord per rimfamilie"),
    min_frekvens: float = Query(1.0, ge=0.0, description="Minimum ordfrekvens per million"),
    dialekt: str = Query("øst", description="Dialektregion: øst, nord, midt, vest, sørvest"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()
    stier = generer_rimstier(
        antall_stier=antall_stier, maks_steg=maks_steg,
        min_familiestr=min_familiestr, min_frekvens=min_frekvens,
        dialekt=dialekt, ord=ord,
    )
    elapsed = (time.perf_counter() - start) * 1000
    return {
        "modus": "sti",
        "stier": stier,
        "antall_stier": len(stier),
        "filter": {
            "maks_steg": maks_steg, "min_familiestr": min_familiestr,
            "min_frekvens": min_frekvens, "dialekt": dialekt, "ord": ord,
        },
        "soketid_ms": round(elapsed, 1),
    }


# --- Arsenal & Rimer ---


@app.get("/api/v1/arsenal/{ord}", summary="Kreativt arsenal — rim, halvrim, synonymer med rim")
def api_arsenal(
    ord: str,
    maks_rim: int = Query(15, ge=1, le=100),
    maks_halvrim: int = Query(10, ge=1, le=100),
    maks_synonymer: int = Query(10, ge=1, le=50),
    maks_synonymrim: int = Query(5, ge=1, le=20),
    dialekt: str = Query("øst", description="Dialektregion"),
    variant: Optional[str] = Query(None, description="Rimsuffiks for disambiguering"),
):
    """Alt kreativt materiale for ett ord i ett kall.

    Returnerer rim, halvrim, synonymer, og rim for hvert synonym.
    Erstatter 10-15 separate API-kall i kreativ skriving.
    """
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()

    info = slaa_opp(ord, dialekt=dialekt, rimsuffiks_override=variant)
    rim_result = finn_perfekte_rim(ord, maks=maks_rim, dialekt=dialekt, grupper=False, rimsuffiks=variant)
    rim = rim_result.get("resultater", [])
    halvrim_result = finn_halvrim(ord, maks=maks_halvrim, terskel=0.7, dialekt=dialekt, rimsuffiks=variant)
    halvrim_liste = halvrim_result.get("resultater", [])
    syns = finn_synonymer(ord, maks=maks_synonymer)
    defn = hent_definisjon(ord)

    # Rim for hvert synonym
    syn_med_rim = []
    for s in syns:
        s_rim_result = finn_perfekte_rim(s["ord"], maks=maks_synonymrim, dialekt=dialekt, grupper=False)
        s_rim = s_rim_result.get("resultater", [])
        syn_med_rim.append({
            "ord": s["ord"],
            "rim": [r["ord"] for r in s_rim],
        })

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "ord": ord,
        "info": {
            "ipa": info.get("ipa_ren"),
            "stavelser": info.get("stavelser"),
            "tonelag": info.get("tonelag"),
            "rimsuffiks": info.get("rimsuffiks"),
            "definisjon": defn.get("definisjon"),
            "ordklasse": defn.get("ordklasse"),
        },
        "varianter": rim_result.get("varianter", []),
        "rim": [r["ord"] for r in rim],
        "halvrim": [{"ord": r["ord"], "score": r["score"]} for r in halvrim_liste],
        "synonymer": syn_med_rim,
        "dialekt": dialekt,
        "soketid_ms": round(elapsed, 1),
    }


@app.get("/api/v1/rimer/{ord1}/{ord2}", summary="Sjekk om to ord rimer")
def api_rimer(
    ord1: str,
    ord2: str,
    dialekt: str = Query("øst", description="Dialektregion"),
):
    """Sammenlign to ord og si om de rimer.

    Bruker de samme motorene som /rim/ og /halvrim/ — sjekker om ord2
    dukker opp i helrim- eller halvrim-resultatene for ord1.
    """
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()

    info1 = slaa_opp(ord1, dialekt=dialekt)
    info2 = slaa_opp(ord2, dialekt=dialekt)

    s1 = info1.get("rimsuffiks") or ""
    s2 = info2.get("rimsuffiks") or ""
    t1 = info1.get("tonelag")
    t2 = info2.get("tonelag")
    samme_tonelag = t1 is not None and t1 == t2
    ord2_lower = ord2.lower()

    # Sjekk helrim via motoren
    rim_result = finn_perfekte_rim(ord1, maks=1000, dialekt=dialekt, grupper=False)
    er_helrim = any(
        r.get("ord", "").lower() == ord2_lower
        for r in rim_result.get("resultater", [])
    )

    # Sjekk halvrim via motoren
    er_halvrim = False
    halvrim_score = 0.0
    if not er_helrim:
        halvrim_result = finn_halvrim(ord1, maks=1000, terskel=0.5, dialekt=dialekt)
        for r in halvrim_result.get("resultater", []):
            if r.get("ord", "").lower() == ord2_lower:
                er_halvrim = True
                halvrim_score = r.get("score", 0.0)
                break

    # Resultat
    if er_helrim:
        score = 1.0
        forklaring = f"Helrim — identisk rimsuffiks /{s1}/"
        if samme_tonelag:
            forklaring += f", begge tonelag {t1}"
    elif er_halvrim:
        score = halvrim_score
        forklaring = f"Halvrim (score {score:.2f}): /{s1}/ vs /{s2}/"
    else:
        score = 0.0
        forklaring = f"Rimer ikke: /{s1}/ vs /{s2}/"

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "ord1": {"ord": ord1, "ipa": info1.get("ipa_ren"), "rimsuffiks": s1, "tonelag": t1},
        "ord2": {"ord": ord2, "ipa": info2.get("ipa_ren"), "rimsuffiks": s2, "tonelag": t2},
        "resultat": {
            "perfekt_rim": er_helrim,
            "halvrim": er_halvrim,
            "score": round(score, 2),
            "samme_tonelag": samme_tonelag,
            "forklaring": forklaring,
        },
        "dialekt": dialekt,
        "soketid_ms": round(elapsed, 1),
    }


# --- Batch ---


@app.post("/api/v1/batch", summary="Batch-oppslag for flere ord")
def api_batch(
    ord: list[str] = Body(..., min_length=1, max_length=50, description="Liste med ord"),
    operasjoner: list[str] = Body(
        ["rim"], description="Operasjoner: rim, halvrim, synonymer, info, arsenal, rimer"
    ),
    maks: int = Body(10, ge=1, le=100, description="Maks resultater per ord"),
    dialekt: str = Body("øst", description="Dialektregion"),
):
    """Kjør operasjoner på flere ord i ett kall.

    Eksempel: {"ord": ["sol", "natt"], "operasjoner": ["rim", "info"], "maks": 5}
    """
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })

    start = time.perf_counter()
    resultater = {}

    for word in ord:
        entry = {}

        if "info" in operasjoner:
            info = slaa_opp(word, dialekt=dialekt)
            defn = hent_definisjon(word)
            entry["info"] = {
                "ipa": info.get("ipa_ren"),
                "stavelser": info.get("stavelser"),
                "tonelag": info.get("tonelag"),
                "rimsuffiks": info.get("rimsuffiks"),
                "g2p": info.get("g2p"),
                "definisjon": defn.get("definisjon"),
                "ordklasse": defn.get("ordklasse"),
            }

        if "rim" in operasjoner:
            rim_result = finn_perfekte_rim(word, maks=maks, dialekt=dialekt, grupper=False)
            entry["rim"] = [r["ord"] for r in rim_result.get("resultater", [])]

        if "halvrim" in operasjoner:
            halvrim_res = finn_halvrim(word, maks=maks, terskel=0.7, dialekt=dialekt)
            halvrim_items = halvrim_res.get("resultater", [])
            entry["halvrim"] = [{"ord": r["ord"], "score": r["score"]} for r in halvrim_items]

        if "synonymer" in operasjoner:
            syns = finn_synonymer(word, maks=maks)
            entry["synonymer"] = [s["ord"] for s in syns]

        if "arsenal" in operasjoner:
            info = slaa_opp(word, dialekt=dialekt)
            rim_result = finn_perfekte_rim(word, maks=maks, dialekt=dialekt, grupper=False)
            rim = rim_result.get("resultater", [])
            halvrim_res2 = finn_halvrim(word, maks=min(maks, 10), terskel=0.7, dialekt=dialekt)
            halvrim_liste2 = halvrim_res2.get("resultater", [])
            syns = finn_synonymer(word, maks=min(maks, 10))
            syn_rim = []
            for s in syns:
                sr_result = finn_perfekte_rim(s["ord"], maks=5, dialekt=dialekt, grupper=False)
                sr = sr_result.get("resultater", [])
                syn_rim.append({"ord": s["ord"], "rim": [r["ord"] for r in sr]})
            entry["arsenal"] = {
                "rim": [r["ord"] for r in rim],
                "halvrim": [{"ord": r["ord"], "score": r["score"]} for r in halvrim_liste2],
                "synonymer": syn_rim,
            }

        resultater[word] = entry

    # Handle "rimer" operation: check all pairs via motorene
    if "rimer" in operasjoner and len(ord) >= 2:
        # Forhåndshent rim og halvrim for alle ord
        rim_cache = {}
        halvrim_cache = {}
        for w in ord:
            rim_res = finn_perfekte_rim(w, maks=1000, dialekt=dialekt, grupper=False)
            rim_cache[w] = {r["ord"].lower() for r in rim_res.get("resultater", [])}
            halvrim_res = finn_halvrim(w, maks=1000, terskel=0.5, dialekt=dialekt)
            halvrim_cache[w] = {
                r["ord"].lower(): r.get("score", 0.0)
                for r in halvrim_res.get("resultater", [])
            }

        par = []
        for i in range(len(ord)):
            for j in range(i + 1, len(ord)):
                w1, w2 = ord[i], ord[j]
                w2_lower = w2.lower()
                er_helrim = w2_lower in rim_cache.get(w1, set())
                er_halvrim = False
                score = 0.0
                if er_helrim:
                    score = 1.0
                elif w2_lower in halvrim_cache.get(w1, {}):
                    er_halvrim = True
                    score = halvrim_cache[w1][w2_lower]
                par.append({
                    "ord1": w1, "ord2": w2,
                    "perfekt_rim": er_helrim,
                    "halvrim": er_halvrim,
                    "score": round(score, 2),
                })
        resultater["_rimpar"] = par

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "ord": ord,
        "operasjoner": operasjoner,
        "resultater": resultater,
        "dialekt": dialekt,
        "soketid_ms": round(elapsed, 1),
    }


# --- Akustisk (acoustic similarity) ---


@app.get("/api/v1/akustisk/sammenlign/{ord1}/{ord2}", summary="Sammenlign to ord akustisk")
def api_akustisk_sammenlign(ord1: str, ord2: str):
    """Beregn akustisk likhet (SSIM) mellom to ord."""
    if not _akustisk_ready:
        return JSONResponse(status_code=503, content={
            "feil": "Akustisk motor laster inn. Prøv igjen om 30 sekunder.",
        })
    start = time.perf_counter()
    try:
        from rimordbok.akustisk import make_spectrogram, compare
        wi1 = _akustisk_lex._w2i.get(ord1) or _akustisk_lex._w2i.get(ord1.lower())
        wi2 = _akustisk_lex._w2i.get(ord2) or _akustisk_lex._w2i.get(ord2.lower())
        if wi1 is None:
            return JSONResponse(status_code=404, content={
                "feil": f"Ordet «{ord1}» finnes ikke i det akustiske leksikonet.",
            })
        if wi2 is None:
            return JSONResponse(status_code=404, content={
                "feil": f"Ordet «{ord2}» finnes ikke i det akustiske leksikonet.",
            })
        spec1 = make_spectrogram(_akustisk_lex.segments[wi1])
        spec2 = make_spectrogram(_akustisk_lex.segments[wi2])
        score = compare(spec1, spec2)
    except Exception as e:
        return JSONResponse(status_code=500, content={"feil": str(e)})
    elapsed = (time.perf_counter() - start) * 1000
    return {
        "ord1": {"ord": ord1, "ipa": _akustisk_lex.ipa[wi1]},
        "ord2": {"ord": ord2, "ipa": _akustisk_lex.ipa[wi2]},
        "score": round(float(score), 4),
        "soketid_ms": round(elapsed, 1),
    }


@app.get("/api/v1/akustisk/{ord}", summary="Finn akustiske naboer")
def api_akustisk(
    ord: str,
    antall: int = Query(20, ge=1, le=100, description="Antall resultater"),
    kandidater: int = Query(500, ge=50, le=5000, description="Kandidatpool-størrelse"),
):
    """Finn ord som høres akustisk like ut basert på syntetiske spektrogrammer og SSIM."""
    if not _akustisk_ready:
        return JSONResponse(status_code=503, content={
            "feil": "Akustisk motor laster inn. Prøv igjen om 30 sekunder.",
        })
    start = time.perf_counter()
    try:
        results = _akustisk_lex.finn_like(ord, n=antall, kandidater=kandidater)
    except KeyError:
        return JSONResponse(status_code=404, content={
            "feil": f"Ordet «{ord}» finnes ikke i det akustiske leksikonet.",
        })
    elapsed = (time.perf_counter() - start) * 1000
    wi = _akustisk_lex._w2i.get(ord) or _akustisk_lex._w2i.get(ord.lower())
    return {
        "ord": ord,
        "ipa": _akustisk_lex.ipa[wi] if wi is not None else None,
        "resultater": [{"ord": w, "score": round(s, 4)} for w, s in results],
        "antall": len(results),
        "soketid_ms": round(elapsed, 1),
        "kandidater": kandidater,
    }


@app.get("/api/v1/sok", summary="Autocomplete / ordsøk")
def api_sok(
    q: str = Query(..., min_length=1, description="Søkeprefix"),
    maks: int = Query(20, ge=1, le=100),
):
    start = time.perf_counter()
    results = sok_ord(q, maks=_clamp_maks(maks))
    elapsed = (time.perf_counter() - start) * 1000
    return {
        "prefiks": q,
        "resultater": results,
        "antall": len(results),
        "soketid_ms": round(elapsed, 1),
    }


@app.get("/api/v1/tilfeldig", summary="Tilfeldig ord")
def api_tilfeldig():
    """Hent et tilfeldig vanlig norsk ord (frekvens > 5 per million, 3-10 bokstaver, uten bindestrek)."""
    start = time.perf_counter()
    from rimordbok.db import _connect
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT LOWER(ord) as ord FROM ord "
            "WHERE frekvens > 5 AND length(ord) BETWEEN 3 AND 10 "
            "AND ord NOT LIKE '%-%' AND ord NOT LIKE '% %' "
            "ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        word = row["ord"] if row else "sol"
    finally:
        conn.close()
    elapsed = (time.perf_counter() - start) * 1000
    return {"ord": word, "soketid_ms": round(elapsed, 1)}


# --- Sitemap ---

_sitemap_cache = {"xml": None, "ts": 0}


@app.get("/api/v1/sitemap.xml", summary="XML Sitemap", include_in_schema=False)
def api_sitemap():
    """Generate sitemap with top 5000 words by frequency."""
    import time as _time

    # Cache for 24 hours
    now = _time.time()
    if _sitemap_cache["xml"] and now - _sitemap_cache["ts"] < 86400:
        from fastapi.responses import Response
        return Response(content=_sitemap_cache["xml"], media_type="application/xml")

    from rimordbok.db import _connect
    conn = _connect()
    cur = conn.execute(
        "SELECT LOWER(ord) as ord FROM ord "
        "WHERE frekvens > 1 AND length(ord) BETWEEN 2 AND 20 "
        "AND ord NOT LIKE '%-%' AND ord NOT LIKE '% %' "
        "GROUP BY LOWER(ord) ORDER BY MAX(frekvens) DESC LIMIT 5000"
    )
    words = [row["ord"] for row in cur]

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    lines.append('  <url><loc>https://www.rimregisteret.no/</loc><priority>1.0</priority></url>')
    lines.append('  <url><loc>https://www.rimregisteret.no/api</loc><priority>0.8</priority></url>')
    for w in words:
        from urllib.parse import quote
        lines.append(f'  <url><loc>https://www.rimregisteret.no/{quote(w)}</loc></url>')
    lines.append('</urlset>')

    xml = "\n".join(lines)
    _sitemap_cache["xml"] = xml
    _sitemap_cache["ts"] = now

    from fastapi.responses import Response
    return Response(content=xml, media_type="application/xml")


import pathlib as _pathlib

_FRONTEND_DIR = _pathlib.Path(__file__).resolve().parent.parent / "frontend"
_INDEX_HTML = _FRONTEND_DIR / "index.html"


@app.get("/", summary="Frontend", include_in_schema=False)
def root():
    if _INDEX_HTML.exists():
        return FileResponse(_INDEX_HTML)
    return {
        "navn": "Rimregisteret API",
        "versjon": "0.1.0",
        "dokumentasjon": "/docs",
    }


# Catch-all: serve index.html for client-side routing (e.g. /sol, /hjerte)
@app.get("/{word}", include_in_schema=False)
def frontend_catchall(word: str):
    # Don't catch API or docs routes
    if word.startswith("api") or word in ("docs", "openapi.json", "redoc"):
        return JSONResponse(status_code=404, content={"feil": "Ikke funnet"})
    if _INDEX_HTML.exists():
        return FileResponse(_INDEX_HTML)
    return JSONResponse(status_code=404, content={"feil": "Frontend ikke funnet"})
