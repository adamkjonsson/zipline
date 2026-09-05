# Rationale extraction — implementation plan

*Written 2026-09-05 against **v0.18**. This is a working roadmap, not normative
text. It moves the argument out of the specification into a companion document
and changes nothing the format means.*

*It is **not a new version**. The specification stays `0.18`, no vector
re-stamps, and no implementation does anything. §The version and the tag says why,
and what to do about the tag that already exists.*

---

## What this work is

**The largest reduction available, and the only one that costs no capability.**
[SIMPLIFICATION-ANALYSIS.md](SIMPLIFICATION-ANALYSIS.md) measures about a third of
the document as rationale and release history rather than specification, and puts
the extracted document near 2 000 lines from 3 526. `python-zipline` prices its
impact on the only complete implementation at **zero**.

**It goes first, before any of the five reduction packages, and the order only
works one way.** Three reasons, in the order they were established:

1. **It removes most of what the packages were going to remove.** Splitting each
   package's deletion region into paragraphs that carry a normative keyword and
   paragraphs that do not:

   | Region a package would delete | Non-normative share |
   |---|---:|
   | The decrypted tunnel example (E) | 100% |
   | Conceptual model, the two axes (E) | 81% |
   | Undecoded (D) | 76% |
   | Discontinuity duty and predicate (D) | 68% |
   | The origin floor (C) | 69% |
   | Sequenced files (B) | 69% |
   | **Conformance, which no package deletes** | **15%** |

   Conformance is the control and confirms the measure discriminates. After
   extraction each package must be argued on the capability it costs rather than
   on the lines it removes, which is the basis the decision should have rested on
   from the start. **These percentages are a reason to extract first. They are not
   an extraction budget** — see §The test.

2. **Reduction first destroys reasoning that extraction would preserve.**
   [RELEASE-0.19-PLAN.md](RELEASE-0.19-PLAN.md) records under Package D that
   dropping the seam predicate while keeping the duty is right, and that deleting
   its *reasoning* is what extraction is for. That is only true if the companion
   already exists. Reduce first and the argument for every deleted rule is gone
   rather than relocated.

3. **It is zero-risk for readers of the format and distinctly non-zero for this
   repository.** Four mechanisms in `check.py` parse the specification as prose,
   and 214 intra-document links resolve against its headings. That is a good
   reason for extraction to be a piece of work that does nothing else, and it is
   most of what this plan is about.

**One non-normative addition rides along.** `0.18` as tagged has no Goals entry
for the findability property; main has carried one since #129. It states a
property the mechanisms already had and adds no rule, so it belongs with a
re-issue rather than with a version bump — but it does change the document, so it
gets a changelog line under `[0.18]` like everything else here.

---

## The version and the tag

**The specification stays `0.18`.** The changelog's Conventions say there is no
patch component "because a version that is not on the wire cannot be communicated
to a reader", and `0.x` files are disposable: a reader **rejects** a
`version_minor` it does not implement. Extraction changes no meaning, so bumping
the number would force every implementation to ship a release solely to accept a
version that says nothing. `0.19` stays reserved for the reduction.

### Do not delete the `v0.18` tag

The tag is pushed and points at `ea3ad7d`. Deleting and re-creating it is the
obvious move and it is the wrong one, for a reason specific to this repository:
**the guard discipline validates against tags, and assumes they do not move.**
Every release since `0.16` has closed by running each new `RETIRED_CLAIMS` entry
against the tag of the release before the one that retired it, and
`RELEASE-0.19-PLAN.md` requires the same against `v0.18`. If `v0.18` names two
different trees, an entry that "reproduces against `v0.18`" no longer says which
one, and the extraction is precisely the change that could move a retired
sentence into a file the scan may not read.

**Add a second tag instead.** `v0.18-r2` on the extraction commit, `v0.18` left
where it is. Both trees stay addressable, the changelog's `v0.17...v0.18` compare
link stays valid, and `0.19`'s guards get an unambiguous baseline — which is
`v0.18-r2`, since that is the tree they will be written against.

The cost is one tag name. The cost of moving `v0.18` is a baseline that cannot be
reconstructed, in the one repository whose release process is built on
reconstructing baselines.

*If the tag is moved anyway, the mitigation is to say so in `RELEASE-0.19-PLAN.md`
where it names `v0.18`, and to re-validate `0.18`'s six `RETIRED_CLAIMS` entries
against `v0.17` before the extraction lands rather than after.*

---

## The test: what moves and what stays

The measurement above splits the document in two. The extraction splits it in
**three**, and conflating the second and third categories is how this work goes
wrong.

| | Category | Test | Where it goes |
|---|---|---|---|
| 1 | **Normative** | A conformant file or a correct reader depends on it: rules, arithmetic, field layouts, enum values, registry tables | Stays |
| 2 | **Instructional** | An implementer follows it to build something: worked examples, the JSONL walkthroughs, declaration order, "how to read this" | **Stays** |
| 3 | **Rationale** | It explains *why* a rule exists, what an earlier version got wrong, what was considered and rejected, or what a defect taught | Moves |

**The measured percentages count 2 and 3 together**, because a worked example
carries no `MUST`. The decrypted tunnel example scores 100% non-normative and is
the only account of a four-hop chain in the document; it **stays**. Anyone reading
the table in §What this work is as a target will extract the examples and leave an
unreadable specification, which is the opposite of what
[CLAUDE.md](../CLAUDE.md) asks for.

**The sharp cases, decided here rather than in the middle of a section:**

- **A rule's justification clause moves; the rule's *scope* stays.** "Decoded-layer
  only, because a transport stream expresses the same break in its offsets" — the
  restriction is normative, the *because* is not. Split the sentence rather than
  moving it whole.
- **"Design decisions not taken" moves entire.** It is rationale by definition, and
  it is the pilot in Phase 1.
- **Defect archaeology moves.** "`0.17` added the second label to a sentence that
  announced there were two of these, and the number went stale" is a note to
  maintainers, not to implementers.
- **A boxed note that prevents a misreading stays.** If deleting it would let a
  competent implementer build the wrong thing, it is category 1 or 2 whatever it
  sounds like.
- **When in doubt it stays.** An over-full specification is the state we are in
  and it is survivable; a specification missing a rule is not. The companion can
  take more later; a rule discovered missing after `0.19` deletes its neighbours
  cannot be recovered as easily.

---

## The guard

Two checks, both new, and neither exists today. In this repository a guard is not
believed until it has been run against a tree where it must fail — `0.17`'s #104
and `0.18`'s #111 were both proposed in forms that could not work, and both were
measured before being built. The same discipline applies here, and the failing
tree is easy to construct: extract a normative sentence on purpose and confirm the
check reports it.

**1. Normative-sentence invariance.** The strongest thing this work can promise is
that no rule moved, and it is mechanizable. Collect every sentence carrying a
normative keyword from the specification before and after; the multiset must be
identical. `v0.18` baseline:

| Keyword | Count |
|---|---:|
| `MUST` (including `MUST NOT`) | 143 |
| `MUST NOT` | 53 |
| `SHOULD` | 27 |
| `MAY` | 54 |

A sentence that appears in the companion and not the specification is the defect
this check exists to catch. A sentence whose *wording* changed because a
cross-reference moved is the expected exception, and each one is reviewed by hand
rather than allowlisted by pattern.

**2. Link integrity.** The specification carries **214** intra-document anchor
links across 37 distinct targets, and all 214 resolve today. Extraction breaks
them in both directions: a specification link into moved text, and a companion
link back. Hand-checking 214 links is not a plan. The check resolves every
`](#anchor)` in both documents against the headings of both, and fails on any
that does not resolve.

Both checks live in `check.py` beside the four mechanisms below, and both run on
every build afterwards, not just during this work.

---

## Mechanics: what parses the specification

`check.py` reads `docs/zipline-payload-format.md` in four places, and each is a
way this work can break the build in a manner no vector will explain:

| Mechanism | What it parses | Risk |
|---|---|---|
| `spec_tables()` | the option and block registry tables | Registry moves or its heading changes → capability coverage cannot parse, hard fail |
| `spec_body_fields()` | body-field names from the binary sections | A field's defining line moves → JSONL key check fails |
| `spec_aliases()` | the JSONL ↔ binary mapping | Same |
| `spec_units()` | paragraph split, for `ENUMERATIONS` | A declared locator moves → site reported as moved |

All four read the **specification**, so the rule that keeps them working is:
**every table, registry row, enum value and field definition is category 1 and
stays.** The binary reference sections are the least rationale-heavy part of the
document and should barely move at all.

Of the six `ENUMERATIONS` locators, five sit in normative paragraphs and stay put.
The sixth, `provenance is the participants' `origin``, is in the *Annotating a
decoded file* worked example — category 2, so it also stays, but it is the one to
re-check after Phase 2.

### The `SCANNED` decision, and it is not obvious

`RETIRED_CLAIMS` scans a fixed set of files so a retired claim cannot quietly
return. Extraction creates a file the scan does not read, and moves text into it.

**Add the companion to `SCANNED`**, because a retired claim reasserted in the
rationale document is still a stale claim in the tree, and an implementer reading
the companion for context will believe it. *(Taken in Phase 0, at zero allowlist
cost — see the Phase 0 notes.)*

**But the companion legitimately discusses history**, which is what the whole
document is for. `check.py` already carries this tension once: `mixed-derivation`'s
summary quotes a retired claim deliberately, as history, and the entry records
that no suite spelling is possible because "a spelling loose enough to catch a
stale copy would catch that too". In the companion that case stops being the
exception and becomes the norm.

So the shape to price in Phase 0 is a **`(claim, file)` allowlist**, exactly as
#111 proposed for the suite, and the cap is the same as `0.18`'s scope decision 5:
if the allowlist grows longer than the check is worth, the companion is **not**
scanned and the changelog says so. A check whose output is mostly allowlist
teaches nothing. Decide it before the first paragraph moves, because retrofitting
it means re-reading everything already moved.

---

## Phases

### Phase 0 — decide, baseline, and build the guards

1. **The tag decision.** `v0.18-r2` as recommended, or the alternative with its
   mitigation written down.
2. **The `SCANNED` decision**, priced per above, with its exit named.
3. **Build both guards and prove they fail.** Normative-sentence invariance and
   link integrity, each run against a tree with a deliberate defect planted. Record
   the baseline: 143 / 53 / 27 / 54 and 214 links.
4. Create `docs/zipline-payload-format-rationale.md` with its own heading
   structure mirroring the specification's, so a moved paragraph has an obvious
   home and a stable anchor to be linked from.
5. Open `[0.18]` in the changelog for a **second dated entry**, non-normative, and
   put the Goals addition from #129 in it.

**Nothing moves in this phase**, and the build stays green throughout.

***Done. Both decisions went the way the plan recommended, and the measurement
that decided `SCANNED` came out cleaner than expected.***

***The `SCANNED` question cost nothing, and the number is worth recording because
it will not stay true.*** The worry was that the companion, being the home for
history, would need an allowlist entry per retired claim it recounts. Measured
against the tree: of **480** paragraphs, **11** recount a superseded rule, and
**none** matches any of the six retired spellings. So the companion joins
`SCANNED` with an **empty** allowlist, and `RATIONALE_QUOTES` ships empty with the
reason attached. The number is a fact about text that has not been written yet —
every paragraph moved in Phase 2 is a new chance to reassert a retired claim in
the companion, which is exactly what the scan is now there to catch.

***Both guards were run against trees where they must fail, and all four planted
defects reported.*** Deleting one `MUST NOT` from the specification moved two
counters, not one, which is the pair of keys earning its keep. A `MUST` written
into the companion was reported by line. A paragraph carrying its same-file
`](#coverage-honesty-undecoded-blocks)` link into the companion was reported as
unresolved — the silent failure, since a dead anchor scrolls nowhere and says
nothing. And a retired claim reasserted in the companion was reported, which is
the `SCANNED` decision working rather than merely being taken. The unmodified tree
reports nothing from either guard, which is the asymmetry that proves a check is
testing something.

***One correction to the plan's own numbers.*** It says 214 links across 37
targets, and the checker reports **37 distinct targets** — the 214 is the count of
link *occurrences*, and the guard deduplicates by target, so a broken heading is
reported once rather than six times. Both numbers are right and the plan conflated
them.

***`_slug` was written the wrong way first, on purpose to check, and it matters.***
Collapsing runs of whitespace before hyphenating mis-resolves three of the
specification's own links: `&` is dropped, leaving a gap that GitHub renders as a
**double** hyphen. A link checker that silently mis-resolves is worse than none,
so the one-for-one substitution is in the code with the reason beside it.

***The changelog entry is open and will accumulate.*** `[0.18] — re-issued, from
2026-09-05`, above the original entry rather than replacing it, carrying the Goals
addition, the companion, both guards and the `SCANNED` measurement. Later phases
add to it; the original `[0.18] — 2026-09-02` entry is not touched.

### Phase 1 — the pilot: sections that move whole

*Design decisions not taken* (135 lines) and any other section that is rationale
in its entirety. Zero judgment required, so it tests the mechanism rather than the
test: anchors, the companion's structure, both guards, and the `SCANNED` decision
under real content.

**Stop here and read the result before Phase 2.** If the companion is already
hard to navigate at 135 lines, its structure is wrong and the cost of fixing it
never gets lower.

***Done, and the pilot earned its place: it found the flaw in the guard rather
than in the text.***

***Three sections moved, not one, because they are the document's whole tail.***
*Prior art this borrows from*, *Open questions* and *Design decisions not taken*
run contiguously to the end of the file, so the move is one cut: **164 lines**,
specification 3 526 → 3 367, companion 78 → 242. Fifteen anchor links inside the
moved text became cross-file links; two links in the specification body that
pointed *into* the moved sections now point at the companion. The specification
ends with a pointer to the companion, because a reader who wants to know why a
rule exists needs to be told where that went.

***The count invariant was wrong, and Phase 1 is where it had to break.***
*Design decisions not taken* carries one `MUST NOT`, so moving it whole dropped
the specification to 142/52 and the guard failed — correctly, and with no way to
proceed that was not either a lie or a knob. The sentence turned out to be a
**restatement**: "a reader MUST NOT gate parsing on `version_minor`", argued
inside a rejected-option entry, whose home is the File Header section. So the
finding is the good kind — **extraction surfaces rules stated twice**, which is
the failure mode #120 is about, and it stays invisible until the text around the
duplicate moves.

The fix keeps the guard honest rather than relaxing it. `NORMATIVE_REMOVALS`
names each deliberately removed statement, the keywords it took and why; the
expected counts are **derived** from that table rather than typed. So a count
cannot be lowered without naming the sentence that went, and a named sentence
still present in the specification fails the check — verified by trying it: a
fabricated entry naming a live rule is reported twice over, once as a bad entry
and once as a count that no longer adds up. Every entry has one shape, and an
entry of any other shape is a normative change wearing extraction's clothes.

***An automated reflow corrupted the list structure and was thrown away.*** The
link substitution stretched twelve lines past the house wrap, and a paragraph-
rewrapping pass merged consecutive list items into single paragraphs — `- -
**pcapng**` and the rest. Reverted and replaced with a **split-only** fixer that
breaks a long line and never joins two, so list structure cannot collapse
whatever the input. The general rule, and it is the second-order lesson of this
phase: *a text tool that can merge lines can destroy structure; one that can only
split cannot.*

***The read-back says the structure holds.*** The companion is seven empty
placeholder sections followed by three full ones, which looks front-loaded with
nothing — but the emptiness is the point the plan argued for, and the filled
sections sit last because the specification's did. Nothing needs restructuring
before Phase 2.

### Phase 2 — the mixed sections, one per commit

In descending order of rationale share, and **one section per commit** so a
mis-extraction is revertible without unpicking the rest. §Undecoded, §Discontinuity,
§Referencing the source by stream offset, §Sequenced files, §Conceptual model,
§Layers.

Each commit: move, then run both guards, then read the section back as an
implementer who has never seen it. The third step is the one that catches a rule
whose scope left with its justification.

***In progress. Two sections done, and the first number out of them changes what
this work is worth.***

| Section | Before | After | Moved | Crude estimate said |
|---|---:|---:|---:|---:|
| §Undecoded | 195 | 173 | **11%** | 76% |
| §Discontinuity | 259 | 221 | **15%** | 68% |

***The crude measure over-estimated by a factor of five, and the reason is the
category the plan already named.*** "Paragraph carries no normative keyword" lumps
category 2 with category 3, and §Undecoded is the proof: the class table, the
recoverability semantics, *Correspondence is not proximity*, *Recovering the
bytes* and the two walk-failure modes all score as non-normative and every one of
them is **instructional**. An implementer needs them. What actually moved was the
history of the `0.17` split, why `gap` is the canonical hole word, why `skipped`
had to exist, and the reasoning behind the capture-source class rule — real
rationale, and about a ninth of the section.

§Discontinuity moved more only because it holds one unusually dense block: *Each
clause is load-bearing*, twelve lines explaining a predicate that is stated
completely without them. That paragraph is now a pointer, and it is the shape to
look for in the sections still to come.

***So the extraction lands nowhere near 2 000 lines.*** At this rate the
specification finishes near **2 950**, not the analysis's estimate. That estimate
was computed from the same crude split this phase has now measured against real
judgment, and it is wrong in the direction that matters.

***Which reverses part of the argument for doing this first.*** The case made in
§What this work is — that extraction removes about seventy percent of what each
reduction package would remove, so the packages must then be argued on capability
alone — **does not hold**. Extraction removes the rationale; the packages remove
the rationale *and the instructional text with it*, because deleting a rule
deletes its examples, its definitions and its consequences too. On these two
sections extraction takes 11-15% of what Package D would take.

The other two reasons to go first still stand, and they were always the stronger
pair: reduction-first destroys reasoning that extraction preserves, and this work
is the one that stresses four spec-parsing mechanisms and 214 links while nothing
else is changing. **`RELEASE-0.19-PLAN.md` needs its line-count column re-measured
when this finishes, and the claim that extraction dissolves the packages' case
struck.** That is on this plan's definition of done and now has a specific reason
rather than a general one.

***One deviation, recorded rather than tidied away.*** §Undecoded and
§Discontinuity landed in a single commit instead of one each. Their edits are in
disjoint line ranges and both were read back, but the plan says one section per
commit so that a mis-extraction reverts alone, and that property is weaker for
these two than for the sections that follow.

### Phase 3 — cross-references and the seams

The 214 links, the companion's links back, and the sentences left with a dangling
"as described above" where the above is now elsewhere. This is where the link
guard earns its place.

### Phase 4 — changelog, tag, and hand-off

The `[0.18]` second entry, listing what moved rather than what changed, since
nothing changed. Tag per Phase 0. Tell `python-zipline` that `0.18` was re-issued,
that the format is unchanged, and that their port target is unaffected.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A rule's scope leaves with its justification | **high — it is this work's characteristic failure** | Normative-sentence invariance, plus the read-back step in every Phase 2 commit |
| The measured percentages are used as a budget and the worked examples go | **high, and the document says to** | §The test's three categories; the tunnel example is the named case |
| A registry table or field definition moves and `check.py` cannot parse the specification | medium, loud | Category 1 covers all four mechanisms; the failure is a hard fail, not a silent one |
| The companion becomes a second specification nobody reads | medium | It is for maintainers and reviewers; the specification must stand alone without it, which is what the read-back step tests |
| `SCANNED` grows an allowlist longer than the check is worth | medium | Priced in Phase 0 with a named exit, as `0.18` priced its completeness check |
| `v0.18` is moved and a later guard cannot be reproduced | medium, permanent | §Do not delete the `v0.18` tag |
| The work runs into `0.19` scope, deleting rather than moving | low, high cost | Nothing is deleted here. A paragraph that seems to deserve deletion is a `0.19` issue, filed and left in place |

---

## Definition of done

- [ ] The specification is near 2 000 lines and the format is unchanged.
- [ ] **Normative-sentence invariance passes**: 143 `MUST`, 53 `MUST NOT`, 27
      `SHOULD`, 54 `MAY`, every sentence still in the specification, every wording
      change reviewed by hand.
- [ ] **Link integrity passes**: every anchor link in both documents resolves.
- [ ] Both guards were run against a tree where they must fail, and did.
- [ ] `python3 vectors/check.py` green, and **no vector changed** — not one byte,
      not one stamp. If a vector needed editing, something normative moved.
- [ ] The four spec-parsing mechanisms still parse; `ENUMERATIONS` reports six
      complete sites.
- [ ] The `SCANNED` decision is recorded with its measurement, either way.
- [ ] `CHANGELOG.md` carries a second dated `[0.18]` entry, non-normative, listing
      what moved and the Goals addition.
- [ ] `v0.18` still points at `ea3ad7d`; the extraction is `v0.18-r2`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] `RELEASE-0.19-PLAN.md` updated: scope decision 4 becomes "extraction is
      done", and the choice table's line-count column is re-measured against the
      extracted text, since that column no longer means what it did.
