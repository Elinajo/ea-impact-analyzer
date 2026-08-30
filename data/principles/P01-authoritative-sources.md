# P01 — Authoritative sources

## Statement
Every data object has exactly one designated authoritative source, and that designation is recorded in the architecture model.

## Rationale
When two systems can both claim to be right about the same data, a disagreement between them cannot be settled by looking at the data. It can only be settled by knowing which system was supposed to be believed. Where that is not recorded, the knowledge lives with whoever happened to be present when the interface was built, and operational staff reconcile the difference by hand. The reconciliation then becomes invisible to architecture, which sees two healthy systems and no problem.

Designating one source per data object turns a recurring operational argument into a decision taken once, written down, and revisited deliberately. It also gives change a defined blast radius. A system that owns data cannot be withdrawn without a successor for that ownership. A system that only reads data can be withdrawn without touching the data at all: the data keeps its owner, and only the consumer loses access. That distinction is what makes retirement impact something to be analysed rather than argued about.

## Implications
Every data object in the model carries an ownership relationship to exactly one application. Systems that read data they do not own record that as consumption. Consumption confers no authority, and a consumer is never an implicit fallback source. Where two systems hold records of the same kind, one is designated authoritative and the other's copy is treated as derived, with the derivation recorded.

Retiring an application that owns a data object requires a named successor owner before the retirement is approved. Migrating the data is not sufficient on its own — the designation has to move with it, and someone has to accept it.

## Applies to
New systems that introduce a data store; interfaces that copy or replicate data between systems; any proposal to retire or replace an application. It is the principle tested whenever an impact analysis reports that a data object would be left without an authoritative source.
