# Response: the 0.10 implementation review

> **Historical record.** This document captures a decision round as it happened —
> what was found, what was decided, and why. It is not a plan and is not kept
> current. **Active work lives in the [issue tracker](https://github.com/adamkjonsson/zipline/issues).**

Assessment of [SPEC-0.10-REVIEW.md](SPEC-0.10-REVIEW.md), a review of `0.10`
from `python-zipline` against tag `v0.10`, and the decisions that follow from it.

Second in a series. The first round (issues #8–#16) is in
[implementation-feedback-analysis.md](implementation-feedback-analysis.md); the
review that produced `0.10` and the renumbering is in
[implementation-review-response.md](implementation-review-response.md), whose
plan ran to Phase 11. Its *Carried to `0.11`* items are absorbed here — all
three into §4, since `0.11` takes no new features.

---

## 1. Verdict at a glance

| # | Finding | Valid? | Disposition | Effort |
|---|---------|--------|-------------|--------|
| D4 | CHANGELOG's versioning invariant is false for `0.9` | **Yes — the worst of the six** | One sentence: a `0.9` file stamps `1`/`0` | XS |
| D1 | `sequenced_basis` required and exempted by the same document | **Yes, and undecidable while streaming** | Require the *recording* unconditionally | S |
| D6 | Alias table illustrates with the retracted `"zipline-payload/1"` | **Yes** | Swap the example | XS |
| — | Positional decoded offsets are O(k) for random access | **Yes** | Add the note; recommend prefix sums on a first pass | XS |
| D2 | The merge has no defined behaviour on a hint-less session | **Half** — the k-way structure determines it; it is never *stated*, and step 4's skew clause is unactionable | State the stability invariant; fix step 4 | S |
| D3 | A version transcode is not expressible | **Half** — a re-stamp *is* a pass-through; a *normalising* transcode is not, and the guidance is missing | `0.11`: state `0.x` disposability. `0.12`: the normalisation permission. **Reject** a third derivation kind | M |
| D5 | `zpf-input` conflates two relationships | **Diagnosis yes, remedy no** | Fix the *Conformance* sentence rather than add an option | XS |
| — | Coverage unverifiable for a decoded pass-through | **Yes** | Confirms the input-extents item — deferred to `0.12`, since it is a new option | (deferred) |

**Six findings; four adopted as stated, two where the diagnosis stands and the
remedy changes.** None reopens a `0.10` design decision — they are
contradictions, omissions, and one missing sentence.

**Two of the six are consequences of decisions taken last round**, and that is
worth stating rather than glossing: D4 falls out of the renumbering, and D1 out
of making `sequenced_basis` a MUST. Both were recommendations of the previous
response.

### Worth recording about the review itself

- **It verified the byte arithmetic independently** — 196 bytes, block
  alignment, and `0xFF20` as exactly the complement of the seven defined flag
  bits. That is a second party confirming the premise the conformance vectors
  rest on.
- **`time_units` was found in the wild a second time.** The implementation
  emitted it as a unit label because it copied `0.9`'s four worked examples,
  which were wrong. That is the defect that motivated building vectors,
  observed again — and it is non-conformant against `0.9` too, not only `0.10`.

---

## 2. Point by point

### D4 — the CHANGELOG's versioning invariant is false for `0.9`

**Valid, and the most consequential of the six despite being the smallest.**

*Conventions* asserts that versions match the `version_major`/`version_minor`
fields in the File Header. For `0.9` that is untrue: a real `0.9` file stamps
`1`/`0`, because the renumbering re-designated the July text without rewriting
any bytes — there never were any `0`/`9` files.

The previous response records exactly this ("nothing ever needs to stamp `0/9`")
and it never reached the CHANGELOG, which is where an implementer actually
reads. Someone building a `0.9` reader from it looks for `0`/`9` and rejects
every real `0.9` file.

**Fix:** one sentence in *Conventions*, and a matching note in the `[0.9]`
section.

### D1 — `sequenced_basis` is required and exempted by the same document

**Valid on both arguments; the second is the stronger.**

The contradiction is real. *Sequenced files* says two cases are "sound
trivially, **with no basis needed at all**"; the option registry says
`sequenced_basis` **MUST** be present on a hint-less `SEQUENCED` session with no
qualification; *Conformance*'s "meets this trivially" leaves open whether "this"
is the soundness requirement or the recording requirement. A checker author
cannot satisfy both readings.

The sharper argument is that **the exemption is undecidable for a streaming
writer**. `SEQUENCED` sits on the Session Descriptor, which declare-on-first-use
places before the session's records, so "only one participant ever sends" is not
known when the flag must be written. That is the same class of problem the
lowest-minor stamping rule was withdrawn for — the review is applying our own
reasoning back to us, correctly.

A **third** site turned up while fixing it, which the review did not catch: the
narrative also said the producer *SHOULD* say what the basis was, contradicting
the registry's MUST. The inconsistency spanned three passages, not two.

**Fix, as proposed:** separate the two requirements. *Soundness* may be trivially
met; *recording* is unconditional. A producer setting `SEQUENCED` on a hint-less
session always writes `sequenced_basis`, and the trivial cases simply make the
claim easy to justify. Decidable at Session Descriptor time, no deferred state on
either side.

**Reversed on `trivial`.** This document first argued against adding the value;
that was wrong. If recording is unconditional, a trivially-sound session must
write *something*, and none of `clock`/`protocol`/`external` is true of it —
forcing a choice among them makes the producer state a falsehood. `trivial` says
what is actually the case. The original objection (that a streaming writer cannot
know the session is single-sender) does not apply: such a writer is not relying on
triviality and records what it *is* relying on, while one decoding a known
one-way feed can say so honestly at Session Descriptor time. Adding a defined
value to an already-open vocabulary documents an existing possibility rather than
adding surface, exactly as `skipped` did in `0.10`.

### D6 — the alias table illustrates with a retired version

**Valid, trivial.** The brevity-alias row explains the omitted-minor rule with
`"zipline-payload/1"` ⇒ major 1, minor 0 — the exact version that was retracted,
in the table a reader consults while working out what the renumbering did.

**Fix:** illustrate with `"zipline-payload/2"`, which is unambiguous because no
such version exists or is planned.

### Cost — positional decoded offsets are O(k) for random access

**Valid, and newly mandatory.** `0.9` left decoded offsets undefined, so the cost
was implementation-chosen; `0.10` makes prefix-summing the only conformant
answer. With no index block and records interleaved across participants,
resolving one arbitrary record's range means scanning from the start of that
participant's stream.

Free for a forward streaming reader — one running counter per participant — which
is the design's primary case, so this is a documented cost rather than a defect.

**Fix:** state it, and recommend that a reader wanting random access build the
per-participant prefix sums on a first pass. Cross-reference the random-access
index under *Possible future extensions*, which would otherwise look unrelated.

### D2 — the merge on a hint-less session

**Half valid, and the half that is wrong matters.**

The merge is specified as *"a streaming k-way merge over already-sorted
per-participant streams"*, holding one frontier per participant. A frontier
releases its own stream's next record, so the merge **cannot** reorder one
participant's records against each other — that is structural, not incidental.
The review's dichotomy — emit timestamp order *or* stored order — is a false
choice: the merge emits an interleaving that preserves each participant's order
and uses timestamps only to choose *between* frontiers. Which is exactly the fix
the review proposes, so it has derived the right answer while claiming it is
absent.

**But make the change anyway.** The invariant is implicit in the algorithm's
shape and stated nowhere, and an implementer reading *Conformance* alone would
not derive it. The review's sentence is the right one: a merge over a hint-less
session is **stable** with respect to stored order.

**And the side-observation is a genuine defect.** Step 4 says "if clocks are
known-skewed, fall back to round-robin / source order", and **known-skewed is not
determinable by a reader** — absence of `SINGLE_CLOCK` asserts nothing. That
clause should become a producer-side note or go entirely.

### D3 — a version transcode

**Half valid, and the proposed remedy is rejected.**

A **re-stamp is already expressible as a pass-through**: declare the old file as
a `zpf-input` Source, put `origin` on every participant, re-emit bytes and
offsets unchanged. The review's objection — that this records a derivation when
"really just a re-stamp" happened — is aesthetic, and recording the derivation is
the more honest of the two.

They are nonetheless half-right, for a reason they do not give: a pass-through
MUST re-emit Undecoded blocks **unchanged**, so a transcode that must rewrite
`tcp-gap` → `gap` is not conformant as one. A *pure* re-stamp works; a
**normalising** transcode does not. There is also an unstated cost: a
pass-through mints fresh ids and maps them with `origin`, so any external
reference to the old file's session 7 breaks.

**Reject the third derivation kind.** That is precisely what Phase 4 spent its
effort avoiding, and the `spans`-versus-`origin` discriminator depends on the
taxonomy having two branches.

**Fix instead:** say that a version upgrade is a pass-through, and permit it to
normalise constructs the new version renamed — the one licensed exception to
"unchanged". Separately, state plainly in the CHANGELOG that `0.x` files are
disposable and no upgrade path is guaranteed. The review is right that the
silence is the problem; both halves of its "either/or" are worth doing.

### D5 — `zpf-input` conflates two relationships

**Diagnosis right, remedy wrong.**

In the annotator example `raw.zpf` and `decoded.zpf` are both `zpf-input`, yet
only `decoded.zpf` is an input — `raw.zpf` is declared solely so an inherited
Undecoded block resolves. *Conformance* says "Every derived file MUST declare
each of its input `.zpf`s as a `zpf-input` Source", so a consumer asking "what
are this file's inputs?" counts two.

But the distinction is **already derivable**: the input is what `origin` points
at for a pass-through, or what the records' `spans` point at for a decode stage.
A `referenced_ancestor` option would spend a registry id declaring something
inferable, in a rare case.

**Fix:** correct the *Conformance* sentence so it stops implying that every
`zpf-input` Source is an input, and say where the distinction is read from.

---

## 3. Roll-out plan — `0.11`

Continues the numbering from
[implementation-review-response.md](implementation-review-response.md) §7, whose
Phases 0–11 are complete. Absorbs that document's *Carried to `0.11`* items.

### Phase 12 — Decisions

- [x] **Scope of `0.11`** — **decided: corrective only, no new features.**
      `0.11` fixes what the review found and adds no option, block or capability.
      Everything that introduces surface moves to `0.12` (below).

      Note this defers one item further than first recommended: *input stream
      extents* is a new Session End option, so despite being the most valuable of
      the carried items it is a feature and waits. `transform_params_digest` goes
      with it.

- [x] **Transcode** — **decided: only the documentation half lands in `0.11`.**
      The CHANGELOG states that `0.x` files are disposable and no upgrade path is
      guaranteed. The *permission* — letting a pass-through performing a version
      upgrade normalise what the new version changed — is a normative relaxation
      and moves to `0.12` with the other deferred work.

      Consequence, stated plainly rather than left implicit: **`0.11` ships
      having identified that every `0.9` file is stranded and having fixed only
      the silence, not the stranding.** That is the deliberate cost of holding
      the line at corrections.

      *Finding to carry into `0.12`, which reshapes the permission.* Working out
      what a `0.9` → `0.10` transcode must actually do shows it is not only
      renames. Three changes are needed: `tcp-gap` → `gap`; or keeping
      `tcp-gap` and adding `reason_class: hole`, since it is no longer canonical;
      and **supplying `sequenced_basis` on a hint-less `SEQUENCED` session**,
      which `0.10` requires and `0.9` never recorded. The third is resolvable —
      the transcoder may honestly write `clock`, because `0.9`'s own rule
      required a single trustworthy clock for exactly that case — but it means
      *adding* a required option, not just renaming one. So the permission must
      read something like: *may supply an option the new version requires, where
      the old version's own rules determine its value*. That clause is what keeps
      it from becoming a licence to invent data. Scoping it "to renames only", as
      §3 previously said, would have left those sessions untranscodable and the
      guidance half-useless

### Phase 13 — The review's contradictions and omissions

Small, independent, and all safe to land together.

- [x] **D4** — state in *Conventions* that a `0.9` file stamps `1`/`0`, with a
      matching note in the `[0.9]` section. Do this first; it is the one that
      actively misleads
- [x] **D1** — separate soundness from recording: `sequenced_basis` is written
      unconditionally on a hint-less `SEQUENCED` session, and the trivial cases
      make the claim easy rather than unnecessary. Reword *Sequenced files*
      (drop "no basis needed at all"), the registry row, and *Conformance*'s
      "meets this trivially"
- [x] **D2a** — state the merge's stability invariant: it never reorders one
      participant's records against each other; timestamps choose only between
      frontiers
- [x] **D2b** — remove or rewrite step 4's "if clocks are known-skewed" clause,
      which asks a reader for a determination it cannot make
- [x] **D5** — reword the *Conformance* sentence about declaring inputs, and say
      that the immediate input is the one `origin`/`spans` reference
- [x] **D6** — illustrate the omitted-minor rule with `"zipline-payload/2"`
- [x] **O(k) note** — record the random-access cost and the prefix-sum
      recommendation, cross-referencing the index under future extensions
- [x] Vectors for D1 and D2a: a hint-less `SEQUENCED` session missing
      `sequenced_basis` (isolate tier), and a hint-less session whose timestamps
      run backwards across participants, which a merge must interleave without
      reordering either participant

### Phase 14 — The disposability statement

Reduced to one item by the Phase 12 decision; the rest moved to §4.

- [x] CHANGELOG: `0.x` files are disposable and no upgrade path between `0.x`
      versions is guaranteed — regenerate from the capture instead. Say it in
      *Conventions*, beside the rule that a reader rejects a `version_minor` it
      does not implement, since that rule is what makes it true

### Phase 15 — Vectors and release

- [x] Vectors for D1 and D2a — landed with Phase 13
- [x] **A real multi-file provenance chain** — three files whose offsets and
      digests actually agree. Already the vector suite's top stated gap, and the
      review's inability to verify decoded-pass-through coverage is a second
      argument for it. It adds no format surface, so it belongs in `0.11`
- [x] Full read-through, not only the mechanical anchor and link sweep. Every
      finding of the last two rounds came from reading the examples and asking
      concrete questions of them; the mechanical sweeps caught none of them
- [x] Cut `0.11`: CHANGELOG dated, and the **version fields bumped** — this plan
      said only "date and tag", which was an omission. `version_minor` becomes
      `11` in the File Header, the byte-level example, all five JSONL examples,
      every vector, and the checker
- [ ] Tag `v0.11` once merged, and hand back to `python-zipline`

---

## 4. Deferred — now scoped to `0.13`

Everything that adds surface. Each is recorded with its reasoning above or in the
[previous response](implementation-review-response.md); none is a `0.10` defect.

> **Deferred once more, and now scoped.** `0.11` shipped corrective-only, and the
> review of it found three further corrections, so `0.12` is corrective too.
> These items are committed to **`0.13`**, whose contents are fixed in
> [implementation-review-response-0.11.md](implementation-review-response-0.11.md)
> §3 — including a rule stopping the release sliding wholesale, since this is the
> second deferral. Note the version re-stamp design changed there: it becomes a
> File Header option rather than a pass-through.

- **Input stream extents** on Session End, so the coverage guarantee is
  verifiable without holding the parent. The most valuable of the three, and
  independently confirmed by this review: `check_coverage` cannot verify a
  decoded pass-through at all, since the output carries no `spans` and coverage
  is inherited by assertion. A new option, so it waits.
- **`transform_params_digest`** on the File Header, so a filter, reordering stage
  or merge can pin its own configuration. A new option, so it waits.
- **The version-upgrade permission.** A pass-through performing a version upgrade
  MAY normalise what the new version changed. It must cover more than renames —
  see the Phase 12 finding: a `0.9` → `0.10` transcode also has to *supply*
  `sequenced_basis` on a hint-less `SEQUENCED` session, so the rule needs a
  clause like *may supply an option the new version requires, where the old
  version's own rules determine its value*. Also record the id-reminting cost,
  which is currently unsaid: a pass-through mints fresh ids and maps them with
  `origin`, so external references to the old file's session ids break. A
  normative relaxation, so it waits.
- **A reader-side tie-break for equal timestamps.** Found during the Phase 15
  read-through. Removing step 4's skew fallback made reader merges nearly
  deterministic — every reader now breaks ties by timestamp — but two concurrent
  records carrying the *same* timestamp remain a genuine tie this document does
  not resolve, so independent readers can still produce different interleavings.
  A fixed rule (sender `pid`, say) would close it. Not legislated in `0.11`,
  which is corrective only and should not invent a rule at release time; the
  situation is no worse than `0.10`, merely now visible.
- **Decrypted tunnels** — the offset space keyed on what a stream *is* rather
  than which stage produced it. Needs its three open questions settled before any
  wording: whether a decode stage may mint sessions unrelated to its input's;
  whether keying on `isn`/`seq_start` misclassifies a hint-less inner flow; and
  whether decrypt-and-resessionize is one stage or two.

Holding these together has a side benefit: `0.12` becomes a deliberate
feature release, which is easier to review as a whole than three additions
smuggled in beside corrections.
