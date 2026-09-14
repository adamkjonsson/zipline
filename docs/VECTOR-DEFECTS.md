# Defects in the conformance vectors

A running list of vectors found to be wrong, and what fixed them. Defects 1 and 2
were found while porting `0.9 → 0.12` against `vectors/` at tag `v0.12` (commit
`c291afc`); the list is appended to as later reviews reach further into the tree.

**Status: 6 defects, affecting 9 vectors and the vectors README. All fixed.**
Defect 2 by commit `a52c717` and defect 1 by the `0.13` version-stamp commit,
which regenerated the three vectors; defect 3 in `0.16`; defect 4 in `0.17`;
defects 5 and 6 in `0.20`. The file is kept as the record of what was wrong and
why.

Ground rule 2 says a vector that disagrees with the specification is the thing
that is wrong, and defects 1 and 2 were vector-side under it. **Defect 3 is the
exception worth naming:** the vector disagreed with a specification that
disagreed with itself, so no reading of the text could have produced a correct
vector, and the fix changed both.

---

## Defect 1 — Three decode-stage vectors omit the mandatory `produced_by`/`produced_at`

**→ FIXED in `0.13`** ([#38](https://github.com/adamkjonsson/zipline/issues/38)).
All three File Headers now carry both options, matching `decoded-basic`; the
`.zpf`, `.hex` and `.jsonl` were regenerated with them.

**Affected:**

| Vector | Tier | Consequence |
|--------|------|-------------|
| `undecoded-skipped` | `accept` | Fails a **correct** reader |
| `undecoded-reason-class` | `accept` | Fails a **correct** reader |
| `isolate-coverage-gap` | `isolate` | Passes an **incorrect** reader |

### What is wrong

All three are decode-stage files: each declares a `zpf-input` Source, declares a
Decoder Descriptor, and carries records with `decoder_id`/`spans` or Undecoded
blocks. Each therefore falls under *Conformance*:

> Every **derived** file (either kind) MUST declare each of its input `.zpf`s as
> a `zpf-input` Source and set the File Header `produced_by`/`produced_at`.

None of the three sets either field. Their File Headers carry no options at all
(`length = 16` — magic, version, `tick_hz`, nothing more). The `.jsonl`
projections agree with the bytes, so the two faces are consistent with each
other; both are simply non-conformant.

### Evidence

Walking each file's blocks:

```
undecoded-skipped        FileHeader produced_by=None produced_at=None
                         Source id=1 kind=zpf-input uri='raw.zpf'
                         Decoder / Session / Participant
                         Undecoded reason='skipped' decoder_id=1
                         Record decoder_id=1 spans=1

undecoded-reason-class   FileHeader produced_by=None produced_at=None
                         Source id=1 kind=zpf-input uri='raw.zpf'
                         Decoder / Session / Participant
                         Undecoded reason='rtp-seq-gap' decoder_id=1

isolate-coverage-gap     FileHeader produced_by=None produced_at=None
                         Source id=1 kind=zpf-input uri='raw.zpf'
                         Decoder / Session / Participant
                         Record decoder_id=1 spans=1
                         Undecoded reason='undecodable' decoder_id=1
```

For contrast, every *other* derived vector — `decoded-basic`,
`annotator-decoded`, `passthrough-transport`, `reordered-decoded`, and all three
`chain/` files — sets both fields correctly. The omission looks like an
oversight in three files rather than a misreading of the rule.

**Everything else about them is right.** Having implemented `reason_class` and
the `skipped` reason, we projected both `accept` vectors and compared against
their shipped `.jsonl`: the output matches, line for line, including
`undecoded-reason-class`'s non-canonical `rtp-seq-gap` reason carrying
`reason_class: "hole"`. So these two vectors test exactly what they set out to,
and adding the two header options is the whole fix — no other content needs
revisiting.

### Why it matters

The two tiers fail in opposite and equally unhelpful directions.

**The two `accept` vectors punish a conformant reader.** A reader that
implements the derived-file rule MUST diagnose these files, which is precisely
what the `accept` tier forbids. The more correct the implementation, the more
certainly it fails.

**`isolate-coverage-gap` rewards a non-conformant one.** It carries two
violations: the coverage gap it exists to test, and this missing provenance. A
reader hits the provenance error first, isolates the file, and passes the vector
**with the coverage check entirely unimplemented** — which is exactly what this
implementation did. That defeats the vector's purpose, and the coverage
guarantee is the format's central honesty claim, so this is the one negative
vector it is least affordable to have inert.

The general principle is worth stating because it will recur: **a negative
vector must carry exactly one violation.** With two, it silently tests whichever
the reader happens to detect first.

### Suggested fix

Add `produced_by` and `produced_at` to the File Header of all three, matching
what `decoded-basic` already does, and regenerate the `.hex` and `.jsonl`
alongside. `isolate-coverage-gap` then carries only the coverage gap, and the
two `accept` vectors become conformant files.

---

## Defect 2 — `vectors/README.md` contradicts the specification on the `isolate` tier

**→ FIXED** by commit `a52c717`. Ground rule 4 now says what the tier table and
*Conformance* say: rejecting an `isolate` vector, with a diagnostic, is
conformant.

### What is wrong

The README says both of these:

> **Tier table:** `isolate` — Well-framed but semantically invalid. A reader MAY
> reject the file *or* discard the smallest unit it can soundly isolate — and
> MUST NOT silently repair, guess, or drop without a diagnostic.

> **Ground rule 4:** A reader that *rejects* an `isolate` vector is as wrong as
> one that accepts it silently.

The table permits rejection; the prose calls it as wrong as silent acceptance.

The specification is unambiguous and matches the table — *Conformance*, semantic
violations: "the reader MAY reject the file, or discard the smallest unit it can
soundly isolate". So the prose is the error.

### Why it matters

It changes what a harness asserts, and it is stated in the section explaining
why the negative vectors are the valuable half — so it is the sentence an
implementer is most likely to encode. A harness built on the prose will fail a
reader that legitimately rejects.

Our harness follows the specification: it accepts either outcome and asserts
only that the violation is not passed silently.

### Suggested fix

Reword ground rule 4 to match the table and the spec — the failure mode being
warned against is a reader that *accepts silently*, and one that treats a
semantic violation as structural corruption (rejecting for the wrong tier's
reason). Rejecting the file, with a diagnostic, is conformant.

---

## Defect 3 — `undecoded-in-capture` wrote this file's own `session_id` into a block read against a capture

**→ FIXED in `0.16`** ([#87](https://github.com/adamkjonsson/zipline/issues/87)),
which settled the reading the vector could not satisfy.

Found by `python-zipline` while reviewing `0.15`
([SPEC-0.15-REVIEW.md](SPEC-0.15-REVIEW.md), Finding 2) — the first vector since
the `0.12` round that could not be implemented from the specification.

**Affected:** `undecoded-in-capture` (`accept`). Consequence: **unimplementable**.
A reader could not parse the block in any way that satisfied all three of the
rules bearing on it, so the vector failed every conformant reader and passed only
one that had guessed the same way its author did.

### What was wrong

The shipped block was:

```jsonl
{"type":"undecoded","source_id":1,"session_id":7,"pid":0,
 "off_start":4096,"off_end":4396,
 "reason":"overlap-discarded","reason_class":"bytes"}
```

`source_id 1` is a `capture` Source (`tap.pcap`). Three normative statements
applied and no reading satisfied all three: the Undecoded field table required
`kind = zpf-input`; §Undecoded said the ids are the *source's* and "never the
current file's", while `7` is this file's own session id; and the span-list rule
said a `capture` source's ids are unused and written 0.

The offsets compounded it. `4096..4396` is a plausible position in a pcap and an
impossible one in this file's stream, which is about 105 bytes long — so the
block's ids pointed one way and its offsets the other, and neither of the two
candidate readings fitted both halves.

### The fix

`0.16` keyed the whole body on the referenced source's `kind`, matching what
`spans` had always done. Against a `capture` source the ids are unused and MUST
be 0, and the offsets are byte offsets into the capture file. The vector now
writes `session_id = 0`, its offsets are correct as they stand, and its `.hex`
annotates them as capture byte offsets rather than "in the input's namespace" —
`build.py` had printed that label unconditionally, which was wrong on the one
vector where a reader most needed it right.

---

## Defect 4 — `tunnel/{inner,outer}.jsonl` spell the flow key `flow_key`, where the mapping says `key`

**→ FIXED in `0.17`** ([#104](https://github.com/adamkjonsson/zipline/issues/104)),
vector-side under ground rule 2, together with the two example lines in the
specification's tunnel walkthrough.

Found by `python-zipline` at Phase 1 of its `0.14` → `0.16` port, when the version
gate moved and `tunnel/outer.zpf` became readable for the first time.

**Affected:** `tunnel/inner.jsonl` and `tunnel/outer.jsonl` (both `accept`).
Consequence: **fails a correct reader**. A reader following the mapping table
emits `"key"` and cannot round-trip either file, so two of that fixture's four
members were out of the accept tier for a reason unrelated to what the fixture
exists to test — the layer rule, the fan-out, the declined crossing.

### What was wrong

Both files spelled the Session flow key with its **binary** name:

```jsonl
{"type":"session","session_id":1,"proto":"udp","flow_key":"198.51.100.7:51820 -> 203.0.113.9:51820"}
```

The JSONL ↔ binary mapping lists that option among the **brevity aliases** — the
keys whose JSON name deliberately differs from the binary name — as `key`, and
the parenthesis under the table exists precisely to stop a reader assuming the
JSON name always matches the option name.

The suite disagreed with itself: `descriptive-metadata.jsonl` shipped `"key"` at
the same version. So did the specification — `"key"` at the IRC example,
`"flow_key"` at the two tunnel walkthrough lines. Walkthrough and fixture are both
new in `0.15`, and both read as having been written from the option registry
rather than from the alias table.

### The fix

The two `.jsonl` files and the two walkthrough lines now write `"key"`. The
mapping table is unchanged — it was unambiguous, and one vector already obeyed it.

**The guard matters more than the fix.** `check.py` now builds the projection's
key vocabulary out of the specification's own tables and requires every key in
every `.jsonl` to be in it. The obvious form of that check would not have caught
this: `flow_key` **is** a registry option name, so a membership test over the
registry passes it. What the mapping states is one rule plus exceptions — a key is
a body field's or a registered option's canonical name, *except* where the alias
table gives it a shorter one — so the check subtracts the aliased binary names,
and that subtraction is the whole of what sees the defect. It reproduced all three
sites from the tree before the fix landed.

---

## Defect 5 — `handshake-at-origin` and `unplaceable-below-origin` write `tcp_role` one below the value their `.jsonl` names

**→ FIXED in `0.20`** ([#141](https://github.com/adamkjonsson/zipline/issues/141)),
vector-side under ground rule 2: the `.jsonl` was right and the bytes were wrong.

Found by `python-zipline` in the first hour of its `0.16 → 0.19` port, by
projecting every vendored `.zpf` through its JSONL face and diffing against the
shipped `.jsonl`. 40 files carry both faces; three disagreed, and this is two of
them.

**Affected:**

| Vector | Tier | The `.zpf` held | The `.jsonl` says | Since |
|--------|------|-----------------|-------------------|-------|
| `handshake-at-origin` | `accept` | `tcp_role` 0 then 1 | `initiator` then `responder`, so 1 then 2 | `0.18` |
| `unplaceable-below-origin` | `accept` | `tcp_role` 0 | `initiator`, so 1 | `0.19` |

Consequence: **fails a correct reader**. A reader that projects the enum as the
specification's table says — `0` unknown, `1` initiator, `2` responder — cannot
round-trip either file, and `handshake-at-origin` is the vector for the
non-descending ordering MUST (#124), the rule whose absence rejects every real
capture. It was held out of `python-zipline`'s ratchet for a projection defect
unrelated to what it tests.

### What was wrong

Semantics settle which face is right. `handshake-at-origin`'s pid 0 sends the
first SYN at `ts 1000` with no `ack`, and pid 1 answers at `ts 1100` with
`ack 1001`: pid 0 is the initiator and pid 1 the responder, which is what the
`.jsonl` says and what the vector's own summary describes. The bytes said
*unknown* and *initiator* — the enum shifted down by one:

```
participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(0)]),
participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000), o_tcp_role(1)]),
```

`o_tcp_role` takes the wire value, so those should have read `o_tcp_role(1)` and
`o_tcp_role(2)`. `unplaceable-below-origin` carried the same shift on its single
participant. `escape-unknown-enum` writes `o_tcp_role(7)` against
`"tcp_role": 7` and was correct, which is why the helper itself was not at fault.

**Everything else about them is right.** The `seq_start` tie
`handshake-at-origin` exists for is in the bytes and correct; the below-origin
placement `unplaceable-below-origin` exists for has nothing to do with
`tcp_role`. Only the projection was wrong.

### The fix

The three values in `build.py`; the two `.zpf` and `.hex` files regenerated; no
`.jsonl` changed.

**Why nothing upstream caught it, and what does now.** The `.hex` is generated
from the same description as the `.zpf`, so it faithfully reproduced the wrong
byte and annotated it — `option 0x0063 tcp_role, len = 1  (0)`. `check.py`
cannot see it by design: ground rule 2 keeps it from parsing block bodies, and
comparing the two faces is exactly that. The capability check saw `0x0063`
present and was satisfied. So `.zpf` ↔ `.jsonl` agreement was unguarded by
construction, and this is the third release running in which such a disagreement
surfaced downstream (defect 4 was the last). `0.20` makes `build.py` compare
the two faces at registration — every option and block now carries the logical
value it wrote, a projector renders that by the mapping, and `vector()` refuses
a vector whose projection is not its `.jsonl` — so a disagreement fails the
build rather than a port. It was seen to refuse both of these on a scratch
revert before it was trusted.

---

## Defect 6 — `mixed-derivation` writes its identity span's `session_id` and `pid` swapped

**→ FIXED in `0.20`** ([#141](https://github.com/adamkjonsson/zipline/issues/141)),
vector-side under ground rule 2, the third of the three faces that port found
disagreeing.

**Affected:** `mixed-derivation` (`accept`). Consequence: **fails a correct
reader**. Its session 11 record's `.jsonl` says the span cites
`session_id 8, pid 0`; the bytes said `pid 8, session_id 0`.

### What was wrong

Session 11 preserves a stream from the input, and the input session is 8 with
participant 0 — its sibling span in the same file cites `(source 1, session 7,
pid 0)` correctly. A participant id of 8 in a file whose participants are all
pid 0 is not a reading anyone intended.

The proximate cause was sharper than a typo. `o_spans` took its triple in
**byte order**, `(source_id, pid, session_id, …)`, because the two u16s lead the
u64 only for alignment — while every prose statement of the same triple, in the
specification and in the JSONL, puts `session_id` before `pid`:

```
o_spans([(1, 0, 7, 0, 40)])   # session 10: source 1, pid 0, session 7   ✓
o_spans([(1, 8, 0, 0, 10)])   # session 11: source 1, pid 8, session 0   ✗ meant (1, 0, 8, …)
```

A positional helper whose argument order deliberately differs from every prose
statement of the same triple is a trap that keeps catching people; the author
wrote the logical order.

**The summary was stale too, and the issue did not mention it.** The same
vector's summary and its README row still said session 11's *participant carries
origin, its records carry no spans*, and restated the rule that a participant
*MUST NOT both carry origin and hold records carrying spans* — the rule `0.19`'s
Package A deleted, in a spelling the `RETIRED_CLAIMS` guard did not match. That
is the paraphrase blindness `0.18` measured, on the very vector `0.19`'s plan
flagged as the likeliest place for it.

### The fix

The one value in `build.py`; the `.zpf` and `.hex` regenerated; no `.jsonl`
changed. The summary and README row now say *identity span*, and the stale
spellings are in `RETIRED_CLAIMS`, where they reproduce against `v0.19`. With
the structural fix, `0.20` also changes `o_spans` and `o_input_extents` to take
their triples in logical order, `(source, session, pid, …)`, so the class of
mistake goes with the instance — and the face check was seen to refuse this
defect too, on a scratch revert.

---

## Verified sound

Checked while investigating, and correct — recorded so the batch report does not
imply doubt about them:

- **`raw-minimal` is byte-for-byte the specification's 196-byte worked example.**
  Independently confirmed: this project transcribed the same example into a test
  fixture by hand, and after the 0.12 version stamp the two agree exactly. They
  still agree byte-for-byte after the `0.13` stamp, both 196 bytes.
- **`undecoded-reason-class` carries `reason_class = "hole"`** (option `0x00A1`)
  on its non-canonical `rtp-seq-gap` reason, exactly as required. Only its
  File Header provenance is wrong.
- **All other derived vectors set `produced_by`/`produced_at`.**

## How the audit was run

Defect 1 was found by tripping over `isolate-coverage-gap`, then generalised:
for every non-`reject` vector, walk its blocks, classify it as derived if it
declares a `zpf-input` Source or carries `decoder_id`/`spans`/`origin`, and flag
any derived file whose File Header lacks `produced_by` or `produced_at`. That
swept up the two `accept` vectors, which had not been reached yet by the port.

The same shape of check is worth running upstream over `build.py`'s
descriptions, since it is mechanical: a vector's declared tier and its actual
violation count should agree, and a negative vector should carry exactly one.
