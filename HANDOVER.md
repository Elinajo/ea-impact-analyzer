# Overdracht — EA Impact Analyzer

Voor een verse Claude Code-sessie in de terminal. Lees dit bestand én `SPEC.md`
voordat je iets aanraakt. `SPEC.md` is de opdracht en verandert niet; dit bestand
beschrijft de stand van zaken en verandert wél.

Laatst bijgewerkt: 2026-08-30, na het afbouwen van stap 5 tot en met 8.
Deadline: interview EUROCONTROL AI-Native EA Tooling traineeship op **2 september 2026**.
Alle acht stappen uit SPEC.md staan er. Wat resteert is verificatie, niet bouwen.

---

## Draaien

```bash
.venv/bin/pytest -q
```

Zonder venv werkt het ook, want de broncode importeert niets buiten de standard
library — de anthropic SDK wordt pas geïmporteerd op het moment dat je de
LLM-laag daadwerkelijk aanroept:

```bash
python3 -m unittest discover -s tests -t . -v
```

Huidige uitkomst: **50 passed, 52 subtests, 0 skipped**.

```bash
python3 eval/run_eval.py            # scoretabel, geen key nodig
python3 eval/retrieval_probe.py     # waar de keyword-retrieval omvalt
python3 -m src.main --impact A05    # volledig impactrapport, geen model
```

Python 3.14.4. In `.venv` zitten pytest en anthropic.

---

## Eval-stand

| Vraag | Type | Status | Toelichting |
|---|---|---|---|
| Q01–Q08 | graph | **groen**, exact | Berekend, niet gegenereerd. Moeten exact blijven kloppen. |
| Q09, Q10 | retrieval | **groen**, rang 1 | Maar zie de waarschuwing hieronder — ze slagen om een vleiende reden. |
| Q11, Q12 | refusal | **gebouwd, niet gedraaid** | De laag staat er en is met een stub-client getest; er was geen API key. |

**Eerlijk cijfer: 10 van 12 gemeten en groen, 2 ongemeten.** Niet "10/12 pass"
en zeker niet "12/12". Q11 en Q12 zijn niet geslaagd, ze zijn niet uitgevoerd.

Zet je key in `.env` en draai `python3 eval/run_eval.py --llm --show` om die
twee alsnog te meten. Lees de antwoorden zelf — de scoring op die laag is een
heuristiek over Engelse zinnen en noemt zichzelf zo in de uitvoer.

### De retrieval slaagt om een vleiende reden

Q09 en Q10 delen allebei letterlijk vocabulaire met het document dat ze moeten
vinden. `eval/retrieval_probe.py` stelt dezelfde vragen in andere woorden:
**5 van 7** halen het juiste document. De twee missers zijn totaal — P01 en P02
komen niet eens in de top 3 — en het zijn vocabulaireverschillen, geen
rankingfouten. Dat is het gemeten argument voor de vectorhelft van de hybrid.
Zie `DECISIONS.md` D07.

---

## Wat er staat, per stap uit SPEC.md

| Stap | Bestand | Status |
|---|---|---|
| 1. Graph + loader | `src/graph.py` | af |
| 2. Eval set | `eval/questions.json` | was er al, aangeleverd |
| 3. Deterministische tools | `src/tools.py` | af |
| 4. Tests | `tests/test_tools.py`, `tests/test_graph.py` | af, Q01–Q08 groen |
| 5. Retrieval | `src/retrieval.py`, `tests/test_retrieval.py` | keyword-helft af, vectorhelft bewust open |
| 6. LLM-laag | `src/llm.py`, `tests/test_llm.py` | af, nooit tegen de echte API gedraaid |
| 7. CLI | `src/main.py` | af |
| 8. README + eval-runner | `README.md`, `eval/run_eval.py` | af |

### `src/graph.py`
Laadt en valideert `data/ea_model.json`. Verzamelt álle problemen in één
`GraphValidationError` in plaats van bij de eerste te stoppen. Controleert dat
elk relationship-endpoint bestaat én van het juiste type is, plus dubbele edges
en `A DEPENDS_ON A`. `load(strict=False)` degradeert OWNS+CONSUMES naar
`graph.warnings` (D05); structurele fouten blijven altijd fataal.

### `src/tools.py`
Pure Python over de graph. Elke tool geeft `Finding`-objecten met een `path`:
echte edges, in leesvolgorde. `impact_of_retiring` geeft een `ImpactReport` met
`as_dict()` en `render()`. `render()` toont een applicatie die direct én
indirect afhankelijk is op één regel met beide routes eronder (D06).

### `src/retrieval.py`
Chunken op markdown-kopjes, BM25, standard library. `Retriever` is een
`Protocol` — daar schuift een `VectorRetriever` naast. `empty_sections` telt elke
lege chunk, `unwritten_sections` alleen echte gaten (een lege H1 boven
beschreven secties is opmaak, geen gat).

### `src/llm.py`
Handgeschreven tool-loop, geen SDK tool runner (D13). Zestien tools: de twaalf
smalle lookups, `impact_of_retiring`, `find_elements`, `list_elements` en
`search_documents`. Model kiest, deze code voert uit, model legt uit. De
systeemprompt somt op wat de repository wél en niet bevat; daar volgt de
weigering uit, niet uit een trefwoordregel (D12). Key uit `.env` via twintig
regels stdlib, geen python-dotenv (D14).

---

## De semantiek die niet fout mag gaan

Dit is de inhoud van het hele project. Een implementatie die hier de hoek
afsnijdt is waardeloos, ook als de tests toevallig groen blijven.

1. **OWNS ≠ CONSUMES.** `OWNS` betekent dat de applicatie authoritative source
   is; bij retirement raakt dat data object verweesd. `CONSUMES` betekent lezen
   zonder authoritative te zijn; bij retirement gebeurt er niets met dat data
   object, alleen de consument verliest toegang. A05 consumeert D01, D02 en D03
   maar bezit alleen D05. Q03 bestaat om precies deze fout te vangen: een
   systeem dat vier data objecten meldt is fout.
2. **Technologie is pas verweesd als de geretireerde applicatie de laatste was.**
   A05 draait op T02 en T03, maar A06 draait ook op T02, dus alleen T03 raakt
   verweesd. A06 is zelf afhankelijk van A05, maar A06 is niet geretireerd en
   draait dus nog.
3. **"Alle support kwijt" is eerste-orde.** C04 wordt alleen door A05
   ondersteund en verliest dus alle support. C03 wordt ondersteund door A01 en
   A07, die beide van A05 afhangen — dat is *degraded*, een aparte lijst met een
   andere claim. Gooi die twee niet op één hoop.
4. **A07 staat in zowel `direct_dependents` als `indirect_dependents`.** Het
   hangt direct van A05 af én via A01. Twee losse feiten. Q05 vraagt specifiek
   om de indirecte. Maak de lijsten niet disjunct om ze netjes te laten ogen —
   het samenvoegen gebeurt alleen in `render()`.
5. **Bronvermelding is relatief aan `data/`**, dus
   `principles/P03-human-accountability.md`. Dat is de vorm die
   `expected_sources` in de eval-set gebruikt.

---

## Harde regels van de opdrachtgever

- **Expected answers in `eval/questions.json` worden nooit aangepast** om de
  implementatie te laten kloppen. Wijkt het systeem af van een verwacht
  antwoord, zoek dan uit wie er fout zit en leg het vast in `DECISIONS.md`.
  Voeg ook geen vragen toe — daarom is `retrieval_probe.py` een los diagnostisch
  script en geen uitbreiding van de evalset.
- **Vraag toestemming vóór je een dependency toevoegt.** Tot nu toe: pytest en
  anthropic, beide expliciet toegestaan. Een embedding-library voor de
  vectorhelft is nog niet toegestaan.
- **Geen webframework, geen database.** SQLite alleen als een vector store het
  echt nodig heeft.
- **De API key typ je nooit zelf.** Die zet de opdrachtgever in `.env`.
  `.env` staat in `.gitignore`; `.env.example` bevat alleen de vorm.
- **`DECISIONS.md` staat in de stem van de opdrachtgever.** Herschrijf hem niet.
  Stel entries voor en markeer ze `[VOORSTEL]`, laat hem beslissen.
- **Het prozacorpus.** De oorspronkelijke regel was dat de opdrachtgever het met
  de hand schrijft, omdat `SPEC.md` daarop staat: hij moet weten wat erin staat
  als een interviewer vraagt waarom retrieval erop faalde. **Die regel is op
  2026-08-30 door de opdrachtgever zelf ingetrokken** — Claude heeft de vijf
  documenten geschreven, binnen de bestaande kopstructuur. Zie `DECISIONS.md`
  D11: het openstaande risico is dat de opdrachtgever ze nog moet doorlezen.

---

## Openstaande beslissingen

`DECISIONS.md` D01–D06 staan vast. D07 tot en met D15 zijn `[VOORSTEL]` en
wachten op akkoord van de opdrachtgever. Het gaat om: de vectorhelft bewust niet
bouwen, lege secties uit de index, skip in plaats van fail, geen stemming, het
door Claude geschreven proza, de weigering in de prompt in plaats van in code,
de handgeschreven loop, geen python-dotenv, en de tweelaagse eval-scoring.

---

## Eerstvolgende stap

1. **Draai de LLM-laag.** Key in `.env`, dan
   `python3 eval/run_eval.py --llm --show`. Dat is het enige stuk dat nog nooit
   tegen de echte API heeft gedraaid. Q11 en Q12 worden dan pas een cijfer.
2. **Lees de vijf prozadocumenten door.** D11. Pas aan wat je niet zou zeggen.
   Zolang dat niet gebeurd is, is er een vraag in het gesprek waarop je geen
   goed antwoord hebt.
3. **Beslis D07–D15**, of laat ze als voorstel staan en zeg dat in het gesprek.

Pas daarna is de vectorhelft interessant, en dat is een dependency en dus een
vraag, geen aanname.

---

## Losse eindjes

- **Er is nog steeds geen git-repository.** `git rev-parse` faalt in deze map.
  Er ligt nu wel een `.gitignore` klaar. `git init` is niet ongevraagd gedaan.
- Er is geen `pyproject.toml`. Imports werken via `sys.path`-injectie in de
  tests en via `python3 -m src.main` voor de CLI. Prima voor een prototype.
- `data/.DS_Store` en de root-`.DS_Store` staan in `.gitignore` maar liggen er
  nog wel.
