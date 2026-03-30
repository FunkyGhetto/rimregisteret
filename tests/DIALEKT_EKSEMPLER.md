# Dialektforskjeller som påvirker rim

## Oversikt over dialektregioner

| Kode | Region | Fil-prefiks | Retroflekser |
|------|--------|-------------|-------------|
| øst | Østnorsk (standard) | e | Ja |
| nord | Nordnorsk | n | Ja |
| midt | Trøndersk | t | Ja |
| vest | Vestnorsk | w | Nei |
| sørvest | Sørvestnorsk | sw | Nei |

## Hovedforskjell: Retrofleks-assimilasjon

Den viktigste dialektforskjellen som påvirker rim er **retrofleks-assimilasjon**.
I østnorsk, nordnorsk og trøndersk smelter r + dental sammen til én retrofleks:

| Bokstav | Øst/Nord/Midt | Vest/Sørvest |
|---------|--------------|-------------|
| rn | ɳ | rn |
| rd | ɖ | rd |
| rl | ɭ | rl |
| rt | ʈ | rt |
| rs | ʂ | rs |

## Konkrete eksempler

### 1. barn (ɑːɳ vs ɑːrn)

| Dialekt | IPA | Rimsuffiks |
|---------|-----|-----------|
| øst/nord/midt | bɑːɳ | ɑːɳ |
| vest/sørvest | bɑːrn | ɑːrn |

Konsekvens: «barn» har forskjellige rim i øst vs vest.

### 2. skjorte/borte — Rimer i øst, ikke i vest

| Ord | Øst-suffiks | Vest-suffiks |
|-----|-----------|------------|
| skjorte | ʊ.ʈə | ʊr.tɑ |
| borte | ʊ.ʈə | ʊr.tə |

- **Østnorsk**: Begge har suffiks `ʊ.ʈə` → **perfekt rim**
- **Vestnorsk**: Forskjellige sluttvokal (`ɑ` vs `ə`) → **ikke rim**

### 3. ferdig/verdig — Rimer i vest, ikke i øst

| Ord | Øst-suffiks | Vest-suffiks |
|-----|-----------|------------|
| ferdig | æ.ɖɪ | ær.dɪ |
| verdig | ær.dɪ | ær.dɪ |

- **Østnorsk**: «ferdig» har retrofleks ɖ, «verdig» har rd → **ikke rim**
- **Vestnorsk**: Begge har `ær.dɪ` → **perfekt rim**

### 4. fort/sort — Rimer i begge

| Ord | Øst-suffiks | Vest-suffiks |
|-----|-----------|------------|
| fort | ʊʈ | ʊrt |
| sort | ʊʈ | ʊrt |

Begge ord endrer seg likt → rimer i alle dialekter.

### 5. norsk/torsk — Rimer i begge

| Ord | Øst-suffiks | Vest-suffiks |
|-----|-----------|------------|
| norsk | ɔ.ʂk | ɔrsk |
| torsk | ɔ.ʂk | ɔrsk |

Begge har rs→ʂ i øst og bevart rs i vest → rimer overalt.

## Sørvest-spesifikke forskjeller

Sørvestnorsk har i tillegg forskjeller i trykklette vokaler:

| Ord | Vest | Sørvest |
|-----|------|---------|
| bakeren | bɑː.kə.rən | bɑː.kɑ.rən |
| skjorte | ʃʊr.tə (?) | ʃʊr.tɑ |

Trykklett `ə` erstattes ofte med `ɑ` i sørvest, som kan bryte rim
mellom vest og sørvest for flerstavelesord.

## Dialektgruppering

I praksis danner dialektene to hovedgrupper for rim:

**Gruppe 1 (retroflekser):** øst, nord, midt
- Identiske rimsuffikser for de aller fleste ord
- Retrofleks-assimilasjon: r+dental → én lyd

**Gruppe 2 (bevart r-kluster):** vest, sørvest
- Beholder r + konsonant som separate lyder
- Flere stavelser i noen ord (bakeren: 2 syl → 3 syl)
- Sørvest skiller seg fra vest med trykklette vokaler

## Database-design

Dialektdata lagres i tabellen `ord_dialekter`:
- Kun ord som **avviker** fra østnorsk lagres
- Østnorsk-data ligger i hovedtabellen `ord`
- Ved oppslag faller systemet tilbake til østnorsk hvis ingen dialekt-entry finnes

| Dialekt | Avvikende oppføringer | Andel |
|---------|----------------------|-------|
| nord | 179 464 | 26% |
| midt | 170 689 | 25% |
| vest | 303 739 | 44% |
| sørvest | 270 208 | 39% |

Vest og sørvest har flest avvik fordi de mangler retroflekser.
