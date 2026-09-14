# Release 0.20 — what the ports found

*Written 2026-09-13 against **`v0.19`**. Sources are the seven issues on the
`0.20` milestone — #142, #141, #140, #133, #125, #106, #80 — five of them filed
from the two implementations porting to `0.19`. This is a working roadmap, not
normative text.*

*The release is **`0.20`**, not `0.20.0`, per the changelog's Conventions.*

---

## What this release is

**A repair-and-vector release, and two implementations are waiting on it.** Four
of the seven issues are what a port finds in its first week: a flags row that
reads two ways (#142), three vectors whose bytes and projection disagree (#141),
an accept tier that cannot see a wrong *value* (#140), and a MUST that `0.19`
created with no fixture pinning it (#133). None changes a rule. Two of them hold
a downstream release: `python-zipline-wire` `0.2.0` is on hold pending #142, and
`python-zipline`'s `0.16 → 0.19` port has three vectors in its `DEFECTIVE` list
pending #141. That is the argument for cutting this release **small and soon**.

**The other three are design questions, and this release answers them with a
decision rather than syntax.** #80 and #106 turn out to be one question (scope
decision 1); #125 is Package D's territory and is decided with D (scope decision
2). Each gets a recorded answer here and moves off the milestone with it, which is
the fourth time #80 has been deferred and the first time with a date.

**It adds no option and no block.** It may add a normative sentence or two —
#142's row and #133's consequence are each candidates for a `MUST` or a
`SHOULD` if that is the clearest way to say them — and **there is nothing holy
about the keyword counts**: `121 MUST, 42 MUST NOT, 26 SHOULD, 53 MAY` is where
`0.19` left them, not a ceiling. What the guard asks is that a keyword arriving
be accounted for the way one leaving is, and the release builds the table that
lets it say so — see §Mechanics, item 1.

---

## The four, ranked

| | Issue | What it is | Where it lands | Blocks downstream? |
|---|---|---|---|---|
| **1** | #141 | three vectors' `.zpf` wrong, `.jsonl` right | `build.py`, three values; `VECTOR-DEFECTS.md` | **yes** — `python-zipline` ratchet |
| **2** | #142 | `retransmit`: sender's act or reassembler's | one flags row, three passages, two summaries | **yes** — `python-zipline-wire` `0.2.0` |
| **3** | #141, structural | the two faces are authored independently | `build.py`: faces compared at registration | no |
| **4** | #140 | accept vectors assert nothing about computed values | `build.py`/`manifest.json`: declared `extents`; README | no |
| **5** | #133 | a merge owes coverage for its input's holes, no vector | `merge/` fixture, negative twin, `RULES`, `check.py` | no — but they are building it |

Ranked by who is waiting, then by size. 1 and 2 are each a one-commit fix and
are what the two ports need; they go first and could be tagged alone if the rest
slips. 3 is the guard that keeps 1 from recurring, and this is the **third
release running** in which a `.zpf`/`.jsonl` disagreement surfaced downstream
(defect 4 → #104 was the last), so it is not optional. 4 and 5 are suite work
that makes the accept tier and the merge obligation testable; 5 is the largest
item by some way.

---

## Scope decisions

### 1. #80 and #106 are one design question, and `0.21` is its release

`#106`'s own comment found it: the fourth option for a decomposing stream — *an
explicit positive marker so that the absence of a block keeps meaning exactly
what it means today* — is #80's shape, a participant-level statement about what
stored adjacency asserts. One Participant Descriptor option answers both:

> This participant is a **unit sequence whose stored order is not stream
> order**. Its offset space is still the stored-order concatenation, so every
> record stays addressable and citable, but no two adjacent records may be
> assumed to join.

Under it, a reordering stage discharges the per-seam Discontinuity duty wholesale
(#80), a nested field-granular decoder declares it and owes no block at any seam
(#106), and **every stream that does not carry it keeps today's splice
semantics** — which is the property #106's cap was written to protect, and the
reason reading 1 there was refused.

**The evidence #80 asked for has arrived, from #106.** #80 said what would settle
it: *a decoder whose output units genuinely never concatenate — objects carved out
of a stream is the shape to watch for*. `kober`'s DNS output, 176 nested records
with the flags word decoded nine times over, is that shape exactly. So the
candidate is no longer waiting on evidence; it is waiting on a design and a
vector.

**Not in `0.20`, deliberately.** #80 is *not safe to skip* — a `1.0` reader
meeting it would splice across a seam — which is why it must land in `0.x`, and
also why it is a load-bearing addition that wants a release to itself. `0.19`
declined #106 as *a design question, and this release is not one*; `0.20` is
not one either, and two implementations are waiting on the four repairs above.
Putting a new option in front of them is the wrong trade.

**What `0.20` does instead:** records this decision, moves both issues to a
`0.21` milestone, and notes the entry criteria — `python-zipline`'s reading of
the option against `kober`'s files, and one vector of each shape (a reversed
stream, a nested decomposition). The design sketch above is the starting point,
not the answer; the name, the enum-or-flag question and the interaction with
`reordered-decoded` are `0.21`'s to settle.

### 2. #125 is decided with Package D, not here

#125 adds a third `reason_class` value or a flag beside it. Package D-pair — the
form `0.19`'s scope decision 3 settled on — deletes `reason_class` and the
`dropped` MUST outright, and `0.19` recorded that D *closes #117 and #125 by
deletion*. Taking #125 now and D later adds a value to an option that the next
reduction removes; that is the churn `0.19`'s Package C ledger warned about,
one release apart.

So #125 moves to whichever milestone decides D. If D is taken, it closes by
deletion; if D is declined, the issue's own analysis is the answer — removal is
orthogonal to recoverability, so it is a **flag beside** `reason_class` rather
than a third value in an enum that classifies something else. Either way the
decision is D's, and nothing is broken meanwhile: the constraint is written down,
the predicate works, and `isolate-unmarked-drop` tests it.

### 3. `retransmit` names the sender's act — reading 1

The flag says the **sender resent bytes** of this record's range and the
reassembler resolved it here. A copy of one transmission — a mirror port, a
two-interface capture, a veth pair — is not a retransmission and does not set it.

Four arguments, and the third is the one that decides it:

- **The token sits among connection facts.** `seq_start`, `ack`, `isn`,
  `tcp_role` all describe the connection, not the capture point. A flag that
  flips depending on whether a SPAN port was in the path would be the only one
  in its table describing the observer.
- **A consumer reading the flag wants the sender's behaviour.** Loss and
  recovery are what `retransmit` is looked at for; a mirror port is not the
  sender. `tshark` labelling the ten duplicated segments in `tcp_dup_ts.pcap`
  *TCP Retransmission* is the misreading this row should not enshrine.
- **The reassembler's act already has a home, and the sender's does not.** An
  Undecoded block against a `capture` source exists for *overlap it discarded*
  (§Undecoded, [:1729](zipline-payload-format.md)). Under reading 1 the two
  mechanisms split cleanly — the flag says what the sender did, the block says
  what the reassembler dropped — and nothing is lost. Under reading 2 the flag
  restates what the block already carries, and the format has no way at all to
  say a retransmission occurred.
- **It is decidable in practice, and the format need not say how.** packeteer's
  `tcp_dup_ts.pcap` and `tcp_lossy_ts.pcap` measure 10/10 duplicates with the
  same TSval and 16/16 retransmissions with a later one, nothing ambiguous. The
  row should not name TSval — that is one producer's method, and the option is
  not always negotiated. It says instead that a producer that **cannot** tell a
  copy from a retransmission treats it as a retransmission, which is what every
  producer did before this sentence and is the conservative reading.

**What changes.** The flags row ([:2336](zipline-payload-format.md)); the
timestamp rule's *a later retransmit that contributes no accepted bytes*
([:1655](zipline-payload-format.md)), which becomes *a later segment —
retransmitted or duplicated — …*; §Undecoded's *an overlapping retransmit the
reassembler discarded* ([:1771](zipline-payload-format.md)), likewise; the
Caveats bullet ([:460](zipline-payload-format.md)), lightly. Two `build.py`
summaries use the word the same way ([:2212](../vectors/build.py),
[:2981](../vectors/build.py)) and follow. The row itself is a definition and
needs no keyword; the *cannot-tell* sentence — a producer that cannot
distinguish a copy from a retransmission treats it as one — reads naturally as
a `SHOULD`, and if it is written that way it is a `NORMATIVE_ADDITIONS` entry
and a `Changed` line rather than `Clarified`. Write whichever is clearer.

**No vector is owed**, as the issue says: a reader treats the bit identically
either way. Worth knowing: no vector sets `0x0040` today at all, and the
capability check does not cover flag bits, only options and blocks. That is a
standing gap and not this release's — but the `RETIRED_CLAIMS` entry retiring the
two-way wording is owed, with the three spellings above found by grep and
validated against `v0.19`.

### 4. #140 Part 1 gets a sentence, not a key

`unplaceable-below-origin`'s `expect` opens *ACCEPT, and REPORT* on a
`violations: 0` vector, and the manifest has no way to say *breaks no rule and
is still reported*. The issue offers two exits: a key orthogonal to `violations`,
or a README sentence saying a SHOULD-report on a clean vector is not testable.

**The sentence.** The suite's tiers name what a reader *must* do, and
`violations` counts rules broken. A SHOULD has no conformant failure mode: a
reader that stays silent on an unplaceable record has broken nothing. A key that
asserted the report would make silence a suite failure — promoting the SHOULD to
a MUST through the manifest, which is the second normative authority ground
rule 2 forbids. So: a README sentence under the tiers table, the `expect` of
`unplaceable-below-origin` reworded so *report* is stated as the SHOULD it is,
and `unplaceable-no-seq-start`'s `expect` brought into agreement, since the same
sentence of §Referencing names both shapes and only one of them mentions it.

### 5. #140 Part 2: `extents`, declared, mandatory on the accept tier

Three accept vectors carry their whole lesson in a number no field states, and a
reader that gets the number wrong passes all three silently. The fix is the one
the issue names and `violations` already models: **declare the expected
per-stream extent in `build.py`**, emit it in `manifest.json`, and let a
downstream harness assert it. `check.py` computes nothing — the numbers come
from the description that built the bytes, so they cannot drift from them, and
ground rule 2 is untouched.

- **Shape:** a list of `{"session_id", "pid", "extent"}` per accept vector — the
  `input_extents` entry shape the JSONL already spells, so no new vocabulary.
- **Extents only, not per-record ranges.** All three cases in the issue are
  caught by the stream extent alone: 16 against 4294967303, 105 against 80, 160
  against 120. Per-record ranges can come when a case needs them.
- **Mandatory on single-file accept vectors**, by the `violations` argument: a
  number an author must confront is one that gets checked, and a default is a
  number nobody looked at. That is **31 vectors**, most with one or two streams.
  `chain` and `tunnel` are exempt — their extents are already verified against
  their inputs by the bespoke checks, and a declared copy would be a second
  statement of the same number.
- **The zero-length and hint-less cases are where the author's number gets
  hard**, and that is the point: a handshake record's extent, a stream with no
  `seq_start`, a decoded stream with a Discontinuity `width`. Each declared
  number is a small reading of the specification, and a wrong one is caught by
  the first implementation that disagrees — which is exactly the loop the issue
  says the suite lacks today.

---

## Mechanics: what is different about this release

**1. The normative guard was built for a subtractive release and has no way
to account for an addition.** `check_normative_split` compares the count of
each keyword to `v0.18` less `NORMATIVE_REMOVALS`, and a *gained* keyword fails
the build the same as a lost one ([:1122](../vectors/check.py)). That is an
accident of when it was built, not a policy: the guard exists so a rule cannot
leave with the paragraph that explained it, and a rule *arriving* deserves the
same record, not a prohibition. This is the first release since the guard that
adds text, so it **builds the other half in Phase 0**: a `NORMATIVE_ADDITIONS`
table in the same shape as the removals — a pattern that must be present in the
specification, the keywords it brought, and why — with the expected counts
derived from both tables. Then #142 and #133 are written in whatever words are
clearest, and each keyword they bring is one entry. If neither ends up needing
one, the table ships empty and the next release has it.

**2. `build.py` becomes the place where the two faces meet.** Item 3 puts a
projection of the blocks beside the hand-authored `.jsonl` at `vector()` time and
refuses to register a vector whose faces disagree. That respects ground rule 2
precisely: `build.py` built the bytes and knows every body value, `check.py`
still parses no block body. It is the same seat `violations` sits in — a
`TypeError` before the build runs is a better moment than a downstream port.

**3. A third bespoke pair check, or the helper three instances justify.**
`check.py`'s one exception to ground rule 2 is `chain/` and `tunnel/`, where
digests and offsets are verified against sibling files. #133's fixture is a third
instance of the same shape — an output hop verified against its input's extent.
Write it bespoke if that is under fifty lines; if `chain_raw_extents`,
`tunnel_covers` and the new one turn out to be one function with three callers,
that is the moment to fold them. Decide when writing it, not before.

**4. The stale-summary hazard is live, and this plan found an instance.**
`mixed-derivation`'s summary ([:2300](../vectors/build.py)) still says session
11's *participant carries origin, its records carry no spans* and restates *a
participant MUST NOT both carry origin and hold records carrying spans* — the
rule Package A deleted — in a spelling without the bold and backticks the
`RETIRED_CLAIMS` pattern at [:202](../vectors/check.py) matches. The README row
([:190](../vectors/README.md)) says the same. That is the paraphrase blindness
`0.18` measured, on the very vector `0.19`'s plan flagged as *high — it is the
default action*. It is fixed with #141's value in the same vector, and the two
spellings go into the existing `pass-through-carries-origin` entry, validated
against `v0.19` where they must report both sites.

---

## Phase 0 — stamp, and the milestone

1. `MAJOR, MINOR = 0, 20` in `vectors/build.py`; `check.py` to match; regenerate;
   the spec's version sites; open `## [0.20] — unreleased` with `Fixed`,
   `Clarified` and `Added` headings.
2. Confirm `reject-unknown-minor` rolls 20 → 21, read out of the stamped bytes.
3. Move #80 and #106 to a `0.21` milestone and #125 off `0.20`, each with a
   comment pointing at the scope decision above. The milestone then holds the
   four this release does.
4. **Build `NORMATIVE_ADDITIONS`** in `check.py`, per §Mechanics item 1, before
   any spec text is written: the same tuple shape as the removals, the counts
   derived from both tables, and a check that every named addition is present.
   Validate it the way the removals table was — an entry naming a sentence not
   in the specification must fail.
5. Grep the tree for every spelling the release retires — the `retransmit`
   passages, the two `origin` paraphrases — **before** any of it is edited. The
   `RETIRED_CLAIMS` patterns are written from what the grep finds.

**What the grep found (Phase 0, 2026-09-14, against `2c5fa72`).** Sites are in
the five files `RETIRED_CLAIMS` scans unless marked *(unscanned)*; line numbers
are pre-edit.

*`retransmit`, for Phase 2* — the row and the three passages the plan named,
plus two summaries and a README row:

- spec `:2336` — `retransmission/overlap was resolved inside this record`
- spec `:1655` — `a later retransmit that contributes no *accepted* bytes`
- spec `:1771` — `an overlapping retransmit the reassembler discarded`
- spec `:460–462` — `SACK/retransmission/overlap are resolved by the
  *reassembler*` … `not raw retransmits` (the Caveats bullet; also `:37–40`,
  which says the same in the introduction and is *not* about the flag)
- `build.py:2212` (`reassembler-declared`) — `overlapping retransmit it could not
  resolve`
- `build.py:2981` (`undecoded-in-capture`) — `an overlapping retransmit the
  reassembler discarded`
- `vectors/README.md:189` (`undecoded-in-capture`) — `declaring an overlapping
  retransmit it discarded`
- *(unscanned)* `docs/ISSUE_41_ANALYSIS.md:219–220` quotes the row's old
  meaning as history; `docs/RELEASE-0.16-PLAN.md:58` likewise. Neither is edited.

*`origin`, for Phase 1* — the two paraphrases §Mechanics item 4 named, and
three softer ones the plan did not know about:

- `build.py:2303` (`mixed-derivation`) — `its participant carries origin, its
  records carry no spans`
- `build.py:2309–2310` — `a participant MUST NOT both carry origin and hold
  records carrying spans`
- `vectors/README.md:190` — `session 11's participant carries \`origin\``
- `build.py:1805` (`filtered-decoded`) — `the spans-versus-origin test is what
  decides that`; the test is now identity-versus-non-identity spans
- `build.py:3059` and `vectors/README.md:225` (`isolate-unbound-zpf-stream`) —
  `no origin` / `carries no origin`, vacuously true now that no such option
  exists, but describing the violation in a model that has moved on
- `vectors/README.md:188` (`proxy-decoded`) — `no \`spans\` and no \`origin\``,
  the same shape
- `build.py:425` — `o_origin` itself is still defined, unused since `0.19`
  removed `0x0064`; the plan's Phase 3 note says it *is gone*, and it should be

The three softer spellings are fixed in Phase 1 with the two named ones, since
they are the same stale model in the same scanned files; whether they get
`RETIRED_CLAIMS` spellings is decided when writing the entry.

---

## Phase 1 — #141, the three values (one commit, first)

Smallest and most waited-on. `handshake-at-origin` guards the non-descending
ordering MUST (#124), the rule whose absence rejects every real capture, and it is
held out of `python-zipline`'s ratchet for a projection defect unrelated to what
it tests.

- `handshake-at-origin` ([:3205](../vectors/build.py)): `o_tcp_role(0)`,
  `o_tcp_role(1)` → `o_tcp_role(1)`, `o_tcp_role(2)`. The enum is
  `0` unknown, `1` initiator, `2` responder ([:2321](zipline-payload-format.md));
  the bytes were shifted down by one and the `.jsonl` was right.
- `unplaceable-below-origin` ([:3421](../vectors/build.py)): `o_tcp_role(0)` →
  `o_tcp_role(1)`, the same shift.
- `mixed-derivation` ([:2347](../vectors/build.py)):
  `o_spans([(1, 8, 0, 0, 10)])` → `o_spans([(1, 0, 8, 0, 10)])`. The tuple is in
  *byte* order — `(source, pid, session, …)` — and the author wrote it in the
  logical order every prose statement uses. Phase 3 removes the trap; this phase
  fixes the instance.
- `mixed-derivation`'s summary and README row, per §Mechanics item 4, in the same
  commit, with the `RETIRED_CLAIMS` spellings.
- `VECTOR-DEFECTS.md`: defects **5** (the `tcp_role` shift, two vectors) and
  **6** (the span triple, one vector), in the file's existing shape — affected
  table, what is wrong, evidence, fix — and the status line to *6 defects*. The
  issue's numbering is kept because `python-zipline`'s harness already uses it.
- Regenerate; `.zpf`, `.hex` and `manifest.json` change, no `.jsonl` does.

Tell `python-zipline` on #141 when it lands, before anything else in the release,
so the three names leave `DEFECTIVE` without waiting for the tag.

---

## Phase 2 — #142, the flag

Per scope decision 3. One commit: the row, the three passages, the two
summaries, the `RETIRED_CLAIMS` entry, a `Clarified` changelog line that names
the reading and the two capture shapes it was decided against. Then answer
python-zipline-wire#17 with the row's final text, since its `0.2.0` is what is
waiting.

**One thing to check that the issue does not raise.** `undecoded-in-capture`
writes `reason: overlap-discarded` for what a reassembler dropped. Under reading
1 that word is still right — it names the reassembler's act, which is what the
block is for — but its summary ([:2981](../vectors/build.py)) says *an overlapping
retransmit the reassembler discarded*, and after this release a discarded segment
may be a duplicate. The summary follows the spec's passage; the reason word does
not change.

---

## Phase 3 — #141, the structural fix

**Keep both faces hand-authored, and make `build.py` compare them.** The issue
suggests generating the `.jsonl` from the block description so a wrong value
produces two matching wrong faces the reviewer sees. This plan takes the other
half of the same idea: the hand-written `.jsonl` has been the *right* face in all
three defects, because it is an independent statement of the expected projection
written by a person reading the mapping. That independence is what gives a diff
between the faces meaning. Single-sourcing removes the disagreement by removing
the second opinion; a comparison at registration keeps the second opinion and
turns the disagreement into a build failure. Both need a projector; only one
keeps the check.

What it takes, in `build.py` only:

1. **`Opt` carries its logical value**, not just the bytes and a display string.
   `o_tcp_role(1)` knows it is `tcp_role = initiator`; `o_spans` knows its
   entries as dicts. The enum tables the JSONL renders as strings — `tcp_role`,
   `output_layer`, source `kind`, `reason_class` — live here in one small dict,
   the way the block constructors already know their body fields.
2. **`o_spans` takes its triple in logical order**, `(source, session, pid)`, or
   by keyword. The current positional order differs from every prose statement
   of the same triple *deliberately* — the u16s lead only for alignment — and a
   helper whose argument order is the one thing about the option a reader must
   not assume is a trap that will keep catching people. `o_origin` had the same
   shape and is gone; `o_input_extents` should be read for the same defect.
3. **A projector**, block → JSONL line, implementing the mapping including the
   four escapes: unknown block, unknown option, unknown enum value (renders as
   the raw number — `escape-unknown-enum` is its test), reserved flag bit (a hex
   token). This is the mapping the specification states and the `.jsonl` files
   already exemplify, so the 40 hand-authored projections are its test suite —
   and it is theirs. That reciprocal check is the property single-sourcing would
   have thrown away.
4. **`vector()` diffs the two** per block and raises with the vector name, block
   index, key and both values. Multi-file fixtures per file.

**Validate it the way `RETIRED_CLAIMS` entries are validated:** revert Phase 1's
three values on a scratch branch and confirm `build.py` refuses all three. A
guard that passes the fixed tree and was never seen to fail the broken one has
not been tested.

---

## Phase 4 — #140, what the accept tier asserts

Per scope decisions 4 and 5.

1. `vector()` gains `extents`, keyword-only, **required when `tier == "accept"`
   and the vector is single-file**, so omitting it is a `TypeError` the way
   omitting `violations` is. Multi-file fixtures pass nothing.
2. Declare it on all 31. Each is a reading of the specification; the three the
   issue names are the ones to write first and to state in the summary — the
   number is the lesson. Expect the zero-length handshake records and the
   hint-less streams to take the longest per vector.
3. `manifest.json` carries `extents`; `check.py` verifies only that every
   single-file accept entry has it and that each entry names a session and pid
   that the vector's blocks declared — shape, not value.
4. The README: the tiers section gets `extents` beside `violations` and
   `advisory`, with the same argument; and the sentence scope decision 4 owes,
   that a SHOULD-report on a `violations: 0` vector is not tested and silence is
   conformant.
5. The two `unplaceable-*` `expect` strings, reworded to agree with each other
   and with the README sentence.

Tell `python-zipline` the key exists once it is in `manifest.json` — it is
additive and their harness can start asserting it before the tag.

---

## Phase 5 — #133, the merge fixture

The obligation binds a merge today: Package A made every `zpf`-sourced record
carry `spans`, a merge writes identity spans, identity spans cite the input, and
the coverage guarantee makes a file answerable for every input offset it cites.
A transport input's holes are ranges no payload covers, so a merge owes an
Undecoded `gap` per hole. `python-zipline` is building to that reading in its own
Phase 3 and has offered the fixture description; take it.

**There is a design fork here, and this plan takes the text's side of it.** One
could argue a pass-through preserving a *transport* layer owes nothing for its
input's holes, because the output's sequence numbers carry them exactly as the
input's did — the block would restate what the offsets already say. That is an
exemption, which is a new rule shape, in a release that adds no rules; it would
weaken a guarantee `0.19` stated uniformly; and the one implementation with a
`merge_files` has already accepted the obligation as written. If the fixture
shows the blocks are pure noise on real merges, that is evidence for a later
release and the fixture is what produces it. Vector the obligation as it stands.

The fixture, in the shape of `chain/`:

- **`merge/a.zpf`, `merge/b.zpf`**: two single-direction capture-sourced
  transport inputs; `a`'s stream carries a sequence gap so its offset space has a
  hole no record covers. Real `isn`/`seq_start` arithmetic, so the hole's range
  is derivable from the bytes.
- **`merge/merged.zpf`**: two `zpf-input` Sources with digests, one session with
  both participants, every record carrying an identity span into its input,
  **and an Undecoded `gap` block naming the hole** in `a`'s stream. `.jsonl` for
  each file, as `chain/` has.
- **`isolate-merge-unmarked-hole`**: the same output with the `gap` block
  omitted. Single-file, on the isolate tier, `violations=1`. It can be
  single-file because `input_extents` on the Session End makes the uncovered
  range visible from the output alone — which is worth saying in its summary,
  since it is the property D-pair would trade away and this vector would then
  need the pair.
- **`RULES`**: `merge-covers-input-holes` (or the name that reads best in the
  table), naming `merge`. The entry could not be added before the vector existed
  because a rule with no vector fails the build; that is the mechanism working.
- **`check.py`**: a `merge_covers` pair check — every offset of each input
  participant stream, as reconstructed from the input's `isn` and `seq_start`
  the way `chain_raw_extents` does, is covered by a span or an Undecoded block of
  `merged.zpf`. Per §Mechanics item 3.
- **The specification**: one sentence, in the pass-through carry-forward
  bullet of §Conformance or beside the coverage guarantee, stating the
  consequence so an implementer does not have to derive it from two rules three
  sections apart: *this includes a pass-through — an identity span cites the
  input, so a hole in a preserved transport stream is marked like any other
  uncovered range*. If it reads better as *a pass-through preserving a transport
  stream MUST mark each hole of its input*, write it that way and account for
  the keyword; the obligation is already a MUST by derivation, so either
  spelling is a `Clarified` entry.

Vector count: **55**, from 53. Rules: **27**, from 26. Options unchanged at 35.

---

## Phase 6 — changelog, downstream, tag

1. `CHANGELOG.md` `[0.20]`: `Fixed` (three vectors, by name, with the defect
   numbers); `Clarified` (#142's reading; #133's sentence); `Added` (`extents`
   in the manifest, the `merge` fixture and its twin, the face check — the last
   as a note on the suite rather than the format).
2. `README.md` gains its `RELEASE-0.20-PLAN.md` line beside `0.19`'s.
3. Tell both implementations before the tag, per the definition of done `0.19`
   set: `python-zipline` on #141/#140/#133 (the `extents` key, the fixture, the
   defects closed) and `python-zipline-wire` on #142. Neither should learn a
   manifest key or a vector count from the diff.
4. Tag `v0.20` on the merge commit.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A sentence written for #142 or #133 carries a new keyword and the guard goes red | **high — it is the natural way to write either** | `NORMATIVE_ADDITIONS` is a Phase 0 step, so the red build is one table entry away rather than a reason to weaken the sentence |
| The additions table becomes a knob — a keyword added and an entry written to match, with no argument | medium | Every entry carries a *why*, as the removals do; the review question is whether the sentence states a rule the document did not already imply |
| The projector (Phase 3) is written to the `.jsonl` files rather than to the mapping, and reproduces a defect in them | medium | It is tested against 40 hand-written projections *and* the mapping's own text; a mismatch is read both ways before either is edited |
| Phase 3 grows into a rewrite of `build.py`'s 4 900 lines | medium | Scope is `Opt`'s value, `o_spans`'s order, one projector, one diff at `vector()`; no vector's authoring changes except the three in Phase 1 |
| A declared `extent` is wrong, and ships as an assertion an implementation now fails on | medium — 31 human readings of the spec | The three the issue names first; the rest reviewed by the first port to assert them, which is the loop this exists to create |
| `mixed-derivation` is fixed for #141 and its stale summary survives | **high — the summary was not in the issue** | §Mechanics item 4; the two spellings go into `RETIRED_CLAIMS` in the same commit and are validated against `v0.19` |
| The merge fixture takes the exemption side of the fork by accident — `merged.zpf` written without the `gap` block and no one notices | medium | The pair check in `check.py` fails on it; that is what the check is for |
| The release grows a design item — #80's option or #125's flag — mid-flight | medium | Scope decisions 1 and 2; both are named as a different kind of release, and two ports are waiting on this one |
| `python-zipline-wire` tags `0.2.0` on reading 1 before Phase 2 lands and the row is worded differently | low | Phase 2 is second and small; answer its issue with the row's final text |

---

## Definition of done

The four:

- [x] `handshake-at-origin`, `unplaceable-below-origin` and `mixed-derivation`
      project to their shipped `.jsonl` byte for byte; `VECTOR-DEFECTS.md` records
      defects 5 and 6 as fixed; `mixed-derivation`'s summary and README row say
      *identity span*, not *origin*.
- [x] The `retransmit` row says which act it names and what a copy of one
      transmission is; no passage in the specification or the suite uses
      *retransmit* for a discarded duplicate; `RETIRED_CLAIMS` carries the old
      spellings, reproducing against `v0.19`.
- [x] `build.py` refuses a vector whose `.zpf` and `.jsonl` disagree, and was
      seen to refuse all three of Phase 1's defects on a scratch revert.
- [x] Every single-file accept vector declares `extents`; the README says what
      the key asserts and that a SHOULD-report is not tested.
- [x] `merge/` exists with its negative twin, a `RULES` entry names it, and
      `check.py` verifies the output against its inputs' holes.

The three:

- [x] #80 and #106 are on a `0.21` milestone with a comment pointing at scope
      decision 1; #125 is on the milestone that decides D, pointing at scope
      decision 2.

Release:

- [x] `python3 vectors/check.py` green; every vector stamps `0.20`;
      `reject-unknown-minor` rolled to `0/21` out of its own bytes. **55
      vectors, 35 options, 27 rules.**
- [x] `NORMATIVE_ADDITIONS` exists, and every keyword the release added has an
      entry with its argument; the split reported by `check.py` is `v0.18` less
      removals plus additions, whatever the numbers turn out to be.
- [x] `ruff check` and `ruff format` clean.
- [x] `CHANGELOG.md` `[0.20]` dated, with the three vectors named under `Fixed`.
- [x] Both implementations told before the tag. *(Told after it, on the merged
      commit, so the comments could point at `v0.20` rather than at a branch.)*
- [x] Tag `v0.20`, on the merge commit, where `v0.19` sits.

---

## What execution changed

*Written 2026-09-14, at the end of Phase 6, before the merge.*

**The three things the plan expected to get wrong, it got right.** Phase 3 was
the size it said: `Opt` and `Blk` as list subclasses carrying a logical value,
one projector written from the mapping section, one diff at `vector()`, and no
vector's authoring changed beyond the 76 tuples reordered inside `o_spans` and
`o_input_extents` brackets. The projector agreed with all 40 hand-written
projections on its first run, which tested both at once. Of the 37 stream
extents, the ones that took thought were the ones the plan named — the
zero-length handshake records, the never-anchored streams, the widthless break —
and none took long. The merge fixture's `gap` block reads as signal: the block is
the only thing in `merged.zpf` that says *which input* has the hole, since the
output's own sequence numbers describe the output's stream.

**What the plan did not know was how much of `0.19` was still in the tree.**
Phase 0's grep for the two `origin` paraphrases found three more in the suite,
and reading the specification for them found thirteen references to the option
`0.19` removed — the merge worked example still wrote it on both participants,
the JSONL mapping still defined it, and the Conformance pass-through bullet still
required it with a MUST. The same read found the `single_clock` alias row, a
File Header options line still listing `flags`, a *needs a basis — see below*
above a paragraph `0.19` had deleted, four summaries naming vectors Package C had
removed or renamed, a README first line still saying `0.18`, and the Conformance
enum paragraph counting *two enums* since `0.15` added the third. All of it is
the paraphrase blindness `0.18` measured: every `RETIRED_CLAIMS` spelling was
written from the sentence being deleted, and none of the sentences left behind
said it the same way. Eleven new spellings went in, each seen to report against
`v0.19`. This release's `Fixed` section is longer than its plan expected, and
the commits that made it so are the ones to read first.

**One premise was weaker than stated.** Phase 5 says the merge obligation is
*already a MUST by derivation*. The coverage guarantee's own statement was
scoped to *a decode stage's output* in §Coverage honesty and the Conformance
decoded-record bullet, and stated for every input offset in §Session End and
§Layers. The derivation rested on the unscoped half. The sentence was written as
the plan allowed, as a MUST with a `NORMATIVE_ADDITIONS` entry, §Coverage
honesty now names both kinds of derived file, and the changelog says which
statements were scoped. Still `Clarified`: an ambiguity pinned, not a rule the
document did not lean to.

**The guard built in Phase 0 fired twice**, once per release keyword, and each
time the red build was one table entry away rather than a reason to weaken the
sentence — which is what it was built for. The split at the tag is `v0.18` less
23 removals plus 2 additions: MAY 53, MUST 122, MUST NOT 42, SHOULD 27.

**Two smaller corrections to the plan's own text.** `o_origin` was not gone; it
was defined and unused, with `o_file_flags` and `o_seq_basis` beside it, and all
three are gone now. And `build.py:2981` was `isolate-hole-against-capture`'s
summary, not `undecoded-in-capture`'s — both used the word, both followed.
