# Release 0.21 — the design release

*Written 2026-09-18 against **`v0.20`**. Sources are the five issues on the
`0.21` milestone — #146, #147, #80, #106, #125 — two of them filed from
`python-zipline-wire` while implementing its `0.3.0`, three of them carried here
from earlier releases with a recorded promise that this is where they get
decided. This is a working roadmap, not normative text.*

*The release is **`0.21`**, not `0.21.0`, per the changelog's Conventions.*

---

## What this release is

**The design release `0.19` and `0.20` each said they were not.** Three of the
five issues are questions the last two plans deferred *with a date*, and the date
is this: #80 and #106 are one Participant-level statement about what stored
adjacency asserts (`0.20` scope decision 1), and #125 is decided with Package D
(`0.20` scope decision 2), whose milestone this now is. The other two are new,
and one of them is a **defect**: a transport stream cannot be placed past 2 GiB
(#146), so an ordinary large download cannot be converted, and
`python-zipline-wire` has hit it.

**It adds one body field, one rule, and no option.** #146 adds a rule to the
offset space — offsets unwrap along stored order — and it is the rule the
document's own arithmetic already implied and never drew. #80/#106 add the first
change to a block body since `0.15`: a `u8` in the Participant Descriptor's
reserved half-word, for the same reason `output_layer` went into the Decoder's.
#147 gets a ruling and a named Session End reason, not syntax. Package D is
**declined**, and #125 is closed with its shape recorded and no deadline.

**The keyword counts will move, and the additions guard is the account.**
`0.20` left them at `MAY 53, MUST 122, MUST NOT 42, SHOULD 27`; this release
expects to add two or three and retire one or two, each with a
`NORMATIVE_ADDITIONS` or `NORMATIVE_REMOVALS` entry saying which sentence and
why. Nothing here should be written to keep a number still.

---

## The five, ranked

| | Issue | What it is | Where it lands | Blocks downstream? |
|---|---|---|---|---|
| **1** | #146 | a stream past 2 GiB is "below the origin"; offsets need an unwrapping rule | §Referencing, two paragraphs; two vectors; `check.py`'s one arithmetic | **yes** — `python-zipline-wire` `0.3.0` refuses the third record |
| **2** | #147 | a consecutive delta ≥ 2³¹ has no representation | a ruling, one paragraph, one named reason, one vector | no — it has a conformant exit today |
| **3** | #80 + #106 | stored order is not stream order; a nested decomposition is not a byte run | Participant body `u8`; §Discontinuity, §Referencing, Enums, JSONL; four vectors | no — but `kober`'s files are unjudged until it lands |
| **4** | #125 / Package D | a third `reason_class`, or a flag; or delete the apparatus | a decision, recorded; no text | no |

Ranked by who is waiting, then by what depends on what. 1 is a defect with a
port stuck on it and goes first; it could be tagged alone. 2 is 1's follow-on and
is decided in the same phase because the ruling is one sentence once 1 is
written. 3 is the release's load-bearing addition and the reason the release is
called what it is. 4 is settled *before* 3 is written, not after — see scope
decision 3 for why the order is forced.

---

## Scope decisions

### 1. #146: offsets unwrap along stored order, and the floor binds each record to its predecessor

The issue has the rule right, and the document already had every premise. A
transport record's position is `seq_start − origin` under serial arithmetic
([:723](zipline-payload-format.md)), the floor is *only decidable within the
serial-arithmetic half-space* ([:745](zipline-payload-format.md)), and the
ordering rule requires per-participant `seq_start` order
([:2425](zipline-payload-format.md)) — which under serial comparison means
consecutive records are within 2³¹ of each other, exactly the range in which
`a − b` is defined. So:

> Record *k*'s offset is record *k−1*'s offset plus the signed serial delta of
> their `seq_start`s (RFC 1982); the first record's offset is its delta from the
> origin — `isn + 1`, or the first captured byte.

**Three things the issue leaves to the text, and this plan settles:**

- **The floor is restated as binding every record to its predecessor, not only
  the first to the origin.** A record serially *below* its predecessor's
  `seq_start` is unplaceable, and the origin is the first record's predecessor.
  That is one sentence where there were two rules, and it makes the existing
  `unplaceable-below-origin` and `unplaceable-no-seq-start` vectors instances of
  the same rule as the new ones. It also closes the inconsistency #146 reports
  downstream — a checker applying no floor without an `isn` — because the floor
  no longer depends on `isn` at all.
- **An unplaceable record does not anchor the chain.** The predecessor in the
  rule above is the last *placeable* record; a below-predecessor record is
  skipped for the purpose of placing what follows, exactly as it is skipped for
  the extent. Without this sentence `unplaceable-below-origin`'s extent is
  ambiguous; with it the declared `16` is the reading.
- **A record below its predecessor is also an ordering violation**, and the two
  rules agree: the reader MAY isolate the session, and a reader that keeps it
  treats the record as unplaceable and SHOULD report it. Neither rule changes;
  §Referencing gains a cross-reference so an implementer sees they are the same
  case.

**It changes no byte of any file and no declared `extent`.** For every stream
under 2 GiB the unwrapped offset equals `(seq_start − origin) mod 2³²` at every
record. What changes is what a reader computes past 2³¹ — a position instead of
*unplaceable* — and what a writer accepts.

**Two vectors, not one, and the second is the one that matters more.** The
issue asks for a stream that passes 2³¹: four records at 1 GiB spacing, and it is
right that no suite has it. But the *commoner* real case is a stream whose
`seq_start` **wraps through 2³²** — any stream does, with probability
`length / 2³²` per random `isn`, which is one in two for a 2 GiB stream and one
in 4096 for a 1 MiB one. No vector wraps today either, and `check.py`'s own
arithmetic would get one wrong: `anchored_ranges` computes
`seq_start − (isn + 1)` as plain integers ([:1417](../vectors/check.py)) and
is the one arithmetic the three pair checks share. So:

- `stream-past-2gib`: `isn` present, four small records at offsets 0, 1 GiB,
  2 GiB, 3 GiB; every neighbour within a window's serial distance; declared
  extent `3 · 2³⁰ + payload_len`. The vector every reader that applies the floor
  against the origin fails.
- `stream-wraps-seq`: `isn = 2³² − 5`, so the origin is `2³² − 4`; the first
  record starts there with eight bytes and the second starts at `4`. Extent 16.
  The vector every reader that subtracts without the modulus fails — including
  `check.py` before this release.

`anchored_ranges` becomes the unwrap rule, and `stream-wraps-seq` is the proof
it did: run the check with the old arithmetic on the new fixture first and see it
fail, per the rule that a guard never seen to fail has not been tested.

### 2. #147: no representation — the honest answer is two sessions, and the option can wait without a deadline

The shape is a hole of 2³¹ bytes or more between two consecutive records of one
participant. The issue offers two representations and asks first whether the
shape deserves one at all. **It does not, in this release, and the reason is not
that it is rare.**

- **The ordering rule already refuses the pair.** Under serial comparison a
  record 2³¹ + *x* past its predecessor *is* 2³¹ − *x* before it; the writer
  MUST NOT emit that, and a reader MAY isolate the session. Either representation
  the issue proposes has to carve an exception into that rule — *ascending,
  except where the record carries `offset`* — as well as add its syntax. That is
  two rules for one shape.
- **The exit that exists is conformant and loses less than it looks.** End the
  session, open another on the same key with no `isn`. The reason vocabulary is
  open, and the connection did not end, so `capture-gap` is the word. What is
  lost is *true position* on the far side — the second session's offsets restart
  at its first captured byte — and nothing downstream can use true position
  across a 2 GiB hole anyway: no decoder resumes a message across it, and no
  span cites into it.
- **The option is safe to add later, and that is the deciding argument.** #80's
  option had to land in `0.x` because a `1.0` reader would skip it and splice
  silently. A `u64 offset` Record option fails *loud* in a reader that ignores
  it: the pair it disambiguates is an ordering violation under serial
  arithmetic, so a reader that does not know the option isolates the session
  rather than misplacing a byte. That is the safe-to-skip property a `1.x` minor
  requires. So the shape's representation can wait for the capture that has it,
  at no cost, where #80's could not.

**What `0.21` does instead:** one paragraph under the unwrap rule saying the
bound and the exit — a consecutive serial delta of 2³¹ or more is not
representable within one participant stream; a producer that knows the hole is
real ends the session and opens another on the same key, and **SHOULD** write
`capture-gap` as the reason so two producers agree on the word. `capture-gap`
joins the row at [:2236](zipline-payload-format.md) and the Session End text at
[:1537](zipline-payload-format.md) beside `capture-end`, with the distinction:
`capture-end` means the capture stopped; `capture-gap` means it resumed and the
stream could not. The SHOULD is a `NORMATIVE_ADDITIONS` entry. One vector,
`session-split-capture-gap`: two sessions on one flow key, the first ended
`capture-gap`, the second with no `isn`, so the shape has a fixture and a reader
sees the repeated key is not a duplicate-id error.

**Record on #147**, when closing it: the `u64 offset` Record option is the
design if evidence arrives, and it is a minor-compatible addition at any time,
including after `1.0`.

### 3. #80 and #106: a body field, `adjacency`, in the Participant Descriptor's reserved half-word

`0.20` sketched the statement and left three things to settle: the name, enum or
flag, and the interaction with `reordered-decoded`. This plan settles a fourth
first, because it decides the other three.

**Body field, not option.** #80's whole deadline argument is that a reader that
retains-but-ignores this statement splices across every seam, silently — the
`0x22` situation verbatim. The document has already answered that shape once, at
[:1401](zipline-payload-format.md): *as an option it would have been not safe to
skip … in the body there is nothing to skip: a reader that parses this block
parses the field*. `output_layer` went into the Decoder's `_reserved` u16 for
exactly this reason, numbered so that every existing file's `0` meant what it
already meant. The Participant Descriptor has the same `_reserved: u16`
([:1469](zipline-payload-format.md)), and the same trade is available at the same
price: free in `0.x`, a major bump after. Taking it now is what `0.x` is for,
and it keeps the Discontinuity block's boxed claim true — *it is the only one
that is not safe to skip* ([:2107](zipline-payload-format.md)) — where an option
would have made it false.

So the body becomes `session_id: u64, participant_id: u16, adjacency: u8,
_reserved: u8`, and no byte of any existing file changes.

**Enum, not flag, and it is the third load-bearing one.** Two values:

| `adjacency` | Meaning |
|---|---|
| `0` = `contiguous` | stored neighbours join — today's semantics, and what every existing file says |
| `1` = `units` | the participant is a **unit sequence**: its offset space is still the stored-order concatenation of payloads plus declared widths, so every record is addressable and citable, but no two adjacent records may be assumed to join |

An enum rather than a bit because an unrecognised value then has an answer the
document already gives: `kind` and `output_layer` are *load-bearing* — a value
the reader does not know leaves it unable to say what the stream's adjacency
asserts, so it MUST NOT guess and MAY isolate ([:2318](zipline-payload-format.md)).
`adjacency` joins that sentence, the JSONL rule at
[:2877](zipline-payload-format.md) says *three*, and the pair of sites becomes an
`ENUMERATIONS` set so a fourth load-bearing enum fails the build at both. In
JSONL it renders `"contiguous"`/`"units"`, **always present** — body fields
always project — which is the cost stated under §Mechanics item 1.

**What `units` changes, stated once in §Discontinuity and referred to elsewhere:**

- *Producer.* The origination duty — emit a Discontinuity wherever two adjacent
  units do not join ([:1936](zipline-payload-format.md)) — is **discharged
  wholesale** by `units`: the participant asserts no join anywhere, so there is
  no seam at which the assertion is false. A reordering stage MAY declare `units`
  instead of a block per seam (#80); a decomposing decoder declares it and owes
  nothing at the seams between a parent and the child carved out of it (#106).
- *Consumer.* The no-splice rule ([:2045](zipline-payload-format.md)) extends:
  a consumer MUST NOT treat any two records of a `units` participant as
  contiguous. The carry duty on a decode stage reading one applies at every
  seam, exactly as it applies at a declared break — a stage whose unit spans two
  input units either declares its own participant `units` or emits a
  Discontinuity where they meet. No third case is invented.
- *Predicate.* The seam predicate's layer test ([:2004](zipline-payload-format.md))
  gains a clause: it does not apply to a `units` participant. That is the honest
  version of what #106 found — the predicate declines every `A ≥ B` pair, and a
  nested file is built out of them; now the file *says* it is exempt rather than
  passing untested.
- *Discontinuity blocks are still permitted* in a `units` participant, because a
  `width` is a term in the positional arithmetic whether or not the no-join
  claim beside it is redundant. One sentence; no rule.
- *Absence keeps today's meaning.* Every stream without `units` asserts that its
  stored neighbours join, which is the property #106's cap was written to
  protect and the reason reading 1 there was refused. The document says this in
  the field's own paragraph, so nobody reads `units` as licence to omit blocks
  elsewhere.
- *Transport layer.* `units` on a transport-layer participant is a **MUST NOT**
  whose violation is **advisory**, in the shape of `content_type` at the
  transport layer: a transport stream's offsets come from sequence numbers, not
  stored order, so the field says nothing there and a reader ignores it, reports
  it, and accepts the file. Not the isolate shape of *Discontinuity in raw*:
  that block contradicts the offsets; this field is merely inert.

**`reordered-decoded` keeps its block.** The per-seam form remains the right
statement for a stream that mostly joins with a seam or two, and the vector's
summary gains a sentence naming the wholesale form. The new vectors are the two
shapes the milestone comment names plus the two the enum owes:

- `unit-sequence-reversed`: a reordering stage's output, `adjacency = units`,
  four records with spans running downward, **no** Discontinuity. Declared
  extent is the payload sum. The vector a reader fails if it applies the
  reordering predicate regardless of the field.
- `unit-sequence-nested`: a decomposing decoder's output — a 12-byte header
  record spanning `[0,12)` of its input, then `flags` spanning `[2,4)`, then
  three one-byte `prim:u8` fields with `role`s each spanning inside `[2,4)` —
  `adjacency = units`, no Discontinuity, extent 17. `kober`'s shape in
  miniature, and the first vector in the suite whose spans overlap by
  containment.
- `isolate-unknown-adjacency`: value `2`; the reader MUST NOT guess; the twin
  of `isolate-unknown-output-layer`.
- `advisory-transport-adjacency`: `units` on a capture-sourced TCP participant;
  `advisory: true`, accepted, reported.

**The name is the one thing Phase 2 may still change, and only before its
first commit.** It will be on every participant line of every JSONL file the
format ever projects, so it is chosen once: it must be a word a reader would grep
for, and it must not overload `order` or `sequenced`, both of which already mean
something here. `adjacency` says what the field is about; `contiguous`/`units`
say what it asserts. A better pair proposed by the port before Phase 2 starts is
taken; one proposed after is not.

### 4. Package D is declined, and #125 closes with its shape recorded

`0.20` put #125 on *whichever milestone decides D*, and this is it. **D is
declined**, which reverses `0.19`'s scope decision 3 (*D-pair is what the goal
requires*), so the reversal is argued rather than assumed:

- **The tree has moved against D twice, with reasons each time.** `0.20`'s
  `isolate-merge-unmarked-hole` is a single-file vector *because* `input_extents`
  makes the uncovered range visible from the output alone, and its changelog
  entry says in as many words that this is *the property Package D-pair would
  trade away* ([CHANGELOG:175](../CHANGELOG.md)). `0.20`'s `extents` key uses the
  `input_extents` entry shape so the suite has one vocabulary for a stream's
  length. `0.19`'s Package A made #133's obligation real, and #133's fixture is
  checkable from one file only through the apparatus D deletes.
- **#106's evidence against the predicate is answered by the field, not by
  deletion.** D-pair's case for dropping the predicate was that no checker
  proves the duty and nested files defeat it. Scope decision 3 makes nested
  files exempt *by declaration*; what remains of the predicate is honest and is
  what `isolate-unmarked-break` and `isolate-unmarked-drop` test. Deleting it
  now would remove two checks an implementation already ships.
- **The cost D was pricing has been paid.** `0.19` recommended D-pair because
  the apparatus was *an opt-in aid, never a guarantee* and deleting it cost
  little. Three releases on, `python-zipline` implements every piece of it, the
  rationale extraction delivered the line-count reduction D was partly for, and
  the seventh goal is served either way. What is left is churn.
- **The order is forced, so the decision cannot wait again.** D rewrites the
  same 130 lines of §Discontinuity that scope decision 3 edits. Taking D after
  this release means writing the field's predicate clause and then deleting the
  predicate; taking D in this release doubles it. `0.20` deferred #125 to avoid
  exactly this churn one release apart. So D is decided now, and *declined* is
  the decision.

**#125 then has its answer, and it is the issue's own:** removal is orthogonal to
recoverability, so when a second removal word is needed it is a **flag beside
`reason_class`**, not a third value in an enum that classifies something else.
It is not built in `0.21`. Nothing is broken, no producer has written a
non-`dropped` removal word, and — unlike #80's field — a flag a checker keys on
is safe to skip: a reader that ignores it reads every byte correctly, so it can
be added as a `1.x` minor when a producer asks. **Closed with the ruling**, not
moved: the shape is recorded here and on the issue, the trigger is a producer
with the word, and there is no deadline to track.

The `0.19` plan's Package D section and the `RULES` comments that anticipate D
(`#117`, `dropped-is-a-break`) stay as written; they are history. #117's
*MUST with no vector* comment in `RULES` stays, since the constraint it records
is now permanent rather than pending deletion.

---

## Mechanics: what is different about this release

**1. A body field is a change every projection sees.** `output_layer` in `0.15`
was the last body change, and it touched 23 decoder lines. `adjacency` touches
every participant: 70 `participant(` calls in `build.py`, 54 participant lines
across the fixtures' `.jsonl` files, and the hand-written `jsonl=` dict beside
every one of them gains `"adjacency": "contiguous"`. That is mechanical, and
`0.20`'s face check is what makes it safe: `participant()` gains the field,
the projector renders the enum, and `vector()` refuses every vector whose
`.jsonl` dict has not been updated, by name, until all 70 agree. The
`ENUMS` table in `build.py` gains the pair. Downstream, every projector and
reader must parse one more byte, which is the point of a body field and is said
in the changelog as a **Changed** line, not Added.

**2. `check.py` gets the unwrap rule, and it is the second place the suite
computes an offset.** Ground rule 2 says `check.py` rules on no semantics, and
the exception is the pair checks, which reconstruct a transport stream's ranges
from `isn` and `seq_start` to verify one file against another.
`anchored_ranges` is that reconstruction, and after this release it is the
unwrap rule — signed serial delta from the last placeable record, origin first.
That is not a second normative authority: it is the suite's reading of one
sentence, tested by `stream-wraps-seq`, and it would have been wrong on the first
wrapped fixture anyone wrote.

**3. The design goes to the port before the text is written.** The milestone
comment on #80 set an entry criterion — *`python-zipline`'s reading of the
option against `kober`'s files* — and this is the first release with an
external gate on a phase. Phase 0 posts scope decision 3 (field, enum, name,
the six consequences) to #80 and #106 and to python-zipline#58, and asks for two
things: whether `units` on `kober`'s DNS participants makes those 176 records a
conformant file under their checker, and whether the name reads. Phase 2 starts
on an answer or after seven days, whichever is first; Phase 1 does not wait.

**4. `NORMATIVE_ADDITIONS` is used as built.** `0.20` built the additions half
of the guard for two keywords; this release brings more. Expected: #147's SHOULD
(`capture-gap`), scope decision 3's MUST NOT (no splice in a `units`
participant), its MAY (a reordering stage MAY declare `units`), and its advisory
MUST NOT (not on a transport participant). Expected removal: the floor's
*only decidable within the serial-arithmetic half-space* paragraph, which
carries no keyword, and possibly one keyword from the two floor paragraphs it
replaces. Each is one entry with its argument; the counts follow.

**5. `RETIRED_CLAIMS`, from a grep done before the edit.** Spellings this release
retires, to be found by grep in Phase 0 and written into entries validated
against `v0.20`: *The floor is only decidable within the serial-arithmetic
half-space* and *more than 2³¹ below the origin is indistinguishable from one
above it* (§Referencing); *Two enums are load-bearing* (§Enums) and *the two
load-bearing enums* (§JSONL); *emits a Discontinuity at each seam* where it is
stated as the only form (§Discontinuity [:1993](zipline-payload-format.md),
§Referencing [:835](zipline-payload-format.md), and `reordered-decoded`'s
summary); and any summary that says the origin floor is applied *against the
origin* for every record. The `unplaceable-below-origin` summary's *places it
near 2**32* stays — it is still what a wrong reader does.

---

## Phase 0 — stamp, the milestone, and the design post

1. `MAJOR, MINOR = 0, 21` in `vectors/build.py` ([:46](../vectors/build.py)) and
   `check.py` ([:71](../vectors/check.py)); regenerate; the spec's version sites;
   open `## [0.21] — unreleased` with `Changed`, `Clarified`, `Added` and
   `Decided` headings — the last is new, is not a Keep a Changelog type, and
   holds scope decisions 2 and 4 so an implementer finds the rulings where they
   look for changes. Add it to the changelog's Conventions in the same commit.
2. Confirm `reject-unknown-minor` rolls 21 → 22, read out of the stamped bytes.
3. Post scope decision 3 to #80, #106 and python-zipline#58 per §Mechanics
   item 3; post scope decisions 1 and 2 to python-zipline-wire#17 as the answer
   to its item 4, with the unwrap rule's text as it will be written, so their
   `0.3.0` can build to it before the tag.
4. Post scope decision 4 to #125 and close it with the ruling. Remove it from
   the milestone; the milestone then holds the four this release changes text
   for.
5. Grep the tree for every spelling §Mechanics item 5 names, **before** any of
   it is edited, and record what the grep found here, as `0.20` did. The
   `RETIRED_CLAIMS` patterns are written from what the grep finds.
6. Run the old `anchored_ranges` against a scratch `stream-wraps-seq` and
   record that it fails, so the Phase 1 fix has a failure to be seen curing.

**What the grep found (Phase 0, 2026-09-18, against `713f622`).** Sites are in
the five files `RETIRED_CLAIMS` scans; line numbers are pre-edit.

*The floor, for Phase 1* — the two spellings the plan named, and the sites
around them that stay:

- spec `:745` — `The floor is only decidable within the serial-arithmetic
  half-space` and `:747–748` — `more than 2³¹ below the origin is
  indistinguishable from one above it`. Both retire; both are the claim #146
  refutes.
- spec `:723` — `**A record below the origin covers no byte of the stream.**`
  Stays true of the *first* record and is rewritten rather than retired: the
  restated floor names the predecessor, and the origin is the first record's.
  Whether the old bold sentence gets a `RETIRED_CLAIMS` spelling is decided
  when the new paragraph is written — if it survives verbatim as the
  first-record case, it is not retired.
- spec `:727` — `returns a number just under 2³²`; `:743` — `trusting the
  wrapped offset`; `build.py:3725` and `README.md:113` — `trusts the wrapped
  offset`. All stay: a reader that trusts the wrapped offset is still wrong.
- spec `:1702` (handshake records) — `isn itself is one below the origin`;
  `check.py:491, :637`; `build.py:3733` — all describe the first-record case
  and stay.
- No site says *serial-number order*: the ordering rule at `:2425` says
  `seq_start order` only, which is the gap Phase 1 closes. No site says
  *against the origin* either — the per-record floor was never spelled out,
  only implied by `:723`.
- The companion's `:88` (*why an unplaceable record sits at a running maximum*)
  argues for a range `0.19` unpinned; it is history and not this release's.

*The enums and the seams, for Phase 2:*

- spec `:2318` — `**Two enums are load-bearing: Source kind and
  output_layer.**` and `:2882–2883` — `For the two **load-bearing** enums`.
  Both retire to *three*; both become `ENUMERATIONS` sites.
- spec `:1993` — `Such a stage emits a Discontinuity at each seam` and `:835` —
  `obliges it to declare at each such seam`. Both gain the wholesale form; the
  retiring spelling is the sentence that states the per-seam form as the only
  one. `build.py:1963–1975` (`reordered-decoded`) says the same in
  `Since 0.15 the seam between the two records carries a Discontinuity`, which
  stays true and gains a sentence.
- spec `:1402` — `the second such case after the Discontinuity block`. A
  historical claim about `output_layer`; it stays, and the new field's note
  refers to it.
- spec `:2107` — `it is the only one that is not`. Stays true under the body
  field, and Phase 2 checks it.

**What the probe found (step 6).** With `isn = 2³² − 5` and records at
`2³² − 4` (8 bytes) and `4` (8 bytes), `check.py`'s `anchored_ranges` returns
`[(0, 8), (−4294967288, −4294967280)]` and an extent of **8**, against the
rule's `[(0, 8), (8, 16)]` and 16. That is the failure Phase 1 cures. The 2 GiB
probe — four records at 1 GiB spacing from `isn = 1000` — comes out **right**
under the plain subtraction, `[(0,8), (2³⁰, …), (2³¹, …), (3·2³⁰, …)]`, because
`check.py` never applied the serial floor at all. So `stream-past-2gib` tests
readers that do, and `stream-wraps-seq` is the one that tests the suite.

---

## Phase 1 — #146 and #147, the offset space (taggable alone)

Per scope decisions 1 and 2. Two commits: the rule and its vectors; then the
ruling and its vector.

**Commit 1, #146.**

- §Referencing: the two floor paragraphs at
  [:723–748](zipline-payload-format.md) become the unwrap rule and the restated
  floor — offsets unwrap along stored order; a record serially below its
  predecessor is unplaceable, the origin being the first record's predecessor;
  an unplaceable record anchors nothing. The *hole-inclusive* paragraph above
  them is unchanged. A cross-reference to the ordering rule, saying a
  below-predecessor record is also out of order and the two rules agree on the
  reader's options.
- §Identifiers & ordering ([:2425](zipline-payload-format.md)): the rule says
  `seq_start` order; it now says **serial-number** order in as many words, and
  notes the consequence the unwrap rule leans on — consecutive records within 2³¹.
- `check.py` `anchored_ranges` ([:1417](../vectors/check.py)) implements the
  rule. The three pair checks are unaffected on their fixtures, all under 2 GiB.
- `stream-past-2gib` and `stream-wraps-seq`, on the accept tier, with declared
  extents; `RULES` gains `offsets-unwrap` naming the first and
  `floor-binds-predecessor` naming the second, or one entry if a rule can name
  only one vector and the second is better carried by the first's summary.
- `unplaceable-below-origin` and `unplaceable-no-seq-start`: summaries and
  `expect` strings reread against the restated floor; both should need a
  sentence, not a rewrite, since their extents do not move.
- `RETIRED_CLAIMS` entries for the two §Referencing spellings, validated against
  `v0.20`. `NORMATIVE_REMOVALS` for any keyword the replaced paragraphs took.

**Commit 2, #147.**

- The paragraph under the unwrap rule per scope decision 2; `capture-gap` in the
  row at [:2236](zipline-payload-format.md) and the Session End text at
  [:1537](zipline-payload-format.md); the SHOULD in `NORMATIVE_ADDITIONS`.
- `session-split-capture-gap`, accept tier, two sessions one key; `RULES`
  gains `session-split-on-unmeasurable-hole` naming it.
- Close #147 with the ruling and the recorded design for later.

Tell `python-zipline-wire` on #17 and `python-zipline` on their unplaceable-floor
issue when commit 1 lands, before Phase 2 — the converter is what is waiting, and
the restated floor is what resolves the checker inconsistency #146 reported.

---

## Phase 2 — #80 and #106, the field

Per scope decision 3, after the Phase 0 gate. One commit for the format, one
for the vectors, or one for both if the face check makes splitting them
impossible — it may, since the field's JSONL projection changes every vector.

**The format.**

- Participant Descriptor ([:1465](zipline-payload-format.md)): the body table,
  and a paragraph in the shape of the Decoder's boxed note at
  [:1401](zipline-payload-format.md) saying why a body field, referring to that
  note rather than restating its argument. The `units` paragraph: what it asserts,
  what absence asserts, the transport-layer advisory.
- §Enums ([:2318](zipline-payload-format.md)): the field's values; *three* enums
  are load-bearing. §JSONL ([:2877](zipline-payload-format.md)): the rendering,
  always present, *three*. `ENUMERATIONS` gains `load-bearing enums` with
  members `kind`, `output_layer`, `adjacency` anchored at both sites.
- §Discontinuity: the six consequences, in the order scope decision 3 lists
  them, placed where each duty is stated — the producer's at
  [:1936](zipline-payload-format.md), the reordering paragraph at
  [:1989](zipline-payload-format.md), the predicate at
  [:2004](zipline-payload-format.md), the consumer's at
  [:2045](zipline-payload-format.md). The boxed note at
  [:2107](zipline-payload-format.md) is unchanged and is checked to be still true.
- §Referencing: the *This is the definition* paragraph
  ([:757](zipline-payload-format.md)) gains one sentence — the definition holds
  for a `units` participant unchanged — and the reordering paragraph at
  [:827](zipline-payload-format.md) names the wholesale form beside the per-seam
  one. §Terminology gains **unit sequence**, pointing at the field.
- §Conformance: the semantic-violation list gains the unrecognised value; the
  advisory list gains `units` at the transport layer.
- `NORMATIVE_ADDITIONS`: the MUST NOT, the MAY, the advisory MUST NOT, each
  with its argument. `RETIRED_CLAIMS`: the *two enums* spellings and the
  *at each seam* spellings, validated against `v0.20`.

**The suite.**

- `build.py`: `participant()` gains `adjacency: int = 0`; `ENUMS["adjacency"]`;
  the projector renders it; every `jsonl=` participant dict gains the key —
  run the build, and let the face check list the 70 that have not.
- The four vectors of scope decision 3, with `RULES` entries
  `unit-sequence-discharges-seams`, `unit-sequence-decomposition`,
  `unknown-adjacency-isolates`, `adjacency-transport-advisory`.
- `reordered-decoded`'s summary: one sentence naming the wholesale form; its
  block stays.
- `vectors/README.md`: the field in the participant description, the four rows.

**Validate the projector the way `0.20` did:** set one vector's dict to
`"units"` where the bytes say `0` on a scratch copy and see the build refuse it.

Then answer #80 and #106 with the field's final text and close both. #80 was
deferred four times, the last with a date, and lands here; the closing comment
says so.

---

## Phase 3 — changelog, downstream, tag

1. `CHANGELOG.md` `[0.21]`: `Changed` (the unwrap rule, with the sentence that no
   extent moves under 2 GiB; the Participant body, with the byte that changed
   meaning and the JSONL key every participant line gains); `Clarified` (the
   restated floor; serial order named in the ordering rule); `Added`
   (`capture-gap`; the seven vectors by name; the `ENUMERATIONS` set); `Decided`
   (#147's ruling and the design held in reserve; D declined and #125's shape).
2. `README.md` gains its `RELEASE-0.21-PLAN.md` line beside `0.20`'s.
3. Tell all three implementations before the tag: `python-zipline-wire` on
   #146/#147 (they were told at Phase 1; confirm nothing moved);
   `python-zipline` on the field, the projection change, and the restated floor;
   `kober` — through python-zipline#58, where it was filed — that `units` is the
   declaration its DNS output makes. None should learn a body field from the diff.
4. Tag `v0.21` on the merge commit, where `v0.20` sits.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The unwrap rule is written so that an unplaceable record anchors the next one, and two readers disagree on `unplaceable-below-origin`'s extent | **high — it is the natural first draft** | Scope decision 1's second bullet is a sentence in the rule, not a note; the declared `16` is the test |
| `stream-past-2gib` is written and `stream-wraps-seq` is not, because the issue named only the first | medium | Both are in scope decision 1 with the probability argument; Phase 0 step 6 makes the wrap fixture the one with a recorded failure to cure |
| The field's name is changed after Phase 2's first commit, re-churning every participant line | medium | The gate: the name is settled with the port in Phase 0; scope decision 3's last paragraph says when it stops being negotiable |
| `units` is read as licence to omit Discontinuities on ordinary streams | medium | The field's paragraph states what absence asserts; `reordered-decoded` keeps its block and says why |
| The carry duty on a `units` input is under-specified and a downstream stage silently splices | medium | Scope decision 3's consumer bullet: every seam is a break for the carry duty, no third case; `unit-sequence-nested`'s summary states it |
| `python-zipline` objects to declining D with a cost figure | low–medium | The decision is posted on #125 in Phase 0, before Phase 2 writes against the predicate; an objection with evidence reopens it *then*, when D could still go first, not after |
| The face check refuses all 70 participant dicts at once and the fix is done with a blind substitution that lands `"contiguous"` on the two vectors meant to say `"units"` | medium | The four new vectors are written *after* the substitution, not before, and the scratch-copy validation in Phase 2 is the check that the projector sees the difference |
| The advisory-versus-isolate choice for `units` on a transport participant is argued the other way mid-flight | low | Scope decision 3 gives the test — does the field contradict the offsets or merely say nothing — and the precedent for each answer |
| The release grows a `u64 offset` option because #147's ruling feels thin next to #146's rule | low | Scope decision 2's third bullet: it is safe to add at any time, so the only thing waiting costs is nothing |
| A new keyword arrives without an entry and the guard goes red | medium | It is one table entry away; §Mechanics item 4 lists the expected ones so the entry is written with the sentence |

---

## Definition of done

The four:

- [x] §Referencing states the unwrap rule and the predecessor-bound floor;
      `stream-past-2gib` and `stream-wraps-seq` exist with declared extents;
      `anchored_ranges` implements the rule and was seen to fail the wrap
      fixture before it did; the ordering rule says *serial-number order*.
- [ ] The bound and the exit are stated under the rule; `capture-gap` is in
      the row and the Session End text; `session-split-capture-gap` exists;
      #147 is closed with the ruling and the reserved design. *(All but the
      closing comment, which waits for the merge to `main` — a port that read
      it and pulled `main` would find nothing.)*
- [ ] The Participant body carries `adjacency: u8`; every existing `.zpf` is
      byte-identical and every participant `.jsonl` line carries
      `"adjacency"`; the four vectors exist; `ENUMERATIONS` has the
      load-bearing set at two sites; `reordered-decoded` keeps its block; #80
      and #106 are closed with the field's text. *(All but the closing
      comments, which wait for the merge.)*
- [x] #125 is closed with the ruling; the reversal of `0.19` scope decision 3
      is recorded here and on the issue.

Release:

- [x] `python3 vectors/check.py` green; every vector stamps `0.21`;
      `reject-unknown-minor` rolled to `0/22` out of its own bytes. **62
      vectors, 35 options, 34 rules** — the numbers the plan expected.
- [x] Every keyword the release adds or retires has its `NORMATIVE_ADDITIONS`
      or `NORMATIVE_REMOVALS` entry; every retired spelling reproduces against
      `v0.20` and is absent now. *(Four additions, no removals: the split is
      `v0.18` less 23 removals plus 6 additions — MAY 54, MUST 124, MUST NOT
      44, SHOULD 28. The replaced floor paragraphs carried no keyword.)*
- [x] `ruff check` and `ruff format` clean.
- [x] `CHANGELOG.md` `[0.21]` dated, with a `Decided` section and the
      Conventions line that admits it.
- [ ] All three implementations told before the tag.
- [ ] Tag `v0.21`, on the merge commit, where `v0.20` sits.

---

## What execution changed

*Written 2026-09-18, at the end of Phase 3's pre-merge half. To be completed
at the tag.*

**The gate was waived, on the day it was set.** §Mechanics item 3 made Phase 2
wait for `python-zipline`'s reading of the field against `kober`'s files, or
seven days. The design was posted in Phase 0 and Phase 2 was started the same
afternoon, by decision — the port's answer is still wanted, but it is now a
review of shipped text on a branch rather than of a proposal, and the name is
correspondingly harder to change. The risk table's *name changed after Phase
2's first commit* row is therefore live rather than mitigated; if the port
proposes a better pair before the merge, the substitution is one scripted pass
over 58 dicts and two `ENUMS` labels, and the churn is on this branch only.

**Phase 1 found what Phase 0's probe predicted, and one thing it did not.**
The wrap fixture failed `anchored_ranges` as recorded and passed once the rule
was in. What the plan had not said is that the *first* draft of the floor
paragraph read wrong once the delta was signed — *the modular subtraction
reports neither* describes the unsigned mistake, not the rule — and had to say
so. Small, but it is the kind of sentence a port quotes.

**One slip the house rule caught late.** The first draft of the two
`unit-sequence-*` vectors derived their `.jsonl` lines from the same tuples as
their bytes, through a helper — which is the single-sourcing `0.20` refused,
because the hand-written face is the second opinion that gives the face check
its meaning. It was rewritten by hand before the commit. The helper was
convenient, and convenience is exactly how the second opinion goes away.

**The face check did the work §Mechanics item 1 assigned it.** 58 hand-written
participant dicts lagged the body field, the build refused at the first and
named it, one scripted pass added the key after `pid`, and the build then
passed with no `.zpf` byte changed — 59 `.hex` annotations and 44 `.jsonl`
files. It was then seen to refuse a face claiming `units` against bytes saying
`0`, on a scratch copy, before the vectors that say `units` for real were
written — the order the risk table asked for.

**The numbers landed where the plan put them**: 62 vectors, 35 options, 34
rules; four keywords added (one SHOULD, one MAY, two MUST NOTs), none retired.
The Phase 3 items — closing #147, #80 and #106 with their text, telling the
three implementations, the README line, the date, the tag — wait for the merge.

**The sweep found three releases of drift in one place the guards did not
reach.** The byte-level worked example stamped `version_minor = 18` in its
bytes and its annotation — through `0.19`, `0.20` and this release's own stamp —
while the README called `raw-minimal` *identical* to it. A stamp touches every
other copy of the version mechanically; this one is hand-maintained prose inside
a code fence, which is why no `RETIRED_CLAIMS` spelling, no anchor check and no
count could see it. The status blockquote's history stopped at `0.18` and its
renumbering note said *`0.10` through `0.18`*; the numbering example used
`0.18`; the vectors README's first line said `0.20`, the very line `0.20` had
found saying `0.18`. `check.py` gains `check_worked_example`, comparing the
example's offset and hex columns to `raw-minimal.hex` line for line, seen to
fail on the pre-sweep text before it was trusted. The rest of the sweep was
this release's own debt: twelve JSONL examples with participant lines lacking
the field that always projects, the worked example's participant still
annotated as a reserved u16, the block table's row, the *fixed body* sentence,
and one summary calling `output_layer` the second load-bearing enum with no
third named.

**Remaining, and gated on the merge to `main`:** the closing comments on #147,
#80 and #106 with their final text; the three implementation notices; and the
tag, on the merge commit, where `v0.20` sits.
