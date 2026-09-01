# Release 0.17 — implementation plan

*Written 2026-08-31 against **v0.16**, the three issues carrying the `0.17`
milestone, and the five other issues open when the release was scoped. This is a
working roadmap, not normative text: it says what to change, in what order, and
what "done" means.*

---

## What this release is

**A feature release, and the one that decides what a decoded record may say about
itself.** `0.16` was corrective, like `0.11`, `0.12` and `0.14`; `0.15` before it
was the feature release that split provenance and layer. `0.17` takes the three
findings `python-zipline`'s `0.3.0` planning pass raised against `0.16`, and — in
the same release, because the same evidence produced them — answers the questions
that pass split out rather than leaving a producer to guess. One of the two
turned out to cost more than a paragraph and moved to `0.18`; see scope decision
2.

The evidence behind four of these seven is `kober`, a spec-driven decoder run over
`zpfwire`-converted DNS and HTTP captures. It is the first implementation to
decode at **field** granularity, which is why it is the first to find that a
decoded record has no name, that a 4-bit field has no width, and that a nested
decomposition is a stream the document has no verdict on.

| Issue | Title | Kind |
|---|---|---|
| [#108](https://github.com/adamkjonsson/zipline/issues/108) | A record's `seq_start` may precede the stream origin, and the handshake shape is only prose | spec, vectors, **blocking** |
| [#107](https://github.com/adamkjonsson/zipline/issues/107) | A decoded record has no name: the type or the name, not both | spec, **new option**, **blocking** |
| [#109](https://github.com/adamkjonsson/zipline/issues/109) | The timestamp rule's "last source element in its span set" is read as per-run | docs |
| [#105](https://github.com/adamkjonsson/zipline/issues/105) | A field narrower or wider than 8/16/32/64 has no `prim:` token | spec, **decided as a "no"** |
| [#106](https://github.com/adamkjonsson/zipline/issues/106) | Is a field-granular decoded stream still a stream? | spec, **moved to `0.18` at Phase 0** |
| [#98](https://github.com/adamkjonsson/zipline/issues/98) | `skipped` does two unrelated jobs, and only one is a break | spec, **deferred from `0.16`** |
| [#103](https://github.com/adamkjonsson/zipline/issues/103) | §Layers still says a derived file is never a mix | spec |
| [#104](https://github.com/adamkjonsson/zipline/issues/104) | `tunnel/{inner,outer}.jsonl` spell the flow key `flow_key` | vectors, process |

**Expect a small `Changed` section and a large `Clarified` one.** Exactly one
entry tightens conformance: #108's floor makes a file carrying a record below the
stream origin non-conformant, and files in the wild carry one — `zpfwire` writes
the SYN record at `isn`, not `isn + 1`. #98 adds a canonical vocabulary word,
which is `Added` and breaks nothing, since the vocabulary is open and a producer
may write `dropped` today. #107 is `Added`. Everything else is `Clarified` or
`Fixed`. Draft the entries in the phase that does the work, not at release —
three releases running have found that this is the part that gets reconstructed
from memory if it is left to Phase 5.

---

## The scope decisions

### 1. #105 ships as a stated "no", not as an option

The issue offers three shapes and declines to pick. Pick the first: `prim:` types
**storage**, a field's true wire width is the decoder's business, and a producer
whose field is 4, 12 or 24 bits widens to the smallest token that holds it.

Two arguments, and the second is the one that decides it. First, the document
already gives exactly this answer one paragraph away, for byte order — "a
fixed-width `prim:` payload is stored **little-endian** … byte-swapped by the
decoder, never by the reader". A width rule that said otherwise would make
`prim:` describe the wire in one respect and storage in the other. Second, the
alternatives cost more than the gap does: a significant-bits option is a new
option for a value no reader can act on, and opening the vocabulary breaks the
width-binds-`payload_len` rule that is the only thing making `prim:` checkable.

**Saying so explicitly is the deliverable**, and it is worth as much here as an
option would be. Today a producer cannot tell whether the silence is a decision
or an omission, and widens in the dark. After this release the widening is
*documented as forced*, which is a different thing from undocumented and
convenient.

### 2. #106 is capped to one reading and one paragraph — and the cap binds

The temptation is to defer it: it is filed as a question, it blocks nobody, and
one of its three readings — a Discontinuity at every seam of a decomposition —
roughly doubles the block count of every field-granular file. Deferring is still
wrong, because **this release ships `label`**, which makes field-granular
decoding a first-class thing the format names. Shipping the naming mechanism
while the document has no verdict on whether such a stream is legal is how a
capability ships ahead of its rule.

**Take reading 1: overlap-by-decomposition is not a non-join.** Adjacency in a
decoded stream asserts that content ran continuously, and a child record that
re-decodes bytes its parent already emitted has withheld nothing — the duty is
about content that *did not reach the output*, and here it reached it twice.

**Ship the second sentence with it, or don't ship the first.** The coverage
predicate declines every pair where `A ≥ B`, which is every parent/child pair and
every pair of siblings citing the same bytes — so a nested field-granular file is
built almost entirely out of pairs the checker is documented as not testing.
"`ConformanceChecker` is clean on 176 records" means *untested*, and the document
should say that at the predicate rather than leaving a producer to infer it from
the `A ≥ B` clause.

**The cap is real.** If reading 1 cannot be stated in a paragraph plus a vector —
if writing it turns up a case where decomposition and withholding are not
separable — it moves to `0.18` and this release ships `label` without it. It
blocks nobody, and #107 is compatible with all three readings by construction.

***Settled in Phase 0: the cap is exercised, and #106 moves to `0.18`.*** Not for
want of time, and not because decomposition and withholding turned out to be
inseparable — they are separable. Because reading 1 is not the cheap reading the
issue prices it as.

The duty as written keys on whether **content ran continuously** from the end of
one unit into the start of the next, not on whether content was withheld. For a
parent and the child carved out of it, it did not: the child restarts *inside*
what was just emitted. So reading 1 is not a clarification of the duty — it is a
**carve-out from it**, and the sentence it needs is not "this pair joins" but
"this pair is exempt".

That has a consequence outside the nested case, which is what decides it. Today
the absence of a Discontinuity between two adjacent decoded records means their
payloads concatenate; a consumer may splice them. Exempting decomposition weakens
that to "they concatenate **unless** one contains the other", and every consumer
of every decoded stream — not only a field-granular one — would have to check
`spans` for containment before splicing. Buying that with one paragraph, in the
release that also ships the option making such files first-class, is the trade
this cap exists to refuse.

`0.18` gets it with the option that Phase 0 could not price and #106 does not
list: an explicit **positive** marker for a decomposing stream, so that the
absence of a block keeps meaning exactly what it means today. That is `0.18`'s
question to weigh against readings 1, 2 and 3 — and it is close enough to #80's
shape (a participant-level statement about what stored adjacency asserts) that
the two should be read together, which scope decision 3 already schedules.

**What ships without it:** `label` on the flat, non-overlapping case, which is
what its vector exercises and what the four-`u32` evidence is. The **nested**
case stays unjudged, and `python-zipline` should hear that in those words — a
clean `ConformanceChecker` on 176 nested records is not the document agreeing
with them.

### 3. #80 stays out, and this is the release that has to say why

[#80](https://github.com/adamkjonsson/zipline/issues/80) — a participant-level
declaration that stored order is not stream order — has been a candidate since
`0.15`, waiting on "a decoder whose output units genuinely never concatenate;
objects carved out of a stream is the shape to watch for". That file has arguably
now arrived: `kober`'s DNS output at field granularity is a pre-order flattening
of a tree with the tree removed, and under #106's reading 2 it would owe ~175
Discontinuities on 176 records.

**It stays out because it is downstream of #106, not because the evidence is
still missing.** Under reading 1 the per-seam duty never fires on those files and
the compression has nothing to compress. Adopting both in one release would mean
adopting a wholesale discharge of a duty this release has just said does not
bind.

**But the deadline in #80 is real and it is getting closer.** The option is not
safe for a reader to skip, so it must land before `1.0` or not at all: a `1.0`
reader meeting an unrecognised option retains it, ignores it semantically, and
splices across a seam — the exact failure it exists to prevent. **Re-decide it in
`0.18`**, not "when evidence arrives"; the evidence question is now settled and
what remains is a design choice with an expiry date.

### 4. `label` already names something else, and the collision is a Phase 0 decision

#107 proposes an option called `label` on Record. Option `0x00B0` is **already**
called `label` — on Name/Identity Resolution, "the human-readable name being
assigned" — and it renders as the JSONL key `"label"` in the annotation example.
Two options, one name, two meanings, both reachable from one file.

Three ways out, and the release must pick one before the registry table is
touched, not while writing it:

- **Let the registry carry two `label`s** distinguished by `applies to`, and make
  the JSONL mapping disambiguate by block. Cheapest in the spec, worst in the
  mapping table, which currently reads as name → meaning.
- **Rename #107's option.** `role` is the closest fit for what the issue actually
  describes — *what this record is within its decoder's vocabulary*.
- **Rename `0x00B0`.** Not an option: it is shipped, it is in a worked example,
  and renaming a shipped option to make room for a new one is the wrong trade.

**Take the rename of the new one unless Phase 0 turns up a reason not to.** The
mapping table's whole job is that a JSON key names one thing.

***Settled in Phase 0: the new option is `role`, at `0x0092`.*** Phase 0 turned up
a reason not to rename — and then a sharper reason to rename anyway.

**The reason not to:** the registry already reuses names across `applies to`
scopes, and more than once. There are **three** `reason` options (`0x00A0`
Undecoded, `0x00C0` Session End, `0x00D1` Discontinuity) and **two** `flags`
(`0x0014` File Header, `0x0052` Session). Two `label`s would not be a new shape
in this registry; it is the shape the registry already has, and the JSONL mapping
resolves it the same way it resolves the others — the block's `type` selects
which option a key means.

**The reason to rename anyway** is what those reuses have in common: each reused
name means *the same kind of thing* in every place it appears. A `reason` is
always why-this-is-so; `flags` is always a bitfield of this block's own flags. The
name is reused where the **concept** is one and the **scope** differs, which is
precisely why reusing it costs a reader nothing.

`label` fails that test in the one way that matters. `0x00B0` is documented as a
**human** name — "map participant ids → human labels", "the human name being
assigned". A reader who transfers that reading onto a Record lands on "a human
note about this record", which is `comment` — the exact confusion #107 exists to
end, arrived at by way of the precedent rather than in spite of it.

`role` transfers correctly, and by the same precedent: `tcp_role` already means
"which of a known set of parts does this thing play", scoped to the protocol that
defines the set. `role` is that at the decoder's scope — *what part does this
record play, in the vocabulary its decoder documents* — which is #107's own
sentence. `0x0092` is free and sits beside `content_type` at `0x0091`, where the
issue suggested it.

Considered and not taken: `field`, which would prejudge #106 by asserting the
granularity the option is deliberately silent about; and `name`, already
overloaded by the decoder `name` that scopes this very option.

### 5. #98 is in, and it is the cut line

`0.16` filed it rather than fixing it, for a stated reason: it is a design change
and folding it into a corrective release would have made three in a row where
corrective and model work landed together. That reason expires with a feature
release. The change is one canonical word — **`skipped`** (withheld; the
survivors join) and **`dropped`** (content removed; they do not) — and its payoff
is that `filtered-decoded` stops being an *example* of #78's duty and becomes a
positive test of it.

It is also the item to cut if the release runs long. It is the only one of the
seven that neither blocks an implementation, corrects a contradiction, nor
belongs to the field-granularity story the rest of the release tells.

### 6. #43, #44 and #45 stay unscheduled

No milestone, no implementation pressure, and none of them is cheaper now than
later. #45 (SCTP) is a feature release of its own. #44 (index block) has a cost
the issue itself states and no demand behind it. #43 (per-session integrity
counts) has lost the pairing that motivated it — #35 shipped in `0.13`.

---

## Dependencies

```
label-name decision (Phase 0) ───▶ #107's registry entry and mapping row

#104's check.py assertion ───▶ #104's vector fix    guard first, then the fix

#106 ── moved to 0.18 at Phase 0, and read there beside #80: both are
        statements about what stored adjacency asserts. #107 ships
        regardless, being compatible with all three readings

#105 ── same section as #107; one edit to §Typing a decoded record

#108, #109, #103, #98   independent of everything, and of each other
```

**#104's assertion before #104's fix**, for the reason #100 went first in `0.16`
and #70 in `0.14`. `check.py` already parses the option-id registry; asserting
that every `.jsonl` key is a registry option name or a listed brevity alias is
mechanical, and it must reproduce the defect from the tree as it stands. If it
does not fire on `tunnel/inner.jsonl` before the fix, the assertion is wrong and
that is Phase 0 work, not a later cleanup.

**#105 and #107 are one edit.** Both land in §Typing a decoded record, both
concern what a `prim:`-typed record can and cannot say about itself, and doing
them in separate phases is how `0.16` ended up adding an isolate-list entry in
one phase and its vector in another.

---

## Phases

### Phase 0 — stamp, tooling, two decisions

1. `MAJOR, MINOR = 0, 17` in `vectors/build.py`; `check.py` to match; regenerate;
   the spec's version sites; open `## [0.17] — unreleased`.
2. Confirm `reject-unknown-minor` rolls 16 → 17 on its own.
3. **#104's JSONL-key assertion**, written and run against the tree as it stands.
   It must report exactly `tunnel/inner.jsonl` and `tunnel/outer.jsonl`.
4. **Settle the `label` name** (scope decision 4). Registry and mapping only; no
   option exists yet.
5. **Settle #106's mandate** (scope decision 2): reading 1, one paragraph, one
   sentence at the predicate, one vector — or it moves to `0.18` now rather than
   in Phase 3 under vector pressure.

Stamp first; every later phase regenerates the tree anyway.

**Expect a red window, and use its shape as the signal.** From step 3 until Phase
4 fixes the two fixtures, `check.py` exits 1 on the JSONL-key assertion. That is
the correct state — the rule exists and the vectors do not yet match it — but it
means green is not a usable signal for Phases 1–3, whose verification is instead
"the failure list holds exactly those two entries and nothing else". `0.14` and
`0.16` both ran this way; `0.16` was the first to say so up front, and it worked.

***Done. Three things Phase 0 found, and one of them changes the release's
shape.***

***The cap on #106 was exercised, and the release is seven items rather than
eight.*** Reading 1 is a carve-out from the duty rather than a clarification of
it, and it would weaken what an *absent* Discontinuity means for every decoded
stream. Reasoning in scope decision 2; the issue is on `0.18`.

***`reject-unknown-minor` rolled on its own, 17 → 18, not 16 → 17 as this
document said.*** The vector stamps `MINOR + 1` — one above whatever version it
ships against — so the release rolling 16 → 17 rolls the vector 17 → 18. Read
back out of the stamped bytes rather than trusting the constant: `version_minor
= 18` at file offset `0x000E`, every other vector at `17`. Coverage baseline
before anything else moved: 37 options, 12 blocks, 22 rules, all exercised, 53
vectors consistent.

***The JSONL-key assertion could not be "every key is an option name or an
alias", which is what #104 proposed and what this plan repeated.*** Written that
way it passes clean on the defect: `flow_key` **is** a registry option name, so a
membership test over the registry sees nothing wrong. The rule the mapping
actually states is one rule plus exceptions — a key is a body field's or a
registered option's canonical name, *except* where the alias table gives it a
shorter one — and "except" is the load-bearing word: where an alias exists, the
alias is the spelling and the binary name is **not** a legal key. So the check
subtracts the aliased binary names from the vocabulary it builds, and that
subtraction is the whole of what catches #104.

Which rows are renames has to be read off the table rather than assumed. Three of
its six rows describe a **rendering** — the version pair as one `format` string,
a flags bit as a boolean — and rename nothing; reading them as renames would
forbid `flags`, a legal key on two blocks. The check takes a row as a rename only
where its right column is a bare binary name with an optional parenthetical,
which is exactly the three that are (`ts`, `pid`, `key`).

It reproduces the defect from the tree as it stands — three sites,
`tunnel/inner.jsonl:4` and `:9` and `tunnel/outer.jsonl:3`, and nothing else —
which is what Phase 0 required of it. Six keys the projection defines
structurally (`type`, the two escapes' `options`/`id`/`value`/`content`, and
`extent` inside an `input_extents` entry) are declared rather than derived, for
the reason `RULES` is declared: they name no binary field and no option, so no
table can supply them.

***One dangling promise, found by reading the paragraph the assertion enforces.***
The alias table's preamble said "one further key, deprecated, is listed below"
and nothing was listed below. The key was `time_units`, removed outright in
`0.10`; the parenthetical has been pointing at nothing for seven releases.
Deleted. A first draft replaced it with a sentence spelling out that the alias is
the only legal spelling — reverted, because that sentence is a **copy** of the
mapping's own "except" rule, and a copy that can drift is what `RETIRED_CLAIMS`
exists to catch. The checker's failure message is where that guidance belongs.

### Phase 1 — #108, the offset floor

The release's blocking finding, and the only one with a live interop hazard: three
defensible reader behaviours on the same bytes, in the offset space the whole
format is built on.

- The MUST in §Referencing the source by stream offset: **a record's `seq_start`
  MUST NOT precede the stream origin** — `isn + 1` where the participant carries
  an `isn`, the first captured byte otherwise. The section already says as much
  for the no-`isn` case; this states it for the anchored one.
- **The reader rule**, which is the half that stops two conformant readers
  disagreeing: such a record is *unplaceable* — zero width at the stream's
  current position, contributing nothing to the extent. That is what a
  `seq_start`-less record already gets, and the only reading that leaves the
  extent usable. Without it the arithmetic yields an extent of 2³²−1 on a file
  whose data ends at 74931.
- **Promote `seq_start = isn + 1`** in the handshake paragraph from prose inside
  a `MAY` sentence to a MUST. It is where the mistake is actually made.
- **The decidability sentence**: the test holds only within the serial-arithmetic
  half-space — a `seq_start` more than 2³¹ below the origin is indistinguishable
  from one above it. A property of the sequence space, not a gap in the rule, and
  worth saying so where two checkers can read it.
- **One negative vector**: a zero-length `syn` record at `isn`, which is the shape
  in the wild. Isolate tier — the file is readable and one record is unplaceable.

***Done. The tier was wrong, and getting it right is most of what this phase
decided.***

***The violation is advisory, not isolating, and the reader rule is what makes it
so.*** This plan said isolate, and so did the issue. But `isolate` is a licence —
"MAY reject the file, or discard the smallest unit it can soundly isolate" — and
handing that licence to a reader here reintroduces exactly the disagreement #108
exists to end: one reader drops the session, another places the record at zero
width, and they disagree about the stream again. The whole point of writing a
reader rule is that there is a right answer; a tier that permits three is the
wrong container for it. `0.16` built the manifest key for precisely this shape —
the file breaks a rule, the reader reports it and accepts, nothing is discarded —
and this is its second user. `advisory-seq-start-below-origin`, accept tier,
`advisory: true`, one violation.

***That falsified a sentence in §Typing, in three places.*** `content_type` at the
transport layer was documented as "the only MUST NOT in this document with that
strength". It is now one of two. The sentence no longer counts — it says the
strength is given where the document can state exactly what a reader does instead,
which is the property that actually decides it — and the old wording is in
`RETIRED_CLAIMS`, verified to reproduce against the pre-edit text.

**The other two copies are outside the specification, where the ratchet cannot
see them:** the vector's summary in `build.py` (which reaches `manifest.json`) and
its row in `vectors/README.md` both said "the only one". Both corrected. Worth
recording as a limit of the mechanism rather than a slip: `RETIRED_CLAIMS` scans
the specification, and a claim can be restated in the suite that illustrates it.

***One thing the issue asserted that the document does not say.*** It offers
zero-width placement as "the treatment a `seq_start`-less record already gets".
No such treatment is stated anywhere — a transport record without `seq_start` has
no defined placement at all. The rule ships on its own terms instead, with the
argument for zero width given rather than borrowed. Copying that appeal to
precedent in would have put a false claim about the document into the document.

### Phase 2 — #107 and #105, what a decoded record says about itself

One section, two edits, in this order.

- **#107** — the new option under whatever name Phase 0 settled: a string on
  Record, **decoded layer only**, **advisory**, **scoped to the record's decoder
  `name`** exactly as `dec:` tokens are, and **opaque to the format** — it names a
  record, it does not assert a tree. The registry row, the mapping row, the
  advisory treatment `content_type` already has, and an accept vector: the
  four-`u32` case from the issue, flat and non-overlapping, which is the case with
  none of the confounders.
- **#105** — the sentence saying `prim:` types storage and the widening is
  forced. Site it beside the width-binds-`payload_len` rule, which is what forces
  it.

The advisory treatment is what keeps the option cheap: dropping the label loses
nothing, the record stays fully readable, and there is no unit a reader could
soundly discard.

***Done. The two edits turned out to be one, and it removed a rule rather than
adding one.***

***The transport-layer bar is now stated once for both labels, not twice.*** The
plan assumed `role` would need its own MUST NOT and its own advisory paragraph,
which would have made a third advisory instance a week after Phase 1 made the
second — and left two copies of one argument to drift apart. But the argument is
identical for both: a reassembly record's boundaries are wherever the reassembler
chunked, so a label on it asserts a unit where there is a slice. So §Typing now
bars *a label* at the transport layer, `content_type` and `role` together, with
one advisory treatment and one vector. `content-type-transport-advisory` in
`RULES` says so; `advisory-transport-content-type` keeps its name and now
exercises the rule for both.

That also left Phase 1's "the other" parenthetical correct as written. Adding a
third instance would have retired the sentence again in the same release that
wrote it.

***#105 shipped as prose beside the width-binding rule, and needs no vector.***
There is nothing to exercise: it adds no capability and states no new obligation.
`RULES` is for permissions a file can demonstrate, so an entry there would have
been a rule with no possible vector — #94's situation, but self-inflicted. It is
recorded in the changelog as *Clarified*, which is exactly what it is.

***One thing the issue's evidence spells differently from this document.*** #107
and #105 both use `cites` for what this format calls `spans`, borrowed from the
implementation that filed them. Worth watching when taking in the remaining
issues: importing an implementation's vocabulary into normative text is how a
document acquires a second name for one thing.

### Phase 3 — #98, the duty question that stayed

#106 moved to `0.18` at Phase 0, so this phase is one item.

- **#98** — `dropped` as a canonical bytes-class word beside `skipped`, its
  registry note, and the checker rule it makes possible: a bytes-class `dropped`
  region lying between the input regions of two adjacent units with no
  Discontinuity is a violation. `filtered-decoded` moves onto `dropped` and
  becomes a positive test; an isolate vector carries the violation.

It does not close the general case and nothing can — the duty rests on producer
knowledge. #98 closes the case #78 was opened for. The case this release's own
new option creates — a nested decomposition — is what #106 will close, and until
it does, that shape is unjudged rather than blessed.

***Done. One vocabulary word, and it moved a rule from one decidable case to
two.***

***The plan called it "the checker rule it makes possible" and sited it wrongly.***
`dropped` does not add a rule beside the duty; it completes the **existing**
single-file predicate, which had exactly one decidable case and now has two. That
is a smaller change than the plan implies and a better-placed one: the predicate
is where a checker looks, the class test and the word test are one condition, and
a checker testing only the class would pass this rule's own title case while one
testing only the word would miss the lost segment. Both clauses now sit in the
one quoted predicate.

***The retired claim was in three places again, and only one of them is text the
ratchet scans.*** "One case is decidable from a single file" is now false;
`RETIRED_CLAIMS` holds it and reproduces it against the pre-edit specification.
The other two copies were `isolate-unmarked-break`'s summary in `build.py` and its
row in `vectors/README.md` — the same pair Phase 1 hit. Two phases, same shape, so
it is worth saying plainly: **a claim retired in the specification is worth
grepping for in `vectors/` before the phase closes**, because the ratchet cannot
see it there.

***Verified with a one-off reader over the bytes, not the projections.***
Ground rule 2 keeps the predicate out of `check.py`, and the two isolate vectors
have no `.jsonl` to read, so the check walked the blocks: `filtered-decoded` fires
and finds its block, `isolate-unmarked-drop` fires and finds none,
`isolate-unmarked-break` is unchanged, and `undecoded-skipped` and `decoded-basic`
stay silent. That silence is the half worth checking — a rule that raised the BOM
case would be worse than no rule.

### Phase 4 — the corrections (#103, #104, #109)

Independent of everything above, and safe in any order once the rules have stopped
moving.

- **#103** — rewrite §Layers' "never a mix" conclusion to state derivation per
  *stream* and point at §Conformance for the discriminator, **and** add the
  `derived-file-is-not-a-mix` entry to `RETIRED_CLAIMS` so it cannot return a
  third time. The pattern has to survive the line wrap between "never a" and
  "mix", which is exactly the case the whitespace-collapsed matching was built
  for. Enter the claim even though the wording is changing — the ratchet holds
  claims, not sentences.
- **#104** — `"flow_key"` → `"key"` in the two `tunnel/` JSONL files and in the
  two example lines in the tunnel walkthrough. Vector-side under ground rule 2:
  the mapping table is unambiguous and `descriptive-metadata.jsonl` already obeys
  it, so the table is not what changes. Phase 0's assertion goes green here.
- **#109** — one sentence after the decoded-record bullet in the timestamp rule:
  where a stage emits several units from one reassembled run, each unit's
  `timestamp` is the completion time of the last input record contributing to
  *that unit*, not to the run. Plus the mirror clause on `ts_first` (`0x0073`),
  which carries the same per-unit/per-run ambiguity at the other end of a unit.

#109 is prose with no vector, and that is correct: it does not change what any
conformant file may contain, only what a reader computes when writing one. What
makes it worth a release slot is that the misreading is already in the reference
implementation's own documentation in three places, including the worked example
every decoder written from it inherits.

***Done, and the red window closed where the plan said it would.*** `check.py` is
green: 56 vectors, 38 options, 12 blocks, 25 rules, 5 retired claims, and the
JSONL-key assertion reports 56 distinct keys across 42 files with nothing outside
the vocabulary the specification defines.

***#104 was two fixes, and the second is the one that lasts.*** The spellings were
a two-line change. The guard was not: written the way the issue proposed — every
key is a registry option name or a listed alias — it passes clean on the defect,
because `flow_key` **is** a registry option name. Phase 0 found that and rebuilt
the check around the mapping's *except* clause instead. Recorded as defect 4 in
`VECTOR-DEFECTS.md`, with the working and non-working forms of the check written
down, since the next person to add a mechanical guard will reach for the obvious
one first.

***#103's fix is one sentence; entering the claim is the durable half.*** It
survived two releases because it is not a restatement of the rule it contradicts
and shares no phrase with it — the exact case `RETIRED_CLAIMS` exists for and the
`0.14` grep could not see. Entered with the wording as it stood, verified to
reproduce against the pre-edit text.

***#109 grew one paragraph beyond the issue's proposal, and it is the paragraph
that says why it matters.*** The issue asked for a sentence pinning the per-unit
reading; the reason the misreading is expensive — ordering by `timestamp` stops
*reproducing* the input's timeline and starts approximating it, because every unit
in a run collapses to one key — was in the issue's body and not in its proposal.
A rule stated without the property it protects is the kind of rule a later editor
trims.

### Phase 5 — changelog, conformance sweep, release

Run `RETIRED_CLAIMS` and the new JSONL-key assertion over the finished release.
Draft `Changed` from the entry written in Phase 1, not from memory.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| #106 expands from one paragraph into a per-seam duty and a `0.18`-sized design | **medium — this release's dominant scope risk** | Scope decision 2 caps it and names the exit: it moves to `0.18` at Phase 0 if it cannot be stated in a paragraph. |
| The new option ships as a second `label` and the mapping table acquires an ambiguous key | medium, cheap now and expensive later | Phase 0 decision, before the registry row exists. |
| `label` is read as asserting a field tree | medium, high cost | The option is opaque by construction; state it in the same paragraph that defines it, not in a note elsewhere. |
| #108's floor is stated and the reader rule is not | medium | They are one bullet list in one phase; the issue enumerates both, and the vector exercises the reader rule rather than the MUST. |
| #98's `dropped` lands in the vocabulary with `filtered-decoded` left on `skipped` | medium | The vector move is what makes it a positive test; without it the entry is decoration. |
| #103's fix lands and the `RETIRED_CLAIMS` entry does not | low, but it is how this survived two releases | Same commit, and the entry is drafted in the issue. |
| The vector estimate is low again | **high — it has been low twice, in the same direction** | Budget 57, expect 58. Every rule and its vector land in the same phase (dependencies, #105/#107). |
| #80 is quietly forgotten after this release declines it | medium | Scope decision 3 schedules the re-decision at `0.18` rather than at "when evidence arrives". |

---

## Definition of done

- [ ] ~~All eight in-scope issues~~ **Seven**, each closed in the commit that
      finishes it. #106 moved to `0.18` at Phase 0 with the reason recorded —
      the cap in scope decision 2, exercised.
- [ ] A record's `seq_start` below the stream origin is a stated violation with a
      stated reader behaviour, the handshake's `isn + 1` is a MUST, and a negative
      vector carries the shape found in the wild.
- [ ] A decoded record can carry both its type and its name, the name is scoped
      to the record's decoder, and no option name in the registry means two
      things.
- [ ] The document says whether a sub-byte field's width is recoverable, so that
      a producer can tell a decision from an omission.
- [x] Either the seam duty's answer for a decomposing stage is stated with a
      vector, or #106 is scheduled with its cap recorded. *The second: on the
      `0.18` milestone, to be read beside #80.*
- [ ] `skipped` and `dropped` are two canonical words with two jobs, and
      `filtered-decoded` is a positive test rather than an example.
- [ ] No statement in the specification implies that a derived file is exactly one
      of a decode stage or a pass-through transform, and `RETIRED_CLAIMS` fails
      the build if one returns.
- [ ] Every `.jsonl` key in the suite is a registry option name or a listed
      brevity alias, enforced by `check.py` rather than by review.
- [ ] The timestamp rule is per unit at both ends of a unit, in words that cannot
      be read as per run.
- [ ] `python3 vectors/check.py` green; every vector stamps `0.17`. ~~*Estimated
      57 entries — 53 today plus #108, #107, #106 and #98*~~ — **56** with #106
      moved, and the estimate has run low twice.
- [ ] `CHANGELOG.md` `[0.17]` complete, with a `Changed` section covering #108 and
      an `Added` section covering #107 and #98.
- [ ] `#80`'s re-decision is on the `0.18` milestone with the deadline argument
      restated, not left as "a candidate".
- [ ] `ruff check` and `ruff format` clean.
