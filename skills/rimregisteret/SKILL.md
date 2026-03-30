---
name: rimregisteret
description: "Norsk rimordbok, freestyle-treningsverktøy, og kunnskapsbase for norsk rim og rap. Bruk når brukeren spør om norske rim, synonymer, fonetikk, freestyle-trening, rapskriving, rimteknikk, eller norsk hip-hop. Gir Claude direkte API-tilgang til 684 000 norske ord med fonetikk."
---

# Rimregisteret — Norsk rimordbok og freestyle-treningsverktøy

Du har tilgang til Rimregisteret-APIet (684 000 norske ord med fonetikk, rim, synonymer og rimklynger). Bruk det aktivt når brukeren spør om norske rim, freestyle, rapskriving, fonetikk eller ordvalg.

---

## A. Norsk fonetikk og rim

### Hvordan norsk rim fungerer

Rim i norsk er **fonetisk, ikke ortografisk**. To ord rimer hvis de har identisk **rimsuffiks** — fonemer fra siste betonte vokal til slutten av ordet.

Eksempler:
- **sol** /suːl/ + **stol** /stuːl/ → begge har rimsuffiks /uːl/ ✓
- **hjerte** /jæ.ʈə/ + **smerte** /smæ.ʈə/ → begge har /æ.ʈə/ ✓
- **natt** /nɑt/ + **hatt** /hɑt/ → begge har /ɑt/ ✓
- **jul** /jʉːl/ + **stol** /stuːl/ → /ʉːl/ ≠ /uːl/ ✗ (ulike vokaler)
- **tid** /tiː/ + **strid** /striːd/ → /iː/ ≠ /iːd/ ✗ (stum d i "tid")

### Tonelag (pitch accent)

Norsk har to tonelag (tonem):
- **Tonelag 1** (↗): enkel stigning — *bønder*, *solen*, *huset*
- **Tonelag 2** (↗↘): stigning etterfulgt av fall — *bønner*, *skolen*, *været*

I skrift spiller tonelag ingen rolle, men i freestyle merkes forskjellen. "bønder" (T1) og "bønner" (T2) har identisk rimsuffiks men ulikt tonelag. Bruk `samme_tonelag=true` for å filtrere.

### Norsk-spesifikke rimegenskaper

**Bøyningsformer** utvider rimfamilier:
- hus/mus → huset/muset → husene/musene (3 rimpar fra ett)
- gate/mate → gaten/maten → gatene/matene

**Retrofleks-assimilasjon** (østnorsk):
- r + n → ɳ (barn /bɑːɳ/, garn /gɑːɳ/)
- r + t → ʈ (fort /fʊʈ/, sort /sʊʈ/)
- r + d → ɖ (gard /gɑɖ/, bord /buːr/)
- r + l → ɭ (karl /kɑːɭ/, perle /pæːɭə/)
- r + s → ʂ (norsk /nɔʂk/, pers /pæːʂ/)

**Stum d og g**:
- "tid" uttales /tiː/ (stum d) — rimer IKKE på "strid" /striːd/
- "dag" uttales /dɑːg/ (g uttales) — rimer på "slag" /slɑːg/

### Dialekter

5 regioner med ulik fonetikk:

| Region | Retroflekser | Eksempel "barn" | Eksempel "skjorte" |
|--------|-------------|----------------|-------------------|
| Østnorsk | ✓ | /bɑːɳ/ | /ʃʊ.ʈə/ |
| Nordnorsk | ✓ | /bɑːɳ/ | /ʃʊ.ʈə/ |
| Trøndersk | ✓ | /bɑːɳ/ | /ʃʊ.ʈə/ |
| Vestnorsk | ✗ | /bɑːrn/ | /ʃʊr.tɑ/ |
| Sørvestnorsk | ✗ | /bɑːrn/ | /ʃʊr.tɑ/ |

Øst/nord/midt deler retroflekser. Vest/sørvest beholder r+konsonant-klynger, noe som gir ulike rimsuffikser og stavelsesstrukturer.

### Nesten-rim

Nesten-rim bruker fonem-ekvivalensklasser:

**Vokal-nærhet** (score +0.6 per match):
- ɑ ↔ ɑː, ɛ ↔ eː, ɪ ↔ iː, ɔ ↔ oː, ʉ ↔ ʉː

**Konsonant-ekvivalens** (score +0.3 per match):
- Stemt/ustemt: b↔p, d↔t, g↔k, v↔f
- Sibilanter: s ↔ ʃ ↔ ʂ ↔ ç
- Retroflekser: ɖ→t, ɳ→n, ɭ→l, ʈ→t

Eksempel: "dag" /dɑːg/ ~ "tak" /tɑːk/ (g↔k ekvivalens, score ~0.9)

### Rimdensitet

Andelen stavelser i en tekst som rimer med en annen stavelse:
- **MF DOOM**: ~43% (ekstremt høy)
- **Eminem**: ~38%
- **Gjennomsnitt rap**: ~25-30%

Høyere densitet = mer komplekst rimarbeid. Tren med brede klynger for å bygge opp arsenalet.

---

## B. Freestyle-trening

### Hvorfor rimklynge-drilling fungerer

fMRI-forskning (Liu et al., Johns Hopkins 2012) viser at erfarne freestylere **deaktiverer dorsolateral prefrontal cortex** (bevisst kontroll) og i stedet bruker **bilateral prosessering** — begge hjernehalvdeler jobber sammen. Rimklynge-trening bygger de nevrale banene som gjør rimhenting automatisk.

### Treningsnivåer

**Nybegynner** (første 1-3 måneder):
- 1-stavelsesord, par-klynger (2-og-2)
- 10 par per økt, 15 min daglig over en beat
- Mål: lær rimfamilier, bygg grunnvokabular
- API: `/rimklynger/par?stavelser=1&antall=10`

**Middels** (3-12 måneder):
- Bland 1- og 2-stavelser, brede klynger (4-og-4)
- 30 min daglig, tren overganger mellom klynger
- Mål: flyt mellom rimfamilier uten pauser
- API: `/rimklynger/bred?antall=10`

**Avansert** (1+ år):
- 3+ stavelser, nesten-rim, bland par og brede
- Daglig freestyle, klynger som oppvarming
- Mål: automatisert rimhenting, fokus på narrativ og punchlines
- API: `/rimklynger/bred?stavelser=3&antall=10`

### Teknikker fra proffene

**Eminem — "Stacking ammo"**: Skriv ord stavelse for stavelse, linje opp rimende stavelser visuelt. Bygg opp et arsenal av multi-stavelsesrim du kan dra frem under battle.

**Juice WRLD — Freehand**: Aldri skriv, bare freestyle. Volum er nøkkelen: 5-10 økter daglig. Ha 3-4 fallback-temaer du kan falle tilbake på når du går tom.

**Battle-rappere — Klynge-drill**: 10 rimklynger à 4 ord, drill over beat. Aldri bruk samme sett to dager på rad — tving hjernen til å koble nye baner.

---

## C. API-referanse

**Base URL**: `https://rimregisteret.no/api/v1`

### Rim

```
GET /api/v1/rim/{ord}
```
Finn perfekte rim — ord med identisk rimsuffiks, sortert etter frekvens.

Parametere: `maks` (int), `stavelser` (int), `tonelag` (1|2), `samme_tonelag` (bool), `dialekt` (øst|nord|midt|vest|sørvest)

```bash
curl "https://rimregisteret.no/api/v1/rim/sol?maks=10"
curl "https://rimregisteret.no/api/v1/rim/hjerte?stavelser=2&dialekt=vest"
curl "https://rimregisteret.no/api/v1/rim/sol?samme_tonelag=true"
```

### Nesten-rim

```
GET /api/v1/nestenrim/{ord}
```
Finn nesten-rim med likhetsscore (0-1).

Parametere: `maks`, `terskel` (float 0.0-1.0), `stavelser`, `tonelag`, `dialekt`

```bash
curl "https://rimregisteret.no/api/v1/nestenrim/dag?terskel=0.6&maks=10"
```

### Synonymer

```
GET /api/v1/synonymer/{ord}
```
Synonymer fra Norwegian WordNet + norsk synonymordbok.

```bash
curl "https://rimregisteret.no/api/v1/synonymer/glad?maks=10"
```

### Antonymer

```
GET /api/v1/antonymer/{ord}
```
Antonymer (motsetningsord).

```bash
curl "https://rimregisteret.no/api/v1/antonymer/billig"
```

### Relaterte ord

```
GET /api/v1/relaterte/{ord}
```
Hypernymer, hyponymer, meronymer, holonymer fra WordNet.

```bash
curl "https://rimregisteret.no/api/v1/relaterte/hund"
```

### Homofoner

```
GET /api/v1/homofoner/{ord}
```
Ord med identisk uttale men ulik stavemåte.

```bash
curl "https://rimregisteret.no/api/v1/homofoner/sol"
```

### Konsonantmatching

```
GET /api/v1/konsonanter/{ord}
```
Ord med samme konsonantskjelett (vokaler stripped).

```bash
curl "https://rimregisteret.no/api/v1/konsonanter/sol"
```

### Ordinfo

```
GET /api/v1/info/{ord}
```
Alt om et ord: IPA, stavelser, tonelag, rimsuffiks, rim, synonymer.

Parametere: `dialekt`

```bash
curl "https://rimregisteret.no/api/v1/info/sol"
curl "https://rimregisteret.no/api/v1/info/barn?dialekt=vest"
```

Respons inkluderer:
- `fonetikk.ipa_ren`: IPA-transkripsjon
- `fonetikk.stavelser`: antall stavelser
- `fonetikk.tonelag`: 1 eller 2
- `fonetikk.rimsuffiks`: fonetisk rimsuffiks
- `fonetikk.g2p`: true hvis estimert (ikke i leksikon)
- `rim`: topp 10 perfekte rim
- `synonymer`: topp 10 synonymer

### Rim i alle dialekter

```
GET /api/v1/rim/{ord}/dialekter
```
Vis hvilke dialekter et rimpar fungerer i.

```bash
curl "https://rimregisteret.no/api/v1/rim/barn/dialekter?maks=10"
```

### Rimklynger

```
GET /api/v1/rimklynger/par    # 2 ord per klynge
GET /api/v1/rimklynger/bred   # 4 ord per klynge
GET /api/v1/rimklynger/dyp    # alle ord fra én rimfamilie
```

Parametere: `antall` (par/bred), `stavelser`, `min_frekvens`, `ord` (startord), `dialekt`

```bash
# 10 tilfeldige rimpar
curl "https://rimregisteret.no/api/v1/rimklynger/par?antall=10"

# 5 brede klynger med 2-stavelsesord
curl "https://rimregisteret.no/api/v1/rimklynger/bred?antall=5&stavelser=2"

# Alle ord som rimer på "natt"
curl "https://rimregisteret.no/api/v1/rimklynger/dyp?ord=natt&min_frekvens=1"

# Klynger i vestlandsk dialekt
curl "https://rimregisteret.no/api/v1/rimklynger/par?dialekt=vest&antall=5"
```

### Autocomplete

```
GET /api/v1/sok?q={prefiks}
```

```bash
curl "https://rimregisteret.no/api/v1/sok?q=sol&maks=10"
```

### Responsformat

Alle endepunkter returnerer JSON:

```json
{
  "ord": "sol",
  "resultater": [
    {"ord": "stol", "rimsuffiks": "uːl", "tonelag": 1, "stavelser": 1, "frekvens": 8.65, "score": 1.0}
  ],
  "antall": 1,
  "dialekt": "øst"
}
```

Rimklynger:
```json
{
  "modus": "par",
  "klynger": [
    {"rimsuffiks": "ɑt", "stavelser": null, "ord": ["natt", "bratt"]}
  ],
  "antall": 1,
  "filter": {"stavelser": null, "min_frekvens": 1.0, "dialekt": "øst", "ord": null}
}
```

---

## D. Bruksmønstre

### Finn rim for et ord
→ `GET /rim/{ord}?maks=20`

### Skriv tekst eller vers
→ Kombiner `/rim/{ord}` for rimord + `/synonymer/{ord}` for alternative ord som bevarer mening.
Eksempel: Trenger rim på "kjærlighet"? Søk rim, men sjekk også synonymer for "kjærlighet" (lidenskap, forelskelse) og søk rim for disse.

### Tren freestyle
→ `/rimklynger/par?stavelser=1&antall=10` (nybegynner)
→ `/rimklynger/bred?antall=10` (middels)
→ `/rimklynger/dyp?ord=natt` (dyp drill på én familie)

### Sjekk uttale og fonetikk
→ `GET /info/{ord}` returnerer IPA, stavelser, tonelag, rimsuffiks, og om ordet er fra leksikon eller G2P.

### Sammenlign om to ord rimer
→ Hent `/info/{ord1}` og `/info/{ord2}`, sammenlign `fonetikk.rimsuffiks`. Like = perfekt rim.

### Dialektspesifikk riming
→ `GET /rim/{ord}?dialekt=vest` for vestlandske rim
→ `GET /rim/{ord}/dialekter` for å se hvilke dialekter et rimpar fungerer i

### Kreative alternativer (for tekstskriving)
1. Søk `/rim/{ord}` for perfekte rim
2. Søk `/nestenrim/{ord}` for nesten-rim (bredere utvalg)
3. Søk `/synonymer/{ord}` for å finne et synonym som har bedre rimord
4. Kombiner: finn synonym → finn rim for synonymet

### Tekstanalyse (rimdensitet, fonetikk)
→ For hvert ord i teksten: hent `/info/{ord}` og analyser rimsuffiks, stavelser, tonelag.
→ Tell antall rimende stavelsespar / totale stavelser = rimdensitet.

### Norsk-spesifikke tips å gi brukeren
- Bøyningsformer trippelrimer: hus/mus → huset/muset → husene/musene
- Norsk har færre enstavelsesord enn engelsk — flerstavelsesrim er mer imponerende
- Tonelag merkes i tale men ikke i skrift
- Retroflekser (øst): "barn"/"garn" rimer. Vest: r-en uttales separat.

---

## Kilder

- Liu et al. (2012), "Neural Correlates of Lyrical Improvisation", Scientific Reports (Johns Hopkins fMRI-studie)
- Hirjee & Brown (2010), "Using automated rhyme detection to characterize rhyming style in rap music", Empirical Musicology Review
- Malmi & Takala (2016), "DopeLearning: A Computational Approach to Rap Lyrics Generation", arXiv
- NB Uttale — Nasjonalbiblioteket, Språkbanken
- Norwegian WordNet — Nasjonalbiblioteket, Språkbanken
