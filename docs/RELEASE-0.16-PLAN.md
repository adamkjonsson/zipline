# Release 0.16 — implementation plan

*Written 2026-08-08 against **v0.15** and the fourteen issues opened from
[python-zipline's review of `0.15`](SPEC-0.15-REVIEW.md). This is a working
roadmap, not normative text: it says what to change, in what order, and what
"done" means.*

---

## What this release is

**A corrective release, like `0.11`, `0.12` and `0.14`.** `0.15` was the feature
release that replaced the raw/derived conflation with two axes; `0.16` fixes what
that release left inconsistent. No new block, no new option, no body-layout
change. Every fix is local, and the review's own verdict on the normative model is
that nothing in it needs challenging.

| Issue | Title | Kind |
|---|---|---|
| [#87](https://github.com/adamkjonsson/zipline/issues/87) | Undecoded against a `capture` Source: three rules disagree | spec, vectors, **blocking** |
| [#88](https://github.com/adamkjonsson/zipline/issues/88) | The decidable Discontinuity case has no layer qualifier and no predicate | spec, **blocking** |
| [#89](https://github.com/adamkjonsson/zipline/issues/89) | §Undecoded's closing paragraph contradicts two accept-tier vectors | spec, **high** |
| [#90](https://github.com/adamkjonsson/zipline/issues/90) | Nothing requires one participant's records to resolve to the same layer | spec, **high** |
| [#91](https://github.com/adamkjonsson/zipline/issues/91) | "A byte run carries no `decoder_id`" is false since reassembly became a decoder | spec, **high** |
| [#92](https://github.com/adamkjonsson/zipline/issues/92) | A `zpf`-sourced stream must be created or preserved, and nothing says so | spec |
| [#93](https://github.com/adamkjonsson/zipline/issues/93) | `isolate-self-derived` has no detection procedure, and carries two violations | spec, vectors |
| [#94](https://github.com/adamkjonsson/zipline/issues/94) | The transport-layer exemption assumes sequence numbers | spec |
| [#95](https://github.com/adamkjonsson/zipline/issues/95) | `content_type` at the transport layer is not written as a MUST | spec |
| [#96](https://github.com/adamkjonsson/zipline/issues/96) | `transform_params_digest` justified by a reason `0.15` disproves | spec |
| [#97](https://github.com/adamkjonsson/zipline/issues/97) | "Re-reads correctly unmodified" contradicts the `0.x` reject rule | docs |
| [#99](https://github.com/adamkjonsson/zipline/issues/99) | Retire "raw" from the worked examples | docs |
| [#100](https://github.com/adamkjonsson/zipline/issues/100) | Extend the #70 restatement grep to the layer and `decoder_id` rules | vectors, process |
| [#98](https://github.com/adamkjonsson/zipline/issues/98) | `skipped` does two unrelated jobs, only one is a break | spec, **deferred** |

**Expect a `Changed` section, and a substantial one.** Four issues tighten
conformance: #90, #92, #94 and #95 each make a file conformant under `0.15`
non-conformant under `0.16`, and #87 changes what an Undecoded block against a
`capture` Source *means* — the one place this release touches semantics rather
than prose. Corrective in spirit; still `Changed`, and drafted while writing, not
at release. `0.14` learned that and `0.15` learned it again.

---

## The scope decisions

### 1. #87 is resolved against the vector, not against the text

The review preferred the opposite. Its argument is that a capture-file byte offset
cannot name a segment that was never captured, so the byte-offset reading makes
the `hole` class unreachable against a capture Source and half the new capability
disappears.

**That capability was never needed.** Against a capture-sourced *transport* stream
a hole is already expressed by the hole-inclusive offset space — which is the same
reason such a stream may not carry a Discontinuity. The format does not say a
thing twice, and a second expression of the gap is exactly the contradiction the
transport bar exists to prevent. What the block genuinely adds at that position is
the bytes-exist class: *I discarded an overlapping retransmit, and it is in the
pcap* — a statement about the capture file, which capture-file byte offsets are
the honest way to make.

The alternative also costs more than the review prices it. One 28-byte struct
would acquire a third reading, keyed on block type *and* source kind, in a block
whose stated property is that it is byte-identical to a packed `spans` entry so
that one struct parses both.

**One correction to the review's account:** it reads the vector's ids as evidence
of intent — "presumably why the vector's ids are this file's own". They do not
survive its own preferred reading either. `undecoded-in-capture`'s offsets are
`4096..4396` and its stream is about 105 bytes long, so under the stream-offset
reading the block names a region that does not exist. The vector needs correcting
whichever way the rule goes; only the byte-offset ruling leaves the offsets alone.

### 2. #88 ships as a checker's minimum obligation, not as the duty

The predicate is the fix and it is right. What matters is where it sits.

The duty — *do these two units join?* — is producer knowledge and the four-row
table is its statement. The predicate is what a checker can see from one file, and
it conservatively skips cases the duty covers: the fan-out seam where the hole
lies in a stream only one of the adjacent pair cites, and any pair whose spans
overlap or descend. Written as *the* rule, implementers will read it as the
definition and under-emit at exactly those seams.

So it lands **inside** the "one case is decidable from a single file" paragraph,
with the layer test first and an explicit sentence that satisfying it is not
satisfying the duty. Same treatment §Discontinuity already gives the difference
between originating and carrying.

### 3. #98 is out, and is filed rather than fixed

`skipped` doing two unrelated jobs is real, and the vocabulary split (`skipped`
withheld / `dropped` removed) is the fix worth making. It is a design change: it
adds a canonical value, turns `filtered-decoded` from an example into a positive
test, and makes #78's title case checkable. None of that is a correction to `0.15`,
and folding it in would make this release the third in a row where corrective work
and model work landed together.

Recorded in #98 with the reasoning, scheduled with the other pre-`1.0` items. The
vocabulary is already open, so a producer wanting `dropped` today can write it.

### 4. The suite has no way to say "accept, but report", and #95 needs one

#95 rules that `content_type` on a transport-layer record is a **MUST NOT** and
**advisory** — the reader ignores the label and carries on. The three tiers are
`accept`, `isolate`, `reject`, and an advisory violation is none of them: the file
is readable, no data is discarded, and a conformant reader still SHOULD report.

`tcp_role`'s advisory treatment escapes this only because an unrecognised enum
value is *not* a violation, so `escape-unknown-enum` sits honestly in `accept`.
This one is a violation that accepts.

**Decide it in Phase 0, before the vector exists.** Either a fourth tier, or an
`advisory: true` key on an `accept` entry that `check.py` enforces as "parses
clean, reports one diagnostic". The second is smaller and does not disturb 49
existing entries; take it unless writing it turns up a reason not to. Either way
it is a manifest-schema change, which is a reason to settle it before Phase 3
rather than during.

***Settled: the key, not a tier.*** The deciding argument turned out to be
sharper than "smaller". A tier names **what a reader does**, and a reader accepts
these files completely — so `advisory` is not a fourth thing a reader does, it is
a statement about *why* the acceptance happened. `advisory: true` on an `accept`
entry declares 1 violation instead of 0; `advisory` on any other tier fails the
build, because where a reader may discard something the word says nothing. Schema
and its six branches are in `check.py`; no vector uses it until Phase 3.

---

## Dependencies

```
#87 ─┬─▶ vector correction (undecoded-in-capture)
     └─▶ #93's second violation is the same shape of question; read together

#90 ───▶ isolate-mixed-layer-participant     the rule before the vector
#92 ───▶ isolate-unbound-zpf-stream          "
#93 ───▶ needs #92 landed, or its "fix" re-files the same gap

#95 ───▶ tier decision (Phase 0) ───▶ its vector

#88, #89, #91, #94, #96, #97, #99   independent of everything, and of each other

#100 ── first; it audits #89 and #91, which are what it failed to catch in 0.15
```

**#92 before #93 is the sharp edge.** #93's vector fix is to give session 21 an
`origin`. Do that before the MUST exists and the vector stops demonstrating a
violation that the specification still does not state — the finding gets closed by
editing the evidence.

**#100 first, for the reason #70 went first in `0.14`.** It exists to catch a rule
whose copies disagree, it failed to catch two of them in `0.15`, and #89 and #91
are those two. A checklist step whose first real use is the release that extended
it is a step known to work.

---

## Phases

### Phase 0 — stamp, tooling, tier decision

1. `MAJOR, MINOR = 0, 16` in `vectors/build.py`; `check.py` to match; regenerate;
   the spec's version sites; open `## [0.16] — unreleased`.
2. Confirm `reject-unknown-minor` rolls 15 → 16 on its own.
3. **#100**, extended and re-run against `v0.15` — it should reproduce #89 and
   #91 from the tree as it stands. If it does not, the extension is wrong and
   fixing it is Phase 0 work, not a later cleanup.
4. **Settle the advisory tier question** (scope decision 4). Schema only; no
   vector yet.

Stamp first. Every later phase regenerates the tree anyway.

***Done. Two things Phase 0 found, both of which change what follows:***

***#100 cannot be a restatement grep, and the issue as filed proposed the wrong
mechanism.*** The issue asked to add the layer rule to the list of statements
whose copies are enumerated before a release. That would not have worked: the
layer rule is stated **exactly once**, so a check counting its copies reports one
site, correct, and passes clean — verified against the tree. Neither #89 nor #91
*restates* the rule; each asserts its negation in words sharing no phrase with it.
What shipped instead is `RETIRED_CLAIMS`, a table of claims the model has retired
that fails the build if one reappears. It reproduces #89 and #91 as required. It
is a **ratchet, not a detector** — it cannot find a stale claim nobody has
noticed, and the docstring says so rather than implying coverage it does not have.

***The suite is red from Phase 0 until Phase 2, deliberately.*** `check.py` now
exits 1 on two retired claims that are still in the specification, and they stay
there until Phase 2 removes them. This is the right state — the rule exists and
the text does not yet match it — but it means **"green" is not a usable signal
during Phase 1**, so Phase 1's own verification is `check.py`'s failure list
containing exactly those two entries and nothing else. `0.14` hit this with #65
and recorded that a future plan should say so up front; this is that.

### Phase 1 — the two blocking findings (#87, #88)

These are what stops `python-zipline` writing a parser branch, and they are the
release's reason to exist. Ship each with the vector work it implies:

- **#87** — the three-way disagreement, the `hole`-class-unavailable rule, the
  `proxy-decoded` sub-question, the corrected `undecoded-in-capture`, the
  `build.py` annotation that prints "in the input's namespace" unconditionally,
  and the `VECTOR-DEFECTS.md` entry.
- **#88** — the predicate, sited per scope decision 2, and confirmed against all
  49 existing vectors rather than on paper.

***Done. Two corrections to this phase as planned:***

***The proxy sub-question had two defensible answers, not one.*** #87 settled it
as *permitted and purely declarative*: against a `capture` source the block
discharges no coverage obligation and creates none, because the guarantee is
scoped within each input participant stream and a capture has none. So the
permission needs no layer key — a reassembler declaring a dropped overlap and a
decode stage reading a pcap directly are both honest, and a proxy carries none
because it read no input, not because its layer forbids it. The alternative
(transport-layer only) would have given a checker a file-visible rule at the cost
of forbidding the direct pcap→HTTP stage, which `0.15` permits.

***The predicate could not be confirmed in `check.py`, and should not be.***
Ground rule 2 forbids the checker from parsing block bodies or adjudicating
semantics — that is what would make it the second normative authority the vectors
exist not to be. Confirmed with a one-off reader instead. It fires on
**`isolate-unmarked-break` and nothing else** across all 50 files, and every
near-miss is excluded by the clause that exists for it:

| Vector | Excluded by |
|---|---|
| `sessionization-stage` | the **layer test** — both records transport |
| `tunnel/inner.zpf` | the **layer test** |
| `reordered-decoded` | **`A ≥ B`** (150 ≥ 0), spans running downward |
| `session-fan-out` | **`A ≥ B`** (80 ≥ 80) on one pair, no hole on the other |
| `filtered-decoded` | the region between is **bytes**-class, not `hole` |

The first two are the finding: without the layer clause a checker rejects two
conformant accept-tier vectors. The last is the conservatism made concrete —
`filtered-decoded` *does* owe its Discontinuity, under the producer duty, and the
predicate is correctly silent about it. That is the sentence about satisfying the
predicate not being satisfying the duty, demonstrated rather than asserted.

### Phase 2 — the restatements (#89, #91)

Two copies of rules `0.15` changed, one in §Undecoded and one in §Conceptual
model. Both were edited in `0.15` for vocabulary without the rule being rechecked,
so fix them by making the copy a **reference**, not by making it agree — `0.14`'s
#63 and #64 both shipped that way and neither has drifted since.

#91's site is three paragraphs above the two-axis statement that corrects it, so
the fix is mostly deletion.

### Phase 3 — the new MUSTs and their vectors (#90, #92, #93, #94, #95)

The `Changed` section's four entries, plus #93.

- **#90** — the layer-consistency sentence in §Conformance, and
  `isolate-mixed-layer-participant`.
- **#92** — the created-or-preserved MUST and its isolate-list entry, and
  `isolate-unbound-zpf-stream`.
- **#93** — the detection procedure, then session 21's `origin`. In that order.
- **#94** — the withholding MUST NOT, stated at both sites (§Discontinuity's
  exemption and §Conformance's transport-layer paragraph).
- **#95** — MUST NOT plus advisory, the registry entry, and its vector on
  whatever Phase 0 decided the shape is.

Two new isolate vectors, so 49 → 51. Both need #39's one-violation rule to hold of
them, which is what #93 exists to restore.

### Phase 4 — prose and docs (#96, #97, #99)

Independent of everything above, and safe to land in any order once the rules have
stopped moving. #99 is the largest diff and the least risky: a filename through
one worked example.

### Phase 5 — changelog, conformance sweep, release

Run #100 over the finished release. Draft `Changed` from the entries written in
Phase 3, not from memory.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| #87 is fixed in the field table and not in the "never the current file's" sentence | **medium — this is the release's own dominant defect** | The issue enumerates all four sites. #100 runs before and after. |
| #88's predicate is read as the duty | medium, high cost | Explicit sentence saying it is not; sited inside the decidable-case paragraph rather than replacing the table. |
| #93 closes by editing the vector while #92's gap stays open | medium | Enforced ordering: #92 lands first. If #92 slips, #93 slips with it. |
| The advisory tier question is settled during Phase 3, under vector pressure | medium | It is Phase 0, before any vector needs it. |
| `Changed` is quietly filed as `Clarified` | medium | Four issues say so in their bodies; entries drafted in Phase 3. |
| The corrected `undecoded-in-capture` still reads ambiguously | low | Its manifest summary states the offset space explicitly, which is what the old one did not. |
| #98 creeps back in as "one small vocabulary entry" | low | Scope decision 3 is written down. |

---

## Definition of done

- [ ] All thirteen in-scope issues closed, each in the commit that finishes it;
      #98 open and scheduled.
- [ ] An Undecoded block against a `capture` Source has **one** reading, stated at
      every site that bears on it, and `undecoded-in-capture` demonstrates it.
- [ ] The single-file Discontinuity check is a predicate, carries its layer test
      first, and says in the text that satisfying it is not satisfying the duty.
- [ ] No statement in the specification implies that a transport-layer stream
      carries no Undecoded blocks, or that a byte run carries no `decoder_id`.
- [ ] "The stream's layer" is well defined: a participant mixing layers is a
      stated violation with a vector.
- [ ] A `zpf`-sourced participant that is neither created nor preserved is a
      stated violation with a vector, and `isolate-self-derived` carries exactly
      one violation again.
- [ ] The transport-layer exemption states what it assumes, and the case it does
      not cover is forbidden rather than unrepresentable.
- [ ] `content_type` at the transport layer is a MUST NOT with a stated tier, and
      the suite can express an advisory violation.
- [ ] `python3 vectors/check.py` green; every vector stamps `0.16`. *51 entries.*
- [ ] #100's tool reports no rule changed in `0.16` with a copy left behind, and
      reproduces #89 and #91 when run against `v0.15`.
- [ ] `CHANGELOG.md` `[0.16]` complete, **with a `Changed` section** covering #87,
      #90, #92, #94 and #95.
- [ ] The `0.15` review is annotated: each finding marked resolved, with the two
      where this release ruled against it (#87's direction, #98's scheduling)
      saying so and why.
