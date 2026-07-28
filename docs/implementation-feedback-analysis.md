# Analysis: implementation feedback on Zipline Payload Format v1.0

Assessment of issues #8–#16, raised while implementing the format in Python.
This document analyses *what each issue means for the standard* and *how big the
impact is*. It deliberately stops short of drafting spec wording; that is the
next step.

All line references are to [docs/payload-format.md](docs/payload-format.md) as of
commit `bc4bcfb`.

---

## 1. Verdict at a glance

| # | Topic | Is the issue right? | Change class | Surface touched | Effort |
|---|-------|---------------------|--------------|-----------------|--------|
| #8 | JSONL projection of an unknown binary block type | **Yes** — real gap | Clarification | JSONL face | S |
| #9 | Missing conversions at three edges | **Yes**, with one nuance (a) and one under-stated consequence (c) | Clarification + one new error rule | JSONL face, Conformance | S–M |
| #10 | `tick_hz` vs `"time_units":"us"` | **Yes** — the examples contradict the normative text | Removed alias *(decided: C)* | JSONL face + 6 examples | S |
| #11 | Sequencing vs non-increasing timestamps | **Premise is wrong** — v1.0 already allows this for TCP | None | — | — |
| #12 | Add a canonical `skipped` reason | **Yes**, and it is better motivated than the issue states | Additive vocabulary | Undecoded `reason` | S |
| #13 | Annotator transforms (no data change) | **Half right** — case A is already legal; case B is a genuine hole | Widening + clarification | Conformance taxonomy | **M–L** |
| #14 | Sequenced order without trustworthy timestamps | **Yes** — both halves, though one is partly vacuous | Widening + clarification | Conformance | M |
| #15 | Rename the spec file | Yes (cosmetic) | Editorial | Repo layout | S |
| #16 | Reader half for record flag reserved bits | **Yes** | Editorial | Enums table | XS |

**Headline: no issue requires a major version bump.** Nothing here touches the
block frame, an existing block body, an existing option id, or the meaning of
any field a v1.0 file already carries. Every v1.0 file stays valid under every
proposed resolution. The largest item, #13, is a *relaxation* of a taxonomy rule
plus a paragraph of provenance text.

Change classes used above:

- **Editorial** — no normative effect.
- **Clarification** — pins down behaviour that is currently undefined; does not
  change any file that a conformant writer can produce today.
- **Additive** — a new value/option in an already-open space.
- **Widening** — permits files that v1.0 forbids. Old *files* stay valid; new
  files may be refused by a strict v1.0 reader (see §5).
- **Structural** — changes existing encoding. **Nothing here is structural.**

---

## 2. The cross-cutting finding: the JSONL face has no unknown-handling principle

Five of the nine issues (#8, #9a, #9b, #9c, and half of #10) are the same defect
wearing different hats, and they are worth fixing as *one* addition rather than
five patches.

The binary face has a single, universal principle for anything a reader does not
recognise, stated in several places and never violated:

- unknown block type → skip via frame `length` ([payload-format.md:716-719](docs/payload-format.md#L716-L719))
- unknown option id → skip via `len`, but **retain every occurrence in file order** ([payload-format.md:1094-1098](docs/payload-format.md#L1094-L1098))
- reserved fields/bits → ignore on read ([payload-format.md:699-700](docs/payload-format.md#L699-L700))
- none of these is an error ([payload-format.md:1385-1387](docs/payload-format.md#L1385-L1387))

The JSONL face is defined as "**one rule plus a short list of exceptions**"
([payload-format.md:1411-1426](docs/payload-format.md#L1411-L1426)) — but that rule
maps *known* names to *known* names. It provides exactly one escape hatch for the
unrecognised: the generic `options` array for unregistered option ids
([payload-format.md:1492-1497](docs/payload-format.md#L1492-L1497)). There is no
escape hatch for an unknown **block type**, an unknown **enum value**, or an
unknown **flag bit** — so a converter meeting one has no conformant output, and
the format's own forward-compatibility promise (a v1.1 file readable by v1.0
tools) breaks the moment such a file passes through the JSONL face.

**Recommendation.** Add one short normative subsection to the JSONL section
stating the mirror principle: *every unrecognised element has a defined syntactic
escape, and a converter never invents meaning and never silently drops.* Concretely
that means four escapes, of which one already exists:

| Unrecognised | Escape | Status |
|---|---|---|
| option id | `options` array of `{"id","value"}` | exists |
| block type | hex `type` string + base64 of the block content | **new** (#8) |
| enum value | the raw number instead of the string label | **new** (#9c) |
| flag bit | hex token in the flags array | **new** (#9b) |

This single addition resolves #8, #9a, #9b, #9c and removes the ambiguity behind
#10. It is a clarification, not a widening: no v1.0 file changes meaning, and no
binary encoding is touched.

---

## 3. Issue-by-issue

### #8 — JSONL projection for an unknown binary block type

**Valid.** [payload-format.md:1428-1442](docs/payload-format.md#L1428-L1442) maps
eleven block types to `type` strings. [payload-format.md:1495-1496](docs/payload-format.md#L1495-L1496)
says an unknown `type` *string* is preserved unchanged — that covers
JSONL→JSONL, but a binary→JSONL converter meeting an unknown u16 type has no
string to emit, and JSONL→binary has no way to recover the number from a string
it was never told how to form.

**What it means.** The spec promises a minor bump adds blocks old readers safely
skip ([payload-format.md:739-741](docs/payload-format.md#L739-L741)). Today that
promise holds in binary and fails in JSONL — the first v1.1 block type makes the
JSONL face lossy. That is the real cost, and it is a forward-compatibility bug,
not merely a missing table row.

**Constraint worth noting for the fix.** A converter cannot split an unknown
block's content into body + options, because the body layout is exactly what it
does not know. So the projection must treat `content` (body ++ options ++
padding) as a single opaque base64 blob. Since `length` is always a multiple of 4
and padding is part of content, round-tripping the blob verbatim is byte-exact —
this is the one place where the JSONL face can be *better* than "semantically
lossless".

**Impact: small. Compatible.** JSONL-only clarification.

### #9 — Missing binary ↔ JSONL conversions

Three separate edges; they deserve three different answers.

**(a) An unknown JSONL key on a known block, converting to binary.**
Correct that it is undefined — but I would push back on framing it as a
round-trip loss. The spec's contract is *binary → JSONL → binary*
([payload-format.md:95-96](docs/payload-format.md#L95-L96)), and a
binary-originated JSONL line can never contain an unknown key: unregistered
options land in the `options` array under their numeric id. Unknown keys arise
only from hand-authored or third-party JSONL, which is outside the round-trip
contract. So this is not a hole in losslessness; it is a missing *error rule*.

The right resolution is a prohibition rather than a mechanism: a converter **MUST
NOT** invent an option id, and MUST either reject the line or drop the key with a
diagnostic (the spec's existing "data must never vanish silently" principle,
[payload-format.md:1379-1380](docs/payload-format.md#L1379-L1380)). Adding a
mechanism here — e.g. a reserved id range for "named but unregistered" — would be
over-engineering: it invents a second extension channel alongside `Custom`
(`0xFF`) and the option registry, for input that is out of contract anyway.

**(b) A record flags bit with no JSONL token.**
Real, and it is a genuine (if small) round-trip loss: a set bit in the `0xFF20`
reserved mask has no token, and "a zero/unset bitfield is omitted"
([payload-format.md:1477](docs/payload-format.md#L1477)) gives it nowhere to go, so
it vanishes.

There is an apparent tension with "reserved bits MUST be ignored on read" — but
it is only apparent, and the spec has already resolved this exact tension for
option ids: *ignore for semantics, preserve for round-trip*
([payload-format.md:1094-1098](docs/payload-format.md#L1094-L1098)). A hex-token
fallback (`"flags":["psh","0x0020"]`) follows the established precedent and, more
importantly, is what lets a v1.1-written file survive a v1.0 JSONL round-trip
once bit `0x0020` is assigned a meaning. Without it, the flags field is the one
place where a minor bump silently loses data.

**(c) A `kind` byte outside `capture` / `zpf-input`.**
Valid, and the issue under-states it — this is **not** just a rendering question.
Source `kind` is load-bearing in three places:

1. It classifies the whole file as raw vs derived ([payload-format.md:1278-1281](docs/payload-format.md#L1278-L1281)).
2. It tells a decoder-less record apart as raw vs pass-through ([payload-format.md:1286-1288](docs/payload-format.md#L1286-L1288)).
3. **It selects how `spans` offsets are interpreted** — logical stream offsets for
   `zpf-input`, byte offsets into the capture file for `capture`
   ([payload-format.md:1158-1163](docs/payload-format.md#L1158-L1163)).

So an unknown `kind` does not merely lack a label: every record and span
referencing that source becomes uninterpretable. This needs a semantic rule in
the error-handling tiers ([payload-format.md:1364-1377](docs/payload-format.md#L1364-L1377)),
not just a JSONL rule — an unknown `kind` should be an isolatable semantic
condition (reject, or discard the sources/records that depend on it), while the
JSONL side renders the raw number.

Note the same "unknown enum value" question exists for `tcp_role`, where the
consequence is benign (absence already means "unknown"). Handle both with one
general rule: **enums render as their label when recognised and as the raw number
otherwise**; the *consequences* of an unrecognised value are per-enum and only
`kind` has teeth.

**Impact: small–medium. Compatible.** (a) and (b) are JSONL-only; (c) adds one
sentence to Conformance.

### #10 — Representation of the file header tick rate

**Valid, and it is an outright contradiction inside v1.0, not an open question.**
`tick_hz` is a u64 ([payload-format.md:730](docs/payload-format.md#L730)); the alias
table maps JSONL `time_units` → `tick_hz` ([payload-format.md:1450](docs/payload-format.md#L1450));
and value encoding says a 64-bit field is a JSON number or a **decimal string**
([payload-format.md:1461-1466](docs/payload-format.md#L1461-L1466)). Under that
rule `"us"` is illegal. Yet all six JSONL examples write `"time_units":"us"`
(lines 180, 346, 422, 648, …).

Normative text wins over examples ([payload-format.md:673-674](docs/payload-format.md#L673-L674)),
so *the examples are non-conformant* — which is the worst possible failure mode,
because implementers copy examples. This is the highest-value item in the whole
set relative to its size.

Three ways out:

| Option | Change | Cost |
|---|---|---|
| **A. Fix the examples** — `"time_units":1000000` | Editorial only | Loses the readability the JSONL face exists for; contradicts the name `time_units`, which promises a unit not a rate |
| **B. Accept both** — closed symbolic vocabulary `"s"`/`"ms"`/`"us"`/`"ns"` plus number/decimal-string for anything else | Widening of the JSONL face | A second representation for one field; readers must try symbolic before decimal |
| **C. Drop the alias** — JSONL key becomes `tick_hz`, numeric only | Editorial + one fewer alias | Breaks every existing example *and* any tool already emitting `time_units` |

**Recommendation: B.** It is the only option that is strictly widening — every
file that exists today under either reading stays legal, including the ones
written by implementers who copied the examples. The ambiguity objection is
weaker than it looks: the four symbolic tokens are a closed, non-numeric set, so
"symbolic first, else decimal" is unambiguous, and the mapping is exact and
bijective on those four rates so nothing is lost. Dual representation is also not
a new precedent — the spec already permits number-or-decimal-string for every
64-bit field.

C is the leanest end-state and worth considering if the Python implementation is
the only consumer and can be changed now; it gets rid of an alias whose name
actively misleads. That window closes as implementations multiply.

**Impact: small. Compatible under B; a break under A or C** (for files that
followed the examples, which were never conformant to begin with).

> **Decision taken: option C.** The JSONL key becomes `tick_hz`, numeric, and
> the `time_units` alias goes. Rationale: leanest end-state, one fewer alias,
> and it removes a name that promises a unit while carrying a rate — worth
> taking now, while the implementation count is one.
>
> **Consequence needing a sub-decision in Phase 1.** `"time_units":1000000` was
> *conformant* 1.0 JSONL (only the symbolic `"us"` in the examples was not), so
> deleting the alias outright breaks a file 1.0 permitted — the only such break
> in 1.1, and it sits against the "every 1.0 file stays valid" claim in the
> status banner and CHANGELOG. Recommended implementation: **deprecate rather
> than delete** — a reader MUST accept `time_units` (numeric) and treat it as
> `tick_hz`; a writer MUST NOT emit it; removal lands in a later version. This
> reaches the decided end-state for writers, keeps the compatibility claim
> intact, and is exactly what the CHANGELOG's *Deprecated* category is for. A
> hard removal remains available if the clean break is preferred — say so and
> the banner claim gets scoped to the binary container instead.

### #11 — Sequenced records for non-increasing timestamps

**The premise is incorrect, and no change follows from this issue.** Three
corrections:

1. *"a zpf-file can only be marked as sequenced"* — sequencing is **per session**,
   not per file, and deliberately so ([payload-format.md:373-385](docs/payload-format.md#L373-L385)).
2. *"…if their time stamps are increasing"* — v1.0 imposes the timestamp/clock
   precondition **only on hint-less sessions**: "A producer therefore **MUST NOT**
   mark a *hint-less* session SEQUENCED unless its records share a single
   trustworthy clock" ([payload-format.md:447-456](docs/payload-format.md#L447-L456),
   restated at [payload-format.md:1332-1334](docs/payload-format.md#L1332-L1334)).
   A TCP session's sequenced order is causal and explicitly clock-independent.
3. *"Look for a mechanism that allows records to be stored logically sequenced
   even if the time stamps contradict"* — that mechanism is v1.0's central worked
   example. [payload-format.md:340-368](docs/payload-format.md#L340-L368) shows the
   server record at `ts:995` answering a client request at `ts:1000`, and
   [payload-format.md:421-438](docs/payload-format.md#L421-L438) shows the merged
   output storing them in that inverted-timestamp order **with `"sequenced":true`**.

So for TCP, the requested capability already exists and is demonstrated. What
survives from #11 is entirely contained in #14, treated below.

That said, the misreading is itself evidence: an implementer read the spec and
came away believing sequencing required monotonic timestamps. The clock
precondition is stated three times and its *scope* (hint-less sessions only) is
carried by a single adjective each time. That argues for a positive statement of
the converse — the point #14's second half makes.

### #12 — Add a canonical `Undecoded` reason: `skipped`

**Valid, and better motivated than the issue argues.** No format change is needed
at all: `reason` is explicitly an open vocabulary
([payload-format.md:1003](docs/payload-format.md#L1003), `e.g.`), so `skipped` is
already legal. The question is whether to *canonicalise* it, and the answer is yes
for a reason the issue does not give:

**The coverage guarantee forces the choice.** In a decode stage, every offset of
every input stream must be covered by a decoded record's `spans` or by an
Undecoded block ([payload-format.md:1302-1307](docs/payload-format.md#L1302-L1307)).
A decoder that deliberately ignores a BOM or a reserved field therefore has only
two legal moves today: stretch a record's span over bytes it did not interpret,
or mark them `undecodable` — which is a lie, since the decoder *could* decode
them and chose not to. `skipped` exists precisely because the coverage guarantee
admits no third option. That is a strong argument for adopting it.

**The practical payoff** is measurement: `undecodable` is a decoder-quality signal
worth alerting on, and intentional skips currently pollute it. Separating them
makes "undecoded bytes" a meaningful metric.

**Where it sits in the existing semantics.** The reason vocabulary is really a
two-class taxonomy, and only the class is machine-relevant
([payload-format.md:1006-1013](docs/payload-format.md#L1006-L1013)):

- *bytes exist upstream, follow the reference*: `undecodable` — and `skipped`
  joins this class
- *hole, no bytes anywhere*: `tcp-gap`, `truncated`

Adding a fourth value makes it worth stating that two-class structure explicitly
rather than leaving it implicit in prose.

**Adjacent gap found while analysing this.** Because the vocabulary is open, a
reader can meet a `reason` it does not recognise — and today has no rule for
which class to assume. It must not assume "hole" (that would silently discard
recoverable bytes) nor assume "recoverable" without qualification. The safe rule
is *unknown recoverability: attempt the follow, report if nothing is there*. This
should be settled in the same edit.

*(Note: the issue spells it "trunkated"; the spec value is `truncated`.)*

**Impact: small. Fully compatible** — purely additive in an already-open space.

### #13 — Transforms that change no data (annotators)

The most substantive issue of the nine. It splits into two cases with opposite
answers.

**Case A — annotating a raw (or pass-through) file: already legal, but the issue
is right that it is not obvious.** An annotator that adds session comments to a
raw file *is* a pass-through transform, and everything it needs exists: declare
the input as a `zpf-input` Source with `uri`+`digest`, mint ids, put an `origin`
option on every participant, re-emit the records byte- and offset-identically
([payload-format.md:1308-1318](docs/payload-format.md#L1308-L1318)). To the issue's
direct question — *"What should the provenance be, the original pcap or the first
zpf?"* — the spec's model already answers unambiguously: **provenance always names
the immediate input**, never the grandparent. The chain is walked one level at a
time ([payload-format.md:1010-1017](docs/payload-format.md#L1010-L1017)), and the
`digest` is a Makefile-style dependency edge, not a copy
([payload-format.md:572-574](docs/payload-format.md#L572-L574)). So: the first
`.zpf`, and the pcap is reached by opening it.

Two consequences worth writing down rather than leaving readers to derive:

- The annotated output is **not a raw file** — its records reference a
  `zpf-input`, so `capture`-level provenance (including `link_type` and
  capture-file byte offsets) is now one level away. That is coherent but is a
  real change in what downstream tools see, and it is the non-obvious part.
- The `origin` bookkeeping is mandatory and non-trivial for a transform whose
  whole point is that it changes nothing.

**Case B — annotating a *decoded* file: a genuine hole in the taxonomy.** This is
the issue's strongest point and it is correct. v1.0 states a strict trichotomy: a
derived file is exactly one of a decode stage or a pass-through, never a mix
([payload-format.md:1278-1285](docs/payload-format.md#L1278-L1285)). An annotated
copy of a decoded file fits neither:

- it cannot be a **pass-through**, because pass-through records carry no
  `decoder_id` ([payload-format.md:1308](docs/payload-format.md#L1308)) while its
  records must (a decoded record's meaning *is* its `decoder_id`), and because
  Decoder Descriptors and Undecoded blocks are "decode-stage files only"
  ([payload-format.md:788](docs/payload-format.md#L788), [payload-format.md:980](docs/payload-format.md#L980))
  while it must carry the Undecoded blocks forward or break the coverage guarantee;
- it cannot honestly be a **decode stage**, because it decoded nothing, and its
  records' `spans` point into its input's *input*, in a namespace it would have to
  re-declare for a file it never opened.

There is no conformant way to express this today. Given #13's own pipeline
(annotate, then decode) this will be hit in practice.

**Resolution options.**

1. **Document case A only.** Cheapest; leaves case B unexpressible.
2. **Generalise pass-through to "layer-preserving"** (recommended). The current
   definition conflates two ideas: *preserving bytes* and *carrying no decoder*.
   Separating them yields a clean formulation — **a decode stage creates a layer;
   a pass-through transform preserves whatever layer its input had** — under which
   a pass-through file re-emitting a decode stage carries the `decoder_id`s,
   re-declares the Decoder Descriptors, and re-emits the Undecoded blocks
   unchanged. This is a small relaxation of two "decode-stage files only"
   sentences plus a preservation obligation (bytes, offsets, `decoder_id`s and
   `spans` all unchanged). It preserves the trichotomy's real purpose — you can
   still tell exactly one thing happened to a file — while making it complete.
3. **Add a third derived kind ("annotation")** asserting machine-checkably that
   nothing but metadata changed. Defer: #13's own pipeline does not need it (step 3
   just reads the annotation), and it buys a guarantee no one has asked to verify.

**Pushback on the mechanism, worth raising back on the issue.** The described
pipeline puts *"which decoder to use"* in a session **`comment`**, which the
registry defines as a "free-text human note"
([payload-format.md:1119](docs/payload-format.md#L1119)). Using it as a
machine-readable control channel is a misuse: unspecified syntax, no namespace, no
way for a second annotator to add a second annotation without collision, and it
makes a *human* field load-bearing for correctness. The format already provides
the right vehicles — a `Custom` block (`0xFF`, PEN-namespaced, designed exactly
for vendor/experimental data, [payload-format.md:1050-1059](docs/payload-format.md#L1050-L1059))
for a tool-private annotation, or a registered option in a later minor if this
becomes a standard pipeline stage. Whichever way #13 is resolved, the annotation
mechanism should move off `comment`.

**Impact: medium–large in prose, small in mechanism. Compatible for existing
files** — option 2 is a widening: no v1.0 file changes meaning, but new files may
be isolated by a strict v1.0 reader (see §5).

> **Decision taken: option 2 — layer-preserving pass-through.** A decode stage
> *creates* a layer; a pass-through transform *preserves* whatever layer its
> input had, and may therefore re-emit `decoder_id`s, re-declare Decoder
> Descriptors, and carry Undecoded blocks forward unchanged. Drafting must keep
> the preservation obligation total — bytes, logical offsets, `decoder_id`s and
> `spans` all unchanged — since that obligation is the whole reason the
> trichotomy still means something afterwards. Case A (annotating a raw file)
> is documented as already-legal, not changed. Carries **[strict-reader]** in
> the CHANGELOG.

### #14 — Logically sequenced records vs. timestamps

Two independent asks; both valid, and the second is more urgent than the first.

**(a) Allow a sequenced session whose ordering basis is neither TCP hints nor a
trustworthy clock.** The diagnosis is accurate: v1.0 hard-wires "has causal hints"
to "has TCP `seq`/`ack`", because those are the only ordering hints in the option
registry. A UDP protocol with its own ordering mechanism therefore cannot be
declared sequenced even when the producer knows the order for certain.

Before changing anything, note that **part of this is already vacuous**, and
saying so may be most of the fix:

- An **N = 1 session** (one-way UDP/multicast feed, [payload-format.md:87](docs/payload-format.md#L87))
  has no cross-participant order to resolve at all, and its per-participant order
  is *already* a normative MUST ([payload-format.md:1250-1257](docs/payload-format.md#L1250-L1257)).
  Its stored order is therefore trivially a valid linearization, whatever the
  clocks did. The clock precondition adds nothing here.
- The same holds for any session whose records all come from one participant.

That leaves the genuinely open case: **N ≥ 2, no TCP hints, no trustworthy shared
clock, but a protocol-level ordering the producer can see.** Two designs:

| Design | What it is | Assessment |
|---|---|---|
| **Generic ordering hints** — transport-neutral `seq_pos`/`cum_ack` option ids | The route already sketched for SCTP ([payload-format.md:1638-1647](docs/payload-format.md#L1638-L1647)) and licensed by the transport-neutrality note ([payload-format.md:310-318](docs/payload-format.md#L310-L318)) | Keeps order *checkable* by consumers. But the merge needs **both** a monotonic per-sender position **and** a cumulative ack of the peer; many UDP protocols (RTP, for instance) supply only the first, which yields no cross-participant edges — so this does not actually solve the N ≥ 2 case for them. Heavier, and pays off only if consumers must re-derive order. |
| **Producer-asserted order** (what #14 asks for) | Relax the precondition from "single trustworthy clock" to "a sound basis, which may be protocol-specific knowledge the producer is responsible for" | Minimal: no new blocks, no new options, no algorithm change. |

**Recommendation: producer assertion**, with the honest caveat stated in the
spec. The cost is that `SEQUENCED` on a hint-less session becomes a pure trust
assertion rather than one backed by a stated precondition. That cost is smaller
than it appears — a reader could never verify the "single trustworthy clock"
claim either; it was always the producer's word. What is genuinely lost is the
reader's ability to *reason* about the basis, which argues for recording it (a
`sequenced_basis` string option, or at minimum a `comment` convention) rather
than leaving it silent. Generic hints remain the right later addition when a
transport actually supplies both required properties.

**(b) State the reader-side obligation.** **Fully endorsed — this is a pure
omission, and the most likely of all nine to cause a real interop failure.** The
Conformance section ([payload-format.md:1320-1339](docs/payload-format.md#L1320-L1339))
never says a reader must not reject or re-sort on timestamp inversion, while it
*does* say, two paragraphs earlier, that a reader meeting an out-of-order record
MAY reject the file ([payload-format.md:1263-1265](docs/payload-format.md#L1263-L1265)).
An implementer reading only Conformance can easily read "out-of-order" as "out of
timestamp order" — and #11 is direct evidence that exactly this misreading
happens. Note that v1.0's own merged worked example
([payload-format.md:421-438](docs/payload-format.md#L421-L438)) would be rejected
by such a reader.

One refinement to the wording proposed in the issue. *"in a session with causal
hints, stored order supersedes timestamps"* is too broad: in a **non**-sequenced
session, cross-participant stored order is explicitly *not* authoritative — only
the per-participant subsequence is, and the interleaving comes from the merge
([payload-format.md:1265-1267](docs/payload-format.md#L1265-L1267)). The obligation
should be scoped: *timestamps are never an ordering invariant a reader may
validate against or re-sort by; for a SEQUENCED session, stored order is the
authoritative order.*

**Impact: (a) medium, (b) small. Both compatible** — (b) is a clarification;
(a) is a widening that only permits new writer behaviour.

> **Decision taken (a): producer-asserted order, with the basis recorded.** The
> precondition relaxes from "single trustworthy clock" to "a sound basis, which
> may be protocol-specific knowledge the producer is responsible for", and a new
> `sequenced_basis` string option lets the producer state which. Generic
> ordering hints are **not** adopted now and move to *Possible future
> extensions* — they stay the right answer for a transport supplying both a
> monotonic per-sender position and a cumulative peer ack (SCTP), which is
> precisely what the UDP cases motivating #14 do not supply.
>
> Two drafting notes: the `sequenced_basis` option is **additive** (a new
> registry id, skippable by old readers), so only the relaxation itself carries
> **[strict-reader]**; and the N = 1 / single-sender vacuity goes in regardless
> of this decision, since it is a statement about what 1.0 already guarantees.
> Whether `sequenced_basis` is a free string or a small open vocabulary
> (`clock`, `transport`, `protocol`, `external`) is a Phase 4 drafting call —
> an open vocabulary with suggested values matches how `reason` already works
> on Session End and Undecoded.

### #15 — Rename the specification file

Uncontroversial and zero format impact. Two notes:

- The repo uses kebab-case (`payload-format.md`), so `zipline-payload-format.md`
  is more consistent than the underscored name proposed in the issue.
- Do **not** put a version in the filename — the document carries its own version
  and is meant to be amended in place.
- It is referenced from [README.md](README.md) and [CLAUDE.md](CLAUDE.md); both
  need updating in the same commit. Any external permalink breaks, which at this
  stage is acceptable.

### #16 — Reader handling of reserved flag bits

Correct, and correctly characterised as harmless. The three bitfields are
inconsistent only in wording:

- File flags: "reserved, MUST be written 0, and MUST be ignored on read" ([payload-format.md:761-762](docs/payload-format.md#L761-L762))
- Session flags: same ([payload-format.md:814-815](docs/payload-format.md#L814-L815))
- Record flags: "reserved, MUST be 0" ([payload-format.md:1201](docs/payload-format.md#L1201))

The global rule at [payload-format.md:699-700](docs/payload-format.md#L699-L700)
already supplies the reader half, so this is editorial. **Do it together with
#9b**, which rewrites the same table row anyway: if unrecognised bits get a hex
token, the row must say both "ignored on read" *and* "preserved for round-trip",
and getting those two statements written at once avoids introducing a fresh
inconsistency.

**Impact: negligible. Compatible.**

---

## 4. Additional gaps found during this analysis

Not raised in the issues, but adjacent and worth folding into the same revision:

1. **The logical offset space of a *decoded* file is never defined.** Offsets are
   defined against "the reassembled stream" with byte 0 anchored at `isn + 1` or
   the first reassembled byte ([payload-format.md:514-526](docs/payload-format.md#L514-L526))
   — a definition that only makes sense for a raw/pass-through stream. Yet chained
   decoding (`raw → tls-records → http → …`) is explicitly supported
   ([payload-format.md:502-504](docs/payload-format.md#L502-L504)) and requires the
   second decoder to cite `spans` into the first decoded file. What offset 0 of a
   *decoded* participant stream means (presumably the concatenation of that
   participant's decoded record payloads in stored order) is nowhere stated.
   **This blocks any two-stage decode**, and it is closely entangled with #13
   case B — both are about what a decoded file looks like when it is somebody
   else's input.
2. **Unrecognised `Undecoded.reason` has no defined recoverability class** — see
   #12 above.
3. **Unrecognised Source `kind` has no defined semantic consequence** — see #9c
   above.

---

## 5. Backwards compatibility

**Every proposed resolution preserves every existing v1.0 file.** Nothing changes
the frame, a block body, an option id, or the meaning of a field a v1.0 file can
carry. The compatibility question is therefore not "do old files still parse"
(they do, universally) but **"can an old reader read new files"**, which splits
the nine issues in two:

**Group 1 — safe in both directions** (#8, #9a, #9b, #9c, #12, #14b, #15, #16).
These either clarify undefined behaviour, widen the JSONL face, or add a value to
an already-open vocabulary. A v1.0 reader is unaffected because these describe
files it could already meet, or JSONL it would already have mishandled.
`sequenced_basis` (#14a) belongs here too — a new option id is skippable by
construction; only the *relaxation* it accompanies is in Group 2.

**Group 1b — the one break, and it is JSONL-only** (#10 as decided). Dropping the
`time_units` alias invalidates `"time_units":1000000`, which was conformant 1.0
JSONL. It touches no binary file, and the recommended deprecate-and-accept-on-read
implementation defers the break to a later version — but taken as a hard removal
it is the single place where 1.1 refuses something 1.0 permitted, and the
"every 1.0 file stays valid" claim would need scoping to the binary container.

**Group 2 — old readers may refuse new files** (#13 option 2, #14a's relaxation). Both are
widenings that let a producer emit a file v1.0 forbids. A strict v1.0 reader
encountering, say, an Undecoded block in a pass-through file will hit the
semantic-violation tier ([payload-format.md:1364-1377](docs/payload-format.md#L1364-L1377))
and MAY reject it. That is a *conformant* v1.0 reader doing its job, so the
incompatibility is real, not a bug.

Two things make this cheap right now and expensive later:

- The permissive branch of that MAY is also conformant, so a lenient v1.0 reader
  copes fine. The exposure is limited to strict readers.
- **There is currently one implementation.** The cost of a widening scales with
  the number of deployed strict readers, which is the argument for landing
  Group 2 now rather than accumulating it.

**On a version bump.** A minor bump (1.1) is the natural container, but note it
buys less than it appears: `version_minor` is advisory, old readers do not gate
behaviour on it, and a v1.0 reader will not consult it before applying its
semantic-violation MAY. So the bump is *documentation of intent*, not a
compatibility mechanism. A defensible packaging:

- **v1.0 errata** — the pure contradictions and omissions, which correct the
  document to what it already meant: #16, #14b, #10 (the example fix, regardless
  of option), #9b/#9c clarifications, #8.
- **v1.1** — everything that permits genuinely new files: #13, #14a, #12 if you
  want it canonical rather than merely legal, #10 under option B.

**Decided: a single v1.1** covering all nine, given the implementation count.
The document is now `1.1-beta` and [CHANGELOG.md](../CHANGELOG.md) carries the
delta; the split above is recorded only as the alternative that was weighed.

---

## 6. Suggested sequencing

Ordered by value per unit of effort, not by issue number:

1. **#10** — a contradiction that actively misleads implementers copying examples.
   Cheapest high-value fix in the set.
2. **#14b** — one paragraph; prevents a real interop failure already evidenced by
   #11's misreading.
3. **#16 + #9b** — same table row, do together.
4. **§2's JSONL unknown-handling principle** — one subsection that closes #8,
   #9a, #9c and repairs the format's forward-compatibility promise across the
   JSONL face.
5. **#12** — small, well-motivated, additive; settle the unknown-`reason` rule
   with it.
6. **#13 + §4.1** — the substantive design work. Case B and the decoded-file
   offset space are the same underlying question and should be resolved together.
7. **#14a** — producer assertion plus `sequenced_basis`, as decided in Phase 0.
8. **#15** — do last, in its own commit; it touches every path reference.

**#11 needs no change**; it should be closed with a pointer to
[payload-format.md:340-368](docs/payload-format.md#L340-L368) and
[payload-format.md:421-438](docs/payload-format.md#L421-L438), noting that the
scope of the clock precondition (hint-less sessions only) is being made more
prominent as part of #14b.

---

## 7. Roll-out plan

Working checklist. Tick items as the wording is drafted and landed. Phases are
ordered so that every decision precedes the text that depends on it, and so the
spec is left in a self-consistent state after each phase.

### Phase 0 — Decisions

Four choices gate the drafting. Recommendations are from §3; each is a one-line
answer, not a design exercise.

- [x] **#10 representation** — **decided: C**, drop the `time_units` alias;
      the JSONL key is `tick_hz`, numeric. One sub-decision deferred to Phase 1:
      deprecate-and-accept-on-read *(recommended)* vs hard removal — see the
      decision note under [#10](#10--representation-of-the-file-header-tick-rate)
- [x] **#13 taxonomy** — **decided: option 2**, generalise pass-through to
      *layer-preserving*
- [x] **#14a basis** — **decided: producer-asserted order, with the basis
      recorded** in a new `sequenced_basis` option; generic ordering hints
      deferred to *Possible future extensions*
- [x] **Packaging** — **decided: a single v1.1** covering all nine, rather than
      the errata/1.1 split in §5. The document is now `1.1-beta`,
      `version_minor` is `1`, and [CHANGELOG.md](../CHANGELOG.md) holds the
      1.0 → 1.1 delta
- [x] Record the decisions in this document — "Decision taken" notes now sit
      under [#10](#10--representation-of-the-file-header-tick-rate),
      [#13](#13--transforms-that-change-no-data-annotators) and
      [#14](#14--logically-sequenced-records-vs-timestamps) in §3

> **Navigating this plan.** The line references throughout this document are
> pinned to commit `bc4bcfb` (see the header) and drift as edits land — the
> spec has already moved by ~19 lines. Navigate by section anchor, not line
> number; the pin exists so the *analysis* stays checkable against the text it
> analysed, not as a live index.

**Standing rule for every phase below:** each landed change gets its
[CHANGELOG.md](../CHANGELOG.md) entry **in the same commit**, under the category
matching its change class in §1 — *Clarified* for clarifications, *Added* for
additive items, *Changed* for widenings (flagged `[strict-reader]` where a v1.0
reader may refuse the result, i.e. #13 and #14a), *Fixed* for the contradictions
in Phase 1.

### Phase 1 — Contradictions and omissions (no new capability)

Each item here corrects the document to what it already meant. Safe in both
directions; no file changes meaning.

- [x] **#10 sub-decision** — **decided: deprecate and accept on read.** Writers
      reach the end-state now; readers keep accepting numeric `time_units` for
      one version, so the "every 1.0 file stays valid" claim needs no scoping
- [x] **#10** — alias row removed from *Brevity aliases*, `tick_hz` stated in a
      new *Deprecated keys* note, `time_units`/`tick_hz` collapsed to `tick_hz`
      in the 64-bit list, and the examples corrected. **Four** example lines, not
      six — the earlier count conflated the `file` lines with the multi-line
      merged/decoded headers, which are the same four
- [x] Check no prose elsewhere says `time_units` — only the mapping table and
      the 64-bit integer list did; both handled
- [x] **#14b** — *Timestamps are not an ordering invariant* added to
      *Conformance*, as three reader rules (never reject on inversion; never
      re-sort a SEQUENCED session; timestamps order only concurrent records in a
      merge) plus a closing note that the sole actionable stored-order guarantee
      is the per-participant `seq_start` rule, which is a sequence rule and not a
      time rule
- [x] **#14b follow-through** — *The clock precondition applies to hint-less
      sessions only* added to *What a sequenced session rests on*, and the scope
      restated in *Conformance*. The third site (the per-session rationale in
      *Sequenced files*) already scoped it correctly and was left alone
- [x] **#16** — record-flags reserved row now reads identically to the File
      Header and Session flag rows
- [ ] **#9b's half of that row** — the round-trip clause ("preserved by a
      converter") lands in Phase 2 with the hex-token mechanism it depends on.
      Splitting it this way introduces no inconsistency: #16 alone *removes* one,
      and a forward reference to a rule that does not exist yet would have added
      one

### Phase 2 — The JSONL unknown-handling principle (§2)

One new subsection in the JSONL section, plus the two rules that hang off it.
Closes #8, #9a and #9c.

- [x] Mirror principle drafted as a new subsection, *Unrecognised data: the four
      escapes*, with the escapes given as a table and one note each
- [x] **#8** — unknown block type: `"type":"0x0042"` + base64 `content` covering
      body ++ options ++ padding as one blob, since a converter cannot split a
      layout it does not know
- [x] **#9b** — unknown flag bit renders as a hex token; the record-flags
      reserved row gained its round-trip clause, completing the row begun in
      Phase 1
- [x] **#9c (JSONL half)** — an enum value with no defined label renders as its
      raw number; noted on the *Enums* bullet and in the escapes table
- [x] **#9a** — prohibition stated: a converter MUST NOT invent an option id;
      reject the line or drop the key, and report it either way
- [x] **#9c (semantic half)** — unknown Source `kind` added to the error tiers as
      an isolatable condition, with `tcp_role` contrasted as advisory, plus a
      note that **`kind` is not a free extension point** — a new value will be
      isolated by existing readers, unlike a new option id
- [x] Checked the *Semantic, not byte-exact* paragraph — it needed a
      parenthetical, since an unrecognised block is now preserved byte-for-byte
      and would otherwise contradict the "never the exact bytes" claim
- [x] Reconciled the two upstream sentences that promised `options` would absorb
      everything unrecognised — they now point at the escapes, and the section
      intro advertises the mirror principle alongside the one-rule formulation

### Phase 3 — Additive vocabulary

- [x] **#12** — `skipped` canonicalised, motivated from the coverage guarantee
      (a decoder skipping a BOM had no honest third option) and from keeping
      `undecodable` usable as a decoder-quality signal
- [x] Two-class structure stated as a table in *Undecoded*: bytes exist
      (`undecodable`, `skipped`) vs hole (`tcp-gap`, `truncated`), with the class
      called out as the only part a consumer acts on
- [x] Unrecognised `reason` settled (§4.2): unknown recoverability, MUST NOT
      assume a class, and specifically MUST NOT assume "hole" — follow the
      reference, report empty only if nothing is found
- [x] `reason` registry row and the *Coverage honesty* narrative both updated
- [x] Considered adding a `skipped` line to the end-to-end decoded example and
      **did not**: its span arithmetic is coverage-consistent as it stands and is
      cited by the byte-level example, so the prose carries the concrete cases
      (BOM, padding, reserved field) instead

### Phase 4 — Taxonomy and derived-file semantics (the substantive work)

#13 case B and the decoded-file offset space are the same underlying question —
what a decoded file looks like as somebody else's input — and must be drafted
together.

- [x] **§4.1 first** — *Each layer has its own offset space* added to
      *Referencing the source by stream offset*: a decoded stream's space is the
      concatenation of that participant's decoded record payloads in stored
      order, explicitly **not** hole-inclusive (Undecoded regions name ranges in
      the input's space, never the output's), and a pass-through defines no space
      of its own. Noted the consequence that reordering or re-chunking a decoded
      participant's records changes its offsets, and so is not a pass-through
- [x] **#13 case A** — *Transforms that change no data* added to *Layers*; an
      annotator is a pass-through, and `origin` names the **immediate** input,
      stated at the `origin` definition too
- [x] **#13 case A consequence** — stated: the output is a *derived* file, so
      capture-level provenance sits one level away, reached through the Source
- [x] **#13 case B** — option 2 implemented. Trichotomy restated as *creates a
      layer / preserves one*, with the preservation obligation total (bytes,
      offsets, `decoder_id`s, `content_type`s, Undecoded blocks) and the four
      "decode-stage only" sites relaxed
- [x] **Discriminator found during drafting** — with `decoder_id` no longer
      implying "this stage decoded it", the taxonomy needed a new machine-checkable
      test. It is **`spans` vs `origin`**: `spans` means this stage built the
      record, `origin` means it re-emitted one. This recovers most of what option
      3 was going to buy, without a third file kind
- [x] Coverage guarantee re-checked — it binds decode stages; for a
      layer-preserving pass-through, total preservation makes the *input's*
      guarantee hold of the output, with no `spans` in the output at all
- [x] **Namespace problem found during drafting** — an inherited Undecoded block
      names a stream in the *grandparent*, so "re-emit unchanged" is unsatisfiable
      unless the pass-through can name that file. Resolved by requiring it to
      declare that Source and make the reference resolve, with a SHOULD-style
      note that keeping the inherited ids lets the blocks be copied verbatim.
      This is the sole exception to "provenance names the immediate input", and
      it is stated as such
- [x] **#14a** — precondition relaxed to "a sound basis" in *Sequenced files* and
      *Conformance*; N = 1 / single-sender stated as trivially sequenceable
- [x] **#14a option** — `sequenced_basis` registered as `0x0053` (string,
      Session). **Open vocabulary** (`clock`/`transport`/`protocol`/`external`),
      matching how `reason` works; SHOULD be set on a hint-less SEQUENCED
      session; unrecognised values and absence are both non-rejectable. No JSONL
      mapping row needed — the general rule covers it, since the key equals the
      option name
- [x] Worked example added: *Annotating a decoded file*, which also demonstrates
      the two-Source shape the namespace rule requires

### Phase 5 — Consistency pass and release

- [x] Bump `version_minor` in the *File Header* table and update the status
      banner and title — **done up front**, along with a new rule that a writer
      stamps the *lowest* minor whose features the file uses (which is why the
      JSONL examples keep `"zipline-payload/1"`: they use no 1.1 feature)
- [x] Create [CHANGELOG.md](../CHANGELOG.md) and point [README.md](../README.md)
      at it
- [ ] Revisit the JSONL `format` strings once 1.1 features actually appear in an
      example — only an example that *uses* one advertises `1.1`
- [ ] Confirm the CHANGELOG's `[Unreleased]` section is the complete 1.0 → 1.1
      delta, then release it as `[1.1]` with a date and a compare link
- [ ] Drop the beta caveat from the status banner and README when 1.1 is final
- [ ] Verify the byte-level worked example
      ([payload-format.md:1508-1591](docs/payload-format.md#L1508-L1591)) is
      unaffected — it should be, since nothing structural changed. If it *is*
      affected, something went wrong in Phases 1–4
- [ ] Re-check every cross-reference and anchor touched by the edits
- [ ] Move anything not adopted into *Possible future extensions*
      ([payload-format.md:1610](docs/payload-format.md#L1610)) — in particular
      generic ordering hints if #14a took the assertion route, and the
      "annotation" derived kind if #13 took option 2
- [ ] **#15** — rename to `zipline-payload-format.md` (kebab-case, no version in
      the name) **in its own commit, last**; update [README.md](README.md) and
      [CLAUDE.md](CLAUDE.md) in the same commit

### Phase 6 — Close the loop

- [ ] Close **#11** with a pointer to
      [payload-format.md:340-368](docs/payload-format.md#L340-L368) and
      [payload-format.md:421-438](docs/payload-format.md#L421-L438) and a note
      that the precondition's scope is now stated more prominently
- [ ] Reply on **#13** about moving the annotation off `comment` (free-text human
      note) to a `Custom` block or a registered option
- [ ] Reply on **#12** noting the `truncated` spelling
- [ ] Close #8, #9, #10, #12, #14, #15, #16 against the landed sections
- [ ] **Strip the issue references from [CHANGELOG.md](../CHANGELOG.md)** — 23 of
      them at present (`(#13)` ×6, `(#9)` ×3, `(#10)` ×3, `(#12)` ×3, `(#14)` ×3,
      and the rest). They are useful while drafting, to trace an entry back to
      the feedback that prompted it, but the changelog's audience is an
      implementer with no access to this repo's issue tracker, to whom a bare
      `(#13)` is noise. Do this **after** the issues are closed, so the trail
      survives in the git history and in this document's §3 rather than being
      lost. Leave this document's own references alone — it is organised by
      issue, so they are its structure
- [ ] Feed the outcome back to the Python implementation — #10 and the Phase 2
      escapes are the items it must change

### Not in scope for this round

Deliberately deferred; recorded so they are not silently lost:

- [ ] Generic transport-neutral ordering hints (`seq_pos`/`cum_ack`) — revisit
      when a transport supplies **both** required properties; RTP-style protocols
      supply only the per-sender position and would gain nothing
- [ ] A machine-checkable "annotation" derived kind (#13 option 3)
- [ ] The two standing *Open questions*
      ([payload-format.md:1603-1608](docs/payload-format.md#L1603-L1608)) —
      compression, and per-session digests on a `zpf-input` Source
