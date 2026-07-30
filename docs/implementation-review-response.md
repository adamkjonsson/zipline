# Response: the 1.1-beta implementation review

Assessment of [SPEC-1.1-REVIEW.md](SPEC-1.1-REVIEW.md), a review from
`python-zipline` dated 2026-07-28, and the decisions that follow from it.

The review is kept **verbatim as received**. It speaks of "1.1-beta" throughout,
which was the working name for this body of work at the time; §2 below is the
decision that renumbered it to `0.10`. A version `1.1` therefore never existed
and will not appear in the CHANGELOG — the name survives only in the review's
filename and its own text, both left alone so the record stays honest.

Companion to [implementation-feedback-analysis.md](implementation-feedback-analysis.md),
which covers the earlier round (issues #8–#16). That round's roll-out plan is
complete through Phase 6; its two remaining Phase 5 release steps are
**superseded** by the renumbering decided here.

---

## 1. Verdict at a glance

| # | Review point | Valid? | Disposition | Effort |
|---|--------------|--------|-------------|--------|
| 1 | `[strict-reader]` carve-out has no wire signal | **Yes — and understated** | Resolved by the 0.x rule: a reader MUST reject a `version_minor` it does not implement while major is `0` | S |
| 2 | Filter example contradicts the offset-space rule | **Yes** | Fix: a decoded-layer filter is a *decode stage* marking dropped ranges `skipped` | S |
| 3 | `sequenced_basis` is unactionable | **Yes** on `transport`; substantially yes on MUST | Fix: MUST, and cut `transport` | S |
| 4 | Unrecognised-`reason` rule buys a MUST with unbounded I/O | **Half** — the second half is the serious one | Fix: `reason_class`, conditional walk, distinct reporting | M |
| 4′ | *(not from the review)* `tcp-gap` is transport-specific | — | Rename to `gap`; other transports detect loss too | S |
| 5 | Lowest-minor rule fights the streaming contract | **Yes** | **Dissolved**: the rule is deleted | — |
| — | Machine-checkable test vectors | **Yes, strongly** | **In scope for `0.10`** — see §6 | **L** |

**Five of five valid at least in part.** Two are silent-data-loss shaped — point 1,
and the second half of point 4 — and should gate the release.

Worth recording plainly: **three of the five are defects introduced in Phases 4–5
of the previous round**, not inherited from the original specification. The
relaxation-without-a-signal, the filter claim, and the streaming conflict were all
added by the 1.1 work. The review is doing exactly the job the beta period exists
for.

---

## 2. The versioning decision

### The problem

The specification says, at *File Header*:

> A **minor** version bump only adds blocks/options (old readers keep working);
> a **major** bump may break frame/body layout.

The 1.1 CHANGELOG says something broader, which was written for 1.1:

> **minor** — adds blocks and options that old readers safely skip, pins down
> behaviour an earlier version left undefined, and **may relax writer
> restrictions**.

These contradict each other, and 1.1 relies on the second. Its relaxations —
layer-preserving pass-through, the `SEQUENCED` basis — produce files that a
conformant 1.0 reader does **not** keep working on: it isolates every record and
reports success. Measured against the specification's own definition, 1.1 is not
a minor bump.

The review frames this as "textually 1.1 is within its own rules". It is
**understated**: 1.1 is within the rules of a definition 1.1 itself widened.

### The decision

**Retroactively designate the July 2026 release `0.9`, and release this work as
`0.10`.** The format stays in `0.x` until it has survived more than one round
with an implementation; `1.0` is reserved for a specification that has earned it.

Safe here because no `1/0`-stamped files exist outside development — confirmed
2026-07-28. That condition is load-bearing: relabelling the *document* is not
enough on its own, because a released file carries its version in its header. Had
real `1/0` files existed, two incompatible formats would claim identical version
bytes, which is strictly worse than calling this 1.1 — a reader would have no
discriminator at all. In that world the answer would have been **2.0**.

**This is honest, not a dodge.** Semantic versioning reserves `0.y.z` for initial
development, where anything may change at any time. Relabelling makes the
incompatibility *contractually expected* rather than merely excused. The actual
error was declaring 1.0 final after zero implementations, and then calling the
fallout a minor bump; the renumbering corrects both rather than hiding them.

**Why `0.10` rather than `1.0`.** More breaking rounds with the implementation
are expected. In `1.x` each would burn a major number — 2.0, 3.0, 4.0 — which
misrepresents a format still being designed. In `0.x` the same sequence reads as
what it is: `0.10`, `0.11`, `0.12`, until the design stops moving.

Note `0.10` is **greater** than `0.9`: the components are independent integers,
not a decimal fraction. See the parsing hazard in §3.

### What it resolves, and how

**Review point 1**, but not for free. Under a `1.0` release the discriminator
would have been the major bump, handled by a rule the format already has — *a
reader MUST reject a `version_major` it does not implement*. Staying in `0.x`
means both files carry major `0`, so that rule never fires: a 0.9 reader meets a
0.10 file, sees a major it implements, proceeds, and silently isolates every
record. That is precisely the failure the review identified.

Staying in `0.x` therefore requires a new rule, which is also what `0.x` honestly
means: **while `version_major` is `0`, a reader MUST reject any `version_minor`
it does not implement.** The pair `(0, minor)` is the compatibility identity, and
nothing is guaranteed to survive a `0.x` minor bump.

No feature-flag bit is needed, and the `[strict-reader]` class still goes: the
signal is the minor itself, and in `0.x` checking it is normative rather than
optional.

### Two notes

**Nothing ever needs to stamp `0/9`.** With no files in the wild, the relabel is
documentary. If a stray 0.9-era file ever surfaces, the major rule handles it: a
1.0 reader does not implement major 0 and rejects cleanly.

**One sequencing risk, outside the spec.** Until `python-zipline` is updated, it
emits `1/0` carrying 0.9 semantics. Files it writes in the interim are ambiguous.
Not a specification problem, but it argues for landing the renumbering before the
implementation adopts anything else.

---

## 3. The minor-version policy

The lowest-minor rule added in Phase 5 is **deleted**, not amended. Two arguments
kill it, and the second is decisive:

1. **It is unsatisfiable while streaming** (review point 5). The File Header is
   block one, and a live writer cannot know whether a session it has not yet
   opened will need a later construct.
2. **It does not scale.** A writer at 1.67 would need a feature→minor mapping
   covering every minor whose features it emits, maintained forever — to buy a
   reader precision that the reader can derive itself, locally and for free, at
   the moment it actually meets an unknown construct.

### The replacement

**`version_minor` is the minor the writer implements.** No bookkeeping, no table,
satisfiable at header time by a streaming writer.

The rest of the policy has **two regimes**, because a format still being designed
and one in service need opposite guarantees:

**While `version_major` is `0` — the current regime.** Anything may change
between minors, including things that break readers. The pair `(0, minor)` is the
compatibility identity: a reader **MUST reject** any `version_minor` it does not
implement. `version_minor` is therefore load-bearing, not advisory.

**From `1.0` onward.** Minors are **strictly additive** — old readers keep
working, guaranteed by the skip rules (unknown block skipped by frame `length`,
unknown option by `len`, reserved bits ignored, and the four JSONL escapes). A
reader **MUST NOT** gate parsing on `version_minor`; it discovers what it does
not know locally, as it meets it. Anything not strictly additive is a **major**
bump, where a reader MUST reject a `version_major` it does not implement.

There is deliberately **no** MUST floor tying the stamp to the features a file
uses. In `0.x` it would be redundant, since the reader rejects on the minor
anyway. From `1.0` it would have nothing to signal, since additive changes are
safe by construction. It would only earn its place in a world where a `1.x` minor
could break readers — and the right answer is to forbid that world rather than
instrument it.

**Consequence for the eventual 1.0:** `version_minor` becomes advisory at exactly
the moment the format stops breaking. That is the transition `1.0` should mean.

### A parsing hazard `0.10` makes live

The `format` string is `"zipline-payload/<major>[.<minor>]"`. An implementer who
parses that tail as a decimal number gets `0.10 == 0.1`, which sorts **below**
`0.9` — inverting the version order and silently accepting a file it must reject
under the `0.x` rule above.

Latent while the versions were `1.0` and `1.1`; live the moment `0.10` ships. The
specification should say outright that `major` and `minor` are independent
non-negative integers, compared componentwise, and never parsed as a single
decimal number. Same for the binary fields, which are already two separate `u16`s
— the hazard is specific to the JSONL spelling.

The companion Phase 5 sentence — that the version describes the file rather than
the rendering — survives and gets simpler: a file's minor is stamped once by
whoever wrote it and never changes, and a converter reporting it merely repeats
what the file says.

---

## 4. What the renumbering un-decides

Several earlier decisions were justified **solely** by "every conformant 1.0 file
stays valid". With no compatibility claim to 0.9, that constraint is gone and
those decisions should be revisited:

- **`time_units` reverts to hard removal.** Deprecate-and-accept-on-read was
  chosen in Phase 1 only because `"time_units":1000000` was conformant 1.0 JSONL.
  Nothing needs preserving now, so the alias goes — restoring the original Phase 0
  choice (option C) before compatibility argued it down.
- **`sequenced_basis` MUST needs no version scoping.** The proposed
  "MUST, for files stamping `minor ≥ 1`" was there to avoid retroactively
  invalidating 1.0 files that set `SEQUENCED` under the old clock rule. Now it is
  simply MUST.
- **The `[strict-reader]` class is deleted** from the CHANGELOG conventions. It
  described a hazard that only exists across a minor bump.
- **The release preamble's "No change alters the binary container" paragraph is
  deleted.** It was a compatibility claim against a version this release no longer
  claims compatibility with.

---

## 5. Disposition of the surviving review points

### Point 2 — the filter example

**Valid; the error is mine.** The CHANGELOG motivates layer-preserving
pass-throughs with "an annotator, a filter, a re-merge", while *Each layer has its
own offset space* excludes filters: a decoded stream's offsets are the
concatenation of its payloads in stored order, so dropping a record shifts every
subsequent offset, and a pass-through must preserve them.

The review's analysis of which transforms survive is correct in detail, including
the subtle cases — re-merges are fine because per-participant relative order
survives interleaving, and transport-layer filters are fine because that space is
hole-inclusive, so offsets do not shift.

**Adopt their second option, not the first.** Rather than dropping "a filter"
from the prose, state what a decoded-layer filter actually is: a **decode stage**
that cites its input's spans and marks the dropped ranges Undecoded with
`reason = skipped`. That satisfies the coverage guarantee and is a good use of
the new reason. It does mean the filter declares a Decoder Descriptor naming
itself, which stretches "decoder" slightly — say so explicitly rather than
leaving implementers to infer it.

### Point 3 — `sequenced_basis`

**`transport` is indefensible** — it is listed as a suggested value beside a
parenthetical saying it can never legitimately appear. Cut it.

**On actionability, a partial pushback.** "No consumer can branch on it" is too
strong. There is one concrete, mechanically checkable case: a hint-less session
marked `SEQUENCED` with `basis = clock`, in a file with multiple `capture`
Sources and **no** `SINGLE_CLOCK`, is self-contradictory — the producer asserts
one trustworthy clock while the file says timestamps are not globally comparable.
`clock` is the common basis, so this is not a corner case. Without the basis
recorded, that inconsistency is invisible.

That said, the review's core point stands and is the reason to act: with SHOULD,
**absence is meaningless** — "no sound basis" is indistinguishable from "producer
did not bother".

**Decision: MUST**, on three grounds, of which the review's own test covers only
the weakest.

**It is a forensic field, not a runtime signal.** The review asks whether a
consumer can branch on it, and mostly the answer is no. But the format already
carries fields that fail that test deliberately — `creator`, `produced_by`,
`params_digest`. Nobody branches on those either; they exist so that when
something turns out to be wrong later, it can be explained. `sequenced_basis` is
in that family. Records in an order that makes no sense are a very different
investigation depending on whether the producer claimed `clock` (look at capture
skew) or `protocol` (look at the producer's protocol assumptions) or `external`
(look outside the file entirely). Judging it as a read-time signal measured it
against the wrong contract.

**The MUST is a speed bump on the producer.** A writer obliged to fill the field
in has to decide what the basis *is* at the moment it sets the bit. That is the
mechanism by which the requirement catches a `SEQUENCED` claim with nothing
behind it, and it works whether or not any consumer ever reads the value. It also
states, in the only way a format can, that marking a session `SEQUENCED` is a
strong assertion rather than a default.

**Absence becomes meaningful**, which is the review's own point and the reason
SHOULD was not enough: under SHOULD, "no sound basis" and "producer did not
bother" are the same file.

The `clock` / `SINGLE_CLOCK` cross-check remains as a bonus rather than the
justification. The alternative the review offers — drop the option and call
`SEQUENCED` an unverifiable assertion — is rejected: it discards the forensic
value and removes the speed bump, keeping only the bare bit that prompted the
complaint.

### Point 4 — unrecognised `reason`

**The first half is a misreading of text I wrote ambiguously.** The provenance
walk was meant to be conditional on wanting the bytes; *"It follows the reference
… and reports the region as empty only if nothing is found there"* reads as
unconditional. The ambiguity is the defect, so it needs fixing regardless of the
reading.

**The second half is the serious finding and deserves top billing.** *Undecoded*
says a missing intermediate file stops recovery, so "found nothing" conflates
**no bytes ever existed** with **the file I needed is gone**. Reporting those
identically is exactly the silent-data-loss shape the coverage guarantee exists
to prevent.

**Fix, in three parts:**

- A **`reason_class`** companion option (`hole` / `bytes`), **required** whenever
  `reason` is not one of the four canonical values. This makes an open vocabulary
  self-classifying without touching the values that already exist.
- Make the walk **explicitly conditional** on a consumer that wants the bytes.
- Require the two outcomes to be **reported distinctly** — "no bytes exist" and
  "bytes unavailable, chain broken" are different answers.

**Pushback on the proposed syntactic prefix** (`hole:tcp-gap`, `bytes:skipped`):
it respells all four canonical values, invalidating existing files, to buy what a
companion option gets additively. The renumbering would technically permit the
respelling, but it is still the worse mechanism — it puts the classification
inside a string that also carries the intent, so every consumer must parse where
one could read a field.

**The smaller wobble is real.** "The class, not the word, is what a consumer acts
on" contradicts `skipped`'s own justification, which is that a consumer counting
unparsed bytes acts on the word. Reword: the *class* governs recovery, the *word*
carries intent, and consumers use both for different purposes.

### Point 4, extended — rename `tcp-gap` to `gap`

Not from the review; raised separately while considering it, and it belongs with
the same edit.

`tcp-gap` is the **only transport-specific token in the vocabulary**, in a format
that is deliberately transport-neutral everywhere else: logical offsets are
defined without reference to TCP, the merge carries a transport-neutrality note,
and *Possible future extensions* already contemplates SCTP. Loss detection is not
a TCP privilege — RTP has sequence numbers, SCTP has TSNs, and an application
protocol may carry its own. A hole found by any of them is the same object.

**`gap` rather than `data-gap`.** The specification's own narrative already calls
it that: *"A plain **gap** is simply the no-data case of an Undecoded block."*
Matching the word the prose already uses beats coining a compound, and everything
in this vocabulary concerns data, so the qualifier adds nothing.

**Nothing is lost by dropping `tcp`.** The transport is already recoverable from
context — the Session's `proto`, and the stream the block references — so the
token was duplicating information the file carries anyway.

**It also fixes a layering mistake.** A *canonical* value should be the generic
case; a producer needing to say precisely how a hole was detected has the open
vocabulary plus the new `reason_class` for exactly that. As a canonical token,
`tcp-gap` was doing the open vocabulary's job.

**Free now, expensive later** — the same argument that returns `time_units` to
hard removal (§4). In `0.x` a rename costs one string; after `1.0` it costs a
deprecation cycle. The vocabulary is already being opened for `skipped` and
`reason_class`, so this is the moment.

Cost to `python-zipline`: one string constant. Four sites in the specification,
one in the CHANGELOG.

---

## 6. The test-vector ask

**Endorsed, and rated above three of the five numbered points.**

The evidence is decisive. The four `"time_units":"us"` examples became a real
conformance defect in `python-zipline`, which copied the examples rather than the
normative text. That is precisely the failure mode vectors prevent, and it has
already happened once in a document with one implementation.

The CHANGELOG's own claim — that clarifications are "where two independent
implementations most easily disagree" — is an argument for vectors, not against
them.

**Decided: in scope for `0.10`.** Accepting that it is the largest remaining item
and will dominate the schedule to release. Five design decisions follow, and they
matter more than the count of vectors.

### They must be built from the specification, not dumped from the implementation

This is the one that determines whether the exercise is worth anything. The
entire value is catching the case where an implementation diverges from the text.
Vectors generated *by* `python-zipline` would encode its current understanding,
including whatever it has already got wrong — the `time_units` defect would have
been faithfully baked into a vector and blessed.

So they are hand-constructed from the normative text, byte by byte. Expensive,
and unavoidable. The existing 196-byte
[byte-annotated worked example](zipline-payload-format.md) is proof the method
works and becomes the first vector nearly for free.

### They are conformance tests, not a second normative source

If a vector and the specification disagree, **the vector is wrong** and gets
fixed. Saying so explicitly matters, because the failure mode being guarded
against — an implementer copying an artifact instead of reading the text — is
exactly what vectors could otherwise reintroduce in a new form.

That said, every disagreement gets investigated before it is dismissed. A vector
that contradicts the text usually means the text is ambiguous, which is the
second thing vectors are for.

### Negative vectors matter more than positive ones

The review asked for valid-file/expected-projection pairs. Those are the easy
half. The format has a **two-tier error model**, and the tiers are exactly where
implementations will differ:

- **Reject** — bad magic, `length` not a multiple of 4, a `payload_len` that
  overruns its block, a `version_major` not implemented, and now a
  `version_minor` not implemented while major is `0`.
- **Isolate, not reject** — an undeclared `session_id`, a doubly-declared id, a
  coverage-guarantee failure. A reader that rejects these is as wrong as one that
  accepts them silently.
- **Neither — the normal path** — an unknown block type, an unknown option id, a
  set reserved bit. A vector here catches the implementation that treats
  extension as corruption.

The last group is where a naive implementation most often fails, and it is
untestable without vectors that deliberately contain unknown constructs.

### The JSONL side cannot be compared byte-for-byte

The projection is *semantically* lossless, not byte-exact: key order within a
line, number-versus-decimal-string encodings, and how a `spans` list is split
across occurrences are all free. But **line order is significant** —
declare-on-first-use and stored record order both carry meaning.

So the comparison rule is: lines in order, each line parsed and compared as an
object, with the documented encoding equivalences normalised first. Worth stating
in the manifest, or every implementer writes a naive differ and gets false
failures on their first run.

### Reviewable in a diff

A committed `.zpf` is an opaque blob; a change to one is unreviewable. Each vector
therefore ships as three files — the binary, a byte-annotated hex dump in the
style the specification already uses, and the `.jsonl` projection — with the hex
dump generated from the binary so it cannot drift. The hex dump is what a human
reads in a pull request.

### Coverage for `0.10`

Baseline: the minimal raw file, a decoded file, a transport-layer pass-through.
Then one per `0.10` construct — each of the four escapes, the annotator shape
(decoded layer preserved), an unrecognised `reason` with `reason_class`, a
`skipped` region, a hint-less `SEQUENCED` session with `sequenced_basis`, and a
`0.11`-stamped file that a `0.10` reader must reject. Roughly a dozen.

---

## 7. Roll-out plan

Continues the numbering from
[implementation-feedback-analysis.md](implementation-feedback-analysis.md) §7,
whose Phases 0–6 are complete.

### Phase 7 — Decisions

- [x] **Versioning** — **decided**: the July 2026 release becomes `0.9`; this work
      releases as `0.10`; the format stays in `0.x` until it has survived more
      than one round with an implementation
- [x] **`sequenced_basis`** — **decided: MUST** on a hint-less `SEQUENCED`
      session. Justified as a forensic field (the `creator`/`produced_by` family)
      and as a speed bump that makes a producer confront the claim, not as a
      read-time signal — see §5
- [x] **Test vectors** — **decided: in scope for `0.10`**, accepting that they are
      the largest remaining item. Built from the specification rather than
      generated by an implementation, or the exercise is worthless — see §6
- [x] **`SPEC-1.1-REVIEW.md`** — committed, moved to `docs/` alongside the
      specification and the two analysis documents. Kept verbatim, including its
      "1.1-beta" framing, which §2 renumbered

### Phase 8 — Renumbering

Do this first and in one commit: it changes the frame every other item is
described in.

- [x] Spec title and status banner — this is `0.10`; say plainly that `0.x` is a
      design in progress, that any minor may break readers, and that `1.0` is
      reserved for a specification that has survived implementation
- [x] *File Header* — `version_major` row becomes `0`, `version_minor` becomes
      `10`; write the two-regime policy from §3; **delete** the lowest-minor
      paragraph added in Phase 5
- [x] Add the `0.x` reader rule: while `version_major` is `0`, a reader MUST
      reject a `version_minor` it does not implement. This is what replaces the
      major-bump discriminator, and without it review point 1 is unfixed
- [x] Add the componentwise-comparison rule for the `format` string — `major` and
      `minor` are independent integers, never a decimal number (§3). `0.10 > 0.9`
- [x] Keep and simplify the "describes the file, not the rendering" sentence
- [x] Examples — every `format` string becomes `"zipline-payload/0.10"`,
      including the annotator example, since in `0.x` the stamp is the writer's
      version rather than a per-file feature floor
- [x] Byte-level worked example — `version_major` and `version_minor` bytes both
      change (`01 00`/`00 00` → `00 00`/`0A 00`); check the annotation text and
      that no length or offset is affected (none should be — both are `u16`)
- [x] CHANGELOG — `[Unreleased] — 1.1-beta` becomes `[0.10]` with a date; the
      existing `[1.0] — 2026-07-09` becomes `[0.9]`; rewrite *Conventions*
      (two-regime policy, delete `[strict-reader]`), delete the binary-container
      compatibility preamble, and state openly that 1.0 was declared final after
      zero implementations
- [x] README status section — no production-readiness claim while in `0.x`; its
      current text still says 1.0 is final and 1.1 is in beta, both now wrong
- [x] README *Documentation* list — add the review and this response alongside
      the specification and CHANGELOG, so the record of how `0.10` was arrived at
      is discoverable
- [x] Git tag `v0.9` created at `bc4bcfb`, annotated with why the renumbering
      happened
- [x] **`v1.0` tag deleted**, locally and on the remote. `v0.9` is the only tag,
      and the CHANGELOG's compare links point at it
- [ ] Tag `v0.10` at the release commit — Phase 11, not now
- [x] Add a note to [implementation-feedback-analysis.md](implementation-feedback-analysis.md)
      recording that its "v1.0 → v1.1" framing was renumbered to "0.9 → 0.10",
      and that its Phase 5 release steps are superseded

### Phase 9 — The surviving review points

- [x] **§4 first** — `time_units` hard removal, now that nothing requires the
      alias; delete the *Deprecated keys* note added in Phase 1 and the
      CHANGELOG's *Deprecated* section
- [x] **Point 2** — state that a decoded-layer filter is a decode stage citing its
      input with dropped ranges marked `skipped`, including the note that it
      declares a Decoder Descriptor naming itself; fix the CHANGELOG motivation
- [x] **Point 3** — `sequenced_basis` becomes MUST for a hint-less `SEQUENCED`
      session; cut `transport` from the vocabulary; state the `clock` /
      `SINGLE_CLOCK` cross-check as the one mechanical check a consumer can run
- [x] Say in the spec what the field is *for* — explaining a suspect order after
      the fact, alongside `creator` and `produced_by` — so it is not read as
      something a consumer must branch on. Absent that, the next reviewer files
      the same objection
- [x] **Point 4a** — register `reason_class` (`hole` / `bytes`), required whenever
      `reason` is outside the canonical four
- [x] **Rename `tcp-gap` → `gap`** — four sites in the spec, one in the CHANGELOG.
      Do it in the same edit as `reason_class`, since both change what the
      canonical vocabulary is, and state the rationale (a canonical value is the
      generic case; specificity belongs to the open vocabulary)
- [x] **Point 4b** — make the provenance walk explicitly conditional
- [x] **Point 4c** — require "no bytes exist" and "chain broken" to be reported
      distinctly
- [x] **Point 4d** — reword the class-versus-word sentence so it stops
      contradicting `skipped`'s justification
- [x] Re-check that `reason_class` does not disturb the two-class table or the
      coverage-guarantee narrative

### Phase 10 — Test vectors

Starts only after Phases 8 and 9 have landed: a vector built against text that is
still moving has to be rebuilt.

- [x] Decide the layout — `vectors/` at the repo root, with a manifest naming
      what each vector exercises and which section it comes from
- [x] Write the manifest's ground rules first: vectors are conformance tests
      subordinate to the normative text, hand-built from it rather than generated
      by an implementation, and the JSONL comparison is line-ordered but
      object-compared per line (§6)
- [x] Build the tooling — a hex-dump generator so the annotated view cannot drift
      from the binary, and a checker that validates a vector against the manifest
- [x] Baseline vectors: minimal raw file (adapt the existing byte-annotated
      example), decoded file, transport-layer pass-through
- [x] Escape vectors: unknown block type, unknown option id, unknown enum value,
      set reserved flag bit
- [x] `0.10` construct vectors: annotator (decoded layer preserved), `skipped`
      region, unrecognised `reason` with `reason_class`, hint-less `SEQUENCED`
      with `sequenced_basis`
- [x] Negative vectors, **reject** tier: bad magic, `length` not a multiple of 4,
      `payload_len` overrunning its block, unimplemented `version_major`, and a
      `0.11`-stamped file that a `0.10` reader must reject under the new `0.x`
      rule
- [x] Negative vectors, **isolate** tier: undeclared `session_id`, doubly-declared
      id, coverage-guarantee failure — a reader that *rejects* these is as wrong
      as one that accepts them silently
- [x] Cross-check every vector against the specification by hand before
      committing. A vector that disagrees with the text is investigated, not
      quietly adjusted — the disagreement usually means the text is ambiguous

### Phase 11 — Release

Two content fixes first, both raised by reading the annotator example and asking
where a *record's* source bytes are. Neither is a design change; the design
answers the question, the document just never says so.

- [x] **State that a record's offset range is positional.** §4.1 defines a
      decoded stream's offset space as the concatenation of that participant's
      decoded payloads in stored order, which *implies* that record *k* occupies
      `[sum of preceding payload lengths, + its own length)` — but never says it.
      A record carries no offset field, so an implementer has to derive the rule
      before it can resolve anything. One sentence beside the offset-space
      definition
- [x] **Explain the resolution asymmetry in a decoded-layer pass-through.** Its
      records resolve through the **immediate** input — participant `origin`,
      then the same offset range in that file, whose records carry the `spans`
      that name the grandparent — while an inherited Undecoded block names the
      grandparent **directly** and resolves in one hop. So the annotated file
      alone cannot say which raw bytes a record came from, even though it
      declares `raw.zpf` as a Source, which makes the wrong reading look
      plausible. Say this at the annotator example, with the reason: `spans` is
      the discriminator between a stage that *built* a record and one that
      *re-emitted* it, so a pass-through cannot carry spans forward without
      breaking the test that spared us a third file kind. The Undecoded block is
      exempt because its statement was always *about* the grandparent — it is
      not provenance for anything this file produced
- [x] **Fix a contradiction Phase 9 introduced about `decoder_id`.** Phase 4 says
      it names *which decoder's layer a record belongs to*, which is what lets a
      pass-through carry inherited ids forward. Phase 9's filter paragraph says
      the transform "declares a Decoder Descriptor **for itself**… the descriptor
      identifies whatever **produced** these records". For a filter or a
      record-reordering transform these give different answers, and the Phase 4
      reading is the load-bearing one — a reordered HTTP message is still an HTTP
      message, so naming the reorderer misdescribes the payload.

      Resolution: **`decoder_id` is layer identity, always.** A transform that
      creates records without decoding them inherits the input's `decoder_id`s,
      re-declares the Decoder Descriptors it references (as the annotator does),
      and identifies *itself* via `produced_by`/`produced_at` on the File Header
      like every other derived file. Delete the "declares a Decoder Descriptor
      for itself" paragraph. Pass-throughs and such stages then treat
      `decoder_id` identically, leaving `spans`-versus-`origin` as the only
      difference — which is exactly the discriminator.

      Note the cost, and do **not** fix it now: a filter's own configuration
      loses its `params_digest` home. That is already true of a merge, so it is
      no regression, but reproducing a filtered file is then unpinned. A
      `transform_params_digest` on the File Header is the obvious future answer —
      record it under *Possible future extensions*, do not add it to `0.10`
- [x] Add a vector for the two-hop case if it is cheap — the suite's stated gaps
      already include multi-file provenance chains, and this is the shape a
      consumer most needs to get right. A record-reordering stage would make a
      good second one, since its `spans` run non-monotonically against stored
      order and a naive implementation may assume they ascend

- [x] Full anchor and cross-reference sweep, as in Phase 5 (the script is worth
      keeping — it found three broken anchors and 65 broken relative links)
- [x] Confirm the CHANGELOG's `[0.10]` section is the complete delta from `0.9`
- [x] Cut the release: date, `v0.10` tag, drop any remaining beta language —
      "beta" is redundant now that the whole `0.x` line is provisional
- [ ] Hand the result to `python-zipline`, and record what it finds
- [ ] Expect a `0.11`. The point of staying in `0.x` is that the next round of
      findings costs a minor bump rather than a major one

### Carried to `0.11`

Not defects in `0.10`, and not blockers — additions that want a release of their
own. Recorded here so they are not rediscovered from scratch.

- [ ] **Input stream extents, so the coverage guarantee is self-verifiable.**
      Raised while asking which normal-processing paths force a consumer back to
      a parent file. The answer is: mostly none — a decoded file stands alone for
      its decoded content, and provenance is for verification and re-derivation
      rather than reading. But **validating coverage is the exception, and it is
      structural.** Nothing records how long each *input* participant stream was,
      so a decoder that silently stopped at offset 500 of a 900-byte stream
      produces a file that looks internally complete, and only the parent
      disproves it.

      The fix is an addition on Session End, where the already-proposed
      per-session integrity counts live — not the Participant Descriptor, which
      declare-on-first-use puts before the records, so a live decode does not yet
      know the extent. Written up under *Possible future extensions* in the
      specification.

      Worth doing because it changes the format's central honesty guarantee from
      one a consumer must take on trust into one it can enforce.

- [ ] **`transform_params_digest` on the File Header.** Falls out of the
      `decoder_id` fix in Phase 11: once a filter or reordering stage inherits
      the input's `decoder_id`s rather than declaring itself, its own
      configuration has no `params_digest` home, so a filtered file is not
      reproducible from what it records. Already true of a merge today, so `0.10`
      is no worse — but the gap is now named.

- [ ] **Decrypted tunnels: an offset space keyed on what a stream *is*, not on
      which stage produced it.** **Needs design work before any wording is
      drafted** — it generalises a rule the rest of the document leans on, so it
      should not be done in a hurry.

      *The case.* Stateless tunnels are already handled: `endpoint` repeats,
      outermost carrier first, and the specification names VPNs in that list. A
      sessionizer decapsulates VXLAN or GRE inline and emits **one raw file**.
      Decryption cannot work that way — IPsec, WireGuard and TLS-VPNs need a
      separate stage, so the inner traffic arrives `zpf-input`-sourced and is
      therefore *derived*, never `raw`, even though it is transport traffic in
      every meaningful sense.

      *What already works.* The chain expresses as two decode stages: decrypt
      (records whose payload is a stream of IP packets, `spans` into the tunnel
      stream), then re-sessionize (inner sessions with byte-run records, `spans`
      into the decrypted stream). Coverage applies cleanly at the second stage,
      and the inner IP/TCP **headers** are a better fit for `skipped` than the
      BOM case that motivated it.

      *What breaks.* §4.1 keys the offset space on how a file was produced: a
      transport stream is "one reassembled from a capture", hole-inclusive and
      `isn`-anchored, while a decode stage's output is a concatenation of payloads
      and explicitly *not* hole-inclusive. The inner streams have `isn`,
      `seq_start` and real gaps from lost inner packets — transport streams by
      every test — but a decode stage made them, so the rule gives them the wrong
      semantics and an inner gap has nowhere to live.

      *Shape of the fix, to be confirmed rather than assumed.* Key the rule on
      the stream: transport semantics when the participant carries `isn` and its
      records carry `seq_start`, message semantics otherwise. The existing raw and
      decoded cases then fall out as the two special cases they already are, and
      no new file kind or block is needed.

      *Open questions to settle first.* Whether a decode stage may mint sessions
      that do not correspond to its input's sessions — stage 2 turns one tunnel
      session into many, and nothing forbids it, but nothing permits it either.
      Whether keying on `isn`/`seq_start` misclassifies a transport stream that
      has neither (a hint-less inner UDP flow). And whether the two-stage split is
      the right decomposition at all, or whether decrypt-and-resessionize should
      be one stage.

**Two production costs to keep in view rather than fix.** Both are consequences
of the layering working as designed, not faults:

- A workload wanting *all* bytes — security scanning, archival — is two-file by
  construction, since a decode stage accounts for unparsed regions by reference
  and may never copy bytes forward, and a file cannot mix decoded and
  pass-through records. On captures rich in encrypted or unknown protocols that
  is most records, not a rare tail.
- Correlating a decoded record back to a capture position costs a hop per record,
  and two across a decoded-layer pass-through.
