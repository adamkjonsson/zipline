# Release 0.13 — implementation plan

*Written 2026-08-03 against **v0.12** and the nine issues carrying the `0.13`
milestone. Line references are to `docs/zipline-payload-format.md` at v0.12.
This is a working roadmap, not normative text: it says what to change, in what
order, and what "done" means. Where it proposes syntax, the proposal is a
starting point for drafting, not a decision already taken.*

---

## What is in the milestone

| Issue | Title | Label | Verdict |
|---|---|---|---|
| [#35](https://github.com/adamkjonsson/zipline/issues/35) | Record input stream extents on Session End | spec | **In** — after C2 |
| [#36](https://github.com/adamkjonsson/zipline/issues/36) | `transform_params_digest` on the File Header | spec | **In** |
| [#37](https://github.com/adamkjonsson/zipline/issues/37) | Record that a file's bytes were re-stamped | spec | **Out** — close, replaced by one sentence |
| [#38](https://github.com/adamkjonsson/zipline/issues/38) | Three vectors omit `produced_by`/`produced_at` | vectors | **In** |
| [#39](https://github.com/adamkjonsson/zipline/issues/39) | Enforce "one violation per negative vector" | vectors | **In** |
| [#40](https://github.com/adamkjonsson/zipline/issues/40) | Add a broken-chain fixture | vectors | **In** |
| [#41](https://github.com/adamkjonsson/zipline/issues/41) | Decrypted tunnels | spec | **Split** — C1/C2/C3 in, F0/F1/F2 to 0.14 |
| [#42](https://github.com/adamkjonsson/zipline/issues/42) | Require `sequenced_basis` on every `SEQUENCED` session | spec | **Out** — defer to 0.14 |
| [#47](https://github.com/adamkjonsson/zipline/issues/47) | Opaque `external_session_id` on the Session Descriptor | spec, vectors | **In** |

Net: six issues ship whole, one ships in part, two move out.

---

## The three scope decisions

These are the only judgement calls in the release. Everything after them is
execution.

### 1. #41 splits; it does not ship or slip as a unit

The milestone makes tunnels conditional on "three pending design questions"
resolving. [ISSUE_41_ANALYSIS.md](ISSUE_41_ANALYSIS.md) answered them, and the
answer is that #41 was never one thing. Three of its parts are general
corrections justified by cases with **no tunnel in them**, and the
tunnel-specific remainder is prose-heavy and reverses documented decisions.

| Part | Ships | Why |
|---|---|---|
| **C1** — byte-transforming decode legal; `spans` means correspondence, not identity | 0.13 | Corrective. `vectors/chain/` already ships a decoder that synthesises bytes while line 806 says decoders only frame. The specification currently contradicts its own conformance vector. |
| **C2** — session fan-out permitted | 0.13 | Required by HTTP/2, no tunnel involved. **Hard dependency of #35** (below). |
| **C3** — declared-discontinuity block, width optional | 0.13 | Closes a live silent-corruption path in `raw → tls-records → http`, the specification's own flagship chain. Justified without tunnels. |
| **F0** — provenance and layer as independent axes | 0.14 | Rewrites the conceptual model, goals, terminology and conformance. |
| **F1** — sessionization stage as a reassembly decoder | 0.14 | Depends on F0; reverses decisions 3 and 4; the one item carrying new syntax for its own sake. |
| **F2** — tunnel worked example and fixtures | 0.14 | Follows F1. |

**Action:** split #41 into six tracking issues (or one per band), re-milestone
C1/C2/C3 to 0.13 and F0/F1/F2 to 0.14, and leave #41 itself as the umbrella.
Closing #41 in 0.13 would misreport what shipped; leaving it whole in 0.13 would
drag F0/F1 in with it.

### 2. #42 leaves the milestone

Its own text answers the question: the gap is "reduced legibility, not a
correctness trap", and the fix "adds an obligation to files that are conformant
today". It is labelled a candidate awaiting evidence, and no evidence has
arrived. Meanwhile 0.14 already carries F0/F1, which change what existing files
mean — batching the compatibility break there costs implementers one migration
instead of two.

**Trigger to reconsider:** a report of a real consumer misreading a
partially-hinted `SEQUENCED` session. Absent that, revisit with 0.14.

### 3. #37 is closed, not deferred

Transcoding is not worth building machinery for while the format is pre-1.0, and
the reason is stronger than cost: **there is no regime in which the proposed
option is the right tool.**

| Regime | What re-stamping is |
|---|---|
| `0.x` — now | Discouraged by the format's own position. A reader MUST reject a `version_minor` it does not implement, and a file that still matters is regenerated from its capture. |
| `1.x` minor | **Unnecessary.** A reader MUST NOT gate parsing on `version_minor`, so a `1.1` file already reads under `1.3`. Nothing to re-stamp. |
| Major bump | **Insufficient.** The frame or a block body may change, so the header cannot simply be re-labelled — the file is rewritten, which is a genuine transform with genuine provenance (the pass-through machinery), not a File Header flag. |

The issue's hard part confirms this. "Adding a required option the new version
requires, where the old version's own rules determine its value" is a transcoding
*specification*, one rule per version pair, growing without bound — and it is
being asked for in the one regime that says not to transcode at all.

**Replace it with one sentence in the spec.** The disposability position lives
only in `CHANGELOG.md` today (lines 24–27); the specification's own version-numbering
prose (1039–1055) never states it. Say there that a writer stamps the version it
implements, that re-stamping an older file's bytes is out of scope while
`version_major` is `0`, and that a file which still matters is regenerated from its
capture. That closes the honesty gap — a re-stamped file otherwise claims to be
something it is not — without syntax, and it stops the question recurring, which
is what [Design decisions not taken](zipline-payload-format.md) exists for.

**Two follow-ups this creates:**

1. **[CHANGELOG.md:131](../CHANGELOG.md) must be corrected.** The `0.11` entry
   promises "A way to record a version re-stamp is planned for `0.13`, as a File
   Header option rather than a transform; until then there is none." Leaving it is
   precisely the stale forward reference the move-to-issues commit set out to end.
   Amend it in the `0.13` release notes rather than editing history: state that
   the plan was dropped and why.
2. **Close #37 with the reasoning**, do not re-milestone to 0.14. The argument is
   about regime, not timing, so a milestone move would only re-litigate it.

---

## Dependencies

```
C1 ─┐
    ├─▶ C3 (correspondence semantics must be settled before a discontinuity
C2 ─┤        block can say what it interrupts)
    └─▶ #35 (extents must be qualified by (source_id, session_id, pid) and
             repeatable IF fan-out is legal — otherwise #35 reopens later)

#47, #36        independent of everything, and of each other
#38             independent; do it first, it is a two-line fix
#39             independent of the spec work; touches manifest + check.py
#40             independent; new fixture only
version stamp   blocks all vector regeneration — do it once, first
```

The only sharp edge is **C2 before #35**. If extents ship keyed on
`(source_id, pid)` alone and fan-out then becomes legal, one input stream
feeding several output sessions has no way to state its extent once per
consumer, and #35 has to be reopened and re-specified. Do C2 first even though
it is prose-only and looks lower-priority.

---

## Phases

### Phase 0 — stamp and scope (half a day) — **done**

1. `vectors/build.py` — a single `MAJOR, MINOR = 0, 13` plus
   `FORMAT = f"zipline-payload/{MAJOR}.{MINOR}"`, read by `file_header()`, all 18
   JSONL `format` strings and the manifest header. The version was spelled in 21
   places; now it is spelled once and `0.14` is a one-line change.
2. **`reject-unknown-minor` must move off `13`.** It stamped `minor=13`
   *precisely so a `0.12` reader would reject it*. At `0.13` that file becomes
   valid and `check.py` fails it — "claims the reject tier but walks cleanly". It
   now derives `MINOR + 1`, so it keeps testing an unimplemented minor at every
   future bump. **Any release that bumps the stamp must check this vector.**
3. `vectors/check.py` — `MAJOR, MINOR = 0, 13`.
4. #38 — `produced_by`/`produced_at` on `undecoded-skipped`,
   `undecoded-reason-class` and `isolate-coverage-gap` (see its item below); done
   here so those three regenerate once, not twice.
5. Regenerate every vector; `python3 vectors/check.py` green.
6. Spec — **eight sites, not one**: the title (1), the status block (3, 13–14),
   five JSONL examples (199, 401, 478, 869, 907), the `version_minor` row (1020),
   the "twelfth minor" prose (1034), and the worked-example hexdump (2062).
   That last one is load-bearing: the 196-byte example is byte-for-byte
   `raw-minimal`, independently confirmed by a second implementation, so the
   hexdump and the vector must move together. Re-verify after regenerating.
7. `README.md` (54, 63) and `vectors/README.md` (5). Delete the latter's
   `Errata against v0.12` block — #38 closes all three of its rows.
8. `CHANGELOG.md` — open an `## [0.13] — unreleased` section, and repoint the
   `[Unreleased]` compare link at it.
9. `docs/VECTOR-DEFECTS.md` — mark both defects fixed. Defect 2 was already
   fixed in the tree by `a52c717`; only its status was stale.
10. Split #41 and un-milestone #42 per the decisions above. Milestone `0.14`
    already exists (see [Issue tracker](#issue-tracker)).

**Not every `0.12` in the tree is a stamp.** Several name the version that
*introduced* a rule — `build.py` 703 and 736, `vectors/README.md` 119,
`README.md` 99, and every `CHANGELOG.md` section below `[0.13]`. Sweeping them
would falsify the record. Grep for residuals and classify each hit.

Do this **first**, not last. Every subsequent vector change regenerates the
files anyway; bumping at the end means one large mechanical diff landing on top
of the substantive ones, which is where review attention goes to die.

### Phase 1 — corrections with no new syntax (C1, C2) — **done**

Prose only. No option ids, no vector regeneration beyond Phase 0. Shipped as #50
and #51; C3's shape was also settled here, as the risk table required.

### Phase 2 — additive options (#47, #36, #35) — **done**

Each is one option plus its touch list. #35 last, after C2 is settled. Also here:
the one-sentence disposability statement replacing #37 — prose, no touch list.

Note the touch list won over the phase list: each option's **vector shipped with
it**, not batched into Phase 4. Missing one of the seven is how the `0.12` defects
happened, and the checklist only works if it is applied whole.

### Phase 3 — the one new block (C3) — **done**

The only genuinely new syntax in the release, and the only item that could slip
without taking anything else with it. It did not. Shape settled in Phase 1 as a
new block type `0x22`; #45 was checked before minting and does not overlap.

### Phase 4 — vectors (#38, #39, #40, plus one per new feature) — **done**

#38 moved to Phase 0, and the per-feature vectors to Phase 2, so this phase was
#39 and #40 alone.

### Phase 5 — changelog, conformance sweep, release — **done**

The sweep was not a formality: it found six vectors added in Phases 2–4 and never
listed in `vectors/README.md`, and a README row still describing
`reject-unknown-minor` as stamping `13` after Phase 0 made it derive `MINOR + 1`.

---

## Item detail

### C1 — `spans` means correspondence

**Change.** Line 806 ("a decoder *frames* — it assembles raw bytes into one
logical unit and marks its edges") widens: a decoder MAY emit bytes that do not
appear in its input, at a different length. Line 1344's `bytes exist`
recoverability class stops promising a consumer can fetch *the* bytes behind a
span; it promises the bytes of the region the span *corresponds to*.

**Why it cannot wait.** `vectors/chain/decoded.zpf` emits `RESP:200` (8 bytes)
spanning 16 input bytes. The specification and its own conformance vector
disagree today, and `vectors/check.py` never noticed because it verifies
coverage of ranges, never payload-to-span correspondence.

**Also needed:** one sentence at line 802 noting the reproducibility contract
holds for a key-gated stage only for a key-holder — verification of the digest
chain is unaffected, third-party regeneration is not possible.

**Touch points:** 806, 802, 1344, 1283–1284.
**Vectors:** none new. Consider a comment in `chain/` recording that its decoder
synthesises deliberately.
**Done when:** a reader of line 806 alone would build the shipped chain vector.

### C2 — session fan-out

**Change.** One input participant stream MAY feed several output sessions in one
decode stage. Today nothing forbids it outright and nothing permits it, which is
the worst of both.

**Touch points:** the coverage guarantee at 1715 (already stated per input
participant stream, so it survives — confirm and say so), the offset-space rules
at 707–716, Conformance 1704–1745.
**Vectors:** one accept-tier fan-out vector (one raw stream → two decoded
sessions, coverage complete across both).
**Done when:** an HTTP/2 decode stage is expressible and its coverage checkable.

### C3 — declared discontinuity

**Change.** A stage states a discontinuity in its **own** output space. Width
optional: absent = unknown width (TLS lost a record, plaintext length
unknowable), present = a real hole of known width (QUIC STREAM offsets).

The positional range rule at 718–732 gains one term:

```
record k occupies [ Σ(preceding payload_len + preceding declared widths), + payload_len )
```

**Shape — DECIDED in Phase 1: a new block type (`0x22`).** Build it in Phase 3.
The rejected candidate is kept because the question will recur.

| Candidate | For | Against |
|---|---|---|
| **New block type (`0x22`)** — **chosen** | unambiguous; no overload of Record semantics | one more block type readers must skip correctly — already a MUST, and `escape-unknown-block` tests it |
| Zero-payload Record + a free `flags` bit + width option `0x0074` | reuses ordering, positional and stored-order machinery; zero-length records already exist for pure ACKs | a Record that is not a record; every "records concatenate" statement needs an exception |

The deciding argument is the *Against* column, not the *For*: the block type's
cost is a skip readers already owe, tested by an existing vector, while the
Record overload's cost is an exception clause on every statement about records
concatenating. C1 has just widened what a record's bytes may be; overloading what
a record *is* on top of that compounds the reading burden in the same release.

It must be a **block**, not a bare option: its meaning is positional and stored
order defines offsets, so it has to interleave with records.

**Do not overload Undecoded (`0x21`).** Its body fields are all defined as
reading against the *input*, and it is deliberately byte-identical to a `spans`
entry (1324–1332). A discontinuity is a statement about the *output*.

**Watch:** E's clean answer may be the transport-neutral position hint that SCTP
([#45](https://github.com/adamkjonsson/zipline/issues/45)) also wants, rejected
in 0.10 under "Transport-neutral ordering hints". Check before minting.

**Vectors:** two accept-tier — unknown width, known width. One isolate-tier: a
decoder parsing across a declared discontinuity.
**Done when:** the `raw → tls-records → http` splice of Finding 3 is expressible
and a checker can see it.

### #47 — `external_session_id`

**Proposed id:** `0x0054`, bytes (opaque), Session Descriptor, single-valued.
`0x0050`–`0x0053` are taken; `0x0054` is free.

**Value type is `bytes`, not `string`.** The issue's examples span UUIDs (16
binary bytes), SHA-256 (32), URNs and arbitrary correlation strings. `bytes` holds
all of them; `string` forces a UUID to be spelled, which invites two spellings of
one id. JSONL projects it as base64, consistent with `payload`.

**Also:** the birthday-arithmetic note the issue asks for, in the Session
Descriptor prose — 2^32 ids is a 50% collision chance in a 64-bit space, ~6
million for one-in-a-million. This is guidance for *external* id choice, not a
constraint the format enforces.

**Do not touch `session_id`.** The issue already records why narrowing it to
u16/u32 was rejected.

**Vectors:** one accept-tier carrying a 16-byte UUID.

### #36 — `transform_params_digest`

**Proposed id:** `0x0015`, string, File Header, single-valued. `0x0010`–`0x0014`
taken.

**Scope it precisely.** It records the configuration of a transform that
produces records **without decoding** — a filter, a reordering stage, a merge.
A decode stage already has `params_digest` per Decoder (`0x0043`), and a file may
legitimately carry both: a filter over a decoded input has an inherited
`decoder_id` (whose descriptor carries the decoder's digest) *and* its own
filter config.

**Note for 0.14.** Decision 5 of the #41 analysis gives reassembly a Decoder
Descriptor and therefore a `params_digest`. If #36 lands as a general
per-transform digest, check at F1 drafting time whether the two mechanisms
overlap; the choice should be deliberate rather than by arrival order. Nothing
blocks #36 now.

**Vectors:** extend the existing `reordered-decoded` vector rather than adding
one — it is exactly the transform whose config had nowhere to live.

### #37's replacement — state disposability in the specification

**Change.** Add to the version-numbering prose (1039–1055) that a writer stamps
the version it implements; that re-stamping an older file's bytes is out of scope
while `version_major` is `0`; and that a file which still matters is regenerated
from its capture, not transcoded.

**No option id, no vector, no `build.py` helper.** This is the whole of the work.

**Touch points:** 1039–1055. Optionally a row in *Design decisions not taken*
recording why the File Header option was dropped — the table's purpose is that a
reader wondering why the format does not do something finds the answer where the
question arises, and "why can't I re-stamp a 0.12 file" is exactly such a question.

**Done when:** the position is readable from the specification alone, without
consulting the changelog.

### #35 — input stream extents on Session End

**Proposed id:** `0x00C1`, packed, Session End, **repeatable**. `0x00C0`
(`reason`) is the only Session End option today.

**Entry layout**, mirroring the span-list convention so the u64s stay 4-byte
aligned:

```
source_id: u16, pid: u16, session_id: u64, extent: u64
```

`extent` is the length of that input participant stream in its own offset space.
Repeatable because a decode stage reads several input streams per output session
— and, once C2 lands, because one input stream may feed several output sessions.

**Two things this must not get wrong:**

1. **Add it to the closed repeatable list.** Line 1489 states "the repeatable ids
   are `endpoint` and `spans` — a closed list; any future repeatable id MUST be
   added to it." Miss this and the option is silently single-valued.
2. **It does not depend on [#43](https://github.com/adamkjonsson/zipline/issues/43).**
   The issue's rationale says Session End "already contains per-session integrity
   counts" — it does not; Session End carries `reason` and `comment` only, and
   integrity counts are unscheduled. The placement argument still holds on its
   own (declare-on-first-use means the Participant Descriptor is written before
   the extent is knowable), but #35 must be drafted to stand alone.

**Why on Session End at all:** a live decode cannot know a stream's extent when
the Participant Descriptor is written. Session End is the moment the writer
already knows.

**Vectors:** extend `decoded-basic` with extents, and add one isolate-tier
vector where the declared extent exceeds what the spans plus Undecoded blocks
cover — the silent-truncation case that motivates the issue.
**Done when:** `check.py`'s chain coverage arithmetic can be stated against the
file itself rather than against a sibling file it happens to have.

### #38 — three vectors omit `produced_by`/`produced_at`

Straight fix: add both options to `undecoded-skipped`, `undecoded-reason-class`
and `isolate-coverage-gap` in `build.py`, matching `decoded-basic`. Regenerate
`.zpf`/`.hex`/`.jsonl`. Update `docs/VECTOR-DEFECTS.md` to mark defect 1 fixed.

Note the two tiers fail in opposite directions — the two `accept` vectors fail a
*correct* reader, and `isolate-coverage-gap` passes an *incorrect* one — so this
is worth doing in Phase 0 alongside the stamp, before anything else regenerates
these files.

### #39 — one violation per negative vector

**Design.** `manifest.json` gains a per-vector `violations: int`. `check.py`
asserts the declared count agrees with the declared tier:

| Tier | Required `violations` |
|---|---|
| `accept` | 0 |
| `reject` | 1 |
| `isolate` | 1 |

**Keep check.py non-normative.** It verifies the *declared* count against the
tier, and that `build.py` and the manifest agree on it. It must not compute the
count by inspecting the file — "a checker that ruled on semantics would become a
second normative authority", which is the constraint the issue and the module
docstring both state.

**Done when:** adding a second defect to a negative vector fails `check.py`
without anyone remembering the ground rule.

### #40 — broken-chain fixture

A fourth `chain/` file whose `zpf-input` Source names a file that is not there.
It exercises the distinction the 0.10 text made normative and no fixture tests:
**no bytes exist** (chain resolved, region genuinely empty) versus **bytes
unavailable** (chain broke — file missing, unreadable, or failing its digest).

Collapsing the second into the first asserts something the consumer never
established, which is precisely the silent data loss the coverage guarantee
exists to prevent.

**Tier:** `isolate` — a reader must distinguish the two, not reject the file.
**Also:** `check_chain()` must not treat the absent file as its own failure; it
currently resolves every declared digest against a sibling and would report the
fixture as stale. Guard it on the manifest entry.
**Also:** delete the "No broken chain" bullet from `vectors/README.md` under
"Coverage this does not have".

---

## The touch list for any new option

Every option in Phase 2 needs all seven. Missing one is how the 0.12 vector
defects happened.

1. **Option id registry** row (1502–1535) — id, name, value type, used-in, meaning.
2. **Block section** — add to that block's `Options:` line.
3. **Prose** — wherever the concept is explained, not only the table.
4. **JSONL ↔ binary field mapping** (1892–1987) — key name, encoding, escapes.
5. **`build.py`** — an `o_*()` helper beside its neighbours.
6. **A vector** carrying it, plus its `manifest.json` entry.
7. **`CHANGELOG.md`** — under `Added`, stating the delta only.

Repeatable options need an eighth: the closed list at line 1489.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| C3's shape does not settle | medium | It is self-contained and last. Slip C3 to 0.14 alone; C1/C2 and every option still ship. Decide the shape in Phase 1 so the slip decision comes early, not at release. |
| #35 ships before C2 and needs reopening | low, high cost | Enforced ordering above. If C2 slips, #35 slips with it — do not ship extents keyed on `(source_id, pid)`. |
| The dropped #37 leaves a stale promise in `CHANGELOG.md` | certain if unhandled | Follow-up 1 of decision 3 — correct it in the `0.13` notes. This is the specific failure the tracker migration was written to stop. |
| Vector regeneration churn hides a real diff | high | Phase 0 does the stamp once. Review substantive vector diffs against a tree already at 0.13. |
| C3 duplicates #45's position hint | low | Check #45 before minting the block; they may share a mechanism. |

---

## Issue tracker

**Close each issue in the commit that finishes it, not in a batch on release
day.** The milestone is this release's status display; a batch close at the end
means it reads "9 open" until the moment it reads "0", and never tells anyone
where the release actually is.

**Prerequisite: the `0.14` milestone.** It exists (`milestone/2`), created after
this plan was written, but is described `TBD`. Give it a description saying what
it carries: the provenance/layer axis separation, the sessionization stage, and
the tunnel worked example.

### Terminal state of every issue in the milestone

| Issue | Action | When |
|---|---|---|
| [#35](https://github.com/adamkjonsson/zipline/issues/35) | Close | Phase 2, after C2 |
| [#36](https://github.com/adamkjonsson/zipline/issues/36) | Close | Phase 2 |
| [#37](https://github.com/adamkjonsson/zipline/issues/37) | **Close unshipped**, with the regime argument from decision 3 in the closing comment | Phase 2, with its replacement sentence |
| [#38](https://github.com/adamkjonsson/zipline/issues/38) | Close | Phase 0 |
| [#39](https://github.com/adamkjonsson/zipline/issues/39) | Close | Phase 4 |
| [#40](https://github.com/adamkjonsson/zipline/issues/40) | Close | Phase 4 |
| [#41](https://github.com/adamkjonsson/zipline/issues/41) | ~~**Split into six**; #41 itself stays open as the umbrella, re-milestoned to `0.14`, closing when F2 lands~~ **DONE** — split into #50–#55; umbrella on `0.14` | Phase 0 |
| [#42](https://github.com/adamkjonsson/zipline/issues/42) | ~~**Re-milestone to `0.14`**; add the trigger condition (a report of a real consumer misreading a partially-hinted `SEQUENCED` session) as a comment so the next reader knows what would settle it~~ **DONE** | Phase 0 |
| [#47](https://github.com/adamkjonsson/zipline/issues/47) | Close | Phase 2 |

### The six issues #41 became

Filed in Phase 0.

| New issue | Milestone | Body |
|---|---|---|
| [#50](https://github.com/adamkjonsson/zipline/issues/50) — C1, `spans` means correspondence | `0.13` | Finding 1 and Finding 2 of the analysis |
| [#51](https://github.com/adamkjonsson/zipline/issues/51) — C2, session fan-out | `0.13` | Finding 2; the #35 dependency in both directions |
| [#52](https://github.com/adamkjonsson/zipline/issues/52) — C3, declared-discontinuity block | `0.13` | Finding 3; the open shape question carried forward explicitly |
| [#53](https://github.com/adamkjonsson/zipline/issues/53) — F0, provenance and layer as independent axes | `0.14` | Finding 6, including case G |
| [#54](https://github.com/adamkjonsson/zipline/issues/54) — F1, sessionization stage as a reassembly decoder | `0.14` | Finding 5 and Finding 7; depends on F0 |
| [#55](https://github.com/adamkjonsson/zipline/issues/55) — F2, tunnel worked example and fixtures | `0.14` | Follows F1 |

Each should link back to [ISSUE_41_ANALYSIS.md](ISSUE_41_ANALYSIS.md) rather than
restating it — the analysis is the reasoning of record and it supersedes parts of
itself in place, which a copied excerpt would not track.

### Cross-references worth adding as comments

These are conclusions this plan reached that belong on issues nobody will
otherwise re-read. **All three posted in Phase 0.**

- **[#35](https://github.com/adamkjonsson/zipline/issues/35)** — its rationale
  says Session End "already contains per-session integrity counts (issue #9)". It
  does not; Session End carries `reason` and `comment` only, and counts are
  [#43](https://github.com/adamkjonsson/zipline/issues/43), unscheduled. The
  placement argument stands on its own, but the premise is wrong as written.
- **[#36](https://github.com/adamkjonsson/zipline/issues/36)** — decision 5 of the
  #41 analysis gives reassembly a Decoder Descriptor and therefore a
  `params_digest`. Whether that overlaps a general per-transform digest should be
  decided at F1 drafting time, not discovered then.
- **[#45](https://github.com/adamkjonsson/zipline/issues/45)** — C3's block may be
  the transport-neutral position hint SCTP also wants, rejected in `0.10`. Check
  before minting a second mechanism.

*None of this can be done from the working tree — it needs `gh` or the web UI.*

The one remaining tracker action for Phase 0 is **closing #38**, held for the
commit that carries its fix rather than done in a batch.

## Definition of done

- [x] Every issue at its terminal state per [Issue tracker](#issue-tracker) — six
      closed on delivery, #37 closed unshipped, #41 split into six, #42 and the
      #41 umbrella on a `0.14` milestone that exists. *The `0.13` milestone reads
      0 open, 10 closed.*
- [x] The `0.11` re-stamp promise at `CHANGELOG.md:131` corrected in the `0.13`
      notes, not left to rot. *(Phase 2, under **Removed**.)*
- [x] `python3 vectors/check.py` green; every vector stamps `0.13`. *(Re-checked
      at release: 32 vectors.)*
- [x] `manifest.json` `format` reads `zipline-payload/0.13` *(Phase 0)*,
      every entry has `violations` *(Phase 4)*.
- [x] Each new option appears in all seven places on the touch list. *Audited at
      release across `0x0054`, `0x0015`, `0x00C1`, `0x00D0`, `0x00D1` and the
      `0x22` block — no gaps.*
- [x] `CHANGELOG.md` `[0.13]` complete, with **Clarified** entries separated from
      **Changed** — the distinction tells an implementer whether existing code was
      wrong or merely incomplete, and C1 is a *Clarified*, not a *Changed*.
      *There is no **Changed** section at all, and the preamble says so: nothing
      conformant under `0.12` stops being conformant.*
- [x] The spec's "Planned, tracked elsewhere" table drops the rows that shipped.
      *#35 and #36 dropped, #37 dropped as closed-unshipped, #41 reworded to name
      only what remains.*
- [x] `docs/VECTOR-DEFECTS.md` marks defect 1 fixed *(Phase 0; defect 2 too — it
      was already fixed in the tree, only its status was stale)*.
- [x] No spec sentence still says a decoder only frames, and no reachable text
      claims a decode-stage output is byte-identical to the region it spans.
      *(Phase 1; re-checked at release.)*

## What execution changed

Recorded because a plan that is only ever read forwards teaches nothing. Three
things this document got wrong, and one it deliberately left open:

- **#40's tier.** This plan and the issue both said `isolate`. It shipped
  `accept`. Enforcing #39's one-violation rule first forced the question, and the
  file has no violation to declare: it is conformant, it declares its input as
  *Conformance* requires, and nothing obliges that input to exist at read time.
  What is absent is a *sibling file*, not a property of the file under test.
- **#40's shape.** Planned as a fourth file in `chain/`, needing `check_chain()`
  guarded. Shipped standalone, so `check_chain()` was untouched and `chain/` goes
  on meaning one thing.
- **When per-feature vectors land.** The Phases list said Phase 4; the touch list
  said with the option. The touch list was right and won.
- **C3's shape**, left open here on purpose, was settled in Phase 1 as block type
  `0x22` — early enough that a slip decision would have come early too.

One item was deferred rather than dropped: the cross-stage discontinuity splice
fixture, which cannot be a standalone vector because the break lives in the
*previous* stage's output. It is [#60](https://github.com/adamkjonsson/zipline/issues/60)
on `0.14`.
