# Testresultater — Rimregisteret

**Dato:** 2026-03-30
**Python:** 3.9.6 | **pytest:** 8.4.2
**Resultat:** 303 bestått, 0 feilet
**Kjøretid:** 30.2s

---

## Oversikt per testfil

| Fil | Tester | Status |
|-----|--------|--------|
| `test_api.py` | 48 | 48 bestått |
| `test_clusters.py` | 45 | 45 bestått |
| `test_dialect.py` | 26 | 26 bestått |
| `test_frequencies.py` | 9 | 9 bestått |
| `test_g2p.py` | 28 | 28 bestått |
| `test_integration.py` | 88 | 88 bestått |
| `test_parser.py` | 12 | 12 bestått |
| `test_rhyme.py` | 22 | 22 bestått |
| `test_rhyme_index.py` | 19 | 19 bestått |
| `test_semantics.py` | 16 | 16 bestått |
| **Totalt** | **303** | **303 bestått** |

---

## Integrasjonstester (`test_integration.py`)

### 1. Perfekte rimpar (25 par)
Verifiserer at kjente norske rimpar faktisk matcher i systemet.
Alle 25 par bestått, inkludert: natt/matt, sol/stol, hjerte/smerte, kjærlighet/evighet.

### 2. Ikke-rim (5 par)
Verifiserer at ord som **ikke** rimer korrekt avvises.
- jul/stol (uːl vs oːl), lys/is (yːs vs iːs), båt/råd (oːt vs oːd), tid/strid (iː vs iːd), dans/sjans (ns vs ŋs)

### 3. Frekvensordning (2 tester)
Rimresultater sorteres etter frekvens synkende. Vanlige ord kommer før sjeldne.

### 4. Halvrim (4 tester)
- dag→tak (stemt/ustemt konsonantpar)
- sang→lang (lik endelse)
- Score mellom 0 og 1, ingen overlapp med perfekte rim

### 5. Tonelag (5 tester)
- bønder (tonelag 1) vs bønner (tonelag 2) har forskjellig tonelag
- `samme_tonelag`-filteret fungerer korrekt
- Tonelag-verdier er alltid 1 eller 2

### 6. Semantikk (9 tester)
- glad → lykkelig, fornøyd, munter (synonymer)
- billig ↔ dyr (antonymer, begge retninger)
- hund har relaterte ord (hypernymer/hyponymer)
- Synonymer sortert etter frekvens

### 7. API-responstid (11 endepunkter)
Alle endepunkter svarer under 150ms etter oppvarming:
`/rim`, `/halvrim`, `/synonymer`, `/antonymer`, `/relaterte`, `/homofoner`, `/konsonanter`, `/info`, `/sok`

### 8. Edge cases (9 tester)
- Ukjente ord faller tilbake til G2P
- Unicode (æ, ø, å) håndteres korrekt
- Store/små bokstaver normaliseres
- Veldig lange ord krasjer ikke
- Enkeltbokstaver fungerer

### 9. Fonetikk-konsistens (5 tester)
- sol → suːl, dag → dɑːg, natt → nɑt (IPA fra leksikon)
- G2P produserer gyldige felter (ipa, stavelser, tonelag)
- Leksikon-oppslag har alle nødvendige felter

### 10. Systemintegrasjon (3 tester)
- Full pipeline: ord → fonetikk → rim → frekvenssortering
- Semantisk pipeline: ord → synonymer med frekvens
- Autocomplete → rimoppslag (brukerflyt)

### 11. Rimklynge-integrasjon (5 tester)
- Klynge → klikk ord → rimresultater (brukerflyt)
- Dyp-klynge: alle ord er perfekte rim av hverandre
- Full API-flyt: klynge → info → rim
- Stavelsesfilter-konsistens (klyngeord matcher faktisk stavelsestall)
- Responstid under 500ms for tilfeldig generering

---

## Rimklynge-tester (`test_clusters.py`)

### Hjelpefunksjoner (8 tester)
- `hent_kvalifiserte_suffikser`: returnerer liste, min_ord filtrerer, stavelsesfilter
- `hent_rimfamilie`: kjent suffiks, tilfeldig rekkefølge, frekvenssortert, maks-begrensning

### Par-modus (5 tester)
- Returnerer klynger med eksakt 2 ord
- Alle ord i en klynge har samme rimsuffiks
- Forskjellige rimfamilier per klynge (uten ord-parameter)
- Tilfeldige resultater mellom kall

### Bred-modus (3 tester)
- Returnerer klynger med eksakt 4 ord
- Rimsuffiks-konsistens

### Dyp-modus (3 tester)
- Returnerer alltid én klynge
- Mange ord (>4)
- Sortert etter frekvens

### Ord-parameter (6 tester)
- Par/bred/dyp med ord="natt": alle rimer på "natt"
- Ukjent ord → tom liste
- Case-insensitivt

### Filtre (3 tester)
- Stavelsesfilter, frekvensfilter, sjeldne stavelser → tomt resultat

### Edge cases (4 tester)
- Ugyldig modus → ValueError
- antall=0 → tom liste
- Dyp ignorerer antall-parameter

### Rimsuffiks-konsistens (3 tester)
- Alle ord i par/bred/dyp-klynger har faktisk riktig rimsuffiks i databasen

### Frekvensfilter-detalj (2 tester)
- Høy terskel filtrerer bort sjeldne ord
- min_frekvens=0 inkluderer alle

### Tilfeldighet (2 tester)
- 5 kall gir minst 2 ulike suffiks-sett (par og bred)

### Antall-parameter (2 tester)
- Eksakt antall par/bred returneres

---

## API-tester (`test_api.py`)

### Rimklynge-API (24 nye tester)
- Par/bred/dyp: grunnleggende respons, klyngestørrelse, responsformat
- Ord-parameter: alle klynger deler suffiks
- Filtre: stavelser, dialekt, umulig filter → tomt
- Ukjent ord → tom klyngeliste
- Responstid: ord-spesifikk <150ms, tilfeldig <500ms

---

## Enhetstester (sammendrag)

| Modul | Hva testes | Nøkkelfunn |
|-------|-----------|------------|
| **G2P** (28) | IPA-transkripsjon, retroflekser, diftonger, stavelsesdeling | Alle regler fungerer |
| **Parser** (12) | IPA-parsing, Nofabet-stress, filtrering | Korrekt parsing |
| **Rimindeks** (19) | Rimsuffiks, vokaler, rimoppslag, søk | Suffiks-algoritme fungerer |
| **Rim** (22) | Perfekte rim, halvrim, homofoner, konsonanter | Alle rimtyper fungerer |
| **Frekvens** (9) | Frekvensfil, DB-frekvenser, sortering | 323K ord med frekvens |
| **Semantikk** (16) | Synonymer, antonymer, relaterte, meronymer | 436K relasjoner |
| **Klynger** (45) | Par/bred/dyp, filtre, tilfeldighet, DB-konsistens | Alle moduser fungerer |
| **Dialekt** (26) | 5 dialekter, rimforskjeller, API-parameter | Dialektrim fungerer |
| **API** (48) | Alle endepunkter, klynger, filtre, responstid, CORS | REST API fungerer |

---

## Databaser

| Database | Størrelse | Innhold |
|----------|-----------|---------|
| `rimindeks.db` | 94 MB | 684 114 ord, 55 254 unike rimsuffikser, dialektdata |
| `semantics.db` | ~15 MB | 436 780 ordrelasjoner |
| `frequencies.jsonl` | ~80 MB | 2 843 989 frekvensoppføringer |
