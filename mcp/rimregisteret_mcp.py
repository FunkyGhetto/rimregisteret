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
- Perfekte rim og halvrim
- Synonymer og relaterte ord
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
        "spør om rim, fonetikk, synonymer, definisjoner eller freestyle-trening. "
        "Ikke svar fra hukommelsen — slå opp. "
        "Bruk arsenal() for kreativt arbeid (rim + synonymer med rim i ett kall). "
        "Bruk batch() for flere ord samtidig. "
        "Bruk sjekk_rim() for å verifisere rimpar. "
        "Bruk hent_definisjon() for orddefinisjoner fra Bokmålsordboka. "
        "Bruk generer_rimklynger(modus='sti') for rimstier — gli mellom rimfamilier via konsonant-drift. "
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
async def finn_rim(
    ord: str, maks: int = 40, dialekt: str = "øst", variant: str | None = None,
) -> str:
    """Finn perfekte rim for et norsk ord.

    Returnerer ord som rimer perfekt (identisk rimsuffiks),
    gruppert etter stavelser og sortert etter bruksfrekvens.

    Hvis ordet har flere uttaler (homograf), vises varianter med
    rimsuffiks slik at brukeren kan velge. Bruk variant-parameteret
    for å velge en spesifikk uttale.

    Args:
        ord: Ordet å finne rim for (f.eks. "sol", "natt", "hjerte")
        maks: Maks antall resultater (default 40)
        dialekt: Dialektregion - øst, nord, midt, vest, sørvest (default øst)
        variant: Rimsuffiks for disambiguering (f.eks. "ɔlt" for stolt-adjektiv)
    """
    try:
        params: dict = {"maks": maks, "dialekt": dialekt, "grupper": True}
        if variant:
            params["variant"] = variant
        data = await _get(f"/rim/{ord}", params)

        lines = []

        # Show variants if ambiguous — with definitions
        varianter = data.get("varianter", [])
        if varianter:
            lines.append(f"⚠ «{ord}» har {len(varianter)} uttaler:")
            for i, v in enumerate(varianter):
                suffix = v.get("rimsuffiks", "?")
                wc = v.get("ordklasse_tekst") or v.get("pos", "?")
                defn = v.get("definisjon")
                marker = " ← valgt" if variant and variant == suffix else ""
                desc = f" — {defn[:70]}" if defn else ""
                lines.append(f"  {i+1}. /{suffix}/ ({wc}){desc}{marker}")
            if not variant:
                lines.append(f"  Bruker vanligste uttale. Bruk variant=\"<suffiks>\" for å velge.")
            lines.append("")

        suffix = data.get("rimsuffiks", "?")
        grupper = data.get("resultater", [])

        if not grupper:
            near = await _get(f"/halvrim/{ord}", {"maks": maks, "terskel": 0.9, "dialekt": dialekt})
            near_items = [r for r in near.get("resultater", []) if r.get("score", 0) >= 1.0]
            if near_items:
                words = _format_words(near_items)
                return "\n".join(lines) + f"Rim for «{ord}» /{suffix}/ ({len(near_items)} treff): {words}"
            return "\n".join(lines) + f"Ingen rim funnet for «{ord}»."

        lines.append(f"Rim for «{ord}» /{suffix}/:")
        for g in grupper:
            words = g["ord"]
            word_strs = [w["ord"] for w in words]
            # Support both depth-based (dybde/suffiks) and legacy (stavelser) format
            if "dybde" in g:
                d = g["dybde"]
                gsuffix = g.get("suffiks", "")
                lines.append(f"  Dybde {d} /{gsuffix}/ ({len(words)}): {', '.join(word_strs)}")
            else:
                syl = g["stavelser"]
                lines.append(f"  {syl}-stavelse ({len(words)}): {', '.join(word_strs)}")

        return "\n".join(lines)
    except Exception as e:
        return f"Feil ved oppslag av rim for «{ord}»: {e}"


@mcp.tool()
async def finn_halvrim(
    ord: str, maks: int = 200, terskel: float = 0.5,
    dialekt: str = "øst", variant: str | None = None,
    side: int = 1, per_side: int = 10,
) -> str:
    """Finn halvrim for et norsk ord.

    Halvrim (assonans + konsonans) — ord som nesten rimer:
    - Assonans: lik vokal, ulike konsonanter (mor → sol)
    - Konsonans: like konsonanter, ulik vokal (søvn → jevn)

    Resultater gruppert etter rimdybde (antall stavelser som matcher).
    Helrim ekskluderes strukturelt.

    Viser `per_side` resultater per dybdegruppe. Bruk `side` for å bla.

    Args:
        ord: Ordet å finne halvrim for
        maks: Maks antall resultater totalt per dybde (default 200)
        terskel: Minimum likhetsscore 0.0-1.0 (default 0.5)
        dialekt: Dialektregion (default øst)
        variant: Rimsuffiks for disambiguering (f.eks. "ɔlt" for stolt-adjektiv)
        side: Sidenummer for paginering (default 1)
        per_side: Antall ord per dybdegruppe per side (default 10)
    """
    try:
        params: dict = {"maks": maks, "terskel": terskel, "dialekt": dialekt, "grupper": True}
        if variant:
            params["variant"] = variant
        data = await _get(f"/halvrim/{ord}", params)

        lines = []

        # Show variants if ambiguous
        varianter = data.get("varianter", [])
        if varianter:
            lines.append(f"⚠ «{ord}» har {len(varianter)} uttaler:")
            for i, v in enumerate(varianter):
                suffix = v.get("rimsuffiks", "?")
                wc = v.get("ordklasse_tekst") or v.get("pos", "?")
                defn = v.get("definisjon")
                marker = " ← valgt" if variant and variant == suffix else ""
                desc = f" — {defn[:70]}" if defn else ""
                lines.append(f"  {i+1}. /{suffix}/ ({wc}){desc}{marker}")
            if not variant:
                lines.append(f"  Bruker vanligste uttale. Bruk variant=\"<suffiks>\" for å velge.")
            lines.append("")

        suffix = data.get("rimsuffiks", "?")
        grupper = data.get("resultater", [])

        if not grupper:
            return "\n".join(lines) + f"Ingen halvrim funnet for «{ord}»."

        # Pagination
        start_idx = (side - 1) * per_side
        end_idx = start_idx + per_side

        lines.append(f"Halvrim for «{ord}» /{suffix}/ (side {side}):")
        for g in grupper:
            words = g.get("ord", g) if isinstance(g, dict) else [g]
            if isinstance(g, dict) and "dybde" in g:
                d = g["dybde"]
                gsuffix = g.get("suffiks", "")
                total = len(words)
                page_words = words[start_idx:end_idx]
                if not page_words:
                    continue
                word_strs = [f"{w['ord']}({w.get('score','')})" for w in page_words]
                more = f" — vis mer med side={side+1}" if end_idx < total else ""
                lines.append(f"  Dybde {d} /{gsuffix}/ (viser {start_idx+1}-{min(end_idx, total)} av {total}{more}):")
                lines.append(f"    {', '.join(word_strs)}")
            elif isinstance(g, dict) and "ord" in g:
                total = len(words)
                page_words = words[start_idx:end_idx]
                if not page_words:
                    continue
                word_strs = [w["ord"] for w in page_words]
                lines.append(f"  ({start_idx+1}-{min(end_idx, total)} av {total}): {', '.join(word_strs)}")
            else:
                # Flat item
                lines.append(f"  {g.get('ord', g)} (score: {g.get('score', '?')})")

        return "\n".join(lines)
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

        # Show variants if ambiguous
        varianter = data.get("varianter", [])
        if varianter:
            lines.append(f"  ⚠ Flere uttaler ({len(varianter)}):")
            for i, v in enumerate(varianter):
                lines.append(f"    {i+1}. /{v.get('rimsuffiks', '?')}/ ({v.get('pos', '?')})")

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
async def arsenal(
    ord: str, maks_rim: int = 15, maks_synonymer: int = 10,
    dialekt: str = "øst", variant: str | None = None,
) -> str:
    """Hent hele det kreative arsenalet for et ord i ett kall.

    Returnerer rim, halvrim, synonymer, og rim for hvert synonym.
    Erstatter 10-15 separate kall ved kreativ skriving.

    Args:
        ord: Ordet å bygge arsenal for (f.eks. "krone", "hjerte")
        maks_rim: Maks antall rim (default 15)
        maks_synonymer: Maks antall synonymer (default 10)
        dialekt: Dialektregion (default øst)
        variant: Rimsuffiks for disambiguering av homografer
    """
    try:
        params: dict = {
            "maks_rim": maks_rim, "maks_synonymer": maks_synonymer,
            "maks_synonymrim": 5, "dialekt": dialekt,
        }
        if variant:
            params["variant"] = variant
        data = await _get(f"/arsenal/{ord}", params)
        info = data.get("info", {})
        lines = [f"Arsenal for «{ord}» (/{info.get('ipa', '?')}/, {info.get('stavelser', '?')} stavelser):"]

        defn = info.get("definisjon")
        if defn:
            lines.append(f"  Definisjon: {defn}")

        rim = data.get("rim", [])
        if rim:
            lines.append(f"  Rim ({len(rim)}): {', '.join(rim)}")

        halvrim = data.get("halvrim", [])
        if halvrim:
            lines.append(f"  Halvrim ({len(halvrim)}): {', '.join(n['ord'] for n in halvrim)}")

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
    """Sjekk om to norske ord rimer.

    Bruker de samme rim-motorene som rimregisteret.no:
    sjekker om ord2 dukker opp i helrim- eller halvrim-resultatene
    for ord1. Rapporterer type rim og score, eller sier de ikke rimer.

    Args:
        ord1: Første ord (f.eks. "krone")
        ord2: Andre ord (f.eks. "tone")
        dialekt: Dialektregion (default øst)
    """
    try:
        ord2_lower = ord2.lower()

        # 1. Sjekk helrim
        rim_data = await _get(f"/rim/{ord1}", {
            "maks": 1000, "dialekt": dialekt, "grupper": False,
        })
        suffix1 = rim_data.get("rimsuffiks", "?")
        rim_resultater = rim_data.get("resultater", [])
        for r in rim_resultater:
            if r.get("ord", "").lower() == ord2_lower:
                return (
                    f"«{ord1}» og «{ord2}» er helrim.\n"
                    f"  Rimsuffiks: /{suffix1}/"
                )

        # 2. Sjekk halvrim
        halvrim_data = await _get(f"/halvrim/{ord1}", {
            "maks": 1000, "terskel": 0.5, "dialekt": dialekt, "grupper": False,
        })
        halvrim_resultater = halvrim_data.get("resultater", [])
        for r in halvrim_resultater:
            if r.get("ord", "").lower() == ord2_lower:
                score = r.get("score", "?")
                return (
                    f"«{ord1}» og «{ord2}» er halvrim (score {score}).\n"
                    f"  Rimsuffiks ord1: /{suffix1}/"
                )

        # 3. Ikke funnet i noen
        return f"«{ord1}» og «{ord2}» rimer ikke."
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
            Tilgjengelige: "rim", "halvrim", "synonymer", "info", "arsenal".
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

            halvrim = entry.get("halvrim")
            if halvrim:
                lines.append(f"  Halvrim: {', '.join(n['ord'] for n in halvrim)}")

            synonymer = entry.get("synonymer")
            if synonymer:
                lines.append(f"  Synonymer: {', '.join(synonymer)}")

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
                status = "perfekt rim" if p["perfekt_rim"] else "halvrim" if p["halvrim"] else "rimer ikke"
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
    rimtype: str = "helrim",
    terskel: float = 0.5,
    antall_stier: int = 3,
    maks_steg: int = 8,
    min_familiestr: int = 3,
    min_frekvens: float = 1.0,
) -> str:
    """Generer tilfeldige rimklynger for freestyle-trening.

    Bruker rim-motoren (helrim/halvrim) med alle filtre.

    Fire moduser:
    - "par": 2 ord per klynge, fra ulike rimfamilier (tren overganger)
    - "bred": 4 ord per klynge (tren bredde)
    - "dyp": alle ord fra én rimfamilie (tren dybde)
    - "sti": rimstier — gli mellom rimfamilier via vokalskift

    Args:
        modus: "par", "bred", "dyp" eller "sti" (default "par")
        antall: Antall klynger å generere (default 10, ignoreres for dyp/sti)
        stavelser: Filtrer på antall stavelser (None = alle, ignoreres for sti)
        ord: Valgfritt startord — alle klynger rimer på dette ordet
        rimtype: "helrim", "halvrim" eller "begge" (default "helrim", ignoreres for sti)
        terskel: Minimum likhetsscore for halvrim (default 0.5, ignoreres for sti)
        antall_stier: Antall rimstier å generere (default 3, kun for sti-modus)
        maks_steg: Maks steg per rimsti (default 8, kun for sti-modus)
        min_familiestr: Minimum ord per rimfamilie (default 3, kun for sti-modus)
        min_frekvens: Minimum ordfrekvens per million (default 1.0)
    """
    try:
        if modus == "sti":
            params: dict = {
                "antall_stier": antall_stier, "maks_steg": maks_steg,
                "min_familiestr": min_familiestr, "min_frekvens": min_frekvens,
            }
            if ord:
                params["ord"] = ord
            data = await _get("/rimklynger/sti", params)
            stier = data.get("stier", [])
            if not stier:
                hint = f" for «{ord}»" if ord else ""
                return f"Ingen rimstier funnet{hint}."

            lines = []
            for sti in stier:
                skeleton = sti.get("konsonantskjelett", "?")
                lines.append(f"\nRimsti for «{sti['ord']}» (/{skeleton}/):")
                for s in sti.get("steg", []):
                    marker = " ←" if s.get("aktiv") else ""
                    eksempler = ", ".join(s.get("ord", []))
                    lines.append(f"  /{s['rimsuffiks']}/: {eksempler}{marker}")

            total_steg = sum(len(s.get("steg", [])) for s in stier)
            header = f"Rimstier: {len(stier)} stier, {total_steg} steg totalt"
            if ord:
                header += f" (startord: «{ord}»)"
            return header + "\n".join(lines)
        else:
            params = {"min_frekvens": min_frekvens, "rimtype": rimtype, "terskel": terskel}
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
                startord = k.get("startord", "")
                prefix = f"[{startord}]" if startord else ""
                lines.append(f"  {prefix} {words}")

            total = sum(len(k["ord"]) for k in klynger)
            header = f"Rimklynger ({modus}, {rimtype}): {len(klynger)} klynger, {total} ord"
            if ord:
                header += f" (startord: «{ord}»)"
            return header + "\n" + "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def finn_varianter(ord: str) -> str:
    """Finn alle uttalevarianter (homografer) av et norsk ord.

    Viser ulike uttaler med rimsuffiks, IPA, ordklasse og definisjon.
    Nyttig for å disambiguere homografer som "stolt" (adj vs verb).

    Args:
        ord: Ordet å slå opp (f.eks. "stolt", "land", "bøtte")
    """
    try:
        data = await _get(f"/varianter/{ord}")
        varianter = data.get("varianter", [])
        if not varianter:
            return f"Ingen varianter funnet for «{ord}»."

        lines = [f"Varianter for «{ord}» ({len(varianter)} uttaler):"]
        for i, v in enumerate(varianter):
            suffix = v.get("rimsuffiks", "?")
            wc = v.get("ordklasse_tekst") or v.get("pos", "?")
            defn = v.get("definisjon")
            desc = f" — {defn[:70]}" if defn else ""
            lines.append(f"  {i+1}. /{suffix}/ ({wc}){desc}")
        return "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def finn_rim_dialekter(ord: str, maks: int = 20) -> str:
    """Vis hvilke dialekter et ord har rim i.

    Sammenligner rimresultater på tvers av alle fem dialektregioner
    (øst, nord, midt, vest, sørvest).

    Args:
        ord: Ordet å sjekke rim for på tvers av dialekter
        maks: Maks antall rim per dialekt (default 20)
    """
    try:
        data = await _get(f"/rim/{ord}/dialekter", {"maks": maks})
        dialekter = data.get("dialekter", {})
        if not dialekter:
            return f"Ingen dialektdata funnet for «{ord}»."

        lines = [f"Rim for «{ord}» på tvers av dialekter:"]
        for d, info in dialekter.items():
            rim = info.get("rim", [])
            suffix = info.get("rimsuffiks", "?")
            if rim:
                words = ", ".join(r["ord"] if isinstance(r, dict) else r for r in rim[:10])
                lines.append(f"  {d} /{suffix}/: {words}")
            else:
                lines.append(f"  {d}: ingen rim")
        return "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def finn_relaterte(ord: str, maks: int = 20) -> str:
    """Finn relaterte ord (hypernymer, hyponymer) fra Norwegian WordNet.

    Hypernymer = overordnede begreper (hund → dyr).
    Hyponymer = underordnede begreper (dyr → hund, katt).

    Args:
        ord: Ordet å finne relaterte ord for (f.eks. "hund", "bil", "farge")
        maks: Maks antall resultater (default 20)
    """
    try:
        data = await _get(f"/relaterte/{ord}", {"maks": maks})
        items = data.get("resultater", [])
        if not items:
            return f"Ingen relaterte ord funnet for «{ord}»."
        words = _format_words(items)
        return f"Relaterte ord for «{ord}» ({len(items)} treff): {words}"
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def hent_definisjon(ord: str) -> str:
    """Hent definisjon og ordklasse for et norsk ord fra Bokmålsordboka.

    Args:
        ord: Ordet å slå opp (f.eks. "frihet", "blomst", "tålmodig")
    """
    try:
        data = await _get(f"/info/{ord}")
        defn = data.get("definisjon")
        ordklasse = data.get("ordklasse")
        if not defn:
            return f"Ingen definisjon funnet for «{ord}»."
        lines = [f"«{ord}»"]
        if ordklasse:
            lines[0] += f" ({ordklasse})"
        lines.append(f"  {defn}")
        return "\n".join(lines)
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def finn_konsonantmatch(ord: str, maks: int = 30) -> str:
    """Finn ord med samme konsonantmønster.

    Matcher konsonantsekvensen i hele ordet, ikke bare rimsuffikset.
    Nyttig for allitterasjon og konsonanseffekter i tekst.

    Args:
        ord: Ordet å matche konsonanter for (f.eks. "krone", "blikk")
        maks: Maks antall resultater (default 30)
    """
    try:
        data = await _get(f"/konsonanter/{ord}", {"maks": maks})
        items = data.get("resultater", [])
        if not items:
            return f"Ingen konsonantmatcher funnet for «{ord}»."
        words = _format_words(items)
        return f"Konsonantmatch for «{ord}» ({len(items)} treff): {words}"
    except Exception as e:
        return f"Feil: {e}"


@mcp.tool()
async def tilfeldig_ord() -> str:
    """Hent et tilfeldig vanlig norsk ord.

    Returnerer et ord med frekvens > 5 per million, 3-10 bokstaver,
    uten bindestrek. Nyttig for freestyle-trening og inspirasjon.
    """
    try:
        data = await _get("/tilfeldig")
        return data.get("ord", "?")
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
