# Rimregisteret

Norsk rimordbok og freestyle-treningsverktøy.

**Live:** [rimregisteret.no](https://rimregisteret.no)

## Funksjoner

- **Fonetisk rimfinn** med 684K ord fra NB Uttale
- **Perfekte rim**, nesten-rim, homofoner, konsonantmatching
- **Synonymer og antonymer** fra Norwegian WordNet
- **Rimklynger** — tilfeldig genererte treningssett for cypher-drill (par, bred, dyp)
- **5 dialektregioner** — østnorsk, nordnorsk, trøndersk, vestnorsk, sørvestnorsk
- **Ordfrekvens** — sortert etter bruksfrekvens fra 1.175 milliarder ord (Språkbanken)

## Kjør lokalt

```bash
pip install -e .

# Bygg databasene (krever rådata fra Språkbanken):
python scripts/parse_phonetics.py
python scripts/build_rhyme_index.py
python scripts/build_frequencies.py
python scripts/parse_wordnet.py

# Start API:
uvicorn api.main:app --reload
# Frontend: http://localhost:8000
```

## API

| Endepunkt | Beskrivelse |
|-----------|-------------|
| `GET /api/v1/rim/{ord}` | Perfekte rim |
| `GET /api/v1/nestenrim/{ord}` | Nesten-rim med scoring |
| `GET /api/v1/synonymer/{ord}` | Synonymer |
| `GET /api/v1/antonymer/{ord}` | Antonymer |
| `GET /api/v1/info/{ord}` | Fonetikk + rim + synonymer |
| `GET /api/v1/rimklynger/par` | Rimklynger: par (2-og-2) |
| `GET /api/v1/rimklynger/bred` | Rimklynger: bred (4-og-4) |
| `GET /api/v1/rimklynger/dyp` | Rimklynger: dyp (alle ord) |
| `GET /api/v1/sok?q={prefix}` | Autocomplete |

Alle rim-endepunkter støtter `?dialekt=øst|vest|sørvest|midt|nord`.

Swagger-dokumentasjon: [/docs](http://localhost:8000/docs)

## Tester

```bash
pytest tests/ -v
# 303 tester
```

## Deploy

**Frontend** deployes til Vercel (statisk HTML):

```bash
vercel --prod
```

Vercel serverer `frontend/index.html` og proxyer `/api/*` til backend via rewrites i `vercel.json`. Oppdater `BACKEND-URL-PLACEHOLDER` i `vercel.json` med den faktiske backend-URLen etter backend-deploy.

Custom domain:
```bash
vercel domains add rimregisteret.no
```

**Backend** (FastAPI + SQLite) krever en egen server med databasefilene. Se `scripts/` for å bygge databasene.

## Datakilder

- [NB Uttale](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-56/) — fonetisk leksikon (5 dialekter)
- [Norwegian WordNet](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-27/) — semantiske relasjoner
- [Språkbanken N-gram](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-32/) — ordfrekvenser
