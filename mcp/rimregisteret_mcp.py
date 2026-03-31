#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp[cli]>=1.0.0",
#     "httpx>=0.27.0",
# ]
# ///
"""Rimregisteret MCP Server — norsk rim-verktøy for LLM-er.

Gir Claude og andre LLM-er tilgang til:
- Perfekte rim og nesten-rim
- Synonymer og antonymer
- Fonetisk informasjon (IPA, tonelag, stavelser)
- Rimklynger for freestyle-trening
- Ordautocomplete

Kjør med:
    uv run mcp/rimregisteret_mcp.py

Eller installer i Claude Desktop:
    claude mcp add rimregisteret -- uv run mcp/rimregisteret_mcp.py
"""

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "rimregisteret",
    instructions=(
        "Rimregisteret er en norsk rimordbok med 684 000 ord. "
        "Bruk verktøyene AKTIVT — kall dem direkte når brukeren "
        "spør om rim, fonetikk, synonymer eller freestyle-trening. "
        "Ikke svar fra hukommelsen — slå opp. "
        "Bruk arsenal() for kreativt arbeid (rim + synonymer med rim i ett kall). "
        "Bruk batch() for flere ord samtidig. "
        "Bruk sjekk_rim() for å verifisere rimpar. "
        "Alle verktøy returnerer norsk tekst."
    ),
)

BASE_URL = "https://www.rimregisteret.no/api/v1"
_TIMEOUT = 10.0


async def _get(path: str, params: dict | None = None) -> dict:
    """Make a GET request to the Rimregisteret API."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{BASE_URL}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict) -> dict:
    """Make a POST request to the Rimregisteret API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{BASE_URL}{path}", json=body)
        r.raise_for_status()
        return r.json()


def _format_words(words: list[dict], key: str = "ord", show_score: bool = False) -> str:
    """Format a list of word dicts into readable text."""
    parts = []
    for w in words:
        s = w[key]
        if show_score and "score" in w and w["score"] < 1.0:
            s += f" ({w['score']:.1f})"
        parts.append(s)
    return ", ".join(parts)


@mcp.tool()
async def finn_rim(ord: str, maks: int = 20, dialekt: str = "øst") -> str:
    """Finn perfekte rim for et norsk ord.

    Returnerer ord som rimer perfekt (identisk rimsuffiks),
    sortert etter bruksfrekvens (vanligste først).

    Args:
        ord: Ordet å finne rim for (f.eks. "sol", "natt", "hjerte")
        maks: Maks antall resultater (default 20)
        dialekt: Dialektregion - øst, nord, midt, vest, sørvest (default øst)
    """
    try:
        data = await _get(f"/rim/{ord}", {"maks": maks, "dialekt": dialekt})
        items = data.get("resultater", [])
        if not items:
            # Fallback: near-rhymes with score >= 1.0 (e.g. vowel length difference)
            near = await _get(f"/nestenrim/{ord}", {"maks": maks, "terskel": 0.9, "dialekt": dialekt})
            near_items = [r for r in near.get("resultater", []) if r.get("score", 0) >= 1.0]
            if near_items:
                words = _format_words(near_items)
                return f"Rim for «{ord}» ({len(near_items)} treff): {words}"
            return f"Ingen rim funnet for «{ord}»."
        words = _format_words(items)
        return f"Rim for «{ord}» ({len(items)} treff): {words}"
    except Exception as e:
        return f"Feil ved oppslag av rim for «{ord}»: {e}"


@mcp.tool()
async def finn_nesten_rim(
    ord: str, maks: int = 20, terskel: float = 0.5, dialekt: str = "øst"
) -> str:
    """Finn nesten-rim (slant rhymes) for et norsk ord.

    Nesten-rim har lignende, men ikke identiske, rimsuffikser.
    Hvert ord får en likhetsscore fra 0 til 1.

    Args:
        ord: Ordet å finne nesten-rim for
        maks: Maks antall resultater (default 20)
        terskel: Minimum likhetsscore 0.0-1.0 (default 0.5)
        dialekt: Dialektregion (default øst)
    """
    try:
        data = await _get(
            f"/nestenrim/{ord}",
            {"maks": maks, "terskel": terskel, "dialekt": dialekt},
        )
        items = data.get("resultater", [])
        if not items:
            return f"Ingen nesten-rim funnet for «{ord}»."
        words = _format_words(items, show_score=True)
        return f"Nesten-rim for «{ord}» ({len(items)} treff): {words}"
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def finn_synonymer(ord: str, maks: int = 20) -> str:
    """Finn synonymer for et norsk ord (fra Norwegian WordNet).

    Args:
        ord: Ordet å finne synonymer for (f.eks. "glad", "stor", "gå")
        maks: Maks antall resultater (default 20)
    """
    try:
        data = await _get(f"/synonymer/{ord}", {"maks": maks})
        items = data.get("resultater", [])
        if not items:
            return f"Ingen synonymer funnet for «{ord}»."
        words = _format_words(items)
        return f"Synonymer for «{ord}» ({len(items)} treff): {words}"
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def finn_antonymer(ord: str, maks: int = 20) -> str:
    """Finn antonymer (motsetningsord) for et norsk ord.

    Args:
        ord: Ordet å finne antonymer for (f.eks. "glad", "stor", "billig")
        maks: Maks antall resultater (default 20)
    """
    try:
        data = await _get(f"/antonymer/{ord}", {"maks": maks})
        items = data.get("resultater", [])
        if not items:
            return f"Ingen antonymer funnet for «{ord}»."
        words = _format_words(items)
        return f"Antonymer for «{ord}» ({len(items)} treff): {words}"
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def ordinfo(ord: str, dialekt: str = "øst") -> str:
    """Hent all informasjon om et norsk ord.

    Returnerer IPA-transkripsjon, antall stavelser, tonelag,
    rimsuffiks, og om ordet er fra leksikon eller G2P-estimert.

    Args:
        ord: Ordet å slå opp (f.eks. "sol", "menneske", "kjærlighet")
        dialekt: Dialektregion (default øst)
    """
    try:
        data = await _get(f"/info/{ord}", {"dialekt": dialekt})
        f = data.get("fonetikk", {})
        if not f:
            return f"Ingen informasjon funnet for «{ord}»."

        lines = [f"Ordinfo for «{ord}»:"]

        defn = data.get("definisjon")
        if defn:
            lines.append(f"  Definisjon: {defn}")

        lines.append(f"  IPA: /{f.get('ipa_ren', '?')}/")
        lines.append(f"  Stavelser: {f.get('stavelser', '?')}")

        tonelag = f.get("tonelag")
        if tonelag:
            lines.append(f"  Tonelag: {tonelag}")

        suffiks = f.get("rimsuffiks")
        if suffiks:
            lines.append(f"  Rimsuffiks: /{suffiks}/")

        kilde = "G2P (estimert)" if f.get("g2p") else "Leksikon"
        lines.append(f"  Kilde: {kilde}")

        rim = data.get("rim", [])
        if rim:
            rim_words = ", ".join(r["ord"] for r in rim[:10])
            lines.append(f"  Rim: {rim_words}")

        syns = data.get("synonymer", [])
        if syns:
            syn_words = ", ".join(s["ord"] for s in syns[:10])
            lines.append(f"  Synonymer: {syn_words}")

        return "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def arsenal(ord: str, maks_rim: int = 15, maks_synonymer: int = 10, dialekt: str = "øst") -> str:
    """Hent hele det kreative arsenalet for et ord i ett kall.

    Returnerer rim, nesten-rim, synonymer, og rim for hvert synonym.
    Erstatter 10-15 separate kall ved kreativ skriving.

    Args:
        ord: Ordet å bygge arsenal for (f.eks. "krone", "hjerte")
        maks_rim: Maks antall rim (default 15)
        maks_synonymer: Maks antall synonymer (default 10)
        dialekt: Dialektregion (default øst)
    """
    try:
        data = await _get(f"/arsenal/{ord}", {
            "maks_rim": maks_rim, "maks_synonymer": maks_synonymer,
            "maks_synonymrim": 5, "dialekt": dialekt,
        })
        info = data.get("info", {})
        lines = [f"Arsenal for «{ord}» (/{info.get('ipa', '?')}/, {info.get('stavelser', '?')} stavelser):"]

        defn = info.get("definisjon")
        if defn:
            lines.append(f"  Definisjon: {defn}")

        rim = data.get("rim", [])
        if rim:
            lines.append(f"  Rim ({len(rim)}): {', '.join(rim)}")

        nesten = data.get("nesten_rim", [])
        if nesten:
            lines.append(f"  Nesten-rim ({len(nesten)}): {', '.join(n['ord'] for n in nesten)}")

        syns = data.get("synonymer", [])
        if syns:
            lines.append(f"  Synonymer med rim:")
            for s in syns:
                if s["rim"]:
                    lines.append(f"    {s['ord']} → {', '.join(s['rim'])}")
                else:
                    lines.append(f"    {s['ord']} (ingen rim)")

        return "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def sjekk_rim(ord1: str, ord2: str, dialekt: str = "øst") -> str:
    """Sjekk om to norske ord rimer, med fonetisk begrunnelse.

    Returnerer om ordene har perfekt rim, nesten-rim, eller ikke rimer,
    med score og forklaring.

    Args:
        ord1: Første ord (f.eks. "krone")
        ord2: Andre ord (f.eks. "tone")
        dialekt: Dialektregion (default øst)
    """
    try:
        data = await _get(f"/rimer/{ord1}/{ord2}", {"dialekt": dialekt})
        r = data.get("resultat", {})
        o1 = data.get("ord1", {})
        o2 = data.get("ord2", {})

        lines = [f"«{ord1}» /{o1.get('ipa', '?')}/ vs «{ord2}» /{o2.get('ipa', '?')}/:"]
        lines.append(f"  {r.get('forklaring', '?')}")
        if r.get("perfekt_rim"):
            lines.append(f"  Perfekt rim (score {r.get('score', '?')})")
        elif r.get("nesten_rim"):
            lines.append(f"  Nesten-rim (score {r.get('score', '?')})")
        else:
            lines.append(f"  Rimer ikke (score {r.get('score', '?')})")
        return "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def batch(
    ord: list[str],
    operasjoner: list[str] = ["rim", "info"],
    maks: int = 10,
    dialekt: str = "øst",
) -> str:
    """Kjør operasjoner på flere ord samtidig i ett kall.

    Støtter vilkårlig mange ord og vilkårlig kombinasjon av operasjoner.
    Bruk dette når du trenger å slå opp, sammenligne, eller analysere
    flere ord på én gang.

    Args:
        ord: Liste med ord (f.eks. ["sol", "natt", "hjerte"]). Maks 50.
        operasjoner: Liste av operasjoner å kjøre per ord.
            Tilgjengelige: "rim", "nestenrim", "synonymer", "antonymer", "info", "arsenal".
            Legg til "rimer" for å sjekke alle par mot hverandre.
        maks: Maks resultater per ord per operasjon (default 10)
        dialekt: Dialektregion (default øst)
    """
    try:
        data = await _post("/batch", {
            "ord": ord,
            "operasjoner": operasjoner,
            "maks": maks,
            "dialekt": dialekt,
        })
        res = data.get("resultater", {})
        lines = []

        for word in ord:
            entry = res.get(word, {})
            parts = [f"«{word}»"]

            info = entry.get("info")
            if info:
                parts.append(f"/{info.get('ipa', '?')}/")
                defn = info.get("definisjon")
                if defn:
                    parts.append(f"— {defn[:60]}")

            lines.append("  ".join(parts))

            rim = entry.get("rim")
            if rim:
                lines.append(f"  Rim: {', '.join(rim)}")

            nestenrim = entry.get("nestenrim")
            if nestenrim:
                lines.append(f"  Nesten-rim: {', '.join(n['ord'] for n in nestenrim)}")

            synonymer = entry.get("synonymer")
            if synonymer:
                lines.append(f"  Synonymer: {', '.join(synonymer)}")

            antonymer = entry.get("antonymer")
            if antonymer:
                lines.append(f"  Antonymer: {', '.join(antonymer)}")

            arsenal = entry.get("arsenal")
            if arsenal:
                if arsenal.get("rim"):
                    lines.append(f"  Rim: {', '.join(arsenal['rim'])}")
                for s in arsenal.get("synonymer", []):
                    if s.get("rim"):
                        lines.append(f"  {s['ord']} → {', '.join(s['rim'])}")

            lines.append("")

        # Rimpar
        rimpar = res.get("_rimpar")
        if rimpar:
            lines.append("Rimpar:")
            for p in rimpar:
                status = "perfekt rim" if p["perfekt_rim"] else "nesten-rim" if p["nesten_rim"] else "rimer ikke"
                lines.append(f"  {p['ord1']} / {p['ord2']}: {status} (score {p['score']})")

        return "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def generer_rimklynger(
    modus: str = "par",
    antall: int = 10,
    stavelser: int | None = None,
    ord: str | None = None,
) -> str:
    """Generer tilfeldige rimklynger for freestyle-trening.

    Tre moduser:
    - "par": 2 ord per klynge, fra ulike rimfamilier (tren overganger)
    - "bred": 4 ord per klynge (tren bredde)
    - "dyp": alle ord fra én rimfamilie (tren dybde)

    Args:
        modus: "par", "bred" eller "dyp" (default "par")
        antall: Antall klynger å generere (default 10, ignoreres for dyp)
        stavelser: Filtrer på antall stavelser (None = alle)
        ord: Valgfritt startord — alle klynger rimer på dette ordet
    """
    try:
        params: dict = {"min_frekvens": 1.0}
        if antall and modus != "dyp":
            params["antall"] = antall
        if stavelser is not None:
            params["stavelser"] = stavelser
        if ord:
            params["ord"] = ord

        data = await _get(f"/rimklynger/{modus}", params)
        klynger = data.get("klynger", [])
        if not klynger:
            hint = f" for «{ord}»" if ord else ""
            return f"Ingen rimklynger funnet{hint} med disse filtrene."

        sep = " / " if modus == "par" else ", " if modus == "bred" else " · "
        lines = []
        for k in klynger:
            words = sep.join(k["ord"])
            lines.append(f"  [{k['rimsuffiks']}] {words}")

        total = sum(len(k["ord"]) for k in klynger)
        header = f"Rimklynger ({modus}): {len(klynger)} klynger, {total} ord"
        if ord:
            header += f" (rimfamilie: «{ord}»)"
        return header + "\n" + "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def sok_ord(prefiks: str, maks: int = 10) -> str:
    """Søk etter norske ord som starter med et gitt prefiks (autocomplete).

    Args:
        prefiks: Starten av ordet (f.eks. "sol", "kj", "rim")
        maks: Maks antall resultater (default 10)
    """
    try:
        data = await _get("/sok", {"q": prefiks, "maks": maks})
        items = data.get("resultater", [])
        if not items:
            return f"Ingen ord funnet som starter med «{prefiks}»."
        return f"Ord som starter med «{prefiks}»: {', '.join(items)}"
    except Exception as e:
        return f"Feil: {e}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
