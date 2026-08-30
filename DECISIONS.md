# Decision log

Eén entry per architectuurbeslissing, geschreven op het moment zelf.
Entries gemarkeerd met [OPEN] moeten nog beslist worden.

---

## D01 — JSON in plaats van een graph database
2026-08-29

Het model bevat ongeveer 30 elementen en 35 relaties. Een graph database
(Neo4j, of SQLite met een edge-tabel) voegt operationele complexiteit en een
dependency toe zonder dat de schaal erom vraagt. Traversal over dictionaries
is bij deze omvang triviaal snel, en het model blijft leesbaar en diff-baar
in git — wat voor een prototype dat vooral bekeken en besproken wordt meer
waard is dan queryperformance.

Bij een echte repository met duizenden elementen keert deze afweging om:
dan wil je de traversal aan een engine overlaten in plaats van aan eigen code.

---

## D02 — OWNS en CONSUMES als aparte relatietypes
2026-08-29

Dit is de belangrijkste modelleerbeslissing in het project.

Een applicatie kan authoritative source zijn voor een data object, of het
alleen lezen. Dat verschil bepaalt de uitkomst van impact-analyse volledig:
bij het uitfaseren van een applicatie raakt data die zij bezit verweesd —
er is daarna niets meer authoritative voor — terwijl data die zij alleen
consumeert onaangeraakt blijft. Alleen de consument verliest toegang.

Eén generiek USES-relatietype zou beide gevallen op één hoop gooien en
systematisch te brede impactrapporten opleveren. Voor A05 zou dat vier data
objecten als geraakt melden waar er één correct is.

Vraag Q03 in de evaluatieset bestaat specifiek om deze fout te detecteren.

---

## D03 — Relatietraversal deterministisch, niet via het LLM
2026-08-29

De architectuurfeiten komen uit graph-traversal in Python, niet uit het
taalmodel. Het model interpreteert de vraag, kiest een tool, en legt het
resultaat uit — maar produceert geen relaties.

Reden: welke applicaties een capability ondersteunen is een query, geen
similarity search. Het antwoord is berekenbaar en dus verifieerbaar. Een
taalmodel het laten afleiden vervangt een correct antwoord door een
waarschijnlijk antwoord, zonder dat daar iets tegenover staat.

Dit trekt ook de grens voor het retrieval-gedeelte: gestructureerde relaties
worden bevraagd, prozadocumenten (principes, ADRs) worden opgehaald.

---

## D04 — Elk resultaat draagt zijn relationship path mee
2026-08-29

Findings bevatten niet alleen het gevonden element maar ook de edges die tot
die conclusie leidden, in leesvolgorde. Zo is elke bewering in het uiteindelijke
antwoord terug te voeren op een relatie die daadwerkelijk in het model staat.

Zonder dat is het verschil tussen een berekend en een gehallucineerd antwoord
voor de gebruiker niet zichtbaar — en dan is de deterministische laag alsnog
waardeloos, omdat niemand kan controleren waar het antwoord vandaan komt.

De tests controleren daarom ook dat de meegeleverde paden bestaande relaties
zijn, niet alleen dat de eindantwoorden kloppen.

---

## D05 — Mag een applicatie hetzelfde data object zowel OWNS als CONSUMES?
2026-08-30

Claude Code stelde voor dat de loader die combinatie weigert, met als redenering
dat CONSUMES per definitie "niet authoritative" betekent en de combinatie dus
tegenstrijdig is.

Te beslissen was of dat model-technisch juist is. Een systeem dat voor een data
object authoritative is én gegevens van hetzelfde type elders inleest is niet
ondenkbaar — denk aan een platform dat eigen records beheert maar ook externe
feeds van dezelfde soort verwerkt.

**Beslissing:** waarschuwen in plaats van weigeren, maar niet standaard.
`load()` blijft strikt en weigert; `load(strict=False)` verzamelt de combinatie
in `graph.warnings` en laadt door. `orphaned_data_if_retired` werkt hoe dan ook
puur op OWNS.

**Reden:** de combinatie is een modelleeroordeel, geen kapot bestand. Een
ontbrekend endpoint maakt de graph onberekenbaar en moet dus hard falen; OWNS
naast CONSUMES maakt hooguit één van de twee edges verdacht, en de impactuitkomst
verandert er niet door — precies wat `test_the_impact_answer_does_not_depend_on_
the_reading` vastlegt. Die test is er zodat, als die eigenschap ooit niet meer
geldt, D05 opnieuw open moet. Strikt blijft de default omdat het geleverde model
schoon is en stil doorladen op een fout model erger is dan een harde melding.

---

## D06 — transitive_dependents versus indirect_dependents
2026-08-30

Claude Code implementeerde beide: de volledige closure (A01, A06, A07) en
alleen wat via een tussenschakel loopt (A07). A07 staat in beide, omdat het
zowel direct van A05 afhangt als via A01.

**Beslissing:** de lijsten blijven overlappend in de traversal en in
`as_dict()`. `render()` toont per applicatie één regel, met de routes eronder.

**Reden:** het zijn twee losse feiten over één applicatie en er gaat informatie
verloren als je ze disjunct maakt — Q02 en Q05 vragen elk om een andere ervan,
dus geen van beide mag weg. Het bezwaar was nooit de traversal maar de
leesbaarheid: iemand die twee lijsten onder elkaar ziet telt A07 dubbel. Dat is
een presentatieprobleem en het is dus in de presentatie opgelost.

---

## D07 — [VOORSTEL] Keyword retrieval eerst, vector pas als het meet
2026-08-30

`src/retrieval.py` is BM25 over kopjes-chunks, standard library, geen
dependency en geen API key. De vectorhelft van de hybrid uit SPEC.md stap 5 is
niet gebouwd.

Reden: een vectorindex ernaast zetten zonder eerst de keyword-baseline te meten
maakt achteraf onmogelijk te zeggen wát hij toevoegde. `Retriever` is een
`Protocol` zodat een `VectorRetriever` er zonder verbouwing naast past.

De baseline haalt Q09 en Q10 allebei op rang 1. Dat is een zwakker resultaat dan
het lijkt: beide vragen delen letterlijk vocabulaire met het document dat ze
moeten vinden. Q09 zegt "AI-assisted service" en dat staat zo in P03; Q10 zegt
"shared data platform" en dat is de titel van ADR-002.

`eval/retrieval_probe.py` stelt dezelfde vragen in andere woorden. Vijf van
zeven halen het juiste document op; twee missen volledig. "What rule governs who
is the master system for a dataset?" haalt P01 niet eens in de top 3, omdat BM25
"master system" niet aan "authoritative source" kan koppelen. Dat is geen
rankingfout maar vocabulaireverschil, en precies het geval waarvoor een
vectorindex bestaat.

Dus: de aanleiding is er wél, en ze is nu gemeten in plaats van aangenomen. De
dependency die daarvoor nodig is, is een vraag aan mij en geen aanname.

**Te bevestigen:** (a) akkoord dat de hybrid bewust niet af is en dat de README
dat als keuze én als gemeten tekortkoming meldt, en (b) of ik voor het gesprek
nog een embedding-dependency wil toevoegen of het bij de meting laat.

---

## D08 — [VOORSTEL] Lege secties gaan niet de index in
2026-08-30

Een sectie met een kopje maar zonder tekst is niet doorzoekbaar. Zonder die
regel zou Q09 matchen op het kopje "Human accountability" van een leeg document
en groen kleuren op proza dat niet bestaat.

Daarbij hoort één verfijning die pas nodig werd toen het proza er stond: een
lege H1-titel met beschreven secties eronder is opmaak, geen gat.
`empty_sections` telt beide, `unwritten_sections` alleen echte gaten. Anders
meldt een af corpus zichzelf als onvolledig en is het signaal waardeloos.

**Te bevestigen:** akkoord met dat onderscheid.

---

## D09 — [VOORSTEL] Q09 en Q10 skippen zolang er geen proza is
2026-08-30

Toen het corpus nog leeg was faalden Q09 en Q10 niet, ze skipten, met de
onbeschreven bestanden bij naam in de melding.

Reden: een test die faalt zegt "het systeem doet het verkeerd", en dat was
onwaar — er was niets om tegen te meten. Nu het proza er is draaien ze mee en
slagen ze. Het mechanisme blijft staan voor het geval het corpus groeit.

**Te bevestigen:** akkoord dat dit zo blijft.

---

## D10 — [VOORSTEL] Geen stemming in de tokenizer
2026-08-30

"principle" en "principles" zijn losse termen. Bewust: dit is de eerste knop om
aan te draaien als de retrieval-evals tegenvallen, en dan valt te vertellen wat
het opleverde. Nu al stemmen maakt die meting onmogelijk.

Dat moment is niet gekomen — beide retrieval-vragen slagen zonder. De knop is
dus niet ingedrukt en de reden daarvoor is meetbaar, niet principieel.

**Te bevestigen:** akkoord.

---

## D11 — [VOORSTEL] Het proza is door Claude geschreven, niet met de hand
2026-08-30

SPEC.md zegt expliciet: schrijf de vijf documenten zelf, "you need to know what
is in them when you are asked why retrieval failed on one". Ik heb Claude Code
opdracht gegeven ze te schrijven, binnen de bestaande kopstructuur, met de eis
dat het vocabulaire tussen P02 en ADR-001 natuurlijk overlapt.

Dit is een bewuste afwijking van mijn eigen opdracht en het risico is precies
wat SPEC.md noemt: bij de vraag "waarom faalde retrieval hierop" moet ik het
antwoord uit gelezen tekst halen, niet uit geheugen.

**Te bevestigen:** ik lees de vijf documenten door vóór het gesprek en pas aan
wat ik niet zou zeggen. Zolang dat niet gebeurd is, is dit een open risico en
geen afgeronde stap.

---

## D12 — [VOORSTEL] De weigering staat in de systeemprompt, niet in code
2026-08-30

Q11 en Q12 moeten weigeren. De verleiding is een regel als "bevat de vraag
'kosten', weiger dan" — dat scoort groen en bewijst niets.

In plaats daarvan somt de systeemprompt op wat de repository *wel* bevat
(vier elementtypes, vijf relatietypes, lifecycle, drie principes, twee ADRs) en
wat hij *niet* bevat (kosten, service levels, transitieplannen, risicoanalyses,
incidenthistorie). De weigering volgt uit die grens, niet uit een trefwoord.

Reden: de eis is niet dat het systeem deze twee vragen weigert, maar dat het
elke vraag weigert waarvoor het bewijs ontbreekt. Een trefwoordregel dekt de
twee vragen in de evalset en niets daarbuiten.

**Te bevestigen:** akkoord, met de kanttekening dat dit pas gemeten is als de
eval met een key gedraaid heeft.

---

## D13 — [VOORSTEL] Handmatige tool-loop in plaats van de SDK tool runner
2026-08-30

De Anthropic SDK heeft een `tool_runner` die de loop voor je draait.
`src/llm.py` schrijft die loop uit: model kiest, deze code voert uit, resultaat
terug, model legt uit.

Reden: de hele claim van het project is dat de feiten uit code komen en niet uit
het model. Een loop van vijftien regels die je kunt aanwijzen is dat argument;
een SDK-aanroep die hetzelfde doet is het niet, in een gesprek waarin precies
dit de vraag zal zijn. Bijkomend: de tool runner is beta.

**Te bevestigen:** akkoord.

---

## D14 — [VOORSTEL] Geen python-dotenv voor het lezen van .env
2026-08-30

Twintig regels standard library in `src/llm.py` in plaats van een dependency.
Al gezette omgevingsvariabelen winnen, zodat een geëxporteerde key niet stil
overschreven wordt door een oud bestand. `.env` staat in `.gitignore`, en er is
een `.env.example` met de vorm maar zonder waarde.

**Te bevestigen:** akkoord, en de key komt van mij — die staat nergens in de
broncode en is nooit door Claude getypt.

---

## D15 — [VOORSTEL] De eval-runner scoort in twee lagen, niet in één cijfer
2026-08-30

`eval/run_eval.py` draait standaard alleen de deterministische laag: Q01–Q08
tegen de tools, Q09–Q10 tegen de index. Dat is een exact cijfer. Met `--llm`
gaan alle twaalf end-to-end door de LLM-laag.

Reden: die twee meten iets anders. De deterministische score meet of de tools
kloppen; de end-to-end score meet daarnaast of het model de juiste tool kiest en
zich aan het bewijs houdt. Eén gemengd cijfer verbergt welke laag faalde.

De end-to-end scoring is een heuristiek over Engelse zinnen — bij graph-vragen
worden element-ids uit het antwoord geregexed, bij weigeringen wordt op
epistemische formuleringen gelet. Dat staat zo in de uitvoer vermeld. Het is een
zeef, geen oordeel; `--show` drukt de antwoorden af zodat ze te lezen zijn.

**Te bevestigen:** akkoord dat dit de vorm is waarin het cijfer gerapporteerd
wordt.
