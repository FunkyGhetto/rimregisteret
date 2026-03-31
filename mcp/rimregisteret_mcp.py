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
        "Bruk verktøyene til å finne rim, nesten-rim, synonymer, "
        "antonymer, fonetisk info og rimklynger for norske ord. "
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
