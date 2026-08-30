# P02 — Standard interfaces

## Statement
Information is exposed through standard, published interfaces, not through direct system-to-system access.

## Rationale
Point-to-point connections are cheap to build and expensive to own. Each one embeds assumptions about the other system's internals — its schema, its release cycle, its availability window — somewhere nobody looks until something breaks. The cost is invisible at the moment the connection is made and arrives years later, as a change that cannot be made because an unknown number of consumers depend on the current shape of the data.

A standard interface makes the dependency explicit and gives it a contract. Consumers depend on the published interface rather than on the provider's internals, so a provider can change how it works without renegotiating with every consumer individually. It also makes the dependency countable: an interface has a register of consumers, whereas a direct database connection has whoever holds the credentials.

External access is routed through the API gateway for the same reason, with the added one that authentication, authorisation, rate limiting and access logging are then applied consistently instead of being reimplemented, differently, per connection.

## Implications
New integrations publish an interface rather than opening a database account or arranging a file drop. Direct reads against another system's data store are not approved for new work, and existing ones are recorded as technical debt with a route to an interface.

Interfaces are versioned, and a breaking change requires a period in which both versions are available. Consumers are registered against the interface they use, so the provider knows who is affected before it changes anything.

An interface is not a substitute for ownership. Exposing a data object through a standard interface says nothing about who is authoritative for it — that is recorded separately, under P01.

## Applies to
New integrations between applications; proposals to grant a system direct access to another system's data store; any exposure of information outside the organisation, which additionally goes through the API gateway under ADR-001.
