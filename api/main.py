from __future__ import annotations

"""REST API for Rimregisteret — norsk rimordbok med fonetikk og semantikk.

Start med:
    uvicorn api.main:app --reload

Swagger-dokumentasjon: http://localhost:8000/docs
"""

import logging
import time
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rimordbok.db import hent_fonetikk, sok_ord, GYLDIGE_DIALEKTER
from rimordbok.phonetics import slaa_opp
from rimordbok.rhyme import (
    finn_perfekte_rim,
    finn_nesten_rim,
    finn_homofoner,
    match_konsonanter,
    finn_rim_alle_dialekter,
)
from rimordbok.semantics import (
    finn_synonymer,
    finn_antonymer,
    finn_relaterte,
)
from rimordbok.clusters import generer_rimklynger

# Dialect enum for API validation
DIALEKT_ENUM = list(GYLDIGE_DIALEKTER)

logger = logging.getLogger("rimordbok.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(
    title="Rimregisteret API",
    description="Rimregisteret — norsk rimordbok med fonetikk, semantikk og ordfrekvens.",
    version="0.1.0",
)

# CORS — tillat alle opphav for frontend-utvikling
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


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


def _clamp_maks(maks: int) -> int:
    return max(1, min(maks, 1000))


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


@app.get("/api/v1/rim/{ord}", summary="Finn perfekte rim")
def api_rim(
    ord: str,
    maks: int = Query(100, ge=1, le=1000, description="Maks antall resultater"),
    stavelser: Optional[int] = Query(None, description="Filtrer på antall stavelser"),
    tonelag: Optional[int] = Query(None, description="Filtrer på tonelag (1 eller 2)"),
    samme_tonelag: bool = Query(False, description="Kun rim med samme tonelag"),
    dialekt: str = Query("øst", description="Dialektregion: øst, nord, midt, vest, sørvest"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()
    results = finn_perfekte_rim(ord, maks=_clamp_maks(maks), samme_tonelag=samme_tonelag, dialekt=dialekt)
    results = _filter_results(results, stavelser, tonelag)
    elapsed = (time.perf_counter() - start) * 1000
    resp = _wrap(ord, results, elapsed)
    resp["dialekt"] = dialekt
    return resp


@app.get("/api/v1/nestenrim/{ord}", summary="Finn nesten-rim")
def api_nestenrim(
    ord: str,
    maks: int = Query(100, ge=1, le=1000),
    terskel: float = Query(0.5, ge=0.0, le=1.0, description="Minimum likhetsscore"),
    stavelser: Optional[int] = Query(None),
    tonelag: Optional[int] = Query(None),
    dialekt: str = Query("øst", description="Dialektregion: øst, nord, midt, vest, sørvest"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()
    results = finn_nesten_rim(ord, maks=_clamp_maks(maks), terskel=terskel, dialekt=dialekt)
    results = _filter_results(results, stavelser, tonelag)
    elapsed = (time.perf_counter() - start) * 1000
    resp = _wrap(ord, results, elapsed)
    resp["dialekt"] = dialekt
    return resp


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


@app.get("/api/v1/antonymer/{ord}", summary="Finn antonymer")
def api_antonymer(
    ord: str,
    maks: int = Query(50, ge=1, le=1000),
):
    start = time.perf_counter()
    results = finn_antonymer(ord, maks=_clamp_maks(maks))
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


@app.get("/api/v1/homofoner/{ord}", summary="Finn homofoner")
def api_homofoner(ord: str):
    start = time.perf_counter()
    results = finn_homofoner(ord)
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

    # Rim (topp 10)
    rim = finn_perfekte_rim(ord, maks=10, dialekt=dialekt)

    # Synonymer (topp 10)
    synonymer = finn_synonymer(ord, maks=10)

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "ord": ord,
        "dialekt": dialekt,
        "fonetikk": info,
        "leksikon": [dict(e) for e in lex_entries] if lex_entries else [],
        "rim": rim,
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
    )
    elapsed = (time.perf_counter() - start) * 1000
    return _klynge_response("par", klynger, elapsed, {
        "stavelser": stavelser, "min_frekvens": min_frekvens,
        "dialekt": dialekt, "ord": ord,
    })


@app.get("/api/v1/rimklynger/bred", summary="Rimklynger: bred-modus (4 ord)")
def api_rimklynger_bred(
    antall: int = Query(10, ge=1, le=50, description="Antall klynger"),
    stavelser: Optional[int] = Query(None, description="Filtrer på antall stavelser"),
    min_frekvens: float = Query(1.0, ge=0.0, description="Minimum ordfrekvens per million"),
    dialekt: str = Query("øst", description="Dialektregion"),
    ord: Optional[str] = Query(None, description="Startord — bruk dette ordets rimfamilie"),
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
    )
    elapsed = (time.perf_counter() - start) * 1000
    return _klynge_response("bred", klynger, elapsed, {
        "stavelser": stavelser, "min_frekvens": min_frekvens,
        "dialekt": dialekt, "ord": ord,
    })


@app.get("/api/v1/rimklynger/dyp", summary="Rimklynger: dyp-modus (alle ord)")
def api_rimklynger_dyp(
    ord: Optional[str] = Query(None, description="Startord (tilfeldig rimfamilie hvis utelatt)"),
    stavelser: Optional[int] = Query(None, description="Filtrer på antall stavelser"),
    min_frekvens: float = Query(1.0, ge=0.0, description="Minimum ordfrekvens per million"),
    dialekt: str = Query("øst", description="Dialektregion"),
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
    )
    elapsed = (time.perf_counter() - start) * 1000
    return _klynge_response("dyp", klynger, elapsed, {
        "stavelser": stavelser, "min_frekvens": min_frekvens,
        "dialekt": dialekt, "ord": ord,
    })


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
