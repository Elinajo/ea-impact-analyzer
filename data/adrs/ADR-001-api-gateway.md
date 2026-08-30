# ADR-001 — API gateway

## Status
Accepted, March 2023.

## Context
External access to our systems had grown one connection at a time. Partner organisations reached four different applications directly, each with its own authentication scheme, its own rate limiting or none, and its own access logging in its own format. Answering "who is currently reading our surveillance data" required asking four teams and trusting four answers.

The immediate trigger was an audit finding: we could not produce a consolidated record of external access within the period the auditor asked for. The underlying problem was that P02 was being applied to internal integration but had never been made concrete for access from outside.

## Decision
All external access to our systems is routed through a single API gateway. Applications do not accept connections from outside the organisation directly. The gateway performs authentication, authorisation, rate limiting and access logging; the application behind it enforces its own domain rules and trusts the gateway for identity.

## Alternatives considered
**Per-application gateways.** Each system keeps its own edge, with a common specification for the controls. Rejected: the specification would drift, and the consolidated access record — the thing the audit asked for — would still have to be assembled from several sources.

**A managed service from the cloud provider.** Cheaper to operate and quicker to stand up, but the access control model we need does not map onto it cleanly, and it would place the record of external access outside our own retention arrangements.

**Do nothing, document the existing connections.** Honest about the cost, but the register would be stale within a release cycle, because nothing would prevent the next direct connection being added.

## Consequences
External access is now countable, and access policy is changed in one place instead of four.

The gateway is on the critical path for every external interaction, which makes it a single point of failure and a shared release constraint: several applications are now on the same technology, and an outage or upgrade affects all of them at once. It is deliberately kept thin for this reason — routing, identity and logging only, with no business logic — so that changes to it stay rare.
