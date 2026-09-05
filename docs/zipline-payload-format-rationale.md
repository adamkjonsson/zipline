# Zipline Payload Format — rationale companion (v0.18)

*Why the rules in [the specification](zipline-payload-format.md) are the way they
are: the argument that produced each one, what an earlier version got wrong, and
what was considered and rejected.*

**This document is not normative and states no rule.** Nothing here decides
whether a file is conformant or how a reader computes anything. Where it appears
to disagree with the specification, the specification is right and this is stale.
An implementer needs only the specification; this is for the people who maintain
it and the people reviewing a change to it.

Two consequences of that, both enforced by `vectors/check.py`:

- **It carries no normative keyword.** A rule found here is one the specification
  lost, so the checker fails the build on any. History that needs to recount a
  rule that once bound says so in the past tense, in ordinary words.
- **It is scanned for retired claims**, like the specification and the vector
  suite. A claim the model has abandoned may be *described* here as history, but
  it may not be *asserted*, and the checker cannot tell those apart from the
  wording alone — so the phrasing is the author's responsibility and a deliberate
  quotation is an allowlist entry with a reason attached.

The section structure mirrors the specification's, so a paragraph that moves has
one obvious home and a stable anchor to be linked from. A section stays here even
when it is empty, because an empty section is a question ("does this rule have no
argument, or was it never written down?") and a missing one is not.

---

## Goals

*Why these six and not others; what was considered as a goal and declined.*

## Conceptual model

*Where the model's vocabulary came from, and the readings it was chosen to rule
out.*

## Encoding: two faces of one model

*Why one model has a binary face and a JSON-Lines face rather than one canonical
encoding, and why the projection is lossy in the direction it is.*

## Causal ordering from TCP seq/ack

*Why ordering rests on sequence numbers rather than on timestamps, what the merge
algorithm's cost argument is defending, and what a sequenced file's guarantees
were reasoned from.*

## Layers: transport and decoded live in separate streams

*The argument for a decoded view as a separate stream rather than a layer inside
a record, and the history of how provenance and layer came to be independent.*

## Binary encoding (normative reference)

*Field-layout decisions: what a body field costs against an option, why packed
types state their entry size, and where an alignment choice was forced.*

## Conformance

*Why the error tiers are three, what the advisory strength is buying, and the
defects that produced each rule stated there.*

## Design decisions not taken

*Extensions considered and declined, with the reason each was declined and what
would have to change for it to be reconsidered. This section moves here whole.*

## Prior art this borrows from

*What was taken from each, and what was deliberately not taken.*
