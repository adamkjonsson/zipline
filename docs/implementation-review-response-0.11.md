# Response: the 0.11 implementation review

Assessment of [SPEC-0.11-REVIEW.md](SPEC-0.11-REVIEW.md), a review of `0.11`
from `python-zipline` against tag `v0.11`, and the scope it settles for `0.12`
and `0.13`.

Third in a series: [issues #8–#16](implementation-feedback-analysis.md), then
[the review that produced `0.10`](implementation-review-response.md), then
[the review that produced `0.11`](implementation-review-response-0.10.md).

---

## 1. Verdict at a glance

The review confirms all six `0.10` findings fixed — **verified by diffing the two
specifications rather than reading the CHANGELOG's claims**, which is the right
way to check and worth noting as a standard for future rounds. It records two
fixes as better than what it had proposed, and finds nothing that `0.11`
introduced.

Three findings remain:

| # | Finding | Valid? | Disposition | Effort |
|---|---------|--------|-------------|--------|
| R1 | The exact-timestamp tie is unresolved — the last place two conformant readers can disagree | **Yes, and it should not wait** | Break ties by `(timestamp, participant_id)` | XS |
| R2 | "hint-less" is load-bearing in 14 places and defined nowhere | **Yes**, and its rule is adopted as proposed | Define it; state the evaluation point. Partial-hint gap left open — see `0.13` | S |
| R3 | The producer-tie-break sentence points at an option scoped to a different case | **Yes — my imprecision** | Scope the clause | XS |

All three are corrective: no block, no option, no capability.

**Two are mine from `0.11` itself.** R3 is a sentence I wrote in Phase 13. R1 I
found in the Phase 15 read-through and deferred, on the grounds that `0.11` was
corrective-only and should not invent a rule at release time — defensible then,
and superseded now that the review supplies a fix costing nothing.

**R2's second half survives from the previous round.** The `0.10` review raised
the reader-side mirror problem — that a `sequenced_basis` check cannot fire when
the Session Descriptor is read — and `0.11` fixed only the writer side. That is
worth owning rather than presenting as new.

---

## 2. Point by point

### R1 — the exact-timestamp tie

**Valid, and the one finding that should not wait for a design cycle.**

`0.11` states the gap openly, having removed the round-robin fallback that
masked it: independent reader merges break ties by timestamp, but two concurrent
records bearing the *same* timestamp are a genuine tie the document does not
resolve. So two conformant readers can produce different orders for the same
non-sequenced file — which undercuts the property the format otherwise sells,
and the reason sequencing is offered as an optimisation rather than a
correctness fix.

**The fix costs nothing.** Within a session `participant_id` is unique, so
`(timestamp, participant_id)` totally orders the merge's frontiers. Combined
with the stability rule `0.11` already carries, that yields one deterministic
order for every file: no new option, no new field, no reader cost.

The decisive evidence is that **`python-zipline` already merges on
`(timestamp, pid)`**, because a total order was needed to make the merge
testable at all. Convergence is happening as folklore; specifying it before more
implementations exist is the whole opportunity, and it closes in proportion to
how many implementations appear.

### R2 — "hint-less" is undefined

**Valid on the diagnosis. The proposed mixed-case rule is wrong.**

The term appears 14 times carrying normative weight, including the
`sequenced_basis` MUST and the `SEQUENCED` soundness rule, and the nearest thing
to a definition is a parenthetical in *Conformance*.

**Adopt the review's rule.** A session is hint-less when no record in it carries
`seq_start` or `ack`; a single hint anywhere means it is not hint-less and needs
no basis.

**A rejected alternative, recorded because it looked right for a while.** This
document first proposed splitting the rule in two — a *reader check* keyed on
that same definition, plus a broader *producer obligation* to record the basis
whenever the stored order does not follow entirely from causal hints. The aim was
to catch the partially-hinted session, whose order rests mostly on timestamps
while one stray hint exempts it.

That obligation is **undecidable for a streaming producer**, for exactly the
reason `0.11` removed the previous exemption: the Session Descriptor is written
before the records. A producer opening a TCP session expects hints and writes no
basis; if a record later arrives without `seq_start`, the order no longer follows
entirely from hints and the descriptor is already on disk. A batch producer knows;
a streaming one cannot. Reproducing the defect we had just removed, in the fix for
it, is worth recording rather than quietly dropping.

The residual gap is also narrower than it first appeared. A consumer *can* see
that some records lack hints, and that the merge leaves those concurrent; what it
cannot learn is what the producer relied on for them. That is reduced legibility,
not a correctness trap.

**The evaluation point must also be stated**, which is the half surviving from
the previous round: whether a session is hint-less is a property of its
*records*, so a reader can only conclude it at Session End or end-of-stream.
Cheap — one boolean per open session, composing with state a reader already
keeps — but every implementer rediscovers it, and the
`isolate-sequenced-no-basis` vector silently encodes whichever answer its author
assumed.

### R3 — the producer-tie-break sentence overreaches

**Valid, and it is my sentence from Phase 13.** It says a producer choosing a
different tie-break "says so with `sequenced_basis`" — but that option is scoped
to hint-less sessions, and *Conformance* is explicit that a session carrying
`seq`/`ack` needs none. So a TCP producer that breaks concurrent-record ties by
something other than timestamp has nowhere to record it, and the sentence implies
otherwise.

Nothing breaks: a sequenced session's stored order is authoritative however it
was arrived at, and a reader never re-derives it. An imprecision, not a defect.
Scoping the clause settles it.

---

## 3. Scope for `0.12` and `0.13`

Both fixed here, deliberately, because **input stream extents has now been
deferred twice** — held from `0.11`, then from `0.12` — and it is the item both
previous reviews independently argued for. A third slide is how an item becomes
permanent. Scoping `0.13` now costs nothing and stops the pattern.

### `0.12` — corrective

R1, R2 and R3, their vectors, and the release. No block, no option, no
capability. Same shape as `0.11`, and for the same reason: R1 in particular
should not queue behind a design cycle.

### `0.13` — the feature release

Contents fixed now:

1. **Input stream extents** on Session End, so the coverage guarantee is
   verifiable without holding the parent. Argued for by both reviews
   independently; the `chain/` fixture demonstrates the gap concretely, being the
   only place coverage can currently be checked at all.
2. **`transform_params_digest`** on the File Header, so a filter, reordering
   stage or merge can pin its own configuration.
3. **A version re-stamp record** — see below; the review's design is better than
   the one this project settled on last round.
4. **Decrypted tunnels** — design first, wording second.

Plus one candidate, to be decided rather than assumed:

5. **A basis on every `SEQUENCED` session**, not only hint-less ones — the clean
   way to close R2's partial-hint gap. Trivially decidable, since a producer
   always knows what it is relying on when it sets the flag, and it removes the
   `hint-less` dependency from that rule entirely. Costs: it reinstates
   `transport` as a vocabulary value, which `0.11` deleted on the grounds that it
   could never legitimately appear — under this rule it appears constantly and
   legitimately — and it puts an option on every sequenced TCP session. It also
   *adds an obligation to files that are conformant today*, which is why it is
   not in `0.12`. Decide it once there is evidence the gap matters.

**A rule so `0.13` cannot slide wholesale.** Items 1–3 are committed; item 5 is
a candidate, not a commitment. Item 4
ships in `0.13` only if its three open questions are settled by the time 1–3 are
drafted; otherwise `0.13` ships without it and tunnels become `0.14`. The
feature release does not wait on the least-settled item in it.

### Adopting the review's design for the re-stamp

The previous round concluded that a version re-stamp *is* expressible as a
pass-through. The review argues it should not be, and is right:

> A transcoded raw file is still raw — capture-sourced, same bytes, same ids —
> and forcing it through the pass-through shape would require declaring a
> `zpf-input` Source and putting `origin` on every participant, recording a
> derivation that did not happen and moving capture provenance a hop away.

That is a better reading. The pass-through route mints fresh ids, so external
references to the old file's session ids break — a cost the previous response
noted and then under-weighted. What is actually missing is a way to say *these
bytes were re-stamped from version X*, which a single File Header option carries
without disturbing the two-kind taxonomy.

So item 3 becomes an option, not a transform, and the taxonomy stays at two
branches.

---

## 4. Roll-out plan

Continues the numbering from
[implementation-review-response-0.10.md](implementation-review-response-0.10.md)
§3, whose Phases 12–15 are complete.

### Phase 16 — Decisions

- [x] **`0.12` scope** — corrective only: R1, R2, R3.
- [x] **`0.13` scope** — input stream extents, `transform_params_digest`, the
      version re-stamp option; decrypted tunnels if their open questions are
      settled in time, otherwise `0.14`.
- [x] **The re-stamp is an option, not a transform** — adopting the review's
      design over the previous round's conclusion.
- [x] **R2's rule** — **decided: the review's single rule.** The split this
      document originally proposed is withdrawn: its producer obligation was
      undecidable for a streaming writer, reproducing the very defect `0.11`
      removed. See §2. The partial-hint gap is left open and recorded as a
      `0.13` candidate below

### Phase 17 — The three fixes

- [x] **R1** — replace step 4 of the merge algorithm: ties break by timestamp,
      then by ascending `participant_id`. Restate the determinism paragraph in
      *Sequenced files* as a plain guarantee rather than a caveat, since it now
      is one
- [x] **R2a** — define **hint-less** once, where it is first used: a session in
      which no record carries `seq_start` or `ack`
- [x] **R2b** — state the evaluation point: it is a property of the records, so a
      reader concludes it only at Session End or end-of-stream, and a checker
      defers the `sequenced_basis` requirement to there
- [x] **R3** — scope the producer-tie-break clause to hint-less sessions
- [x] Checked all fourteen uses of "hint-less" against the new definition; all
      read correctly. One gap the plan did not anticipate: the producer applies a
      rule keyed on a property it cannot evaluate at descriptor time either. It
      does not need to — it decides by what it is *relying on* — but the document
      now says so, or a reader would reasonably ask

### Phase 18 — Vectors and release

- [ ] Vector for R1: two concurrent records, different participants, **identical
      timestamps** — the case where an unspecified tie-break makes two conformant
      readers disagree
- [ ] Vector for R2: a **partially-hinted** `SEQUENCED` session carrying no
      basis — conformant under the adopted rule, and the case a future `0.13`
      change would reclassify. Worth having precisely because it pins today's
      answer to the question that was hardest to settle
- [ ] Confirm `isolate-sequenced-no-basis` still expresses what R2 settles, since
      it currently encodes an assumption rather than a stated rule
- [ ] Bump `version_minor` to `12` — File Header, byte-level example, all JSONL
      examples, every vector, the checker, and `reject-unknown-minor` to `13`.
      *This is not automatic; the `0.11` plan omitted it and it was nearly
      shipped stamping `10`*
- [ ] Full read-through, not only the mechanical sweeps
- [ ] Cut `0.12`: date the CHANGELOG section, tag, hand back

### Phase 19 — `0.13`

Outlined only; planned properly once `0.12` ships.

- [ ] Settle the three tunnel questions, which gate whether item 4 makes `0.13`
- [ ] Input stream extents, `transform_params_digest`, the re-stamp option
- [ ] Vectors for each, including a **broken** chain — the fixture gap `0.11`
      left open, exercising *bytes unavailable* against *no bytes exist*
