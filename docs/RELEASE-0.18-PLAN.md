# Release 0.18 — implementation plan

*Written 2026-09-02 against **v0.17** and the twelve issues `python-zipline` and
`zpfwire` opened reviewing it, plus [#111](https://github.com/adamkjonsson/zipline/issues/111),
carried from `0.17`'s own Phase 5. This is a working roadmap, not normative text:
it says what to change, in what order, and what "done" means.*

*The release is **`0.18`**, not `0.18.0`: versions here are `major.minor` with no
patch component, because a version that is not on the wire cannot be communicated
to a reader (see the changelog's Conventions).*

---

## What this release is

**A corrective release, like `0.11`, `0.12`, `0.14` and `0.16`.** `0.17` was the
feature release that decided what a decoded record may say about itself; `0.18`
fixes what that release left inconsistent. No new block, no new option, no
body-layout change.

Every one of the twelve findings traces to `0.17`, and they divide sharply:

- **Four are the edges of the two MUSTs `0.17` added** — the origin floor's tier,
  its placement clause, its vacuous half, and the half of the handshake MUST that
  got no reader rule.
- **Four are one failure repeated**: `0.17` changed two rules and left other
  statements of them standing. The transport-layer bar gained `role` in §Typing
  and was not updated in the two §Conformance sites or the pass-through
  carry-forward; `skipped` split into `skipped`/`dropped` in §Undecoded and was
  not updated in §Referencing's filter instruction or §Discontinuity's join
  table — where it now classifies a byte-order mark as owing a Discontinuity,
  contradicting an accept vector.
- **Two are missing vectors** for rules `0.17` shipped.
- **Two are pre-existing gaps that `0.17` made load-bearing**: whether the
  ordering MUST admits a `seq_start` tie, which the handshake MUST now *requires*
  in every capture that records a handshake, and where a `seq_start`-less record
  sits.

| Issue | Title | Kind |
|---|---|---|
| [#124](https://github.com/adamkjonsson/zipline/issues/124) | The ordering MUST does not say whether two records may share a `seq_start` | spec, **highest severity** |
| [#122](https://github.com/adamkjonsson/zipline/issues/122) | The join table has one row for both sides of #98's split, and the BOM lands on the wrong one | spec, **high** |
| [#119](https://github.com/adamkjonsson/zipline/issues/119) | §Referencing still tells a filter to write `reason = skipped` | spec, **high** |
| [#114](https://github.com/adamkjonsson/zipline/issues/114) | The unplaceable record's position is defined by the preceding record's end | spec, **weakly blocking** |
| [#116](https://github.com/adamkjonsson/zipline/issues/116) | A handshake above the origin violates the MUST with no reader rule | spec |
| [#113](https://github.com/adamkjonsson/zipline/issues/113) | §Conformance lists the origin floor as an instance of the isolate tier | spec |
| [#115](https://github.com/adamkjonsson/zipline/issues/115) | The floor is vacuous without an `isn`, and its cost is argued only for a zero-length record | spec |
| [#117](https://github.com/adamkjonsson/zipline/issues/117) | The `dropped` arm of the seam predicate tests a word in an open vocabulary | spec |
| [#120](https://github.com/adamkjonsson/zipline/issues/120) | The transport-layer bar is restated without `role`, in a list that counts its members | spec |
| [#121](https://github.com/adamkjonsson/zipline/issues/121) | A pass-through is not told to carry `role` forward | spec |
| [#123](https://github.com/adamkjonsson/zipline/issues/123) | The only `syn` record in the suite is the one that violates the new MUST | vectors |
| [#118](https://github.com/adamkjonsson/zipline/issues/118) | `role` at the transport layer has no vector, where `content_type`'s has one | vectors |
| [#111](https://github.com/adamkjonsson/zipline/issues/111) | `RETIRED_CLAIMS` scans only the specification | vectors, process |

**Every one of the twelve was verified against the tree before scoping**, quote
by quote and inference by inference. All twelve hold. One sub-claim in #114 does
not — see scope decision 3 — and two proposals are declined as extensions or as
manufacturing the very defect another issue reports.

**Expect a small `Changed` section and a large `Fixed` one.** Two entries change
behaviour: #117 states a restriction on the open `reason` vocabulary that was not
there before, and #114 replaces the placement clause with one that computes a
different answer on files where the old one was reachable. #116 *loosens* — a
file a reader could isolate under `0.17` is accepted and reported under `0.18`.
Everything else is `Fixed` or `Clarified`. Draft the entries in the phase that
does the work; four releases running have found this is what gets reconstructed
from memory otherwise.

---

## The scope decisions

### 1. The four propagation misses are the release's centre of gravity

#119, #120, #121 and #122 are not four small edits that happen to have landed
together. They are one failure mode with four instances, and it is the third
release running to hit it (#89 and #91 in `0.15`; #103 in `0.16`; these in
`0.17`). The shape is always the same: **a rule moves, and the sites that state
it in other words do not move with it.**

What makes this batch different from #103 is that the ratchet built for #103
could not have caught any of the four, and it is worth being exact about why:

- #119 and #122 are **stale vocabulary in a normative instruction**. `0.17`
  redefined `skipped`; §Referencing still instructs a filter to write it, and the
  join table's row 3 still covers both sides of the split. Neither *restates* the
  §Undecoded paragraph, so neither is a copy the `0.17` release could have
  entered as retired — the claim being retired was a word's meaning, not a
  sentence.
- #120 and #121 are **enumerations that omit a new member**. "Two further
  requirements", "carry each record's `content_type` forward". Nothing is retired
  here at all; the sentences were true before `role` and are incomplete after.
  A ratchet holding retired claims from returning is structurally blind to this.

So the mechanism this batch calls for is a **completeness** check, not a ratchet,
and that is a different thing to build. Scope decision 5 handles it.

### 2. #113's optional half is declined

The issue proposes rewording the §Conformance clause so the relation is
displacement rather than membership — take that; it is exactly right, and it
fixes the `prim:` width-mismatch rule in the same sentence.

It then optionally suggests naming the two advisory MUST NOTs together in one
place. **Decline.** That manufactures a second statement of a rule stated
elsewhere, which is precisely the defect #120 is a bug report about, in the
release that is fixing #120. The cross-references already carry it: §Typing names
the origin floor, §Referencing names `content_type`.

### 3. #114 is right about the clause and wrong about why

The issue argues the placement clause is *circular*: it defines a position in
terms of a quantity the same rule refuses to assign. That does not hold. An
unplaceable record **is** given a position — a zero-width range at P — so it ends
at P, and a second unplaceable record lands at P too. The rule is defined; what
it is not is *stated* to cover that case.

The other three points hold and are what the fix is for:

- In a conformant file the clause is unreachable. The ordering MUST puts a
  below-origin record first, so "or `0` where there is none" is the only branch a
  conformant file takes.
- Where a file breaks the ordering MUST, "the preceding record's end" and a
  running maximum diverge, because records within a participant may overlap.
- **The `seq_start`-less case is the common one and has no rule at all.**
  `partially-hinted-sequenced` is an accept vector whose pid 0 carries a record
  with `seq_start` followed by one without. `0.17` stated a rule for the rare
  case and left the routine one silent — and `0.17`'s Phase 1 knew this: it
  declined to write "the treatment a `seq_start`-less record already gets"
  *because* no such treatment is stated. Stating one rule for both is the fix.

Their proposed wording needs one correction: "one past the highest offset any
earlier record reached" is off by one against `off_end`. Write it as **the
highest `off_end` any earlier record in the participant reached, or `0` where
there is none**.

### 4. #117 takes option 1, not option 2

Option 2 — a third `reason_class` value, or a flag beside it, so any producer word
can carry "content removed" — generalises properly and is the better design. It is
also **new syntax in a corrective release**, which is what this release is not
for. `0.16` filed #98 rather than fixing it for the same reason and `0.17` shipped
it; the same discipline applies here.

Option 1 is the corrective fix: say out loud at the predicate that content-removed
is expressible **only** as `reason = dropped`, that a producer wanting a more
specific word writes `dropped` and puts the detail in `comment`, and that this is
a real restriction on an otherwise open vocabulary. The openness paragraph
currently promises the opposite, so this is a contradiction to resolve rather than
a nicety.

Re-file option 2 against `0.19` when this lands, with the note that the constraint
is now written down and can therefore be lifted deliberately.

### 5. #111 is in, and the completeness check is a Phase 0 decision with an exit

#111 as filed — extend the scan beyond the specification to the suite, exclude
`CHANGELOG.md` and the release plans by construction, and keep a short allowlist
of `(claim, file)` pairs for deliberate historical mentions like
`mixed-derivation`'s. That is bounded and the issue carries the measurement.

It would not have caught #119–#122, per scope decision 1. **Whether a completeness
check ships in `0.18` is settled in Phase 0, before any phase depends on it**, and
the shape to price is a small table of term groups the model treats as a set —
`{content_type, role}`, `{skipped, dropped}` — with the rule that a **normative**
paragraph or table row naming one member must name all, allowlist for the rest.

The cap: if that cannot be built without an allowlist longer than the check is
worth, it moves to `0.19` and `0.18` ships #111 as filed. Noise is the risk —
§Typing mentions `content_type` many times without `role`, correctly — and a check
whose output is mostly allowlist teaches nothing.

### 6. #106 and #80 move to `0.19`

Neither is corrective. #106 is an open design question that needs the positive
marker priced — the option `0.17`'s Phase 0 could not price and the issue does not
list. #80 is a new option by definition.

**#80's deadline still runs and gets restated on the milestone, not softened.** It
is not safe for a reader to skip, so it must land before `1.0` or not at all, and
`0.x` is the only window it has. Deferring it for a corrective release is right;
deferring it indefinitely is a decision nobody will have made on purpose.

---

## Dependencies

```
#111 ── first, for the reason #100 went first in 0.16: it is the release's
        guard, and a guard whose first use is the release that added it
        is a guard known to work

#124 ─┬─▶ #114   one edit: ties are what make "the preceding record"
      │          ambiguous, so both are fixed by removing it
      └─▶ #123   the vector demonstrates the tie the rule permits;
                 the rule first, or the vector edits the evidence

#113 ──▶ #116    both are the floor's strength; #116 extends the treatment
                 #113 makes it possible to state cleanly

#119, #122, #117    §98's split; independent of each other
#120, #121, #118    role; independent of each other
#115                independent of everything
```

**#124 before #123**, for the reason #92 went before #93 in `0.16`. If the vector
lands first, a reader that rejects ties is failed by a fixture the document does
not yet support, and the finding gets closed by editing the evidence.

**#124 touches a site neither issue names.** §Merge algorithm's cost argument says
the per-participant streams "are always **totally ordered**" because of the
ordering MUST ([:412](zipline-payload-format.md)). Under a tie they are not
totally ordered *by `seq_start`* — stored order supplies the rest. That sentence
needs the same clause, and it is the third site, not the second. Found while
scoping; it is exactly the propagation failure scope decision 1 is about, and
this release should not commit it while fixing four instances of it.

---

## Phases

### Phase 0 — stamp, #111, and the completeness question

1. `MAJOR, MINOR = 0, 18` in `vectors/build.py`; `check.py` to match; regenerate;
   the spec's version sites; open `## [0.18] — unreleased`.
2. Confirm `reject-unknown-minor` rolls on its own — it stamps `MINOR + 1`, so it
   goes 18 → 19. Read it out of the stamped bytes, not the constant.
3. **#111**, and validated by reproduction rather than by inspection: run the
   extended scan with `0.17`'s `RETIRED_CLAIMS` entries against the **`v0.16`**
   tree. It must report the two stale copies `0.17` fixed by hand — the vector
   summary in `build.py` and the row in `vectors/README.md`. Against the current
   tree it reports nothing, which is correct and proves nothing.
4. **Settle the completeness check** (scope decision 5). Table shape and noise
   floor only; no phase depends on it, and if it is deferred it is deferred here.

Stamp first. Every later phase regenerates the tree.

**Expect green throughout.** Unlike `0.16` and `0.17` this release opens no red
window: no vector is wrong today, and the two new ones are additions. If
`check.py` goes red, something is broken rather than pending.

### Phase 1 — the ordering tie (#124, #123)

The release's highest-severity item, and the one a third implementation cannot
arrive at on its own.

- **#124** — one clause where the rule is stated: `seq_start` order is
  **non-descending**; two records MAY share a `seq_start`; stored order decides
  which comes first. Name the handshake case as the ordinary one, since `0.17`'s
  MUST makes it mandatory in every capture that records a handshake.
- **The third site**: §Merge algorithm's "always totally ordered". Order by
  `seq_start` then stored order, and say so.
- **#123** — the positive handshake vector, on the accept tier: SYN at `isn + 1`,
  first data record at `isn + 1`, and a manifest entry saying what it exists for —
  the correct shape of the record `advisory-seq-start-below-origin` gets wrong,
  and the tie the origin being `isn + 1` necessarily produces. Cross-reference the
  two in both directions.

Nothing in the suite has ever carried a `seq_start` tie; verified across all 56
vectors while scoping. A reader implementing `<` passes the whole suite today and
fails on real traffic.

### Phase 2 — the floor's edges (#113, #114, #116, #115)

- **#113** — reword the §Conformance clause to displacement: a stated rule for a
  violation *displaces* the licence, whether stronger or weaker than isolation.
  One sentence, and it repairs the `prim:` width-mismatch rule in the same breath.
- **#116** — extend the advisory treatment to a `syn` record whose `seq_start` is
  above the origin, so one sentence covers the whole MUST. Name the two shapes the
  MUST leaves open while there: a `syn` record with no `seq_start`, and a
  `syn`-flagged record that is not zero-length.
- **#114** — one placement rule for both unplaceable shapes, stated without "the
  preceding record": *the highest `off_end` any earlier record in the participant
  reached, or `0` where there is none.* This is the edit #124 also needs.
- **#115** — the floor is non-vacuous only on an `isn`-anchored participant, and
  why; plus one sentence costing the non-empty case honestly: a below-origin
  record carrying payload has those bytes excluded from the extent and from
  coverage, and that is the price of not trusting the wrapped offset.

**One vector, conditionally**: #115 suggests a payload-carrying below-origin
record. It exercises a different reader path from the zero-length one and is where
the two wrong implementations — wrap, or drop the record — diverge visibly. Take
it if Phase 2 confirms the path really is different in a reader; skip it if it
only re-tests the same arithmetic.

### Phase 3 — #98's split, unpropagated (#122, #119, #117)

- **#122** — split the join table's row 3. The `skipped` side joins and belongs
  with framing; the `dropped` side does not. Name the words in the rows so the
  table and the predicate can be read against each other. This is the table a
  producer actually follows, and it is the one place the duty is stated in terms
  of what the stage *did* rather than what word it wrote.
- **#119** — `skipped` → `dropped` in §Referencing's filter paragraph, and rewrite
  the trailing clause: it currently says `skipped` is "exactly what that reason is
  for", which `0.17` made false. Enter the old sentence in `RETIRED_CLAIMS` — it
  names a canonical word in a normative instruction, which is the shape that gets
  copied into an implementation.
- **#117** — state the restriction on the open vocabulary at the predicate.

### Phase 4 — `role`, unpropagated (#120, #121, #118)

- **#120** — both §Conformance sites. Prefer "no label (`content_type` or `role`)"
  or "carries no label, in the sense §Typing gives that word" over a fresh
  enumeration, so the next label added does not stale them again. Fix the count.
- **#121** — name `role` beside `content_type` in the pass-through carry-forward
  bullet and in §Annotating a decoded file. "Carry each record's labels
  (`content_type`, `role`) forward" survives the next label.
- **#118** — `advisory-transport-role`, built as `advisory-transport-content-type`'s
  twin: accept tier, `advisory: true`, one violation, and an `expect` saying the
  label is ignored, reported, round-trips, and that rejecting or isolating is not
  conformant. Two vectors rather than one file carrying both labels, so each
  isolates one rule.

### Phase 5 — changelog, conformance sweep, release

Run `RETIRED_CLAIMS` — extended — over the finished release, and each new entry
against the tag of the release before the one that retired it, as `0.17` did.
Draft `Changed` from the entries written in Phases 2 and 3, not from memory.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The completeness check turns into a `0.19`-sized design mid-release | **medium — this release's dominant scope risk** | Scope decision 5 prices it in Phase 0 and names the exit: it defers, and #111 ships as filed. |
| #124 is fixed in §Identifiers & ordering and not in §Merge algorithm | **medium — the release's own failure mode** | The third site is named in Dependencies. Fix both in one commit. |
| #114's new placement rule silently changes an existing vector's meaning | medium | `partially-hinted-sequenced` is the file to check first; confirm no manifest number moves before writing the rule. |
| #120 is fixed by enumerating again, and stales at the next label | medium | Prefer the "no label" formulation; the issue makes the same point. |
| #117 is read as forbidding a specific `reason` word rather than requiring `dropped` alongside | low, high cost | State it as: the region carries `reason = dropped`; specificity goes in `comment`. |
| #113's declined half creeps back in as "one small list" | low | Scope decision 2 is written down, and #120 is the evidence. |
| Vector estimate is low again | medium | Budget **58** (56 + #123 + #118), 59 with #115's conditional. The estimate has run low twice and right once. |
| #80 is deferred again in `0.19` with no decision | medium | The milestone carries the deadline argument, not just the issue. |

---

## Definition of done

- [ ] All thirteen in-scope issues closed, each in the commit that finishes it.
- [ ] The ordering MUST says whether two records may share a `seq_start`, at
      **both** sites that depend on it, and a vector carries the tie.
- [ ] One placement rule covers both unplaceable shapes — below the origin, and
      no `seq_start` on a hinted stream — without reference to "the preceding
      record".
- [ ] The whole of the handshake MUST has one stated strength, and §Conformance
      describes the two advisory MUST NOTs by displacement rather than membership.
- [ ] The floor's vacuous half says it is vacuous, and the non-empty case is
      costed honestly.
- [ ] No section instructs a filter to write `reason = skipped`, and the join
      table tells the two sides of #98's split apart.
- [ ] The restriction `dropped` places on the open `reason` vocabulary is stated
      where the predicate uses it.
- [ ] No statement of the transport-layer bar or of a pass-through's carry-forward
      names `content_type` without `role`, and `advisory-transport-role` exists.
- [ ] `RETIRED_CLAIMS` scans the suite as well as the specification, with the
      changelog and the release plans excluded by construction, and reproduces
      `0.17`'s two hand-fixed copies against `v0.16`.
- [ ] Either a completeness check ships, or it is on `0.19` with its noise floor
      recorded.
- [ ] `python3 vectors/check.py` green; every vector stamps `0.18`. *Estimated 58
      entries.*
- [ ] `CHANGELOG.md` `[0.18]` complete, with a `Changed` section covering #117 and
      #114.
- [ ] #106 and #80 are on `0.19`, #80 with its pre-`1.0` deadline restated.
- [ ] `ruff check` and `ruff format` clean.
