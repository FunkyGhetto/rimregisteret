# Rimordbok

Norsk rimordbok.

## Installasjon

```bash
pip install -e ".[dev]"
```

## Struktur

- `data/` — rådata, prosessert data, SQLite-databaser
- `scripts/` — datapipeline-scripts
- `rimordbok/` — kjernelogikk (fonetikk, rim-motor, semantikk, DB)
- `api/` — FastAPI-backend
- `frontend/` — web-frontend
- `tests/` — pytest-tester
