# Rimregisteret MCP Server

MCP-server (Model Context Protocol) som gir LLM-er tilgang til Rimregisteret — norsk rimordbok med 684 000 ord.

## Verktøy

| Verktøy | Beskrivelse |
|---------|-------------|
| `finn_rim` | Finn perfekte rim for et norsk ord |
| `finn_halvrim` | Finn halvrim med likhetsscore |
| `finn_synonymer` | Finn synonymer (Norwegian WordNet) |
| `ordinfo` | IPA, stavelser, tonelag, rimsuffiks |
| `generer_rimklynger` | Tilfeldige rimklynger for freestyle-trening |
| `sok_ord` | Autocomplete for norske ord |

## Installasjon

### Claude Code

```bash
claude mcp add rimregisteret -- uv run mcp/rimregisteret_mcp.py
```

### Claude Desktop

Legg til i `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rimregisteret": {
      "command": "uv",
      "args": ["run", "/full/sti/til/mcp/rimregisteret_mcp.py"]
    }
  }
}
```

### Manuell kjøring

```bash
uv run mcp/rimregisteret_mcp.py
```

### Utvikling / test

```bash
mcp dev mcp/rimregisteret_mcp.py
```

## Eksempler

Når MCP-serveren er installert kan du si til Claude:

- *"Finn rim for 'sol'"*
- *"Hva er IPA-uttalen av 'kjærlighet'?"*
- *"Generer 10 rimpar for freestyle-trening"*
- *"Finn synonymer for 'glad'"*
- *"Lag en dyp rimklynge for 'natt'"*
