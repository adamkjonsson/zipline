# Release 0.14 — implementation plan

*Written 2026-08-05 against **v0.13** and the nine issues carrying the `0.14`
milestone. This is a working roadmap, not normative text: it says what to change,
in what order, and what "done" means.*

---

## What this release is

**A corrective release, like `0.11` and `0.12`.** It fixes what
[python-zipline's review of `0.13`](SPEC-0.13-REVIEW.md) found and adds no option
and no block. The `#41` completion work — F0, F1, F2 and `#42` — moved to `0.15`
when the review landed.

| Issue | Title | Kind |
|---|---|---|
| [#63](https://github.com/adamkjonsson/zipline/issues/63) | Offset space defined three times, only one includes widths | spec, **high** |
| [#64](https://github.com/adamkjonsson/zipline/issues/64) | Pass-through Discontinuity rule stated two contradictory ways | spec, **high** |
| [#65](https://github.com/adamkjonsson/zipline/issues/65) | Discontinuity's central duty described but never required | spec |
| [#66](https://github.com/adamkjonsson/zipline/issues/66) | Session fan-out ships with no vector | vectors, **high** |
| [#67](https://github.com/adamkjonsson/zipline/issues/67) | `input_extents` optional with no SHOULD | spec |
| [#68](https://github.com/adamkjonsson/zipline/issues/68) | "fed" versus "accounted for exactly once" | spec |
| [#69](https://github.com/adamkjonsson/zipline/issues/69) | `input_extents` entry size unstated | spec |
| [#60](https://github.com/adamkjonsson/zipline/issues/60) | Two-file fixture: decoding across a discontinuity | vectors |
| [#70](https://github.com/adamkjonsson/zipline/issues/70) | Release checklist: restatement grep, capability coverage | vectors, process |

**Expect a `Changed` section**, unlike `0.13`. #65 and #67 tighten conformance: a
reader that splices across a Discontinuity was conformant under `0.13` and is not
under `0.14`, and a writer that knows an extent now SHOULD declare it. Corrective
in spirit — splicing is the exact thing the block exists to prevent — but it
changes what "conformant" means, and burying that under *Clarified* would repeat
the dishonesty this release exists to correct.

---

## The three scope decisions

### 1. #68 settles span-on-span overlap, it does not defer it

The review could not answer from the text whether the same input range appearing
in **two records' `spans`** is a violation. "Exactly once" implies yes; nothing
states it; python-zipline's checker does not flag it and would need to if it is.

**Decide it, state it, and give it a vector if it is a violation.** A
checker-visible question with two defensible readings and no vector is exactly how
#66 happened. The narrow rule #68 introduces — *cited by one output unit, the one
whose emission it completed* — already implies the answer, which is a reason to
say it outright rather than leave it inferable.

### 2. #70 is built early, and audits this release

The natural instinct is to build tooling last, once the vectors have stopped
moving. Build it **first** instead. #64, #65 and #66 each add a capability that
needs exercising, and #70 exists precisely to catch an unexercised one. A checker
whose first real use is the release that built it is a checker known to work; one
built afterwards has audited nothing and its first genuine test is `0.15`.

This is #39's lesson repeated: the one-violation rule sat in `vectors/README.md`
unenforced from the beginning, and by the time it was mechanised
`isolate-coverage-gap` had been carrying two violations for a whole release.

### 3. The multi-file fixture becomes a shape, not a special case

`chain/` is the suite's only multi-file fixture: three files, a `files` key in the
manifest, and a `check_chain()` hardcoded to its three names. #60 needs a second.

**Generalise the build side, keep the checking side specific.** `build.py` should
support a multi-file fixture as an ordinary shape — the manifest already has
`files` — while `check_chain()`'s arithmetic stays about `chain/`, because that
arithmetic is about *those* files' digests and offsets. `0.15`'s F2 tunnel
fixtures will be the third user, and the shape is easier to set now than with
three bespoke copies in place.

---

## Dependencies

```
#70 (coverage tool) ─── first; it audits everything after it

#63 (offset space) ─┬─▶ #66 (fan-out vectors)   extents arithmetic must be settled
                    │        before a vector can declare the right numbers
                    └─▶ #60 (splice fixture)

#65 (the MUST NOTs) ───▶ #60   the duty before the test of it

#64 (pass-through)  ───▶ its own vector, in the same change

#67, #68, #69       independent of everything, and of each other
```

**#63 before the vectors is the sharp edge.** It decides whether a decoded
stream's offset space includes declared widths — which decides what every
`input_extents` value in a new vector should be. Build #66's demux vector first
and its numbers are computed under a rule that is still moving.

**#65 before #60** for the same reason in a different form: #60 tests a duty that
does not exist yet. Writing the fixture first means guessing what it must
demonstrate.

---

## Phases

### Phase 0 — stamp and tooling — **done**

1. `MAJOR, MINOR = 0, 14` in `vectors/build.py`; `check.py` to match; regenerate;
   the spec's version sites; open `## [0.14] — unreleased`.
2. **Confirm `reject-unknown-minor` rolls 14 → 15 on its own.** It derives
   `MINOR + 1`, so it should — but `0.13` shipped precisely because that vector
   silently became valid, and the point of deriving it is only proved by checking.
3. **#70's coverage tool**, so everything after it is audited.

Stamp first, as `0.13` proved: every later phase regenerates the tree anyway, and
bumping at the end lands one large mechanical diff on top of the diffs that need
reading.

### Phase 1 — the contradictions (#63, #64) — **done**

The two `high` spec findings, and the two that produce wrong output rather than
ambiguity. #64 ships with its vector — a decoded-layer pass-through carrying an
inherited Discontinuity with the ids visibly renumbered — because that vector is
what would have caught it.

**#63's fix is a restructure, not a patch.** Make the *Layers* definition the
single normative statement, including declared widths and the narrowed
hole-inclusive clause, and reduce the `input_extents` gloss to a reference. Three
copies is what caused the finding; fixing two of them leaves the third to rot.

### Phase 2 — the precision fixes (#65, #67, #68, #69) — **done**

Prose. #65 and #67 are the two that tighten conformance, so draft their changelog
entries as **Changed** while writing them, not at release.

#68 also decides span-on-span overlap and, if it is a violation, adds an
`isolate` vector for it.

### Phase 3 — vectors (#66, #60) — **done**

After #63 has settled the arithmetic and #65 the duty.

- **#66** — two vectors. The `accept` demux vector first: one input participant
  stream into two output sessions, each declaring that stream's **whole** extent,
  their covering spans partitioning it, so a per-session checker fails and a
  per-stream one passes. Then the `isolate` vector where two sessions declare
  different extents for one stream.
- **#60** — the two-file splice fixture, on the generalised multi-file shape.

### Phase 4 — changelog, conformance sweep, release — **done**

Run #70's tool over the finished release. Then the sweep, with the restatement
grep as a required step rather than a good intention.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| #63 is fixed in two of its three sites | **this already happened once** | The fix is explicitly a restructure to one normative statement. Grep every restatement before closing, per #70. |
| #66's vectors are built against unsettled extent arithmetic | medium, high cost | Enforced ordering: #63 lands first. If #63 slips, #66 slips with it. |
| The `Changed` section is quietly filed as `Clarified` | medium | #65 and #67 both say so in their issue bodies, and their entries are drafted in Phase 2 rather than at release. |
| #70's tool is built but never run on this release | low | It is Phase 0, and Phase 4 runs it as a gate. |
| The multi-file generalisation grows | low | Build side only. `check_chain()` stays specific. |

---

## Definition of done

- [x] All nine issues closed, each in the commit that finishes it.
- [x] A decoded stream's offset space is defined **once**, includes declared
      widths, and the other two sites reference it rather than re-glossing it.
      *The grep found two further partial copies in §Discontinuity that the
      review had not listed — three was an undercount.*
- [x] §Discontinuity and §Conformance agree on pass-through re-emission, and a
      vector demonstrates the renumbering. *Fixed by collapsing to one statement
      rather than making the copies agree.*
- [x] A consumer's duty at a Discontinuity is a **MUST NOT**, and the chain-carrying
      half of it is too.
- [x] Span-on-span overlap is settled explicitly, either way. *Permitted; the
      guarantee became at-least-once.*
- [x] Fan-out is exercised: a demux vector on which a per-session coverage checker
      fails and a per-stream one passes. *Both checkers were implemented and run
      against the shipped file rather than reasoned about.*
- [x] `python3 vectors/check.py` green; every vector stamps `0.14`. *39 entries.*
- [x] #70's tool reports no capability added or clarified in `0.14` without a
      vector naming it. *37 options, 12 blocks, 9 rules, all exercised.*
- [x] `CHANGELOG.md` `[0.14]` complete, **with a `Changed` section** covering #65
      and #67.
- [x] Every vector in `manifest.json` appears in `vectors/README.md` — the check
      `0.13`'s sweep had to invent after finding six missing.

## What execution changed

Recorded because a plan only ever read forwards teaches nothing. Six things this
document or the review got wrong, and one the plan did not anticipate:

- **#64's fix.** The review asked to correct the wrong copy so the two agreed.
  Shipped by collapsing to one normative statement in §Discontinuity, because two
  statements of one rule is the condition that produced the finding. Same
  treatment as #63, in the same phase.
- **#60's shape**, and what building it exposed. It shipped as a self-contained
  pair rather than riding on `chain/` — and writing it revealed that `check.py`
  skipped *any* entry with a `files` key, so **`chain/`'s own three files had
  never been walked** for framing or projection either. Fixed first, in its own
  commit, before the fixture that needed it.
- **#66's demux vector overlaps rather than partitions.** The review proposed a
  clean partition; #68 landed first and made coverage *at least once*, so a
  partitioning vector would have left the loosened rule exercised by nothing.
  Complete overlap would have been worse than either — each session would cover
  its declared extent alone and a per-session checker would pass.
- **#68's open sub-question answered as *permitted*.** The review could not settle
  it from the text. The deciding case came from `0.13`'s own correspondence
  clarification: a decryptor's nonce and tag *fed* the plaintext, so where one
  ciphertext record yields two output units both genuinely span the framing.
- **#70's first run found eight coverage gaps, not the five estimated.** The
  estimate had counted helper *definitions* in `build.py` as uses. The notable
  one: `params_digest`, the option the whole reproducibility contract is stated
  against, had never appeared in a vector.
- **The restatement grep can miss a line-wrapped copy.** The `0.14` sweep nearly
  missed a third statement of the coverage guarantee because the phrase spanned a
  line break. The check is worth keeping and worth distrusting; grep for the rule,
  then read the section.

Not anticipated by the plan: **#65's `RULES` entry deliberately left the suite red
for two phases**, from Phase 2 until #60 landed in Phase 3. That was the right
state — the rule existed in the specification and its vector did not — but it
means "green" was not a usable signal mid-release, and a future plan should say so
up front rather than discovering it.
