# Response: the 1.1-beta implementation review

Assessment of [SPEC-1.1-REVIEW.md](../SPEC-1.1-REVIEW.md), a review of the
1.1-beta line from `python-zipline`, dated 2026-07-28, and the decisions that
follow from it.

Companion to [implementation-feedback-analysis.md](implementation-feedback-analysis.md),
which covers the earlier round (issues #8–#16). That round's roll-out plan is
complete through Phase 6; its two remaining Phase 5 release steps are
**superseded** by the renumbering decided here.

---

## 1. Verdict at a glance

| # | Review point | Valid? | Disposition | Effort |
|---|--------------|--------|-------------|--------|
| 1 | `[strict-reader]` carve-out has no wire signal | **Yes — and understated** | **Dissolved** by the renumbering | — |
| 2 | Filter example contradicts the offset-space rule | **Yes** | Fix: a decoded-layer filter is a *decode stage* marking dropped ranges `skipped` | S |
| 3 | `sequenced_basis` is unactionable | **Yes** on `transport`; substantially yes on MUST | Fix: MUST, and cut `transport` | S |
| 4 | Unrecognised-`reason` rule buys a MUST with unbounded I/O | **Half** — the second half is the serious one | Fix: `reason_class`, conditional walk, distinct reporting | M |
| 5 | Lowest-minor rule fights the streaming contract | **Yes** | **Dissolved**: the rule is deleted | — |
| — | Machine-checkable test vectors | **Yes, strongly** | Decision pending (Phase 7) | M–L |

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
`1.0`.**

Safe here because no `1/0`-stamped files exist outside development — confirmed
2026-07-28. That condition is load-bearing: relabelling the *document* is not
enough on its own, because a released file carries its version in its header. Had
real `1/0` files existed, two incompatible formats would claim identical version
bytes, which is strictly worse than calling this 1.1 — a reader would have no
discriminator at all. In that world the answer would have been **2.0**.

**This is honest, not a dodge.** Semantic versioning reserves `0.y.z` for initial
development, where anything may change at any time. Relabelling makes the
incompatibility *contractually expected* rather than merely excused. The actual
error was calling this work a minor bump; the renumbering corrects that error
rather than hiding it.

### What it dissolves

**Review point 1, entirely.** The problem stops being "a minor bump that breaks
readers" and becomes a **major** bump — a case the format already handles
correctly, via a rule it has always had: *a reader MUST reject a `version_major`
it does not implement*. No feature-flag bit, no `[strict-reader]` class, no new
reader-guidance sentence. The existing mechanism does the work.

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

- **`version_minor` is the minor the writer implements.** No bookkeeping, no
  table, satisfiable at header time by a streaming writer.
- **Minors are strictly additive.** Old readers keep working, guaranteed by the
  skip rules — unknown block skipped by frame `length`, unknown option by `len`,
  reserved bits ignored, and the four JSONL escapes. A reader **MUST NOT** gate
  parsing on `version_minor`.
- **Anything not strictly additive is a major bump**, where a reader MUST reject
  a `version_major` it does not implement.

That is the whole policy. There is deliberately **no** MUST floor tying the
stamp to the features used: under strict additivity there is nothing for such a
floor to signal. It would only have a job in a world where a minor could break
readers, and the right answer is to forbid that world rather than instrument it.

**Consequence:** `version_minor` is advisory. A reader needs it for nothing,
because the skip rules already guarantee the outcome. It remains useful to humans
and diagnostics.

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

**Decision: MUST**, justified two-thirds on producer discipline (it forces the
producer to articulate a basis, which catches the case where there is none) and
one-third on the `clock` cross-check. The alternative the review offers — drop
the option and state plainly that `SEQUENCED` is an unverifiable producer
assertion — is clean and now costs nothing, so it stays on the table as the
simplicity option.

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

**Scope proposal:** a dozen `.zpf` / `.jsonl` pairs covering the annotator shape,
the four escapes, an unrecognised `reason`, an unknown block type, and a sequenced
hint-less session. Each pair is a binary file plus its exact projection, so a
converter can be tested in both directions.

**Open question for Phase 7:** in scope for this release, or immediately after?
Arguments both ways — they would catch defects in the very text being written
now, but they are the largest single item remaining and this release is already
overdue for a cut.

---

## 7. Roll-out plan

Continues the numbering from
[implementation-feedback-analysis.md](implementation-feedback-analysis.md) §7,
whose Phases 0–6 are complete.

### Phase 7 — Decisions

- [ ] **Versioning** — confirm: July 2026 release becomes `0.9`; this work
      releases as `1.0` *(recommended, and assumed by the rest of this plan)*
- [ ] **`sequenced_basis`** — MUST *(recommended)* vs drop the option and state
      that `SEQUENCED` is an unverifiable producer assertion
- [ ] **Test vectors** — in scope for 1.0, or a follow-up release
- [ ] **`SPEC-1.1-REVIEW.md`** — commit it (and probably move it to `docs/`) so
      this document's references resolve for anyone reading the repo

### Phase 8 — Renumbering

Do this first and in one commit: it changes the frame every other item is
described in.

- [ ] Spec title and status banner — drop the 1.1-beta language; this is `1.0`
- [ ] *File Header* — `version_minor` row back to `0`; rewrite the minor/major
      definition per §3; **delete** the lowest-minor paragraph added in Phase 5
- [ ] Keep and simplify the "describes the file, not the rendering" sentence
- [ ] Examples — the annotator example's `zipline-payload/1.1` reverts to
      `zipline-payload/1`, since it is no longer a later-minor construct
- [ ] Byte-level worked example — confirm `version_minor = 0` still stands (it
      should; it was 1.0 content all along)
- [ ] CHANGELOG — `[Unreleased] — 1.1-beta` becomes `[1.0]` with a date; the
      existing `[1.0] — 2026-07-09` becomes `[0.9]`; rewrite *Conventions*
      (minor/major definitions, delete `[strict-reader]`), delete the
      binary-container compatibility preamble, and state openly that 1.0 was
      declared final too early
- [ ] README status section
- [ ] Git tags — add `v0.9` at `bc4bcfb`, delete the `v1.0` tag locally and on
      the remote, and re-tag `v1.0` at the release commit. **Confirm before
      deleting the remote tag**
- [ ] Add a note to [implementation-feedback-analysis.md](implementation-feedback-analysis.md)
      recording that its "v1.0 → v1.1" framing was renumbered to "0.9 → 1.0", and
      that its Phase 5 release steps are superseded

### Phase 9 — The surviving review points

- [ ] **§4 first** — `time_units` hard removal, now that nothing requires the
      alias; delete the *Deprecated keys* note added in Phase 1 and the
      CHANGELOG's *Deprecated* section
- [ ] **Point 2** — state that a decoded-layer filter is a decode stage citing its
      input with dropped ranges marked `skipped`, including the note that it
      declares a Decoder Descriptor naming itself; fix the CHANGELOG motivation
- [ ] **Point 3** — `sequenced_basis` becomes MUST for a hint-less `SEQUENCED`
      session; cut `transport` from the vocabulary; state the `clock` /
      `SINGLE_CLOCK` cross-check as the one mechanical check a consumer can run
- [ ] **Point 4a** — register `reason_class` (`hole` / `bytes`), required whenever
      `reason` is outside the canonical four
- [ ] **Point 4b** — make the provenance walk explicitly conditional
- [ ] **Point 4c** — require "no bytes exist" and "chain broken" to be reported
      distinctly
- [ ] **Point 4d** — reword the class-versus-word sentence so it stops
      contradicting `skipped`'s justification
- [ ] Re-check that `reason_class` does not disturb the two-class table or the
      coverage-guarantee narrative

### Phase 10 — Vectors and release

- [ ] Test vectors, if Phase 7 puts them in scope
- [ ] Full anchor and cross-reference sweep, as in Phase 5 (the script is worth
      keeping — it found three broken anchors and 65 broken relative links)
- [ ] Confirm the CHANGELOG's `[1.0]` section is the complete delta from 0.9
- [ ] Cut the release: date, tag, drop any remaining beta language
- [ ] Hand the result to `python-zipline`, and record what it finds
