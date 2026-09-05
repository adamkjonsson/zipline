# Changelog

All notable changes to the **Zipline Payload Format** specification are
documented in this file. It records changes to the *standard*, not to any
implementation of it.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
with two adaptations noted under [Conventions](#conventions).

## Conventions

**Versions are `major.minor`**, matching the `version_major` / `version_minor`
fields in the [File Header](docs/zipline-payload-format.md#file-header-0x01) — there is
no patch component, because a version that is not on the wire cannot be
communicated to a reader. Both components are independent integers compared
componentwise: **`0.10` follows `0.9`** and is greater than it.

**One exception, and it matters if you are writing a `0.9` reader.** A real
`0.9` file stamps `version_major = 1`, `version_minor = 0`. The renumbering
re-designated the July 2026 text; it did not rewrite any bytes, and no file has
ever stamped `0`/`9`. `0.9` is the one version where the name and the header
disagree — every version from `0.10` on stamps what it is called.

`0.x` files are also **disposable**: a reader rejects a `version_minor` it does
not implement, and no upgrade path between `0.x` versions is guaranteed. Where
a `0.9` file still matters, regenerate it from the capture rather than
transcoding it.

The compatibility rules have two regimes, and the format is currently in the
first:

- **`0.x` — a design in progress.** Any minor release may change anything,
  including in ways that break existing readers. A reader MUST reject a
  `version_minor` it does not implement. Nothing is guaranteed to survive a
  `0.x` bump, and no file written against one `0.x` version should be expected
  to read under another.
- **`1.0` and later.** A **minor** bump only adds blocks and options that old
  readers safely skip, and pins down behaviour an earlier version left
  undefined; every file valid under `1.n` stays valid under `1.n+1`, and readers
  do not consult the minor at all. A **major** bump may change the frame, a
  block body, or the meaning of an existing field, and a reader MUST reject a
  `version_major` it does not implement.

**Change categories.** Keep a Changelog's six types, plus one:

- **Clarified** — behaviour the previous version left undefined or stated
  ambiguously, now pinned down. Distinguished from *Changed* because no
  conformant file and no correct reader becomes wrong: only under-specified
  cases are affected. Implementers should read these first — they are where two
  independent implementations most easily disagree.

Entries state the delta only; the specification itself remains the normative
text.

**Reading across versions.** While in `0.x`, don't: a reader rejects a minor it
does not implement, and that is the intended behaviour. The entries below still
distinguish *Clarified* from *Changed*, because the distinction tells an
implementer whether their existing code was wrong or merely incomplete — but
neither is safe to skip within `0.x`.

---

## [0.18] — re-issued, from 2026-09-05

**The same format, in two documents instead of one.** About a third of the
specification explains why a rule exists rather than stating it, and that material
is moving to a
[rationale companion](docs/zipline-payload-format-rationale.md). Nothing the
format means changes: no block, no option, no body layout, no rule, and **not one
vector byte**. Scope and reasoning in
[docs/RATIONALE-EXTRACTION-PLAN.md](docs/RATIONALE-EXTRACTION-PLAN.md).

**It is not `0.19`, deliberately.** A version that is not on the wire cannot be
communicated to a reader, and `0.x` files are disposable — a reader rejects a
`version_minor` it does not implement. Bumping for a change with no semantic
content would oblige every implementation to ship a release solely to accept a
number that says nothing. `0.19` stays reserved for the reduction the
[simplification analysis](docs/SIMPLIFICATION-ANALYSIS.md) proposes, and this work
goes first so that each of those proposals is argued on the capability it costs
rather than on the lines it removes.

**The `v0.18` tag is not moved.** Every release since `0.16` closes by running each
new `RETIRED_CLAIMS` entry against the tag of the release before the one that
retired it, so a tag that names two trees breaks the reproduction step that
validates every guard this repository has. The re-issue is tagged `v0.18-r2` and
`v0.18` keeps pointing at `ea3ad7d`.

### Added

- **A Goals entry for findability of decoding failures.** The specification has
  never listed the property that a decode stage's output says where its decoder's
  model of the protocol broke, in the input's own bytes, so that a tool knowing
  nothing about the protocol can find each such place and re-derive just those
  ranges. The mechanisms have been there since `0.9`; the goal they serve was
  left implicit. It states a property rather than adding a rule, which is why it
  rides with a re-issue.
- **`docs/zipline-payload-format-rationale.md`**, structured to mirror the
  specification's sections so a moved paragraph has one obvious home.
- **Two guards in `vectors/check.py`, both validated against trees where they must
  fail** before being believed, as `0.17` and `0.18` established after two guards
  in a row were proposed in forms that could not work.
  - *Normative-sentence invariance*: the specification's normative keyword counts
    must match the `v0.18` baseline (143 `MUST`, 53 `MUST NOT`, 27 `SHOULD`, 54
    `MAY`), and the companion must carry none at all. A rule leaving with the
    paragraph that explains it is this work's characteristic failure, and this is
    what catches it.
  - *Anchor-link integrity*: every `](#anchor)` in either document resolves
    against the headings of the document it sits in. The specification carries 214
    such links across 37 targets; moving a section breaks them in both directions,
    and a dead anchor is silent in a rendered page.
- **The companion is scanned for retired claims**, alongside the specification and
  the suite. Measured before it was taken: of 480 paragraphs, 11 recount a
  superseded rule and none matches a retired spelling, so the allowlist is empty.

## [0.18] — 2026-09-02

**A corrective release, like `0.11`, `0.12`, `0.14` and `0.16`.** `0.17` decided
what a decoded record may say about itself; `0.18` fixes what that release left
inconsistent, as the reviews `python-zipline` and `zpfwire` returned on it found.
No new block, no new option, no body-layout change. Scope and reasoning in
[docs/RELEASE-0.18-PLAN.md](docs/RELEASE-0.18-PLAN.md); every item is an issue on
the [`0.18` milestone](https://github.com/adamkjonsson/zipline/milestone/6).

**Four of the twelve findings are one failure repeated**, and it is the one worth
reading first: `0.17` changed two rules and left other statements of them
standing. The transport-layer bar gained `role` in §Typing and was not updated
where §Conformance restates it or where a pass-through's carry-forward
enumerates it; `skipped` split into `skipped`/`dropped` in §Undecoded and was not
updated in §Referencing's instruction to a filter or in §Discontinuity's join
table — where it classified a discarded byte-order mark as owing a Discontinuity,
contradicting an accept vector.

**Expect a small *Changed* section and a large *Fixed* one.** Two entries change
behaviour: the restriction `dropped` places on an otherwise open vocabulary, and
the rule for where an unplaceable record sits. One *loosens* — a handshake record
above the origin was isolatable under `0.17` and is advisory under `0.18`.

### Changed

- **One placement rule covers every unplaceable record, and it is a running
  maximum.** ([#114](https://github.com/adamkjonsson/zipline/issues/114)) `0.17`
  put a below-origin record at "the offset the preceding record ended at, or `0`
  where there is none". That clause is unreachable in a conformant file — the
  ordering MUST stores a below-origin record first, so only the `0` branch is
  ever taken — and where a file breaks that MUST it disagrees with the obvious
  alternative, because records within a participant may overlap and the record
  stored last is not always the one that reached furthest.

  A record is now **unplaceable** when the offset space cannot say where it
  belongs, which covers two shapes: `seq_start` below the origin, and **no
  `seq_start` at all** on a stream whose other records carry one. `0.17` stated a
  rule for the rare shape and left the common one silent — `partially-hinted-
  sequenced` has shipped an instance since `0.12` — so both are now one sentence:
  a zero-width range at the **highest `off_end` any earlier record of that
  participant reached**, `0` where there is none.

- **Content-removed is expressible only as `reason = dropped`.**
  ([#117](https://github.com/adamkjonsson/zipline/issues/117)) The seam
  predicate's two arms are not symmetric: `hole` tests a **class**, so it reaches
  the whole open vocabulary — `gap`, `truncated` and any producer-specific hole
  word all carry or imply `reason_class: hole`. Content-removed has no class of
  its own, because bytes-exist is the wrong set: `skipped` is the case that joins
  and `undecodable` decides nothing. So the second arm tests a **word**, and a
  producer taking the document up on its invitation to be more specific —
  `{"reason": "filtered", "reason_class": "bytes"}` — says something true and
  escapes the only single-file test of the origination duty on the bytes side.

  A stage that removed content of the stream now **MUST** write `reason =
  dropped`, with any specificity in `comment`. That is a real qualification of an
  openness the document promises two sections earlier, so it is stated in both
  places: at the predicate, with the reason, and as a pointer where the openness
  is offered. Like the transport-layer withholding rule, this MUST **can have no
  vector** — a file writing `filtered` for removed content and one writing it for
  anything else are byte-identical, which is the whole reason the rule is needed —
  and that absence is recorded in `check.py` rather than left to look like an
  oversight.

- **The `syn` MUST has one strength across its whole domain.**
  ([#116](https://github.com/adamkjonsson/zipline/issues/116)) `0.17` made
  `seq_start = isn + 1` a MUST and gave a reader rule for records *below* the
  origin only. A `syn` at `isn + 7` violated the same MUST with no specific rule,
  so it fell to the general licence to isolate — meaning a reader could discard a
  session over a zero-length record six bytes up, while the shape that wrecks the
  entire offset space was accept-and-report. The strengths were inverted relative
  to the damage. Violating the handshake MUST is now advisory wherever the record
  sits.

  Two shapes the MUST left open are named with it: a `syn`-flagged record with no
  `seq_start` is unplaceable like any other, and the zero length is part of the
  shape being described — a writer with data on the SYN (TCP Fast Open) emits it
  as an ordinary record at the origin, which is exactly where such data starts.

### Clarified

- **The per-participant ordering MUST is non-descending: two records MAY share a
  `seq_start`.** ([#124](https://github.com/adamkjonsson/zipline/issues/124)) The
  rule said "in `seq_start` order" and never said whether that was strict. Before
  `0.17` the question was a corner; `0.17` made the tie **mandatory** in every
  file that records a handshake, because the SYN sits at the stream origin and
  the first data record starts at the same origin by definition — the handshake
  paragraph's own parenthetical relies on it, resolving the two by stored order.

  A reader that reads an unqualified "in order" strictly — which is what a `<`
  comparison produces without anyone deciding anything — **rejects or isolates
  every conformant capture whose handshake was observed**, and the licence in the
  same paragraph makes that a conformant thing for it to do. The evidence that
  this is a live fork rather than a theoretical one: two implementations in one
  family read it opposite ways, and the one that read it strictly is why the file
  behind [#108](https://github.com/adamkjonsson/zipline/issues/108) was written
  with its handshake below the origin.

  Where two records share a `seq_start`, **stored order decides which comes
  first**. §Merge algorithm's cost argument is corrected with it — the
  per-participant streams are sorted by `seq_start` and then by stored order,
  which is a total order because stored order is; "always totally ordered" was
  true of `seq_start` alone only while ties were undecided. Neither review named
  that site; it was found while scoping, and leaving it would have repeated the
  failure this release exists to fix.

  New vector: `handshake-at-origin`, the mandated shape in both directions.
  **No vector in the suite carried a `seq_start` tie before this**
  ([#123](https://github.com/adamkjonsson/zipline/issues/123)), so a reader
  comparing with `<` passed all 56 and failed on real traffic. It is the positive
  twin of `advisory-seq-start-below-origin` — the same record, one below the
  origin — and it also carries the responder's SYN-ACK as its own zero-length
  `syn` record with an `ack`, which the specification describes and nothing else
  exercised.

### Fixed

- **The join table tells the two sides of `0.17`'s split apart.**
  ([#122](https://github.com/adamkjonsson/zipline/issues/122)) §Discontinuity's
  table is the one place the origination duty is stated in terms of *what the
  stage did* rather than what word it wrote, which is why it is the part a
  producer follows — and it was the one place `0.17`'s split was not applied. Row
  3 read "declined **or** dropped content that was present", which a discarded
  byte-order mark matches exactly: it declined, and the bytes were present. Its
  verdict is *no join, block required*, while §Undecoded says the text either side
  of a BOM runs continuously and `undecoded-skipped` is an accept vector carrying
  no Discontinuity. Row 1 did not rescue it — a BOM is not framing, not a record
  header, not a nonce and not a tag.

  Row 3 is now split. Declining data that carries no content of the stream joins
  row 1, where §Undecoded's reasoning puts it; removing content that was present
  stands alone. Each row names the `reason` a region of that shape carries, so the
  table and the predicate can be read against each other — with the caveat that
  the words do not *decide* the rows, since the question remains what the stage
  did.

- **§Referencing tells a filter to write `dropped`, not `skipped`.**
  ([#119](https://github.com/adamkjonsson/zipline/issues/119)) The section an
  implementer reads to learn what a filtering stage *is* still instructed it to
  mark every removed region `reason = skipped` — and closed with "which is exactly
  what that reason is for", which `0.17` made precisely false. A filter written
  from that paragraph produced a conformant-looking file that the seam predicate
  could not check, which is the capability `0.17` shipped. The trailing clause now
  says why the Discontinuity obligation *follows* from the removal rather than
  being an additional rule. Entered in `RETIRED_CLAIMS`, since it named a
  canonical word in a normative instruction.

- **Every statement of the transport-layer bar names both labels, and the one
  that counted its members no longer counts.**
  ([#120](https://github.com/adamkjonsson/zipline/issues/120)) `0.17` stated the
  bar once, for `content_type` and `role` together, and updated §Record to match.
  Two §Conformance sites were not: the paragraph announcing what binds on the
  layer — which said there were **two** such requirements, so the number went
  stale with the content — and the sessionization-stage bullet, which is the list
  a reassembler is written from. That is the single most tempting place to write a
  `role`, and `role`'s open vocabulary makes it worse than `prim:bytes` was: there
  is no wrong-looking value to notice, since `role: "segment"` reads as helpful.
  The count is now deliberately absent, with a note saying why.

- **A pass-through preserving a decoded layer carries `role` forward.**
  ([#121](https://github.com/adamkjonsson/zipline/issues/121)) The carry-forward
  obligation named `content_type` alone, in a sentence that enumerates what
  "additionally" means, and the annotator worked example — the one such a tool is
  written from — said the same. A lost `content_type` degrades to something the
  document defines: opaque payload, fall back to the decoder `name`. A lost
  `role` leaves records typed `prim:u32` with nothing saying which is the
  checksum, which is the state `role` was added to end, reintroduced by a stage
  whose whole purpose is to change nothing — and because the option is advisory,
  no reader can detect that it happened.

- **`advisory-transport-role`**, the vector for the half of the bar that shipped
  without one. ([#118](https://github.com/adamkjonsson/zipline/issues/118))
  `advisory-transport-content-type` exists because the advisory strength is a
  coin-flip a suite should settle, and every argument for it applies to `role`.

- **A stated rule for a violation *displaces* the isolate licence rather than
  being an instance of it.**
  ([#113](https://github.com/adamkjonsson/zipline/issues/113)) §Conformance listed
  the origin floor among rules that are "an instance of this tier" — a tier headed
  *the reader MAY isolate* — while §Referencing says the floor binds *instead of*
  that licence and its vector says isolating is not conformant. Two sections gave
  opposite instructions to a harness that routes on the tier. The clause now says
  displacement, and notes that some such rules are **weaker** than isolation: the
  `prim:` width-mismatch rule and the origin floor both keep the record, ignore
  the part that is wrong, and report. The `prim:` rule had the same imprecision
  and is fixed by the same sentence.

- **The origin floor says where it is vacuous, and what it costs when it is not.**
  ([#115](https://github.com/adamkjonsson/zipline/issues/115)) Without an `isn`
  the origin *is* the first record's `seq_start` and the ordering MUST stores that
  record first, so the floor cannot be violated there — stated, so an implementer
  whose check never fires on an unanchored stream knows the rule is unreachable by
  construction rather than misread. And the advisory argument, which `0.17` costed
  as "one record is unplaceable and every other byte is exactly where it was", now
  says what a *payload-carrying* below-origin record costs: those bytes are
  excluded from the extent and from every coverage answer the file supports. The
  bytes are kept and only their placement is refused; "data must never vanish
  silently" is discharged by the SHOULD-report, not by pretending they were
  placed. New vector: `advisory-below-origin-payload`.

---

## [0.17] — 2026-09-01

**A feature release, and the one that decides what a decoded record may say
about itself.** `0.16` was corrective; `0.17` takes the three findings
`python-zipline`'s `0.3.0` planning pass raised against it and, in the same
release, answers a question that pass split out rather than leaving a producer
to guess. Four of its seven items rest on one piece of evidence: the
first implementation to decode real captures at **field** granularity, which is
why it is the first to find that a decoded record has no name, that a sub-byte
field's width is unrecoverable, and that a nested decomposition is a stream this
document has no verdict on — that last one is `0.18`'s to answer, and why is
recorded with the rest. Scope and reasoning in
[docs/RELEASE-0.17-PLAN.md](docs/RELEASE-0.17-PLAN.md); every item is an issue on
the [`0.17` milestone](https://github.com/adamkjonsson/zipline/milestone/5).

**Expect a small *Changed* section and a large *Clarified* one.** Exactly one
entry tightens conformance — a record whose `seq_start` precedes its stream's
origin — and files in the wild carry one, which is how it was found. The rest
add a name a decoded record can carry, a canonical word for content that was
removed rather than withheld, and answers to questions the document had left
silent.

### Added

- **`role` (`0x0092`): a decoded record may carry its type and its name at once.**
  ([#107](https://github.com/adamkjonsson/zipline/issues/107)) A string on Record,
  decoded layer only, advisory, saying what the record **is** within a vocabulary
  scoped to its decoder's `name`.

  The gap it closes is total rather than partial. A decoder emitting one record
  per protocol field produces four `u32` fields as four records typed
  `prim:u32` — contiguous, non-overlapping, `payload_len` binding exactly, a
  conformant and well-formed decoded stream in which **nothing says which one is
  the checksum**. Position is not a contract: an optional field the decoder later
  emits renumbers everything after it. The first implementation to decode at field
  granularity reported 176 of 176 DNS records distinguishable only by `comment`.

  The two spellings available before this each destroyed the other's information.
  `content_type = prim:u32` leaves the value readable by a generic reader and says
  nothing about which field it is; `dec:checksum` names the field, discards the
  normative typing, and makes `dec:checksum` and `dec:seq_no` two distinct types
  that happen both to be `u32`; `comment` is defined as a free-text human note, so
  a consumer parsing it relies on something this document says means nothing.
  `role` is **independent** of `content_type` — a record may carry both, either or
  neither — which is the whole of the change.

  Three constraints keep it small, each borrowed from a mechanism already here.
  It is **name-scoped to the record's decoder**, exactly as a `dec:` token is, so
  two decoders may both use `checksum` without colliding — and that declared scope
  is what makes it more than a `comment`, not any ability to verify the meaning,
  which this format has for neither. It is **opaque to the format**: it names a
  record and asserts no tree, so `dns.flags.qr` is a convention this document does
  not parse. And it is **advisory, decoded layer only** — the transport-layer bar
  and its advisory strength are now stated once for both labels, since the reason
  is the same for each: a reassembly record's boundaries are wherever the
  reassembler chunked, so a label on it asserts a unit where there is a slice.

  Whether a **nested** decomposition is a well-formed decoded stream at all is a
  separate question, deliberately not answered here
  ([#106](https://github.com/adamkjonsson/zipline/issues/106)); `role` is
  compatible with any answer to it, which is why it did not wait for one.

  New vector: `decoded-field-roles`.

- **`dropped`: a canonical bytes-class `reason` for content that was removed
  rather than withheld.**
  ([#98](https://github.com/adamkjonsson/zipline/issues/98)) `skipped` was doing
  two unrelated jobs and only one of them is a break. A decoder discarding a
  byte-order mark and a filter dropping a record wrote the same word, and the two
  files were byte-shaped alike: `undecoded-skipped` owes no Discontinuity, because
  a BOM withholds no content of the stream and the text either side joins;
  `filtered-decoded` requires one, because a whole record went missing. Nothing in
  either file distinguished them.

  `dropped` says content of the stream was removed. The **word still does not
  decide the duty** — the test remains whether the survivors join, and only the
  producer knows — but it is the producer's own statement that they do not, which
  is what makes the case checkable.

  So the single-file predicate now has **two** decidable cases rather than one: a
  `hole`-class region between the input regions of two adjacent output units, and
  a bytes-class region carrying `reason = dropped`. `undecodable` decides nothing,
  since a failed parse says nothing about whether content went with it, and
  `skipped` decides nothing by design. The `hole` half has had a vector since
  `0.15`; the other half could not be tested at all while one word did both jobs.

  `filtered-decoded` moves onto `dropped` and stops being an *example* of #78's
  duty — the predicate now fires on it and finds the block. Its negative twin,
  `isolate-unmarked-drop`, is that file with the Discontinuity deleted and nothing
  else changed. The canonical vocabulary is now five words, not four; the
  vocabulary itself was already open, so no existing file becomes invalid and a
  producer that wrote `dropped` before this release was already saying the right
  thing.

### Clarified

- **`prim:` types storage, not the wire: a sub-byte field's width is not
  recoverable, and that is a decision.**
  ([#105](https://github.com/adamkjonsson/zipline/issues/105)) A field narrower or
  wider than 8/16/32/64 — a 4-bit flag, a 24-bit length — has no `prim:` token,
  and the conformant move is to widen to the smallest that holds it. The value
  stays readable by any reader, which is what the width-binding rule is for; the
  true width is gone, and `spans` do not recover it, since a sub-byte field names
  the byte containing it and several fields name the same byte.

  Nothing about a file changes. What changes is that the silence is now a stated
  answer: `prim:` types **storage**, exactly as it already does for byte order,
  where a big-endian wire value is byte-swapped by the emitting decoder and never
  by the reader. A field's true width is the decoder's business, read from what
  the decoder documents. The alternatives are recorded as weighed and declined — a
  significant-bits option would add a field no reader can act on, and opening the
  vocabulary would break the width-binding rule that is the only thing making
  `prim:` checkable. A producer could not previously tell the omission from the
  decision, and picked the widening in the dark.

- **A decoded record's `timestamp` is per unit, not per reassembled run.**
  ([#109](https://github.com/adamkjonsson/zipline/issues/109)) The rule already
  said "the last source element **in its span set**", which is per unit; the
  reading that kept appearing was per *run*, stamping every message a decoder
  carves out of one contiguous run with the run's completion time. Three 4-byte
  messages arriving in three packets then carry one stamp instead of three, and
  the two earlier ones claim to have completed after they did.

  It matters beyond display. The rule is what makes ordering decoded records by
  `timestamp` *reproduce* the input's timeline rather than approximate it — the
  property hint-less decoded output leans on. Under the per-run reading every unit
  in a run collapses to one key, and ordering within it becomes whatever the
  merge's tie-break does.

  Stated explicitly now, with `ts_first` given the same treatment at the other end
  of a unit: the first input record contributing to **that unit**, not to the run
  it was carved from. No file changes and no vector can test it — a per-run stamp
  and a per-unit one are both well-formed, and only the input's timeline tells
  them apart — which is why it was worth stating rather than leaving to the
  reader. The misreading had reached three places in the reference
  implementation's own documentation, including the worked example every decoder
  written from it inherits.

### Changed

- **The stream origin is a floor: a record's `seq_start` MUST NOT precede it.**
  ([#108](https://github.com/adamkjonsson/zipline/issues/108)) The origin is
  `isn + 1` where the participant carries an `isn`, the first captured byte
  otherwise. The floor was *presumed* everywhere — the leading hole is defined as
  `first seq_start − (isn + 1)`, and "without an `isn` there is no room below the
  first captured byte" — but presumed is not stated, so a file carrying a record
  below the origin broke nothing this document said, and a checker had nothing to
  cite.

  The **handshake record's `seq_start` is now a MUST** rather than prose inside a
  "a writer MAY record" sentence: where a writer records the handshake, the record
  sits at `isn + 1`. That is where the mistake is actually made — a converter in
  the field writes it at `isn`, one below the origin.

  What that costs is the reason this is a `Changed` and not a note. The subtraction
  is modular, so it does not report the error, it absorbs it: one zero-length
  record at `isn` lands at offset 4294967295 and the stream measures 4294967295
  bytes. On a real 71 KB capture the stream measured 2³²−1 where its data ended at
  74931, and the coverage check then reported four violations against a file that
  was otherwise correct.

  **A reader meeting one MUST treat that record as unplaceable**: a zero-width
  range at the stream's current position, covering no byte and contributing
  nothing to the extent. It MUST NOT place it at the wrapped offset. Three
  treatments were available before this — wrap it, skip it, place it at zero width
  — and all three were defensible, so two conformant readers could disagree about
  the offset space, which is the one thing this format cannot leave open.

  **The violation is advisory, not isolating**: the reader accepts the file,
  applies the rule, and SHOULD report. Isolation is for damage a reader cannot
  bound; here one record is unplaceable and every other byte is where it was, so
  discarding the session would lose a whole capture to fix one offset. This is the
  **second** advisory MUST NOT — `content_type` at the transport layer was the
  first, and the sentence calling it the only one is retired accordingly.

  One limit is stated with the rule rather than left to be found: the floor is
  decidable only within the serial-arithmetic half-space, so a `seq_start` more
  than 2³¹ below the origin is indistinguishable from one above it. That is a
  property of the sequence space — the same limit governs record ordering and
  every `ack` edge — not a gap in the rule.

  New vector: `advisory-seq-start-below-origin`, carrying the shape found in the
  wild.

### Fixed

- **§Layers no longer says a derived file is never a mix.**
  ([#103](https://github.com/adamkjonsson/zipline/issues/103)) `0.15` made the
  created-or-preserved discriminator bind **per participant**, so one file may
  decode one session while passing another through — which is what
  `mixed-derivation` is an accept-tier vector for. §Layers kept `0.14`'s
  conclusion that a derived *file* is exactly one of the two, never a mix,
  correct when written and false since. The section is where an implementer goes
  to learn what a derived file *is*, and the practical cost was a classifier built
  the wrong way round: one file-wide kind, locked and short-circuited, which then
  fails `mixed-derivation` with no way to tell which of the two statements was
  normative.

  The paragraph now states derivation per **stream** and says the discriminator is
  per participant, pointing at §Conformance for the test. The retired claim is in
  `RETIRED_CLAIMS`, so it cannot return a third time — it survived two releases
  because it is not a *restatement* of the rule it contradicts and shares no
  phrase with it, which is exactly what the `0.14` grep could not see.

- **`tunnel/{inner,outer}.jsonl` spell the flow key `key`, as the mapping says.**
  ([#104](https://github.com/adamkjonsson/zipline/issues/104)) Both fixtures wrote
  the binary name `flow_key` where the brevity-alias table gives the JSON name
  `key`, so a reader following the table could not round-trip either — two of that
  fixture's four members out of the accept tier for a reason unrelated to what it
  exists to test. The specification's own tunnel walkthrough carried the same two
  spellings and is corrected with them. Vector-side under ground rule 2: the
  mapping was unambiguous and `descriptive-metadata.jsonl` already obeyed it.
  Recorded as defect 4 in [docs/VECTOR-DEFECTS.md](docs/VECTOR-DEFECTS.md).

  **`check.py` now enforces the mapping**, which is the part that outlives the
  fix: it builds the projection's key vocabulary from the specification's own
  tables and requires every key in every `.jsonl` to be in it. The obvious form of
  that check does not work — `flow_key` *is* a registry option name — so it
  subtracts the aliased binary names, which is the whole of what sees this defect.

---

## [0.16] — 2026-08-09

**A corrective release, like `0.11`, `0.12` and `0.14`.** `0.15` replaced the
raw/derived conflation with two independent axes; `0.16` fixes what that release
left inconsistent, as
[python-zipline's review of it](docs/SPEC-0.15-REVIEW.md) found. No new block, no
new option, no body-layout change — every fix is local, and the review's verdict
on the normative model is that nothing in it needs challenging. Scope and
reasoning in [docs/RELEASE-0.16-PLAN.md](docs/RELEASE-0.16-PLAN.md); every item is
an issue on the
[`0.16` milestone](https://github.com/adamkjonsson/zipline/milestone/4).

**Expect a *Changed* section, and read it as tightening rather than adding.**
Four entries make a file conformant under `0.15` non-conformant under `0.16` —
a participant whose records mix layers, a `zpf`-sourced stream that is neither
created nor preserved, a transport stage withholding content it cannot express,
and `content_type` on a transport-layer record. A fifth changes what an Undecoded
block against a `capture` Source *means*, which is the one place this release
touches semantics rather than prose.

**Two of the fixes are the same defect `0.14` was written to stop**, and the
checklist step `0.14` added to stop it did not catch either. `0.15` changed the
layer rule and left two paragraphs asserting the old one — and because neither
paragraph *restates* the rule, a check that enumerates a rule's copies passes them
clean: the layer rule is stated exactly once, so the enumeration reports one site,
correct. What they do is assert its negation, in words sharing no phrase with it.
So `check.py` now carries `RETIRED_CLAIMS`
([#100](https://github.com/adamkjonsson/zipline/issues/100)): claims the model has
retired, each with the release that retired it and the issue that found it,
failing the build if one reappears and matching whitespace-collapsed so a
line-wrapped copy is still caught. It is a **ratchet, not a detector** — it cannot
find a stale claim nobody has noticed, only hold a retired one from returning
quietly.

### Changed

- **An Undecoded block's body is read by the referenced source's `kind`, and
  against a `capture` source the ids are unused.**
  ([#87](https://github.com/adamkjonsson/zipline/issues/87)) `0.15` shipped three
  statements that could not all hold: the field table required
  `kind = zpf-input`, §Undecoded said the ids are the source's and "never the
  current file's", and the span-list rule said a capture source's ids are unused
  and written 0. No reading satisfied all three, and `undecoded-in-capture` — the
  vector the capability shipped for — satisfied none. It was the first vector
  since the `0.12` round that could not be implemented from the text.

  The span-list rule wins, so the Undecoded body and a `spans` entry are now read
  by one rule as well as parsed by one struct. Against a `zpf-input` source
  nothing changes. Against a **`capture`** source `session_id`/`participant_id`
  are unused and MUST be written **0**, and the offsets are **byte offsets into
  the capture file**.

  Two consequences are stated rather than left to be derived. Only the
  **bytes-exist** class is available there — a `hole` needs no block, because the
  reassembled stream is a transport layer whose offsets already carry the gap, and
  declaring it twice is the contradiction that also bars a Discontinuity from such
  a stream. And the block **discharges no coverage obligation and creates none**,
  because the guarantee is scoped within each input participant stream and a
  capture has none; it is purely declarative there. That is why the permission is
  not keyed on the layer: a reassembler declaring a discarded overlap and a decode
  stage reading a capture directly are both honest. A decoded stream with no
  predecessor file still carries none — it read no input at all.

  `undecoded-in-capture` changes bytes: `session_id` `7` → `0`. Recorded in
  [docs/VECTOR-DEFECTS.md](docs/VECTOR-DEFECTS.md) as defect 3, and it is the one
  defect there that was not vector-side alone — the text disagreed with itself, so
  no reading could have produced a correct vector.

### Fixed

- **`transform_params_digest`'s restriction is stated as placement, not as the
  absence of a transform.**
  ([#96](https://github.com/adamkjonsson/zipline/issues/96)) The option said "a
  capture-sourced stream is not the output of a transform" — the exact claim
  `0.15` spent an entry refuting when it legalised an Undecoded block on such a
  stream, on the grounds that reassembly *is* a transform and a destructive one.
  The outcome was right and the reason was not. A reassembler wanting its
  configuration recorded declares itself as a Decoder and puts it in that
  descriptor's `params_digest` (`reassembler-declared`); this option is for a
  stage that produced records **without decoding** and so has no Decoder to hang
  one on, which a capture-sourced file has none of.

  Two smaller things in the same paragraph. "A file holding nothing else" now
  reads "a file all of whose streams are capture-sourced". And `produced_by`'s
  registry entry no longer implies derived files only — `proxy-decoded` sets it on
  a file with no `zpf`-sourced stream, which was legal and unstated; every file
  was produced by something, and only a file holding a `zpf`-sourced stream is
  *required* to say so.

- **"Raw" is gone from the worked examples.**
  ([#99](https://github.com/adamkjonsson/zipline/issues/99)) `0.15` retired the
  term but left `raw.zpf` as the predecessor's filename through the decoded-file
  walkthrough and the annotator example — about a dozen uses, in prose explaining
  what resolves where. A reader learning the model there learned "raw file →
  decoded file", the implication the two-axis model exists to remove. It is
  `transport.zpf` now, which names the layer rather than the retired axis.

  Documentation only: no vector or fixture bytes change. `raw-minimal`,
  `isolate-discontinuity-in-raw` and `chain/raw.zpf` keep their names, which are
  identifiers that downstream harnesses reference — the churn would buy tidiness
  and cost every port a migration. Ordinary English uses ("raw TCP segment", "raw
  byte string") are untouched; those were never the retired term.

- **Intra-file derivation gets a detection procedure, and stops resting on an
  optional field.** ([#93](https://github.com/adamkjonsson/zipline/issues/93))
  The prohibition was argued from the `digest` — "no file can contain its own
  hash" — but `digest` is an option a writer may omit, and
  `isolate-self-derived`'s own is the placeholder `sha256:0000`. It now rests on
  the ordering instead: a stage reads its input and then writes its output, so a
  file cannot be among its own inputs whether or not it carries a digest.

  Detection is stated as **partial by design**, since there is no in-band
  self-identifier: a reader handed a *path* compares it against a `zpf-input`
  `uri` after normalisation and MAY isolate on a match; a reader handed a file
  object — stdin, a socket, a tar member — cannot, and is **not obliged to
  detect it**. Saying so keeps a reader that cannot check from looking
  non-conformant, and tells one that can what to compare.

  The vector also carried a **second violation** through `0.15`: session 21 was
  `zpf`-sourced with no `origin` and no `spans`, so a reader could isolate it for
  entirely the wrong reason and appear to pass. It now carries `origin`, and that
  shape has a vector of its own
  ([#92](https://github.com/adamkjonsson/zipline/issues/92)).

- **§Conceptual model no longer says a byte run carries no `decoder_id`.**
  ([#91](https://github.com/adamkjonsson/zipline/issues/91)) It told the byte-run
  from the decoder-imposed unit by "a single fact: whether it carries a
  `decoder_id`", which `0.15` made false when it let reassembly be a decoder —
  `sessionization-stage` ships records that carry a `decoder_id` and are byte
  runs, and the `content_type` rule rests on exactly that. Worse placed than
  [#89](https://github.com/adamkjonsson/zipline/issues/89): the correct two-axis
  statement is three paragraphs below it, so the section contradicted itself
  within one screen, in the first thing an implementer reads.

  The distinction now follows from the stream's **layer** and points at the rule
  four paragraphs down rather than restating a fact about `decoder_id`. The trap
  is named outright, since it is the one a `0.14` reader carries in: a reassembly
  record carries a `decoder_id` and is a byte run all the same.

- **`0.15`'s byte-compatibility claim is corrected where it stands.**
  ([#97](https://github.com/adamkjonsson/zipline/issues/97)) That release said
  "every existing `.zpf` re-reads correctly unmodified", which contradicts the
  `0.x` rule the specification opens with: a conformant `0.15` reader MUST reject
  `version_minor = 14`, so no existing file re-reads at all. The byte-level half
  was right and is independently verified — the Decoder body stays 4 bytes and
  `decoded = 0` lands on bytes a conformant `0.14` writer MUST have written 0.

  The `0.15` entry is amended in place with a note saying what was wrong, rather
  than rewritten to look correct: the property has operational content only for
  files **re-stamped** to `0.15`, which is what happened to `reordered-decoded`.
  The same clause is added to that release's headline, so a reader does not have
  to reconcile the two claims themselves.

- **§Undecoded no longer says a transport-layer stream carries no Undecoded
  blocks.** ([#89](https://github.com/adamkjonsson/zipline/issues/89)) The
  section's closing paragraph still read "neither carries Undecoded blocks,
  because no decoder ran" — contradicting the paragraph 60 lines above it that
  legalised the case, and contradicting two of `0.15`'s own accept-tier vectors:
  `undecoded-in-capture` (no decoder anywhere) and `sessionization-stage`
  (`output_layer = transport`, carrying a `gap`). The sentence *was* edited in
  `0.15`, for the retirement of "raw" and not for the rule that changed two
  paragraphs earlier, which also left its "neither" with a single subject.

  Rewritten as a **reference rather than a restatement**, the treatment `0.14`
  gave #63 and #64: a transport-layer stream expresses its gaps in its offsets,
  which is why it may not carry a Discontinuity — stated once, in that block's own
  section — and that says nothing about Undecoded, because the offsets describe
  the shape of the output while an Undecoded block accounts for an input. The two
  are not alternatives and a transport stream may carry both.

- **Every record of one participant MUST resolve to the same layer.**
  ([#90](https://github.com/adamkjonsson/zipline/issues/90)) The layer fixes a
  stream's offset space, but `0.15` computed it per *record*, through
  `decoder_id → output_layer`, while mixing decoders per record stayed legal.
  Nothing forbade a participant holding a `transport` record beside a `decoded`
  one, so its offset space had two incompatible definitions and every
  `input_extents` or downstream `spans` resolved against it was meaningless — with
  no rule broken. Now a semantic violation a reader MAY isolate, which also
  licenses resolving the layer **once per participant** and caching it. Vector:
  `isolate-mixed-layer-participant`.

  Not the structural alternative. Putting the layer on the Participant body would
  make this unexpressible, but the reason the Decoder placement was chosen does not
  transfer — `decoded = 0` lands on `_reserved` bytes every existing writer wrote
  0, while a participant's `_reserved` would want `0 = transport` for old capture
  files and `0 = decoded` for old decoded ones, and one field cannot be both.

- **A `zpf`-sourced participant MUST be created or preserved, never neither.**
  ([#92](https://github.com/adamkjonsson/zipline/issues/92)) §Conformance
  described the two ways and forbade being *both*; it never required being
  *either*. A participant with no `origin` whose records carry no `spans` names no
  provenance for its bytes at all — nothing resolves one level down, and no
  coverage obligation can be computed in either direction. Binds on `zpf`-sourced
  streams only; a capture-sourced participant correctly carries neither. Vector:
  `isolate-unbound-zpf-stream`.

- **A stage emitting a transport layer MUST NOT withhold content from a stream
  whose offsets are not sequence-anchored.**
  ([#94](https://github.com/adamkjonsson/zipline/issues/94)) The exemption that
  frees a transport stream from carrying a Discontinuity assumes its offsets can
  express the break, which holds only where something anchors them. In a
  message-oriented or `N = 1` stream with no `isn` — `tunnel/outer.zpf` is one —
  offsets are the accumulation of what arrived, and a withheld datagram leaves no
  trace while the block that would say so is barred by the layer. Academic before
  `0.15`, because a transport stream was a capture's reassembled output; reachable
  now that a stage may declare `output_layer = transport` and filter.

  **No reader can check this**, and the text says so: a file that withheld and one
  that did not are byte-identical, which is exactly the defect. It has no vector
  for the same reason, and `check.py`'s rule table records the omission as a
  decision rather than leaving it to look like an oversight. A stage needing to
  withhold emits a decoded layer, where the break is expressible.

- **`content_type` at the transport layer is a MUST NOT, and its violation is
  advisory.** ([#95](https://github.com/adamkjonsson/zipline/issues/95)) `0.15`
  stated it as prose, the option registry still read `Record (decoded)`, and the
  isolate list did not name the case — so a checker could not tell whether it was
  a MUST NOT, whether it isolated, or what to do with the label. It is now a MUST
  NOT and **advisory**: dropping the label loses nothing and the record stays
  fully readable, so there is no unit a reader could soundly discard. A reader
  MUST ignore the label and SHOULD report it, and MUST NOT read it as evidence
  that the stream is decoded — which would put every later offset in that
  participant in the wrong space. Vector: `advisory-transport-content-type`.

  This is the format's first violation that **accepts**, and the three tiers could
  not say it. `manifest.json` gains an optional `advisory: true` on an `accept`
  entry, which then declares 1 violation rather than 0 — a key rather than a fourth
  tier, because a tier names what a *reader does* and a reader accepts these files
  completely.

### Clarified

- **The single-file Discontinuity check is stated as a predicate, with the layer
  test first.** ([#88](https://github.com/adamkjonsson/zipline/issues/88)) `0.15`
  said a checker may raise the case where a `hole`-class Undecoded region lies
  between the input regions of two adjacent output units, and left three things
  unsaid: that the check applies to decoded-layer streams only, which input stream
  is meant when units cite several, and how to reduce a span *set* to a region
  when spans may overlap or run downward. A checker written from that paragraph
  rejects `sessionization-stage`, a conformant accept-tier vector.

  The predicate is now written out. Verified against every vector: it fires on
  `isolate-unmarked-break` and nothing else, and each near-miss is excluded by the
  clause that exists for it — `sessionization-stage` and `tunnel/inner.zpf` by the
  layer test, `reordered-decoded` and `session-fan-out` by the overlap clause,
  `filtered-decoded` because the region between its records is bytes-class.

  **Satisfying the predicate is not satisfying the duty**, and the text now says
  so. It is the minimum a checker owes and is deliberately conservative;
  `filtered-decoded` owes a Discontinuity that the predicate is correctly silent
  about. A producer that emits the block only where this fires has misread the
  duty, which rests on producer knowledge and is mostly not mechanically decidable.

---

## [0.15] — 2026-08-08

**A feature release, and the first that changes what already-written files
mean** — which inside `0.x`, where a reader rejects a `version_minor` it does not
implement, bites only on files **re-stamped** to `0.15` (clause added in `0.16`,
[#97](https://github.com/adamkjonsson/zipline/issues/97)). `0.13` shipped the
corrective third of
[#41](https://github.com/adamkjonsson/zipline/issues/41); `0.15` finishes it —
provenance and layer as independent axes, and sessionization as a decoder that
declares the layer it emits — and closes the hole
[python-zipline found](https://github.com/adamkjonsson/zipline/issues/78) in
what `0.13` shipped: a stage must emit a Discontinuity when its *own* output
breaks, not only carry one forward. Scope and reasoning in
[docs/RELEASE-0.15-PLAN.md](docs/RELEASE-0.15-PLAN.md); every item is an issue on
the [`0.15` milestone](https://github.com/adamkjonsson/zipline/milestone/3).

**Expect the largest *Changed* section the format has had, and read it in two
halves.** The origination duty makes files conformant under `0.14`
non-conformant under `0.15`. The `#41` work leaves every existing file
*byte*-conformant while restating what its records mean — no reader breaks on
the bytes, and every reader's model of them is out of date.

**`#41` closes here**, three releases after it opened. If you want the release in
one artifact rather than four entries, read
[*Worked example: a decrypted tunnel*](docs/zipline-payload-format.md#worked-example-a-decrypted-tunnel)
and the `vectors/tunnel/` fixture beside it: every rule this release adds or
changes is load-bearing somewhere in those four files.

### Changed

- **A stage MUST declare a break in its *own* output, not only carry one
  forward.** Every normative statement about emitting a
  [Discontinuity](docs/zipline-payload-format.md#discontinuity-0x22) was
  conditioned on the input already carrying one, so the head of a chain — the
  stage that first loses something — was unobliged, and Finding 3 of the `0.13`
  review stayed conformant through two releases that were written to close it.
  The new duty is stated **once**, in §Discontinuity under *What a producer owes
  the block*, and keyed on the one question a producer can always answer: **do
  these two adjacent output units join?**

  It binds any stream whose offsets are the concatenation of its own record
  payloads — the property, not the file kind — which is why a transport stream is
  exempt and why the rule needs no rewriting when this release's later items
  change what a layer is. Three shapes now require a block that did not before: a
  decode stage that leaves a `hole`-class region between two output units
  (**Finding 3**), a **filter** whose dropped records break its survivors apart
  (this is [#78](https://github.com/adamkjonsson/zipline/issues/78)'s title), and
  a **reordering** stage, whose stored neighbours were never adjacent. One shape
  is explicitly *not* a break: framing bytes, nonces and tags left undecoded
  withhold nothing, and the content either side joins.

  **This is what makes `0.14`-conformant files non-conformant.** If you produce
  decoded output, the question to ask of every seam is whether content that
  belonged between those two units reached the file. Note the duty does **not**
  key on `spans` adjacency: correspondence is not identity, so a transforming
  decoder's spans need not abut where its output is continuous — the workaround
  that looks obvious has been unsound since `0.13`.

  One case is decidable from a single file and is now a vector:
  `isolate-unmarked-break`, a `hole`-class Undecoded region between the input
  regions of two adjacent output units, is `discontinuity-unknown-width` with the
  block deleted. Everything else rests on producer knowledge. Two `reason` values
  join the open vocabulary for the new shapes: `records-dropped` and `reordered`.

  The shipped vector `reordered-decoded` changed as a result — it gains a
  Discontinuity at its one seam. It was conformant when shipped and is not now,
  which is the clearest statement of what this entry means.

- **Provenance and layer are independent axes, and "raw" is retired as a
  normative term.** The specification keyed a stream's offset space on *how the
  file was produced*: capture-sourced meant transport-shaped, `zpf`-sourced meant
  decoded. That implication is false in both directions, and one word — `raw` —
  was carrying a statement about provenance while reading as one about how
  processed the bytes were. `decoder_id` already
  [named a layer, not a stage](docs/zipline-payload-format.md#layers-transport-and-decoded-live-in-separate-streams);
  §Conformance contradicted it. Most of this entry is making §Conformance obey.

  **Every existing file stays byte-conformant, and every reader's model of one is
  out of date.** No block, option, enum or field changes. What changes is what a
  file's records *mean*, and the unit those statements are made about: **the
  stream, not the file**. `decoder_id` and `source_id` are per record, so one
  file may hold streams at different positions on the two axes and needs no
  syntax to say so.

  Three things that were forbidden are now legal, each a cell the conflation had
  closed off:

  - **A decoded stream with no predecessor file** — a TLS-terminating proxy, an
    `SSL_write` uprobe, a QUIC library's own stream log. Records carry
    `decoder_id` and reference a `capture` Source. The coverage guarantee does not
    apply, having no input stream to be scoped to, and the referenced Decoder is a
    claim of **identity, not a recipe**: nothing can regenerate that output, so
    verification tooling must not assume re-derivation is available. Vector:
    `proxy-decoded`.
  - **An Undecoded block on a capture-sourced stream** — a reassembler declaring
    what it discarded, with offsets into the capture. The old bar assumed
    capture-sourced meant no transform had run; reassembly is a transform, and a
    destructive one. Vector: `undecoded-in-capture`.
  - **One file creating one stream and preserving another.** "A derived file is
    exactly one of a decode stage or a pass-through, never a mix" is replaced by a
    per-participant rule: a participant MUST NOT both carry `origin` and hold
    records carrying `spans`. The old rule left a tool with a decoder for one
    protocol and not the other two dishonest options — pass everything through, or
    mark the second stream entirely Undecoded, which drops those bytes from the
    output. Vector: `mixed-derivation`.

  One thing is newly forbidden in writing, because legalizing mixed-state files is
  what makes it reachable: **a file MUST NOT derive one of its own streams from
  another.** `spans` name a Source carrying a `digest`, and no file can contain its
  own hash. Vector: `isolate-self-derived`.

  **What to change in a reader.** Nothing parses differently. Stop inferring a
  stream's layer from its Source `kind`, and stop inferring a file's kind at all:
  ask each stream what layer it is at and which `kind` of Source its records
  reference (provenance). The two answers are independent — and the layer question
  gains a second half in the next entry, so read the two together. The
  section formerly titled *Layers: raw and decoded live in separate files* is now
  *Layers: transport and decoded live in separate streams*, and its anchor changed
  with it.

- **A decoder declares the layer it emits, so reassembly can be a decoder.** The
  release's only new syntax: **`output_layer`**, a u8 enum in the Decoder
  Descriptor **body** (`0 = decoded`, `1 = transport`). The rule becomes *layer =
  decoder present ? the decoder's declared `output_layer` : transport*.

  `decoder_id` was doing two jobs — *what produced this and what is it*, and *which
  offset-space semantics apply*. A reassembler wants the first and wants
  **transport** for the second, and one field could not say that, so a
  sessionization stage had to be characterised by the *absence* of `decoder_id`,
  purely because absence was the only way to say "hole-inclusive, `isn`-anchored".
  Its overlap policy, buffer depth and timeout then had nowhere to be recorded, and
  the layer it created had no name. Both now have one.

  **No existing file changes — not one byte.** The field occupies two bytes that
  were `_reserved`, which a conformant writer MUST have written 0, and `decoded` is
  numbered **0**. So every Decoder Descriptor ever written already holds the value
  that says what it always meant, and a `0.14` Decoder body **re-stamped to
  `0.15`** is correct with no byte of it changing — which is what happened to
  `reordered-decoded`. The JSON-Lines projection does change: a `decoder` line now
  always carries `"output_layer"`. The ordering is chosen for exactly that reason
  and is deliberately *not* parallel to Source `kind`.

  > *Corrected in `0.16`
  > ([#97](https://github.com/adamkjonsson/zipline/issues/97)).* As shipped, this
  > entry said "every existing `.zpf` re-reads correctly unmodified", which
  > contradicts the `0.x` rule this document opens with: a conformant `0.15`
  > reader **MUST reject** `version_minor = 14`, so no existing file re-reads at
  > all. The byte-level claim was right and is verified; the compatibility claim
  > around it was not. Inside `0.x` the property has operational content only for
  > files re-stamped to `0.15`.

  **A body field rather than an option, and this release is when that was
  affordable.** As an option it would have been *not safe to skip* — the second
  such case after the Discontinuity block — because a reader retaining but ignoring
  it would read a transport stream's offsets as a payload concatenation, silently.
  In the body there is nothing to skip and no absent case to define. A body-layout
  change is free only while the format is in `0.x`, which is why it is made now.

  **The enum is load-bearing, joining Source `kind`.** A reader that does not
  recognise the value cannot compute the stream's offset space and **MUST NOT**
  guess. Vectors: `sessionization-stage`, `isolate-unknown-output-layer`.

  **A head-of-pipeline reassembler SHOULD declare itself too** — capture-sourced,
  with a Decoder declaring `transport` — but is not required to, so every existing
  file stays conformant. That leaves one logical layer labelled in derived files and
  usually unlabelled in capture-sourced ones. The asymmetry is deliberate and is
  written down: a consumer cannot conclude that an undeclared transport stream had
  no reassembler, only that none was named. Vector: `reassembler-declared`.

  Three consequences settled in the text rather than left to be discovered. A
  **transport-layer record carries no `content_type`**, including a reassembly
  record — `prim:bytes` is mechanically legal and is the wrong answer, because such
  a record's boundaries are a slice and not a unit. **`isn`, `seq_start` and the
  `message` flag bind on the layer, not on provenance**, which a sessionization
  stage's `zpf`-sourced output needed stated explicitly. And **carrying
  `decoder_id` forward through a pass-through is keyed on the decoder, not the
  layer**, so a transport stream whose reassembler declared itself keeps its Decoder
  Descriptor — `output_layer` included — across a merge.

  **Changed, not only added:** "a record is *decoded* iff it carries a
  `decoder_id`" was true and is now only half the question. It is stated once, in
  §Conceptual model, and the four other sites refer to it.

### Added

- **A worked example and a fixture for a decrypted tunnel**, closing
  [#41](https://github.com/adamkjonsson/zipline/issues/41). No new syntax: this is
  the case the rest of the release was for, shown end to end.
  *Worked example: a decrypted tunnel* under §Layers, and `vectors/tunnel/` — four
  files, the largest fixture the suite has:

  ```
  wg.pcap → outer.zpf → packets.zpf → inner.zpf → http.zpf
            capture     zpf           zpf         zpf
            transport   decoded       TRANSPORT   decoded
  ```

  It is worth reading for four things. An inner packet spans the **whole** outer
  datagram, nonce and tag included, so tunnel coverage closes with **no `skipped`
  blocks at all**. One input stream **fans out** into two inner TCP sessions,
  neither covering the input alone and both declaring its whole extent. `inner.zpf`
  is a **`zpf`-sourced transport stream** whose 40-byte hole lives in the sequence
  numbers, with no Discontinuity and no `content_type` — the cell that was
  unreachable before this release. And the loss is traceable at every hop: a
  `decrypt-failed` break in `packets.zpf`, a sequence hole in `inner.zpf`, an
  originated Discontinuity in `http.zpf`, and 80 bytes of still-unreadable
  ciphertext in `outer.zpf`.

  One detail is worth lifting out, because it is the only place the specification
  says what to do when a stage *cannot* carry a break forward: `inner.zpf` reads
  `packets.zpf`'s Discontinuity and is a transport stream, so it may not emit one.
  It declines the crossing instead — no record spans the break — and the
  information survives as a TCP sequence gap. Staying silent *and* splicing would
  have been the violation.

---

## [0.14] — 2026-08-06

A corrective release, like `0.11` and `0.12`: it fixes all seven findings of
[python-zipline's review of `0.13`](docs/SPEC-0.13-REVIEW.md) and adds no option
and no block. Scope and reasoning in
[docs/RELEASE-0.14-PLAN.md](docs/RELEASE-0.14-PLAN.md); every item is a closed
issue on the [`0.14` milestone](https://github.com/adamkjonsson/zipline/milestone/2).

Three of the seven were **rules the specification stated in more than one place,
with only some copies updated** when `0.13` changed them — one of which
contradicted itself outright. That is the pattern worth taking away from this
release, and the reason `check.py` now enforces capability coverage and the
release checklist requires grepping every restatement of a rule before it is
called done.

**Unlike `0.13`, this release has a *Changed* section.** Two findings tighten
conformance rather than clarify it, and burying that under *Clarified* would
repeat the kind of dishonesty this release exists to correct. Read those two
first: a reader that was conformant under `0.13` may not be now. Everything else
either loosens a rule or fixes text that contradicted itself.

### Changed

**These tighten conformance.** A reader or a stage that was conformant under
`0.13` may not be under `0.14`. Both are corrective in spirit — each forbids
something the format already intended to forbid — but neither is a *Clarified*,
and filing them as one would misreport what an implementer has to do.

- **A consumer MUST NOT splice across a Discontinuity.** `0.13` described the
  block's central duty and never required it: everything about the two sides not
  joining was descriptive, with no MUST anywhere, in a document otherwise precise
  about reader duties. A downstream stage could read a Discontinuity, compute
  every offset correctly, emit a unit whose `spans` cross the break, satisfy the
  coverage guarantee, **and remain conformant** — leaving the release's flagship
  block present in files and inert in practice. Two duties now: a consumer MUST
  NOT treat the records either side as contiguous, and **a decode stage reading an
  input that carries one MUST NOT emit a unit whose `spans` cross it without
  emitting a Discontinuity of its own in the corresponding position of its
  output.** The second is what carries the property down a chain; without it a
  break is visible at one stage and gone at the next, which is the original defect
  one hop along.
- **A decode stage that knows an input stream's extent SHOULD declare it.**
  `input_extents` was optional twice over — Session End is `SHOULD`, and the
  option carried neither `MUST` nor `SHOULD` — so the self-verifiability it exists
  to give was available only from writers who volunteered. Now also stated, and it
  is the part a consumer actually needs: **an absent entry asserts nothing.** It
  does not mean the extent is unknown, that the stage consumed the whole stream,
  or that it did not; a consumer cannot tell "did not know" from "did not bother"
  from "predates `0.13`", and for some time the third will be the common case. A
  consumer MUST NOT read absence as either reassurance or alarm. The `SHOULD`
  narrows the gap between writers that opt in and writers whose output most needs
  checking; it does not close it, and the text now says so.

### Clarified

- **A region is cited by the output unit whose emission it *completed*, and two
  records MAY cite the same region.** `0.13` put two rules in one sentence that
  pull apart for exactly the decoders it invokes to justify itself: a region
  "belongs in a unit's span set when it **fed** that unit", and "every input
  offset is still accounted for **exactly once**". Under deflate an early region
  feeds every later unit, so "fed" read literally is the O(n)-spans-per-record
  explosion the same paragraph had just rejected — and putting it in many span
  sets contradicts "exactly once". The workable rule, and the one an implementer
  will reach for, is narrower: the unit it *delivered*, not every unit it
  influenced.

  The coverage guarantee accordingly requires every offset to be covered **at
  least once**, not exactly once. **Never both** — spanned *and* marked Undecoded
  — stays absolute, because that is a contradiction rather than a duplication.
  Overlap is permitted because a real case needs it: a decryptor's nonce and auth
  tag *fed* the plaintext, so an inner record honestly spans the whole ciphertext
  packet, and where one such packet carries **two** output units both were
  genuinely computed from that same framing. Requiring exactness would force a
  producer to award those bytes to one of them arbitrarily. The guarantee exists
  to stop bytes being silently *dropped*; overlap drops nothing.

  **Nothing becomes non-conformant** — this is the one finding in the release that
  loosens rather than tightens, which is why it is here and not under *Changed*.

### Fixed
- **A decoded stream's offset space is defined once, and now counts declared
  widths.** `0.13` added `width` as a term in the positional arithmetic and
  updated **one** of the three places that say what a decoded stream's offset
  space *is* — leaving the *defining* statement in *Layers* and the `extent` gloss
  in *Session End* saying "the concatenation of that participant's record
  payloads". A consumer following either computed every later range short by
  `Σ width`; the `discontinuity-known-width` vector exists precisely because the
  two answers differ visibly (`[75,105)` versus `[50,80)`). The "**not**
  hole-inclusive" clause was outright false — a known-width Discontinuity makes a
  decoded stream hole-inclusive in exactly that region. *Layers* now carries the
  one normative statement and the other sites refer to it. One consequence is
  spelled out because nothing exercises it: a **decoded** input stream's
  `input_extents` counts declared widths too.
- **The pass-through rule for Discontinuity is stated once.** §Discontinuity said
  a pass-through re-emits these "unchanged, exactly as it re-emits Undecoded
  blocks"; §Conformance said it **renumbers** them, each invoking the comparison
  to Undecoded to make its point. §Conformance was right, and the wrong copy was
  in the block's own section — the first place an implementer looks — where it
  produced references into the *input's* namespace among ids that are otherwise
  all the pass-through's own, dangling wherever it minted fresh ones. The rule now
  lives in §Discontinuity alone and §Conformance refers to it. Nothing had tested
  it: `annotator-decoded` carries an inherited *Undecoded* block only.
- **A `passthrough-discontinuity` vector**, which would have caught that. It puts
  both re-emission rules in one file — an Undecoded block copied verbatim beside a
  Discontinuity renumbered from the input's `(session 7, pid 0)` to this file's
  `(session 42, pid 1)` — so a transform that copies ids verbatim produces visibly
  wrong output rather than accidentally-correct output. 36 vectors in total.
- **`input_extents` states its entry size.** Entries are **20 bytes**, so
  `count = len / 20` — which the specification had never said. `spans` pins the
  equivalent down ("each 28 bytes … `count = len / 28`"), and the only place the
  20 was implied was the chunking cap in the repeatable-ids list, which is not
  where a parser author looks. A packed type whose entry size a reader has to
  infer is one an off-by-one hides in.
- **Capability coverage is enforced.** `check.py` now parses the option-id
  registry and the block-type table out of the specification and requires every
  entry to appear in some vector, so **new syntax cannot ship uncovered**. Rules —
  permissions with no id to derive — are declared beside the vector exercising
  each. It **hard-fails**: session fan-out shipped in `0.13` as a *Clarified* item
  with nothing exercising it and the gap survived a whole release, and an advisory
  warning is what gets scrolled past. What a vector exercises is recorded by
  `build.py`, which built the bytes, so `check.py` still parses no block body and
  remains deliberately not a conformant reader.
- **Three vectors, and one option added to a fourth, for capabilities the suite
  had never exercised** — found by the check above on its first run.
  `file-clock-metadata` carries `time_epoch` and the File Header **SINGLE_CLOCK**
  flag; `descriptive-metadata` carries `link_type`, `flow_key`, `identity` and
  `ts_first`; `custom-block` carries a Custom (`0xFF`) vendor block, which is
  *recognised* rather than unknown and projects as `pen`/`subtype`/`payload`. And
  `decoded-basic`'s Decoder gains `params_digest` — **the option the whole
  reproducibility contract is stated against, and it had never appeared in a
  vector.** 35 in total.
- **Session fan-out is exercised at last**, by `session-fan-out` — one input
  participant stream demultiplexed into two output sessions. It shipped in `0.13`
  as a *Clarified* item with nothing testing it, and the gap survived a whole
  release. It mattered more than an untested permission usually would, because
  fan-out and `input_extents` interact: **the obvious implementation — accumulate
  coverage per output session, compare against the extent that session declared —
  passes every other vector in the suite**, since `session-fan-out` is the only
  one with more than one output session, and then fails on the first HTTP/2 file
  it meets. Neither of its sessions covers the extent 200 it declares; only the
  union across both does.

  Its `[0,80)` is spanned by **both** sessions — one ciphertext record's framing
  fed an inner unit in each, which is the case that justified permitting overlap
  in the first place — so it is also the only file exercising *at least once*.
  Paired with `isolate-extents-disagree`, where two sessions declare **different**
  extents for one stream, which an input stream having one length makes a
  contradiction. Both are reachable only because fan-out is legal.
- **Finding 3 is tested end to end**, by the new `splice/` fixture — the
  conformance test for the MUST NOT above. It could not be a standalone vector:
  the break lives in stage 1's *output*, so a reader handed only stage 2 has
  nothing to detect the violation from. `tls-records.zpf` declares a
  Discontinuity at 50; `http.zpf` emits one record spanning `[0,80)` of that
  output — straight across it — and declares nothing. The violation belongs to
  **the pair**: stage 1 breaks no rule, and stage 2 is well-framed with complete
  coverage and nothing wrong on its face, so **a harness that tests files
  individually will pass it**.

  It is also the first fixture the checker actually walks. `check.py` skipped any
  entry with a `files` key and handed it to the chain-specific arithmetic, so the
  chain's own files had never been checked for framing or projection either, and
  a second multi-file fixture would have been checked by nothing at all.

---

## [0.13] — 2026-08-04

The first release since `0.9` to add capability rather than only correct: three
options, one new block type, and two clarifications that the format's own
conformance vectors had been contradicting. Scope and reasoning in
[docs/RELEASE-0.13-PLAN.md](docs/RELEASE-0.13-PLAN.md); every item is a closed
issue on the [`0.13` milestone](https://github.com/adamkjonsson/zipline/milestone/1).

**There is no *Changed* section, and that is the useful thing to know.** Every
entry below is *Clarified*, *Added*, *Fixed* or *Removed*, so **no file that is
conformant under `0.12` stops being conformant** and no writer is obliged to
change. A reader is the other story: one built on the letter of the old text may
have been rejecting valid files, which is what the two *Clarified* entries are
about — read those first.

The one thing to carry into a `1.0` reader: the new
[Discontinuity](docs/zipline-payload-format.md#discontinuity-0x22) block is **not
safe to skip**, the only block of which that is true.

### Clarified

Both of these describe what the format already did. **No file that is conformant
under `0.12` stops being conformant**, and no writer has to change — but a reader
built on the letter of the old text may have been rejecting valid files.

- **`spans` asserts correspondence, not identity.** A decoder **frames, and may
  transform**: it may emit bytes that appear nowhere in its input, in a different
  quantity, and its `spans` name the input region the unit was *computed from*
  rather than a region holding those same bytes. This is what makes gzip, HPACK
  and any decryption stage expressible. *The specification contradicted its own
  shipped conformance vector here:* `vectors/chain/decoded.zpf` has emitted
  `RESP:200` — 8 bytes spanning 16 — since `0.11`, while the text said a decoder
  only frames. `vectors/check.py` never caught it, because it verifies coverage of
  ranges and never payload-to-span correspondence. Consequences now stated: the
  recoverability walk reaches the *corresponding* bytes and not necessarily the
  ones it set out to find (ciphertext, below a TLS stage); the reproducibility
  contract holds for a key-gated stage but only for a key-holder, leaving digest
  verification intact and third-party regeneration impossible; and correspondence
  is **not proximity** — a discarded byte-order mark stays `skipped`, while a
  decryptor's nonce and auth tag are honestly spanned, which closes tunnel-stream
  coverage with no Undecoded blocks rather than one per packet.
- **A decode stage's sessions need not line up with its input's.** The mapping
  from input participant streams to output sessions is **many-to-many** in both
  directions: one input stream may feed several output sessions (HTTP/2
  demultiplexed into a session per stream), one output session may draw on several
  input streams (every two-direction decode already does), and a stage may mint
  sessions with no upstream counterpart. Previously neither permitted nor
  forbidden. What binds an output record to its input is `spans`, never a shared
  `session_id`. The coverage guarantee is unchanged and needed no widening — it
  was already stated per *input participant stream*, which is exactly what makes
  it survive fan-out.

### Added

- **`external_session_id` on the Session Descriptor** (`0x0054`, bytes,
  single-valued) — an identity assigned by something *outside* this format: a
  trace id, a capture orchestrator's UUID, a NetFlow flow key, a case number.
  Nothing here interprets it. It answers a different question from `session_id`,
  which stays **u64** and is still what `spans` and `origin` reference — a
  cross-file reference needs a fixed-width numeric key. Deliberately **opaque and
  variable-length**: one option per session costs nothing per record, so fixing a
  width would foreclose SHA-256s and URNs to save nothing. `bytes` is the option
  registry's first value of that type; it projects as base64, by the same rule
  that already covers `payload`, so a UUID never acquires a second spelling. The
  Session Descriptor prose carries the birthday arithmetic for anyone choosing
  random ids — 2³² is the 50% point in a 64-bit space, and one-in-a-million needs
  only ~6 million ids.
- **`transform_params_digest` on the File Header** (`0x0015`, string,
  single-valued) — the configuration of a transform that produced records
  **without decoding**. Two kinds of stage had nowhere to record it, and the
  specification named the gap without closing it. A **filter or reordering
  stage** is a decode stage, but `decoder_id` names a *layer, not a stage*: it
  inherits its input's decoders and re-declares their descriptors, so every
  `params_digest` in the file describes something that ran further upstream,
  never this stage. A **merge** declares no Decoder at all. Both are
  parameterised, so `produced_by`/`produced_at` did not settle reproducibility
  on their own. A file may carry this *and* an inherited `decoder_id` whose
  descriptor has its own `params_digest` — they describe different stages, one
  here and one upstream — and a raw file, not being a transform's output, MUST
  NOT carry it.
- **`input_extents` on Session End** (`0x00C1`, packed, **repeatable**) — the
  length of each input participant stream a session drew on, in that stream's own
  offset space, as `source_id: u16, pid: u16, session_id: u64, extent: u64`. This
  makes the **coverage guarantee self-verifiable**: a consumer holding only the
  derived file could state which input ranges were covered but never how long the
  streams were, so a stage that stopped early and said nothing about the tail was
  indistinguishable from one that consumed everything — checking meant fetching
  the input and measuring it. Session End is where it goes because
  declare-on-first-use puts the Participant Descriptor before any record, when a
  live decode cannot yet know a stream's length; at Session End it does.
  **Under fan-out, every session consuming a stream declares that stream's whole
  extent identically**, and a checker unions the covering spans across all of
  them — which follows from the coverage guarantee being per input participant
  stream rather than per session. Two sessions declaring different extents for one
  stream is a contradiction a reader MAY treat as a semantic violation. Added to
  the closed repeatable-id list, which now reads `endpoint`, `spans`,
  `input_extents`. Raw files MUST NOT carry it.
- **Three conformance vectors.** `external-session-id` carries a 16-byte binary
  UUID; `decoded-basic` gains a Session End with extents that meet its coverage
  exactly — **the suite's first Session End block anywhere**, a gap nobody had
  noticed; and `isolate-extent-exceeds-coverage` declares a 40-byte stream while
  covering only `[0,20)`, the silent-truncation case the option exists to catch.
  `reordered-decoded` gains a `transform_params_digest`, it being exactly the
  transform whose configuration had nowhere to live.
- **A `Discontinuity` block** (`0x22`), with `width` (`0x00D0`, u64, optional) and
  `reason` (`0x00D1`, string). The release's only new block type. It states a
  break in a file's **own** output stream: the records either side are **not
  contiguous**. This closes a live silent-corruption path on the specification's
  own flagship chain, `raw → tls-records → http`, with no tunnel involved. A
  decode stage's output is the concatenation of its record payloads, so two
  records either side of an input gap are *adjacent* in it — the gap does not
  survive the layer — and nothing obliges a decode stage to re-emit its input's
  Undecoded blocks. So the HTTP stage could emit one message spanning the join,
  **coverage would pass**, and a consumer would read a message that was never
  sent, with no marker in the file it was reading.

  It is the mirror of `Undecoded` (`0x21`), and the two are easy to confuse:
  every field of an Undecoded block is read against the *input*, while a
  Discontinuity's ids name a stream in the file that carries it. Consequently a
  pass-through preserving a decoded layer **renumbers** these to its own ids
  rather than copying them verbatim as it does Undecoded blocks. It discharges no
  coverage obligation; a stage that both failed to decode an input region and
  needs to say its output breaks emits both blocks.

  **`width` absent means unknown** — TLS lost a record and the plaintext length is
  unrecoverable — and contributes **0** to the positional arithmetic, so later
  records stay addressable and a downstream stage can still cite `spans` into the
  output. Present, it is a real hole of known extent (QUIC STREAM offsets) and
  contributes `width`. The positional rule is now
  `[Σ(preceding payload_len + preceding declared widths), + payload_len)`.
  Raw files MUST NOT carry the block: a transport offset space is already
  hole-inclusive, so the two accounts would contradict.

  **This block is not safe to skip, and it is the only one that is not.** A reader
  skipping it by `length` computes a wrong positional range for every later record
  of that participant, silently. The `0.x` rule that a reader MUST reject an
  unimplemented `version_minor` covers that completely today; after `1.0` the same
  block would need a **major** bump. *Version numbering* now uses it as the worked
  example, and states the test for a minor-bump addition as "is a reader that
  skips this still correct", not "can a reader skip this".
- **Three more conformance vectors**, for the block. `discontinuity-unknown-width`
  is Finding 3's stage 1 verbatim; `discontinuity-known-width` picks numbers where
  a reader ignoring `width` computes visibly different ranges (`[75,105)` versus
  `[50,80)`); `isolate-discontinuity-in-raw` puts the block in a raw file, where
  the sequence numbers already state the same gap.
- **A `broken-chain` vector** — the provenance walk that **fails**. `chain/`
  exercises one that succeeds; nothing exercised one that does not, so the two
  outcomes `0.10` made normative and a consumer MUST NOT report identically were
  untested: *no bytes exist* (chain resolved, region genuinely empty) versus
  *bytes unavailable* (chain broke). The vector declares a `zpf-input` Source for
  a `missing.zpf` that is deliberately not in the tree, and an Undecoded block of
  the bytes-exist class pointing into it — so the reference promises fetchable
  bytes and the walk cannot deliver them. It is an **`accept`** vector, not a
  negative one: the file breaks no rule, and what is absent is a sibling. The
  requirement under test belongs to a consumer's recovery walk, not to the file.
  32 vectors in total.

### Removed

- **The planned version re-stamp option is dropped, and will not appear.** The
  `0.11` notes below promise "A way to record a version re-stamp is planned for
  `0.13`, as a File Header option rather than a transform; until then there is
  none." **There will be none.** Correcting it here rather than editing that
  entry, which said what was believed at the time.

  The reason is regime, not cost. In `0.x` the format's own position is that a
  file which still matters is regenerated from its capture, so the option would
  support the one thing the specification says not to do. In a `1.x` minor it is
  unnecessary — a reader MUST NOT gate parsing on `version_minor`, so a `1.1`
  file already reads under `1.3`. Across a major bump it is insufficient — the
  frame or a block body may change, so the file is rewritten, which is a genuine
  transform with real provenance rather than a relabelling. What it really asks
  for is a transcoding specification, one rule per version pair, growing without
  bound. The specification now **states the disposability position directly**,
  under *Version numbering*, where it had never been said — it lived only in this
  file's *Conventions* — and records the rejected option under *Design decisions
  not taken* so the question stops recurring.

### Fixed

- **Three decode-stage vectors now set `produced_by`/`produced_at`.**
  `undecoded-skipped`, `undecoded-reason-class` and `isolate-coverage-gap` are
  derived files, which *Conformance* requires to declare both, and none did. The
  two tiers failed in opposite directions: the `accept` pair failed a **correct**
  reader, while `isolate-coverage-gap` carried a second violation and so passed
  an **incorrect** one — a reader could trip on the missing provenance and pass
  it with coverage checking entirely unimplemented. Found by `python-zipline`
  porting to `0.12`.
- **`reject-unknown-minor` now stamps the minor after this one.** It stamped
  `13`, which this release makes valid; it is derived from the current version so
  it keeps testing an unimplemented minor at every future bump.
- **"One violation per negative vector" is now enforced, not just stated.** It
  has been a ground rule since the suite began and was never checked — and
  `isolate-coverage-gap` broke it through `0.12`, carrying both the coverage gap
  it existed to test and a missing `produced_by`, so a reader could trip on the
  provenance error and pass it **with coverage checking entirely unimplemented**.
  Every vector now declares a `violations` count in `manifest.json`, and
  `check.py` requires it to agree with the tier: 0 for `accept`, 1 for `reject`,
  1 for `isolate`. Declaring it is mandatory — omitting it fails the build rather
  than defaulting — so a new vector cannot be written without confronting the
  number, and adding a second defect to an existing one fails rather than quietly
  weakening it. The count is **declared, never computed** from the file:
  `check.py` is deliberately not a conformant reader, and one that ruled on
  semantics would become a second normative authority. Affects the vector suite
  only; no change to the format.

---

## [0.12] — 2026-07-31

A corrective release, like `0.11`: it fixes what the review
of `0.11` found and adds no option, block or capability. Reasoning in
[docs/implementation-review-response-0.11.md](docs/implementation-review-response-0.11.md).

### Clarified

- **`hint-less` is defined**, having carried normative weight in fourteen places
  with only a parenthetical to explain it: **a session in which no record carries
  `seq_start` or `ack`.** One such hint anywhere means the session is not
  hint-less.
- **Deciding it is deferred to Session End.** Hint-lessness is a property of a
  session's *records*, and declare-on-first-use puts the Session Descriptor
  before them — so a reader concludes it only at Session End or end-of-stream,
  and the `sequenced_basis` check defers to that point. *One boolean per open
  session; it composes with state a reader already keeps.* The producer needs no
  such deferral: it decides by what it is relying on, which it knows when it sets
  the flag.

### Added

- **Two conformance vectors.** `merge-timestamp-tie` — two concurrent records
  from different participants with identical timestamps, stored in the *opposite*
  order to the one the merge must produce, so a reader that falls back to stored
  order fails it. And `partially-hinted-sequenced` — a `SEQUENCED` session with
  one hinted record and two unhinted ones, pinning the answer to the question
  that took longest to settle. 26 in total.

### Changed

- **The merge is now fully deterministic.** Step 4 breaks ties by
  `(timestamp, participant_id)` rather than by timestamp alone. `participant_id`
  is unique within its session, so the frontiers are totally ordered and every
  reader of the same file computes the same interleaving — closing the last place
  two conformant readers could legitimately disagree. `0.11` surfaced this gap
  after removing the round-robin fallback that had masked it. *At least one
  implementation already merges on `(timestamp, pid)` because a total order was
  needed to test the merge at all; this ratifies the convention before more
  implementations pick differently.*
- **Sequencing is stated as an optimisation, not a correctness fix**, which
  follows from the above: a producer baking in the order saves each reader the
  work, it does not change the answer.
- **The producer tie-break clause is scoped.** `0.11` said a producer choosing a
  different tie-break "says so with `sequenced_basis`", but that option is scoped
  to hint-less sessions, leaving a TCP producer nowhere to record it. Now: on a
  hint-less session the producer records the basis; on a session with hints there
  is nothing to record, since causal edges account for the order and only
  genuinely concurrent records reach the tie-break.

---

## [0.11] — 2026-07-30

A corrective release: it fixes what the first review of
`0.10` found and adds no option, block or capability. Everything that would add
surface is held for `0.12`. Reasoning in
[docs/implementation-review-response-0.10.md](docs/implementation-review-response-0.10.md).

### Clarified

- **A `0.9` file stamps `1`/`0` in its header**, not `0`/`9` — stated in
  *Conventions* above and in the `[0.9]` section. The renumbering re-designated
  the July 2026 text without rewriting bytes, so `0.9` is the one version whose
  name and header disagree. *Anyone building a `0.9` reader from the CHANGELOG
  alone would otherwise look for `0`/`9` and reject every real `0.9` file.*
- **`0.x` files are disposable**, stated plainly for the first time: no upgrade
  path between `0.x` versions is guaranteed, and a `0.9` file that still matters
  should be regenerated from its capture. *A way to record a version re-stamp is
  planned for `0.13`, as a File Header option rather than a transform; until then
  there is none.*
- **Recording `sequenced_basis` is unconditional; soundness may be trivial.**
  `0.10` required the option in the registry while the narrative exempted the
  trivially-sound cases and a third passage still said SHOULD — three statements,
  no consistent reading. The exemption was also undecidable for a streaming
  writer, since `SEQUENCED` is written before the records that would settle
  whether only one participant sends. A hint-less `SEQUENCED` session now always
  carries the option.
- **The merge never reorders one participant's records against each other.** It
  is a k-way interleaving of already-sorted streams, so the timestamp tie-break
  chooses only *between* participants — including on a hint-less session, where
  every record is concurrent and the whole order is that tie-break. The property
  followed from the algorithm's shape and was stated nowhere.
- **Not every `zpf-input` Source is an input.** A file may declare one so an
  inherited reference resolves — a pass-through carrying Undecoded blocks that
  name a file further up the chain. The immediate inputs are the Sources that
  `origin` or `spans` point at.
- **A decoded record's positional range costs O(k) for random access**, with the
  recommendation to build per-participant prefix sums on a first pass. Free for
  forward reading, which is the design's primary case.

### Changed

- **The specification is version `0.11`**, so a `0.11` file stamps
  `version_major = 0`, `version_minor = 11`, and renders as
  `"zipline-payload/0.11"`. A `0.10` reader MUST reject it — that is the `0.x`
  regime working as intended, not a defect. *Nothing in this release changes the
  frame, a block body, or an option's meaning; the bump is required because the
  version is how a reader tells the two apart.*

### Added

- **`sequenced_basis` value `trivial`** — for a session with one participant, or
  only one that ever sends. Without it, making the recording unconditional would
  force a producer to claim `clock`, `protocol` or `external` when none is true.
  *A defined value in an already-open vocabulary, so this documents an existing
  possibility rather than adding surface — as `skipped` did in `0.10`.*
- **Two conformance vectors**: `hintless-merge-backwards-ts` (accept) and
  `isolate-sequenced-no-basis` (isolate). 23 in total.
- **A three-file provenance chain** in [`vectors/chain/`](vectors/), whose
  digests and offsets genuinely agree: `raw.zpf` → `decoded.zpf` →
  `annotated.zpf`. It is the only fixture that can exercise the recovery walk,
  two-hop resolution through a decoded-layer pass-through, and digest
  verification — and the only place the **coverage guarantee is actually
  checked**, since verifying it requires the input's stream extents, which live
  in the parent. *That is also a concrete demonstration of why recording those
  extents is on the list for a future version.*

### Changed

- **The merge's step 4 no longer asks a reader to detect clock skew.** "If
  clocks are known-skewed, fall back to round-robin / source order" required a
  determination a reader cannot make — skew is not a property a file asserts, and
  the absence of `SINGLE_CLOCK` says nothing either way. A **producer** computing
  a sequenced order may still choose any deterministic tie-break and record it via
  `sequenced_basis`; a reader always uses the timestamp.

### Fixed

- **The brevity-alias table illustrated the omitted-minor rule with
  `"zipline-payload/1"`** — the retracted version, in the table a reader consults
  while working out what the renumbering did. Now `"zipline-payload/2"`.
- **A stale cross-reference to the merge's removed skew fallback.** One passage
  still cited "step 4's clock/round-robin tie-break" as the reason independent
  reader merges may disagree. With the fallback gone, readers agree except on an
  exact timestamp tie — which this version does not resolve, and now says so.

---

## [0.10] — 2026-07-30

### A note on the numbering

A release was designated `1.0` on 2026-07-09, before any implementation of the
format existed. That was premature. The first implementation surfaced enough
genuine problems — and their resolutions broke enough existing behaviour — that
calling the result a minor bump would have been false: a conformant reader of the
July release silently isolates every record in some files this version permits.

So the July release is retroactively designated **`0.9`**, and this one is
**`0.10`**. The format stays in `0.x` until it has survived implementation, and
`1.0` is reserved for a version that has. More `0.x` rounds are expected.

This is not a compatibility-preserving release, and does not pretend to be:
`0.10` changes existing behaviour, removes a key, and renames a value. The
reasoning is in
[docs/implementation-review-response.md](docs/implementation-review-response.md);
the round of work that preceded it is in
[docs/implementation-feedback-analysis.md](docs/implementation-feedback-analysis.md).

### Clarified

- **Timestamps are not an ordering invariant**. A reader MUST NOT
  reject a file or discard a session because stored timestamps run backwards,
  and MUST NOT re-sort a `SEQUENCED` session by timestamp — its stored order is
  authoritative. Timestamps order records in exactly one place: as the tie-break
  between causally concurrent records during a merge. 0.9 demonstrated a
  legitimate inversion in a worked example but never stated the reader's side of
  it. *A reader that validates monotonic timestamps must drop that check.*
- **The single-trustworthy-clock precondition for `SEQUENCED` binds hint-less
  sessions only**. A session carrying TCP `seq`/`ack` may be sequenced
  however badly its capture clocks disagree; sequencing means "stored in a valid
  causal order", never "sorted by timestamp". 0.9 said this, but rested the
  scope on a single adjective and was misread.
- **Reserved bits of the Record `flags` field are ignored on read**, now
  stated as it already was for the File Header and Session `flags` fields. The
  global reserved-fields rule always required this; only the wording differed.
  A bit nonetheless set is *preserved* through a round-trip without being
  interpreted — the same split between retaining and interpreting that 0.9
  already applied to unknown option ids.
- **Unknown Source `kind` values are an isolatable semantic condition**. A
  reader that cannot classify a Source cannot interpret any record or span
  referencing it — `kind` selects whether span offsets are capture-file byte
  offsets or logical stream offsets — so it MAY reject or discard that Source
  and its dependents, and MUST NOT guess. An unrecognised `tcp_role`, being
  advisory, just means "unknown". *`kind` is therefore not a free extension
  point: unlike a new option id, a new `kind` value will be isolated by existing
  readers.*
- **The `Undecoded` `reason` vocabulary has two recoverability classes**:
  *bytes exist* (`undecodable`, `skipped`) and *hole* (`gap`, `truncated`). 0.9
  described the split in prose without naming it as the part a consumer must get
  right.
- **Each layer has its own offset space, and a decoded stream's is now defined**:
  the concatenation of a participant's decoded record payloads in stored order,
  byte 0 being the first byte of the first such record. Undecoded regions
  contribute nothing, so unlike a transport stream's space it is *not*
  hole-inclusive. 0.9 defined offsets only for reassembled transport streams,
  which left `raw → tls-records → http` — a pipeline 0.9 explicitly invites —
  with no defined offset space for its second stage to reference.
  *Implementers doing multi-stage decode: this is the rule you were missing.*
- **`spans` versus `origin`, not `decoder_id`, discriminates what a file's own
  stage produced**. A record carrying `spans` was built by this stage; a
  record without them, whose participant carries `origin`, was re-emitted from
  the input. `decoder_id` says which decoder's layer a record belongs to, and a
  pass-through carries inherited ones forward, so it no longer implies the
  decoder ran in this stage.
- **`version_minor` describes the file, not the rendering.** A converter
  projects any file into whichever version of the JSONL face it implements, so
  the `format` string reports what the file says rather than what the tool is.
  *The field answers "what does this file contain", never "which tool wrote this
  line".*
- **A one-participant or single-sender session is trivially sequenceable**.
  It has no cross-participant order to get wrong, so it needs no basis at all.
  Vacuous under 0.9's rule, but worth stating, since the clock precondition
  appeared to bite exactly the one-way UDP case it cannot apply to.
- **A decoded-layer filter or reordering stage is a decode stage, not a
  pass-through.** Dropping or reordering a decoded record shifts offsets in that
  participant's space, which stored order defines, so the output cannot claim to
  preserve it. Such a transform cites its input in `spans` — which for a
  reordering stage will *not* ascend with stored order — and marks dropped
  regions `skipped`, bringing the coverage guarantee to bear.
- **`decoder_id` names a layer, not a stage.** A transform that rearranges
  records without decoding them **inherits** its input's `decoder_id`s and
  re-declares the Decoder Descriptors they reference, exactly as a pass-through
  does; a filtered or reordered HTTP message is still an HTTP message. It
  identifies itself through `produced_by`, as every derived file does. *A
  consequence, recorded under future extensions rather than fixed: such a
  transform's own configuration has no `params_digest` to live in, so a filtered
  file records what it came from but not how. A merge already had this gap.*
- **A decoded record's offset range is positional.** A Record block carries no
  offset field, so record *k* of a participant occupies `[Σ payload_len of the
  preceding records, + its own payload_len)` in stored order. The offset-space
  rule implied it; nothing stated it, and a consumer cannot resolve a record
  without it.
- **The class of an `Undecoded` `reason` governs recovery; the word carries
  intent.** Both are usable, for different purposes — a consumer counting
  genuinely unparsed bytes separates `undecodable` from `skipped`. `0.9`'s
  "the class, not the word, is what a consumer acts on" contradicted `skipped`'s
  own justification.
- **A failed recovery walk has two outcomes and they MUST be reported
  distinctly**: *no bytes exist* (the chain resolved; the region is genuinely
  empty) versus *bytes unavailable* (the chain broke — an intermediate file is
  missing, unreadable, or fails its `digest`). Collapsing the second into the
  first asserts something the consumer never established, and is the exact
  silent-data-loss the coverage guarantee exists to prevent.
- **The recovery walk is explicitly conditional.** Nothing obliges a consumer
  that is merely reading a file to walk any provenance chain; the walk is for a
  consumer that actually wants the bytes.

### Added

- **[Conformance vectors](vectors/)** — 21 small `.zpf` files with their
  expected projections or expected failures, covering the baseline container,
  all four unrecognised-data escapes, every `0.10` construct, and both error
  tiers. Hand-built from the normative text rather than generated by any
  implementation, which is what lets them catch an implementation diverging from
  it. `raw-minimal` is byte-for-byte identical to the specification's worked
  example. *Start here when implementing: the `escape-*` and `reject-unknown-minor`
  vectors are the ones a plausible-looking reader most often fails.*
- **Session option `sequenced_basis`** (`0x0053`, string) — what a `SEQUENCED`
  hint-less session's order rests on. A producer **MUST** set it on such a
  session; omitting it is a semantic violation. Open vocabulary, defined values
  `clock`, `protocol`, `external`; a reader MUST NOT reject a session for a value
  it does not recognise.

  It is mostly *not* something a consumer branches on — it is an explanation kept
  for when an order turns out to be wrong, in the family of `creator` and
  `params_digest`: a nonsensical order is a different investigation under `clock`
  (capture skew) than under `protocol` (the producer's assumptions). Requiring it
  also puts the obligation where the knowledge is, since a producer that must name
  a basis has to decide what it is at the moment it sets the bit. One mechanical
  check does fall out: `basis = clock` on a file with several `capture` Sources
  and no `SINGLE_CLOCK` is self-contradictory.
- **Undecoded option `reason_class`** (`0x00A1`, string, `hole` or `bytes`) —
  **required** with any `reason` outside the canonical four. The `reason`
  vocabulary is open so producers can be specific; this keeps that freedom from
  costing consumers the one fact they must act on. *Previously an unrecognised
  reason had no discoverable class at all.*
- **Canonical `Undecoded` reason `skipped`** — a region the decoder
  declined *on purpose*: data it does not care about, or data carrying no
  information, such as a byte-order mark, a padding or a reserved field. It sits
  in the bytes-exist class alongside `undecodable`, from which it differs in
  intent, not recoverability. It earns canonical status because the coverage
  guarantee leaves a decoder no honest third option — without it, a decoder
  ignoring a BOM must either stretch a record's `spans` over bytes it never
  interpreted or call them `undecodable`, asserting a failure that did not
  happen. It also keeps `undecodable` usable as a decoder-quality signal.
  *The vocabulary was already open, so this canonicalises an existing
  possibility rather than adding a capability; 0.9 readers treat `skipped` as
  any unrecognised reason.*
- **The JSONL projection's four escapes for unrecognised data**. The
  binary face has always had one universal rule for what a reader does not
  recognise — skip by length, retain, never error. The projection now mirrors
  it: every unrecognised element has a defined syntactic escape, a converter
  never invents meaning for one, and never silently drops one.

  | Unrecognised | JSONL form |
  |---|---|
  | option id | `options` array entry *(already in 0.9)* |
  | block type | `"type":"0x0042"` + base64 `"content"` |
  | enum value | the raw number |
  | flag bit | a hex token, e.g. `["psh","0x0020"]` |

  *Without this, the first block type or flag bit added by any future minor
  version would be silently lost by a JSONL round-trip, breaking the format's
  forward-compatibility promise on the JSONL side.* An unrecognised block's
  content is base64'd whole — body, options and padding together, since a
  converter cannot take apart a layout it does not know — which makes that one
  case byte-exact rather than merely semantically lossless.

### Changed

- **Version numbering, and what a reader does with it.** Three parts:
  - **`major` and `minor` are independent integers, compared componentwise** —
    never one decimal number. `0.10` is the tenth minor and is **greater** than
    `0.9`. *A parser that reads the `format` string's tail as a float sorts
    `0.10` below `0.9` and silently accepts a file it must reject.*
  - **While `version_major` is `0`, a reader MUST reject a `version_minor` it
    does not implement** — joining the structural-corruption tier alongside an
    unimplemented `version_major`. This is what makes a breaking `0.x` release
    detectable instead of silently destructive.
  - **A writer stamps the version it implements.** The rule that it should
    compute the *lowest* version whose features a file happens to use is
    **withdrawn**: a streaming writer cannot satisfy it, since the File Header
    precedes the content, and it would oblige a writer at, say, `1.67` to carry
    a feature-to-minor mapping forever — to buy a precision readers derive
    locally for free.
- **The `Undecoded` reason `tcp-gap` is renamed `gap`.** It was the only
  transport-specific token in the vocabulary, in a format that is
  transport-neutral everywhere else — and loss detection is not a TCP privilege:
  RTP has sequence numbers, SCTP has TSNs, an application protocol may carry its
  own. Nothing is lost by dropping `tcp`, since the session's `proto` already
  says what the transport was. *A canonical value should be the generic case;
  saying precisely how a hole was found is what the open vocabulary and
  `reason_class` are for.*
- **A pass-through transform preserves its input's *layer*, not just its bytes**.
  0.9 defined pass-through as carrying no
  `decoder_id`, which silently confined it to raw input and left any transform
  over a decoded file — an annotator or a re-merge — unexpressible. A
  pass-through now re-emits its input's records with bytes, logical offsets,
  `decoder_id`s, `content_type`s and Undecoded blocks unchanged, whatever layer
  the input was at, and re-declares the Decoder Descriptors they reference. The
  input's coverage guarantee then holds of the output without the output
  carrying any `spans`. Decoder Descriptors and Undecoded blocks are no longer
  restricted to decode-stage files. *A strict 0.9 reader may refuse a file that
  carries `decoder_id`s alongside `origin`; the [annotator example](docs/zipline-payload-format.md)
  shows the shape.*
- **A transform that only adds metadata is a pass-through**, and its
  output is a *derived* file. Annotating a raw file therefore moves capture-level
  provenance (`link_type`, the capture's `uri`/`digest`) one level away, reached
  through the input Source rather than directly. Nothing is lost, but a consumer
  reading it must take the extra hop.
- **A pass-through carrying inherited Undecoded blocks MUST also declare the
  file those blocks name** and make their `source_id` resolve to it. This
  is the one case where a derived file names something other than its immediate
  input — because the statement being carried forward was always about that
  further-up file. Keeping the inherited ids and numbering the immediate input
  around them lets the blocks be copied verbatim.
- **`SEQUENCED` on a hint-less session requires a sound basis, not specifically
  a clock**. A single trustworthy clock remains the
  common basis; ordering knowledge the format does not model — a server-assigned
  order, an application sequence number, an out-of-band record — now also
  qualifies, with `sequenced_basis` to say which. The producer owns the
  soundness; a reader could never verify the clock claim either. *This permits
  sequenced multi-party UDP and chat sessions that 0.9 forbade.*
- **The specification file is now `docs/zipline-payload-format.md`**,
  renamed from `docs/payload-format.md`: kebab-case, project name included, and
  no version in the filename so the path survives future versions. *A
  documentation-layout change, not a format change — but it breaks existing
  links.*
- **A converter MUST NOT invent an option id** for an unrecognised JSON key on a
  known block. There is no id to write, and guessing manufactures data.
  Such a key cannot arise from a binary source, only from hand-written or
  third-party JSONL; on the JSONL → binary path a converter MUST reject the line
  or drop the key, and MUST report it either way.
- **JSONL: the File Header rate is the key `tick_hz`, carrying a number** —
  previously the alias `time_units`. `tick_hz` is the binary field's own name, so
  the projection's general naming rule now covers it and the alias table has one
  fewer exception. *Writers: emit `tick_hz`.*

### Removed

- **JSONL key `time_units`**, superseded by `tick_hz`. Removed outright rather
  than deprecated: `0.10` claims no compatibility with `0.9`, so there is nothing
  to keep accepting. *A converter that still emits or accepts `time_units` is
  writing `0.9`.*

### Fixed

- **Four JSONL examples wrote `"time_units":"us"`** — a unit label, where
  0.9's normative text defines the value as a rate in ticks per second and
  permits only a number or a decimal string. The examples were non-conformant
  against their own specification, so anything written by copying them was too.
  Corrected to `"tick_hz":1000000`.
- **The example of an *unregistered* option id was `0x0091`**, which is
  registered — it is `content_type`. Changed to `0x0200`, which is outside the
  registry.
- **The decoded-file example's two `record` lines omitted `source_id`**, a
  mandatory body field that the projection's own rule says always projects. Every
  other example in the document includes it. Added.
- **A single-occurrence `endpoint` rendered as a scalar string in every
  example**, while the rule says a repeatable option renders as a JSON array —
  and `spans`, the other repeatable id, is an array even with one entry. Settled
  in favour of the rule: `endpoint` is **always** an array, so a reader never
  branches on a key's JSON type. Eleven example lines corrected. *Found while
  building the conformance vectors, which could not be written until it was
  decided.*
- **Three cross-reference anchors never resolved** — `#session-descriptor-0x10`,
  `#participant-descriptor-0x11` and `#session-end-0x12` pointed at bold labels,
  which generate no anchor. Those five descriptor blocks are now `####`
  headings, matching every other block in the document.

---

## [0.9] — 2026-07-09

The initial specification, published at the time as **`1.0`** and designated
final. It was neither: no implementation existed yet, and the first one found
enough to force a breaking revision. Retroactively renumbered — see the note
under `0.10` above.

**Files of this version stamp `1`/`0` in the File Header**, not `0`/`9`. Only
the designation changed; the bytes never did.

### Added

- **Container.** Length-prefixed typed blocks with an 8-byte frame, little-endian
  throughout, 4-byte aligned; TLV options (`id: u16, len: u16, value`) with
  skip-what-you-don't-know rules for both unknown block types and unknown option
  ids.
- **Model.** Sessions holding *N* participants (not two sides), carrying directed
  records that name a sender and no recipient — covering TCP (`N = 2`), chat
  rooms (`N > 2`) and one-way UDP (`N = 1`) in one shape.
- **Blocks.** File Header, Source Descriptor, Decoder Descriptor, Session
  Descriptor, Participant Descriptor, Session End, Record, Undecoded,
  Name/Identity Resolution, End, and a PEN-namespaced Custom block.
- **Declare-on-first-use.** A descriptor need only precede its first reference,
  making the format append-only and streamable; Session End is its mirror,
  bounding reader state.
- **Causal ordering.** Cross-participant order derived from absolute TCP
  `seq_start`/`ack` under RFC 1982 serial-number arithmetic, so separately
  captured directions with skewed clocks order correctly; specified as a
  streaming k-way merge, with timestamps used only to break genuine ties.
- **Precomputed order.** Per-session `SEQUENCED` flag and file-level
  `SINGLE_CLOCK` flag, letting a producer commit a resolved order once so
  readers skip the merge.
- **Layering.** Decoding as a file → file transform (`raw.zpf → decoded.zpf`)
  rather than an in-record layer, with logical 0-based stream offsets, `spans`
  provenance, `digest` dependency edges, and the coverage guarantee enforced by
  Undecoded blocks.
- **JSON-Lines projection.** A semantically lossless one-object-per-line face
  defined by one naming rule plus a short list of exceptions.
- **Conformance.** Two-tier error handling (structural corruption → reject;
  semantic violation → MAY isolate), truncation and completeness rules, and a
  byte-annotated worked example of a complete 196-byte raw file.

[0.18]: https://github.com/adamkjonsson/zipline/compare/v0.17...v0.18
[0.17]: https://github.com/adamkjonsson/zipline/compare/v0.16...v0.17
[0.16]: https://github.com/adamkjonsson/zipline/compare/v0.15...v0.16
[0.15]: https://github.com/adamkjonsson/zipline/compare/v0.14...v0.15
[0.14]: https://github.com/adamkjonsson/zipline/compare/v0.13...v0.14
[0.13]: https://github.com/adamkjonsson/zipline/compare/v0.12...v0.13
[0.12]: https://github.com/adamkjonsson/zipline/compare/v0.11...v0.12
[0.11]: https://github.com/adamkjonsson/zipline/compare/v0.10...v0.11
[0.10]: https://github.com/adamkjonsson/zipline/compare/v0.9...v0.10
[0.9]: https://github.com/adamkjonsson/zipline/releases/tag/v0.9
