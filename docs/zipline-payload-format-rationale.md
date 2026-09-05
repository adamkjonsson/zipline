# Zipline Payload Format — rationale companion (v0.19)

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

**Why provenance and layer were split into two axes in `0.15`.** `decoder_id` was
doing two jobs — *what produced this and what is it*, and *which offset-space
semantics apply* — and a reassembler wants the first while wanting **transport**
for the second. One field could not say that, so a sessionization stage was
characterised by the *absence* of `decoder_id`, purely because absence was the
only way to say "hole-inclusive, `isn`-anchored". Its configuration then had
nowhere to live and the layer it created had no name.

**What the four-cell table's bottom-left corner cost before that.** A rule that
inferred "decoded" from "derived" left a TLS-terminating proxy's output with no
honest encoding at all: its decoded records have no predecessor `.zpf` and never
will.

## Encoding: two faces of one model

*Why one model has a binary face and a JSON-Lines face rather than one canonical
encoding, and why the projection is lossy in the direction it is.*

## Causal ordering from TCP seq/ack

**Why recording the sequencing basis is unconditional while soundness may be
trivial.** Keeping the recording unconditional is what makes the rule decidable at
the moment it has to be applied. `SEQUENCED` is written on the Session Descriptor,
which declare-on-first-use places *before* the session's records, so a streaming
producer cannot yet know whether only one participant will ever send. It can
always know what it is relying on.

**The same asymmetry settles a question the rule otherwise raises.** Whether a
session is hint-less is a property of its records, which the producer cannot
confirm when it writes the descriptor either — and it does not need to, because it
decides by what it is relying on. Only the reader, which cannot see the producer's
reasoning, has to wait until Session End.

**Why the basis is required rather than merely permitted.** It puts the obligation
where the knowledge is: a producer that has to name a basis has to decide what the
basis *is* at the moment it sets the bit. `SEQUENCED` is a strong assertion, not a
default.

## Layers: transport and decoded live in separate streams

**Why an unplaceable record sits at a running maximum rather than where the
previous record ended.** Stating the weaker of the two would leave an unplaceable
record inside a range already covered, and two readers taking the two readings
would disagree about the offset space — which is the disagreement the rule exists
to end.

**Why zero width is the safe placement.** A record the reader cannot place is one
whose bytes it cannot attribute to any offset, and a zero-width range is the only
claim that stays true whatever the writer meant.

## Binary encoding (normative reference)

*Field-layout decisions: what a body field costs against an option, why packed
types state their entry size, and where an alignment choice was forced.*

### Undecoded (`0x21`)

**Why a hole may not be declared against a capture.** The rule is that only the
bytes-exist class is available there. The reason is that declaring the hole again
would be a second account of the same missing bytes with no rule for which to
believe — the transport offsets already carry the segment's extent, so the block
would contradict them. It is the same contradiction that bars a
[Discontinuity](zipline-payload-format.md#discontinuity-0x22) from a transport
stream.

**Why the capture-source permission is not keyed on the layer.** A block naming a
capture is purely declarative, so there is nothing for a layer test to protect. A
reassembler declares an overlap it dropped; a decode stage reading a capture
directly declares a region it could not parse. Both are honest, and neither is
answerable to a guarantee that has nothing to bind to.

**Why the canonical hole word is plain `gap`.** A hole is the same object whether
it was found from TCP sequence numbers, an SCTP TSN, an RTP sequence number, or an
application protocol's own counter. Naming the transport in the word would put the
same fact in two places, and the session's `proto` already carries it.

**Why `skipped` had to exist at all.** The
[coverage guarantee](zipline-payload-format.md#coverage-honesty-undecoded-blocks)
leaves a decoder no honest third option. Without `skipped`, a decoder that ignores
a byte-order mark has to either stretch a record's `spans` across a region no
output unit corresponds to, or report the region `undecodable` — asserting a
failure that did not occur.

**Why `dropped` was split out of `skipped` in `0.17`.** Before that release both
cases wrote the same word, and two byte-identical files — one where the survivors
join and one where they do not — were indistinguishable to every consumer and
every checker. Keeping the two apart also keeps `undecodable` usable as a
decoder-quality signal: a consumer counting unparsed bytes should not have
deliberate skips folded into the total.

**Why an open vocabulary still owes a class.** The vocabulary is open precisely so
a producer can be more specific than the five canonical words. Requiring
`reason_class` alongside a non-canonical word is what keeps that freedom from
costing the consumer its one actionable fact — whether the bytes can be fetched at
all.

**Why a broken chain and an empty region must be reported differently.**
Collapsing the second into the first is the exact silent data loss the coverage
guarantee exists to prevent: the consumer would assert that nothing was there,
having established only that it could not look.

### Discontinuity (`0x22`)

**Why the output space needs its own marker at all.** Absent the block, a decode
stage's output space is just the concatenation of its record payloads, so two
records either side of an input gap are *adjacent* in it — the gap does not
survive the layer. Nothing obliges a decode stage to re-emit its input's Undecoded
blocks, that duty falling on pass-throughs, so on the chain
`capture → tls-records → http` one lost TCP segment under TLS leaves the HTTP
stage free to emit a single message spanning the join, covering it completely,
with coverage passing and no marker anywhere in the file the consumer is reading.
The information survives only in principle, by walking down to the
capture-sourced file and noticing a gap between two stage-1 spans — which nothing
states as an invariant and no checker tests. The block is what makes the break
visible where it is read.

**Why an absent `width` contributes 0 rather than making later offsets
undefined.** Declaring them undefined would end a chain at its first lost record,
and a consumer would lose the whole remainder of a stream rather than one hole in
it.

**Why the transport-layer withholding rule had to be written down.** Before
`0.15` it cost nothing to say, because a transport stream was a capture's
reassembled output and nothing dropped from it. A stage may now declare
`output_layer = transport` and filter, which is what makes the rule necessary.

**Why `dropped` is decidable and the other bytes-exist words are not.** It is the
producer's own statement that content was removed, not an inference from the
reason word. `skipped` is the byte-order-mark case, where the survivors join, and
`undecodable` says a parse failed without saying whether anything of the stream
went with it.

**Why each clause of the seam predicate is there.** Read against the predicate as
the specification states it:

- **Decoded-layer only**, because a transport stream expresses the same break in
  its offsets and is forbidden the block. A checker without that clause rejects a
  conformant sessionization stage.
- **Cited by both**, because a unit may span several input streams, and fan-out
  means adjacent units may cite different ones. A stream only one of them names
  says nothing about whether they join.
- **Max and min**, because spans may overlap, which has been legal since `0.14`.
- **`A ≥ B` not tested**, because a stage that reorders or overlaps its input
  produces pairs whose input regions run backwards, where "the region between
  them" names nothing.
- **`dropped` beside the class test**, because the two decidable cases are one
  predicate. A checker testing only the class would pass the filter that is the
  rule's own title case; one testing only the word would miss the lost segment.

**Why content-removed is expressible only as `dropped`.** `hole` generalises —
`gap`, `truncated` and any producer-specific hole word all carry or imply
`reason_class: hole`, so the class test reaches the whole vocabulary. Content-
removed has no class of its own, because bytes-exist is the wrong set: `skipped`
is the case that joins and `undecodable` decides nothing. So the restriction falls
on the single word, and it is stated in the specification rather than left to be
discovered while writing a checker, which is where it was found.

## Conformance

*Why the error tiers are three, what the advisory strength is buying, and the
defects that produced each rule stated there.*

## Prior art this borrows from

- **pcapng** — block container with TLV options; multiple sources per file.
- **WARC (ISO 28500)** — record stream; raw payload + linked derived/metadata
  records (the model for transport-vs-decoded views).
- **Matroska/MP4** — N timestamped, interleaved tracks (the multi-participant
  mental model).
- **HAR** — the ergonomics target for the optional decoded JSON view (not the
  storage format).

## Open questions

- Compression: per-record, per-session, or whole-file?
- Should a `zpf-input` Source reference a whole input file, or also pin a
  per-session digest, so a single changed session forces re-derivation of only
  that session?

## Design decisions not taken

Ideas weighed and **rejected**, kept here with the reasoning because each is a
question that recurs — a reader who wonders why the format does *not* do one of
these finds the answer where the question arises.

This is not a backlog. Planned work lives in the
[issue tracker](https://github.com/adamkjonsson/zipline/issues); see
[Planned, tracked elsewhere](#planned-tracked-elsewhere) below.

- **A File Header option recording that a file's bytes were re-stamped from an
  earlier version.** So a `0.12` file could be relabelled `0.13` and say honestly
  that it had been. *Not adopted, and not deferred:* there is no regime in which
  it is the right tool. **In `0.x`** — now — the format's own position is that a
  file which still matters is regenerated from its capture, so the option would
  exist to support the thing the specification says not to do. **In a `1.x`
  minor** it is unnecessary: a reader does not gate parsing on `version_minor`,
  so a `1.1` file already reads under `1.3` and there is nothing to re-stamp.
  **Across a major bump** it is insufficient: the frame or a block body may
  change, so the header cannot simply be relabelled — the file is rewritten,
  which is a genuine transform with genuine provenance and belongs in the
  pass-through machinery, not in a header flag. What the option really implies is
  a *transcoding specification*, one rule per version pair, growing without
  bound. See
  [Version numbering](zipline-payload-format.md#file-header-0x01) for the rule
  this would have contradicted, and for where it lives.

- **A marker saying a record's payload is byte-identical to its span.** Since
  `spans` asserts [correspondence, not
  identity](zipline-payload-format.md#tlv-option-framing--id-registry),
  a consumer cannot tell from a decoded record whether following its span yields
  those same bytes or transformed ones — so a flag, or a `transform: none`
  option, would say. *Not adopted:* the question it answers is not the one a
  consumer acts on. What decides behaviour is whether the bytes are **fetchable
  at all**, and the [recoverability
  class](zipline-payload-format.md#undecoded-0x21) already answers that.
  A consumer that has the bytes in front of it has no use for a second copy, and
  one walking the chain to re-derive must re-run the stage regardless — the
  identity case just makes re-running trivial. The marker would also be
  per-record while the property is per-span-entry (a record may span one region it
  copied and another it rewrote), so an honest version is a parallel array,
  which is real weight for a hint. If it is ever wanted, a `content_type` scheme
  is the cheaper place than a new option.

- **Self-describing repeatability (a `repeatable` id-bit).** Reserve the high bit
  of a TLV `id` to mark an option as an ordered list, so a schema-less tool could
  render an unknown option as scalar-vs-array without consulting the registry.
  *Not adopted:* a reader already preserves every occurrence in order (see
  [TLV framing](zipline-payload-format.md#tlv-option-framing--id-registry)), so
  generic round-trip is
  lossless without it; the bit would only buy prettier rendering of unknown
  single-valued options, at the cost of a permanent framing bit, a per-occurrence
  consistency rule, and duplicating a fact the registry already holds. If ever
  wanted, the `id` high bit (dropping ids to a 15-bit space) is the place — *not*
  the `len` bit, which would halve the 64 KB option-value cap.

- **Promoting frequent options into block bodies.** A TLV costs a 4-byte header
  plus padding, so an option carried by nearly every block of its type is paying
  framing for nothing. *Considered and not adopted*, and the reasoning is worth
  keeping because the question recurs.

  There is no option to promote on correctness grounds: **every mandatory option
  in this document is *conditionally* mandatory** — `isn` when the handshake was
  seen, `decoder_id` when a decoder produced the record, `spans` when the file
  is a decode
  stage, `origin` when it is a pass-through, `sequenced_basis` on a hint-less
  `SEQUENCED` session, `reason_class` on a non-canonical reason. A body field is
  always present, so each would need a sentinel for "absent" — and absence here
  *carries meaning*: no `isn` means the capture began mid-stream and the origin is
  unknowable, no `decoder_id` means the record is a byte run, no `tcp_role` means
  unknown rather than responder. A sentinel would also collide with a legal value
  (`isn = 0` is a real ISN). The same block type additionally serves several file
  kinds — `origin` is required in a pass-through and forbidden on a
  capture-sourced stream — and a body cannot vary by file kind.

  The strongest *efficiency* candidates are therefore not the mandatory options
  but `seq_start` and `ack`, near-universal in a TCP file and costing 8 bytes each
  as a TLV against 4 inline. In the [worked
  example](zipline-payload-format.md#worked-example-a-minimal-capture-sourced-file)
  that is 16 of the record block's 64 bytes spent framing 8 bytes of ordering
  data; on a pure-ACK record it is 16 bytes of framing in 44. Still not adopted:
  inlining taxes every UDP, chat and decoded record with 8 unused bytes, needs a
  sentinel (`seq_start = 0` is legal), and saves around an eighth of a TCP record
  carrying payload.

  Timing matters if this is ever revisited. Moving an option into a body is a
  **body-layout change**, so it is free while the format is in `0.x` and costs a
  major bump afterwards.

- **Transport-neutral ordering hints.** Generic `seq_pos` / `cum_ack` options,
  letting the [merge](zipline-payload-format.md#merge-algorithm) derive causal
  edges for transports the
  format does not model. *Not adopted in `0.10`:* the merge needs **both** a
  monotonic per-sender position and a *cumulative* peer acknowledgement, and the
  sessions that motivated the request (multi-party UDP, chat) supply neither.
  RTP-style protocols supply only the first, which yields no cross-participant
  edges at all. Those cases are served instead by a producer asserting the order
  and recording `sequenced_basis` (see
  [Sequenced
  files](zipline-payload-format.md#sequenced-files-precomputed-order)). Worth
  revisiting for any
  transport that genuinely carries both — SCTP is the concrete one, and is
  tracked as an issue.

- **A machine-checkable "annotation" file kind.** A third derived-file kind
  asserting that a transform changed nothing but metadata, so a consumer could
  skip re-verifying the payloads. *Not adopted in `0.10`:* the layer-preserving
  pass-through already covers the case, and the `spans`-versus-`origin`
  distinction (see [Conformance](zipline-payload-format.md#conformance))
  already tells mechanically
  whether a file's own stage built a record or re-emitted it. A third kind would
  add a permanent branch to a taxonomy whose value is that it has two, to buy a
  guarantee nobody has yet needed to check.

- **Requiring `sequenced_basis` on every `SEQUENCED` session.** The requirement
  binds [hint-less](zipline-payload-format.md#merge-algorithm) sessions only,
  and hint-less is
  all-or-nothing: one record carrying `seq_start` or `ack` among a hundred that
  carry none makes the session hinted, so no basis is required even though nearly
  all of its order still rests on timestamps. Requiring the basis unconditionally
  closes that gap and removes the hint-less dependency from the rule entirely.
  *Filed as a candidate in `0.12` pending evidence the gap mattered, and not
  adopted in `0.15` because none arrived* — three releases and one full external
  implementation later, including a review of `0.14` that returned a single
  finding, about something else.

  The cost was never in doubt: it puts an option on every sequenced TCP session,
  reinstates the `transport` vocabulary value that `0.12` deleted on the grounds
  that it could never legitimately appear, and adds an obligation to files that
  are conformant today. What it buys is narrower than it first looks. A consumer
  can already see which records carry no hints, and that the merge leaves those
  concurrent; what it cannot learn is what the producer relied on for them. The
  loss is **legibility, not correctness**, and the behaviour is pinned by the
  `partially-hinted-sequenced` vector, so it cannot drift unnoticed.

  One variant is worth not proposing a third time: splitting the rule, so that a
  reader checks the hint-less proxy while a producer is obliged to record the
  basis whenever the order does not follow entirely from causal hints. That
  obligation is **undecidable for a streaming producer** — the Session Descriptor
  is written before the session's records, which is the same asymmetry
  [Recording the
  basis](zipline-payload-format.md#sequenced-files-precomputed-order) resolves
  by keying on
  what the producer relies on. It is the defect `0.11` removed from the previous
  exemption, reproduced inside the fix for it. The full analysis is
  [#42](https://github.com/adamkjonsson/zipline/issues/42), and reopening it costs
  nothing.

### Planned, tracked elsewhere

Additions this document once listed here, now in the
[issue tracker](https://github.com/adamkjonsson/zipline/issues) so they carry
state and a milestone rather than drifting in prose:

| Extension | Issue |
|-----------|-------|
| Per-session integrity counts on Session End |
[#43](https://github.com/adamkjonsson/zipline/issues/43) |
| Random-access index block | [#44](https://github.com/adamkjonsson/zipline/issues/44) |
| SCTP support | [#45](https://github.com/adamkjonsson/zipline/issues/45) |
