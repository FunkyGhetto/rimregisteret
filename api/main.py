from __future__ import annotations

"""REST API for Rimregisteret — norsk rimordbok med fonetikk og semantikk.

Start med:
    uvicorn api.main:app --reload

Swagger-dokumentasjon: http://localhost:8000/docs
"""

import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
    finn_rimsti,
    _score_near_rhyme,
)
from rimordbok.semantics import (
    finn_synonymer,
    finn_antonymer,
    finn_relaterte,
)
from rimordbok.definitions import hent_definisjon
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
    maks: int = Query(0, ge=0, le=1000, description="Maks antall ord (0 = alle)"),
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
    # Truncate if maks is set
    if maks > 0 and klynger and len(klynger[0]["ord"]) > maks:
        klynger[0]["ord"] = klynger[0]["ord"][:maks]
    elapsed = (time.perf_counter() - start) * 1000
    return _klynge_response("dyp", klynger, elapsed, {
        "stavelser": stavelser, "min_frekvens": min_frekvens,
        "dialekt": dialekt, "ord": ord,
    })


# --- Rimsti ---


@app.get("/api/v1/rimsti/{ord}", summary="Finn rimsti — rimfamilier med samme konsonantskjelett")
def api_rimsti(
    ord: str,
    maks_steg: int = Query(20, ge=1, le=50, description="Maks antall rimfamilier"),
    min_familiestr: int = Query(3, ge=1, le=100, description="Minimum ord i en rimfamilie"),
    min_frekvens: float = Query(1.0, ge=0.0, description="Minimum ordfrekvens per million"),
    dialekt: str = Query("øst", description="Dialektregion: øst, nord, midt, vest, sørvest"),
):
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()
    result = finn_rimsti(
        ord, maks_steg=maks_steg, min_familiestr=min_familiestr,
        min_frekvens=min_frekvens, dialekt=dialekt,
    )
    elapsed = (time.perf_counter() - start) * 1000
    result["soketid_ms"] = round(elapsed, 1)
    return result


# --- Arsenal & Rimer ---


@app.get("/api/v1/arsenal/{ord}", summary="Kreativt arsenal — rim, nesten-rim, synonymer med rim")
def api_arsenal(
    ord: str,
    maks_rim: int = Query(15, ge=1, le=100),
    maks_nesten: int = Query(10, ge=1, le=100),
    maks_synonymer: int = Query(10, ge=1, le=50),
    maks_synonymrim: int = Query(5, ge=1, le=20),
    dialekt: str = Query("øst", description="Dialektregion"),
):
    """Alt kreativt materiale for ett ord i ett kall.

    Returnerer rim, nesten-rim, synonymer, og rim for hvert synonym.
    Erstatter 10-15 separate API-kall i kreativ skriving.
    """
    if dialekt not in GYLDIGE_DIALEKTER:
        return JSONResponse(status_code=400, content={
            "feil": f"Ugyldig dialekt: {dialekt}",
            "gyldige": sorted(GYLDIGE_DIALEKTER),
        })
    start = time.perf_counter()

    info = slaa_opp(ord, dialekt=dialekt)
    rim = finn_perfekte_rim(ord, maks=maks_rim, dialekt=dialekt)
    nesten = finn_nesten_rim(ord, maks=maks_nesten, terskel=0.7, dialekt=dialekt)
    syns = finn_synonymer(ord, maks=maks_synonymer)
    defn = hent_definisjon(ord)

    # Rim for hvert synonym
    syn_med_rim = []
    for s in syns:
        s_rim = finn_perfekte_rim(s["ord"], maks=maks_synonymrim, dialekt=dialekt)
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
        "rim": [r["ord"] for r in rim],
        "nesten_rim": [{"ord": r["ord"], "score": r["score"]} for r in nesten],
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
    """Sammenlign to ord og si om de rimer, med fonetisk begrunnelse."""
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

    perfekt = s1 == s2 and s1 != ""
    score = 1.0 if perfekt else (_score_near_rhyme(s1, s2) if s1 and s2 else 0.0)
    nesten = not perfekt and score >= 0.5
    samme_tonelag = t1 is not None and t1 == t2

    # Generer forklaring
    if perfekt:
        forklaring = f"Identisk rimsuffiks /{s1}/"
        if samme_tonelag:
            forklaring += f", begge tonelag {t1}"
    elif nesten:
        # Finn hva som er forskjellig
        if s1.replace("\u02D0", "") == s2.replace("\u02D0", ""):
            forklaring = f"Nesten-rim: vokallengde-forskjell /{s1}/ vs /{s2}/"
        else:
            forklaring = f"Nesten-rim (score {score:.1f}): /{s1}/ vs /{s2}/"
    else:
        forklaring = f"Rimer ikke: /{s1}/ vs /{s2}/"

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "ord1": {"ord": ord1, "ipa": info1.get("ipa_ren"), "rimsuffiks": s1, "tonelag": t1},
        "ord2": {"ord": ord2, "ipa": info2.get("ipa_ren"), "rimsuffiks": s2, "tonelag": t2},
        "resultat": {
            "perfekt_rim": perfekt,
            "nesten_rim": nesten,
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
        ["rim"], description="Operasjoner: rim, nestenrim, synonymer, antonymer, info, arsenal, rimer"
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
            rim = finn_perfekte_rim(word, maks=maks, dialekt=dialekt)
            entry["rim"] = [r["ord"] for r in rim]

        if "nestenrim" in operasjoner:
            nesten = finn_nesten_rim(word, maks=maks, terskel=0.7, dialekt=dialekt)
            entry["nestenrim"] = [{"ord": r["ord"], "score": r["score"]} for r in nesten]

        if "synonymer" in operasjoner:
            syns = finn_synonymer(word, maks=maks)
            entry["synonymer"] = [s["ord"] for s in syns]

        if "antonymer" in operasjoner:
            ants = finn_antonymer(word, maks=maks)
            entry["antonymer"] = [a["ord"] for a in ants]

        if "arsenal" in operasjoner:
            info = slaa_opp(word, dialekt=dialekt)
            rim = finn_perfekte_rim(word, maks=maks, dialekt=dialekt)
            nesten = finn_nesten_rim(word, maks=min(maks, 10), terskel=0.7, dialekt=dialekt)
            syns = finn_synonymer(word, maks=min(maks, 10))
            syn_rim = []
            for s in syns:
                sr = finn_perfekte_rim(s["ord"], maks=5, dialekt=dialekt)
                syn_rim.append({"ord": s["ord"], "rim": [r["ord"] for r in sr]})
            entry["arsenal"] = {
                "rim": [r["ord"] for r in rim],
                "nestenrim": [{"ord": r["ord"], "score": r["score"]} for r in nesten],
                "synonymer": syn_rim,
            }

        resultater[word] = entry

    # Handle "rimer" operation: check all pairs
    if "rimer" in operasjoner and len(ord) >= 2:
        par = []
        for i in range(len(ord)):
            for j in range(i + 1, len(ord)):
                info1 = slaa_opp(ord[i], dialekt=dialekt)
                info2 = slaa_opp(ord[j], dialekt=dialekt)
                s1 = info1.get("rimsuffiks") or ""
                s2 = info2.get("rimsuffiks") or ""
                perfekt = s1 == s2 and s1 != ""
                score = 1.0 if perfekt else (_score_near_rhyme(s1, s2) if s1 and s2 else 0.0)
                par.append({
                    "ord1": ord[i], "ord2": ord[j],
                    "perfekt_rim": perfekt,
                    "nesten_rim": not perfekt and score >= 0.5,
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
