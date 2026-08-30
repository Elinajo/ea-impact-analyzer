# ADR-002 — Shared data platform

## Status
Accepted, September 2023.

## Context
Operational data was distributed point to point. Flight, weather and surveillance data reached their consumers over separate bilateral feeds, built at different times to different conventions. Adding a consumer meant negotiating with each producer in turn, and the same data arrived at two systems in two shapes, with no agreed answer as to which was current.

Two failures made the position untenable. A surveillance schema change was released without one downstream consumer knowing, because no producer held a complete list of who was reading. A capacity analysis was then run twice against feeds that had drifted apart, and the difference went unnoticed for a fortnight.

P02 already required standard interfaces. What it did not settle was whether every producer publishes its own, or whether operational distribution is consolidated.

## Decision
Operational data distribution is consolidated into a shared operational data platform. Producers publish to the platform; consumers subscribe to it rather than to each other. The platform is the authoritative source for operational events, which it originates, and a consumer — not an owner — of the flight, weather and surveillance data it redistributes.

## Alternatives considered
**Per-producer interfaces, no shared platform.** Each producer publishes its own interface under P02, with no central component. Rejected: it satisfies the letter of P02 but leaves the consumer register fragmented, which is what caused both failures.

**A message bus with no ownership semantics.** Transport only, with producers and consumers agreeing formats between themselves. Cheaper and less coupling, but it moves the drift problem rather than solving it — nothing would make the authoritative source explicit.

## Consequences
Adding a consumer is now a single negotiation. The consumer register is complete, and schema changes have a known audience.

The accepted cost is coupling. A component everything subscribes to is a component everything depends on. We are choosing one shared dependency over a tangle of bilateral ones, on the grounds that a visible dependency is easier to manage than twelve invisible ones. This is a deliberate trade, not an oversight.

Two consequences follow. Platform availability becomes an operational concern for every subscriber, so it is treated as a critical service. And replacing the platform later will be substantially harder than replacing any single feed: a replacement must satisfy every subscriber at once and take over authority for operational events. We judge that acceptable, on the understanding that the dependency is recorded in the architecture model and so is visible when that day comes.
