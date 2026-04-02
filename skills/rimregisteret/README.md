# Rimregisteret Skill

Claude Code skill som gir Claude dyp kunnskap om norsk rim, freestyle-trening, og direkte API-tilgang til Rimregisteret (684 000 norske ord).

## Installasjon

Kopier denne mappen til `.claude/skills/` i prosjektet ditt:

```bash
cp -r skills/rimregisteret /ditt-prosjekt/.claude/skills/
```

Eller lag en symlink:

```bash
ln -s /sti/til/rimregisteret/skills/rimregisteret /ditt-prosjekt/.claude/skills/rimregisteret
```

## Hva den gjør

Når denne skillen er aktiv, kan Claude:

- Slå opp rim, halvrim, synonymer og antonymer for norske ord
- Forklare norsk fonetikk (IPA, tonelag, retroflekser, dialekter)
- Generere rimklynger for freestyle-trening
- Analysere rimdensitet i tekster
- Gi treningsråd basert på forskning og teknikker fra profesjonelle rappere
- Sammenligne rim på tvers av 5 norske dialekter

## Krav

- Internettilgang til `rimregisteret.no` (API-kall)
- Ingen API-nøkkel nødvendig (gratis, 100 req/min)

## Kombinasjon med MCP

For enda bedre integrasjon, installer også MCP-serveren:

```bash
claude mcp add rimregisteret -- uv run mcp/rimregisteret_mcp.py
```

Da kan Claude kalle APIet direkte som verktøy, i tillegg til å ha kunnskapsbasen fra denne skillen.
