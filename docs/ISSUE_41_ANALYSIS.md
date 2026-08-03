# Issue #41 — analysis

*Analysis of [#41](https://github.com/adamkjonsson/zipline/issues/41) ("Decrypted
tunnels: key the offset space on what a stream is") against **v0.12**, 2026-08-02;
Findings 6 and 7 and their consequences added 2026-08-03. Line references are to
`docs/zipline-payload-format.md` at that version.*

**Status: analysis only.** No spec wording is proposed here. The purpose is to
establish what the problem actually is before deciding which parts of it ship in
which release.

---

## Summary

The issue as filed describes a narrow problem — a decrypted tunnel's inner
streams are transport streams that a decode stage produced, and the offset-space
rule keys on the wrong thing. That description is accurate but the framing is too
narrow in one direction and too broad in another.

**Too narrow:** three of the things #41 treats as tunnel-specific are general
properties of the format, already present today in cases with no tunnel in them.
One of them is a live silent-corruption path in the specification's own flagship
example.

**Too broad:** the fix #41 proposes — reclassify streams by whether they carry
`isn`/`seq_start` — fails on QUIC, and once the general problems are separated
out, the genuinely tunnel-specific remainder needs **no new syntax at all**.

The findings, in the order they were reached:

1. The format already permits and ships byte-transforming decode, in its own
   conformance vector, while the prose says decoders only frame.
2. `spans` cannot mean "what these bytes were computed from" — gzip and HPACK
   make that O(n). It has to mean correspondence.
3. A lost TCP segment under TLS produces a silent splice in `raw → tls-records →
   http`, and the coverage guarantee does not catch it.
4. The fix #41 proposes — infer semantics from `isn`/`seq_start` — fails on QUIC,
   and #41's own load-bearing question is not the load-bearing one.
5. Sessionization is destructive, the spec says so, and the file records almost
   nothing about what was destroyed.
6. "Raw" names *provenance* while reading as *processing state*. That single
   conflation is what makes both remaining problems look like new file kinds.
7. `decoder_id` names the layer *and* selects the offset space. That is the same
   conflation one level down, and it is why reassembly cannot be a decoder —
   which it otherwise plainly is.

---

## Finding 1 — the format already does byte-transforming decode

`vectors/chain/` ships this:

| | input (`raw.zpf`) | output (`decoded.zpf`) | span |
|---|---|---|---|
| pid 0 | `GET /\r\n\r\n` (9 B) | `REQ:GET /` (9 B) | `[0,9)` |
| pid 1 | `HTTP/1.1 200\r\n\r\n` (16 B) | `RESP:200` (8 B) | `[0,16)` |

The reference decoder does not frame — it **synthesizes**. Different bytes, and
on pid 1 a different length: 8 output bytes corresponding to 16 input bytes.

Against that, [line 806](zipline-payload-format.md) states "a decoder *frames* —
it assembles raw bytes into one logical unit and marks its edges", and the
`bytes exist` recoverability class (line 1344) promises a consumer may follow a
span and fetch *the* bytes.

The same assumption fails in the prose. `raw → tls-records → http` is the
specification's flagship chaining example, used at lines 636, 735 and 1284. For
an HTTP decoder to read a TLS-records stream, that stage must **decrypt**. The
canonical example of chaining has always been a decryption chain.

This went unnoticed because `vectors/check.py` verifies coverage of *ranges* and
never payload-to-span correspondence.

**Consequence for #41.** The issue is not requesting a new capability. It is the
first thing to notice that the format has been doing this all along without
writing down what it means. Part of #41 is therefore corrective, not a feature.

---

## The real-world case matrix

The analysis was re-grounded by asking what actually needs representing.

| | Case | Inner offset space | Fan-out? | Bytes exist upstream? | Re-derivable |
|---|---|---|---|---|---|
| A | `Content-Encoding: gzip` body | message (concatenation) | no | **no** | yes |
| B | TLS + keylog → HTTP | message (concatenation) | no | **no** | needs keys |
| C | HTTP/2 → streams | message, per stream | **yes** | no | needs keys |
| D | WireGuard / IPsec → inner TCP | **transport** (`isn`, `seq`, holes) | **yes** | no | needs keys |
| E | QUIC → streams | **transport-ish** (stream offsets, holes, no `isn`/`seq`) | **yes** | no | needs keys |
| F | VXLAN / GRE | n/a — decapsulated inline, one raw file | n/a | yes | n/a |
| G | `SSL_write` hook / terminating proxy | message (concatenation) | no | **no upstream at all** | never |

Row G was added by Finding 6 and was missing from the original grounding, which
is part of why the design below came out more expensive than it needed to be.

Four distinct problems fall out, and only one is about tunnels:

1. **Bytes that don't exist upstream** — A, B, C, D, E. Five of seven, including
   a plain HTTP feature. A property of decoding, not of tunnels.
2. **Session fan-out** — C, D, E. Required by HTTP/2, which involves no tunnel.
3. **Transport semantics in a derived file** — D and E only. This is
   #41-proper, and it is the narrowest of the three.
4. **A decoded layer with no predecessor file** — G only. Not a decoding problem
   and not a tunnel problem; a property of where the file came from.

---

## Finding 2 — gzip is the right lens, and it settles what `spans` means

gzip isolates variables the tunnel case confounds. It is byte-transforming but
needs **no secret**, so it separates "output bytes don't exist upstream" (a
`spans`-semantics question) from "re-derivation needs a key" (a
reproducibility-contract question). #41 treats these as one thing. Only the first
is hard.

gzip also settles the semantics. Deflate is stateful: a byte mid-stream depends
on the whole preceding window. If `spans` means *everything this unit's bytes
were computed from*, an honest gzip decoder emits O(n) spans per record, and
HPACK is worse — every HTTP/2 header block would span every preceding one. No
implementation will do that.

**`spans` must mean the input region this unit *corresponds to*.** That reading
makes gzip, HPACK and decryption all expressible, and it is what the existing
chain vector already assumes.

It has a second effect that was not expected. A decryptor **does** interpret the
nonce and authentication tag — they are inputs to the computation — so under the
correspondence reading an inner record honestly spans the whole ciphertext
packet, framing included. Tunnel-stream coverage then closes with **zero**
Undecoded blocks. The earlier estimate, that the coverage guarantee would cost
roughly one `skipped` Undecoded block per tunnel packet for nonces, tags and
padding, was wrong. This clarification is what makes case D affordable.

Also affected: the reproducibility contract at line 802 ("same input `digest` +
same decoder `version`/`params_digest` ⇒ identical output") remains *true* for a
decryption stage if the key is part of the hashed config, but it becomes a
statement only a key-holder can act on. Verification of the digest chain is
unaffected; third-party regeneration is not possible. Worth one sentence.

---

## Finding 3 — TLS → HTTP splices silently, today

Take the specification's own chain with one TCP segment lost under TLS:

- Stage 1 (`tls-records`) emits an Undecoded block naming the lost range **in
  `raw.zpf`'s offset space**, and records with spans `[0,100)` and `[139,200)`.
- Stage 1's **output** space is the concatenation of its record payloads, so
  those two records are **adjacent** in it. The discontinuity does not exist
  there.
- Stage 2 (`http`) works in stage 1's output space. Nothing obliges a decode
  stage to re-emit its input's Undecoded blocks — that duty falls on
  pass-throughs only (lines 1738–1745) — so stage 2 need never mention the loss.
- Stage 2 emits a record spanning the join and covering it completely.
  **Coverage passes.**

A consumer receives one HTTP message glued from two sides of a hole, with no
marker anywhere in the file it is reading. The information is recoverable in
principle by walking all the way down to `raw.zpf` and noticing the gap between
two stage-1 records' spans, but nothing states that invariant and no checker
tests it.

This is the same failure #41 describes for tunnels — "an inner gap has nowhere to
live" — reached with no tunnel at all, on the most common decode chain in
existence. The coverage guarantee is the format's headline honesty property and
it does not catch this.

**The real subject of #41 is discontinuity propagation through decode chains.**
Tunnels are one instance.

---

## Finding 4 — why the proposed fix fails

#41 proposes: transport semantics when the participant carries `isn` and its
records carry `seq_start`, message semantics otherwise.

**It fails on QUIC (case E).** QUIC inner streams carry explicit offsets in
STREAM frames and have real, known-width holes — transport streams by every
meaningful test — and carry neither a TCP ISN nor a TCP sequence number. The
inference gives them message semantics.

It has a second cost even where it works. Inferring from `isn`/`seq_start` would
**retro-reclassify** an existing raw hint-less UDP stream from transport to
message semantics. Observably harmless (no sequence numbers means no detectable
holes), but it changes what already-conformant files mean in exchange for
elegance.

The issue's own Q2 asks whether the inference misclassifies a hint-less inner UDP
flow. It does, and QUIC makes the consequence material rather than academic.

**On #41's Q3** ("is the two-stage split right, or should decrypt-and-resessionize
be one stage — *this is the load-bearing one*"): as filed, this is misjudged.
Under one stage the output is still inner sessions with `isn`, `seq_start` and
inner gaps in a derived file, so the offset-space rule breaks identically. One
stage saves an intermediate file; it does not dissolve the problem. Q3 is not
load-bearing. The unlisted question — may a stage emit bytes that do not exist
upstream — is.

---

## Finding 5 — sessionization is destructive and the file barely says so

Raised during review of the two-stage question, and it reverses an earlier
conclusion in this analysis that two stages buy nothing.

The specification is explicit about the loss at lines 384–386: "SACK /
retransmission / overlap are resolved by the *reassembler* before records are
emitted; the format records the reassembled result … not raw retransmits."

The sharper case is in the ordering rule at lines 1646–1649: having committed a
gap, a writer "MUST NOT emit the missing bytes if they later turn up — **they are
dropped**; a writer that wants them must have buffered longer." A late segment
arriving after a committed gap is discarded and the file records nothing. That
gap is byte-identical to a genuine loss.

The only existing acknowledgement is a single bit — `retransmit` (`0x0040`),
"retransmission/overlap was resolved inside this record" — with no count, no
extent and no sequence numbers. A consumer learns *that* something was resolved,
never what.

For an ordinary capture the discarded segments still exist in the pcap. **For a
decrypted tunnel they exist nowhere**: the inner packets are the transform's
output and have no other home. So preserving them requires materialising the
packet stream, which requires two stages. Preservation is not a stylistic
preference between decompositions; it is only available under one of them.

### The packet-preserving intermediate is already legal

The per-participant ordering MUST was expected to block it — a packet stream with
retransmits is not in `seq_start` order. It does not. Line 1640 binds records to
"`seq_start` order (**logical stream order for non-TCP streams that have no
sequence numbers**)". A packet-stream record carries no `seq_start` — it is one
opaque inner packet — so the binding clause is *logical stream order*, which for
a concatenation-defined space is stored order. Self-satisfying; no exemption
needed.

A decrypt stage emitting one decoded record per inner packet — payload = the
inner packet, message semantics, duplicates and retransmits as successive records
— is **conformant under 0.12 today**, given only Finding 2's clarification.

There is a confirmation buried in this. Had the packet stream been keyed on *seq*
(transport space), two copies of a retransmitted segment would occupy the **same
offset range**, and the format has no notion of two records at one offset.
Concatenation semantics is the only shape that can hold what needs preserving.

### The payoff exceeds preservation

Stage 2 reassembles that packet stream, and coverage obligates it to account for
every offset of its input. A discarded duplicate, a superseded overlap, a
late-after-gap segment — each is an input region producing no output record, so
each must carry an Undecoded block with a bytes-class reason. The open vocabulary
plus `reason_class` (lines 1367–1372) already covers it: `reason: "duplicate"` /
`"superseded"` / `"late"`, with `reason_class: "bytes"`.

That converts the pipeline's most opaque step into a machine-checkable statement
of what reassembly discarded and where it still lives — with no new syntax.

---

## Finding 6 — "raw" names provenance while reading as processing state

Reached from the vocabulary rather than from a case, after the design below had
been written. It recasts F1, adds case G, and absorbs spin-off 1.

Line 1665 defines the term outright: a **raw** file is "capture-sourced (all its
records reference `capture` Sources)". That is a statement about the *first link
in the provenance chain*. It says nothing about how processed the bytes are, and
line 34 concedes the second reading is false: "a `.zpf` holds the reassembled
bytes, never raw retransmits". A TCP session in a raw file has already been
through a transform that Finding 5 shows is destructive. A UDP session beside it
has not. One file, two processing states, one word covering both — and the word
is the one that reads as "unprocessed".

### Three axes wearing one word

| Axis | Values | Where the spec keys on it |
|---|---|---|
| **provenance** | capture-sourced / `zpf`-sourced | line 1665, and Source `kind` at 1855–1862 |
| **layer** | transport / decoded | lines 707–716, offset-space semantics |
| **processing state** | packets as intercepted / reassembled / decoded ×N | nowhere — not expressible |

The specification treats axis 1 as *implying* axis 2: capture-sourced means
transport layer, `zpf`-sourced means decoded. Both remaining problems are cells
where the implication fails.

| | capture-sourced | `zpf`-sourced |
|---|---|---|
| **no `decoder_id`** (transport layer) | raw record — legal | pass-through — legal · **sessionization stage — forbidden** |
| **`decoder_id`** (decoded layer) | **case G — forbidden** | decode stage, pass-through — legal |

Two of four cells are forbidden, and each forbidden cell is one of the open
problems. The top-right is F1, whose absence is the taxonomy hole named at the
start of this analysis (a `spans`-carrying byte run with no home, lines 1689–1690).
The bottom-left is case G. They are one prohibition seen from two sides.

The spec already asserts the half of the fix that matters, at line 751:
"**`decoder_id` names a layer, not a stage**". Line 1711 then contradicts it —
"a **decoded** record MUST carry a `decoder_id` and reference a `zpf-input`
Source" — by binding the layer axis to the provenance axis. Stating the two
axes as independent is largely a matter of making 1711 obey 751.

### Case G — a decoded layer with no predecessor

A TLS-terminating proxy, an eBPF uprobe on `SSL_write`, a QUIC library's own
stream log: each yields application messages whose generating bytes were never
written to a `.zpf` and never will be. Under 0.12 the only conformant encodings
are to drop `decoder_id` and call them byte runs — losing what the records are —
or to fabricate a predecessor file that never existed.

This is the cleanest motivation for separating the axes, because it carries no
tunnel, no key and no fan-out. It is also common tooling, not a corner.

Two consequences to write down when it is allowed:

- **The coverage guarantee does not apply.** There is no input stream to cover.
  It is already scoped "within each input participant stream" (line 1715), so it
  degrades by itself rather than needing an exception.
- **A Decoder reference becomes a claim of identity, not a recipe.** The
  reproducibility contract at line 802 is not merely key-gated here (Finding 2)
  but vacuous: nothing can regenerate this output. One sentence, and it has to be
  explicit, or verification tooling will assume re-derivation is available.

### It absorbs spin-off 1

Undecoded blocks are barred from capture-sourced files (lines 1720–1721, with
their presence a listed semantic violation at 1827–1828) on the unstated
assumption that capture-sourced means no transform ran. Finding 5 shows a
reassembler *is* a transform with things to declare. Once the assumption is named
as false the prohibition reads as an oversight rather than a design, and the
mechanism is already there: capture-source spans are capture-file byte offsets
(lines 1857–1860). The audit property stops being available to re-sessionization
but not to the head of the pipeline.

### What it does not fix

- **C3 stands unchanged.** A decoded stream's concatenation space still cannot
  express a hole. B and E need the declared-discontinuity block whatever the
  vocabulary is.
- **C2 stands unchanged.** Fan-out is one input stream to many output streams;
  orthogonal to both axes.
- **The unit is the stream, not the session.** Offset spaces are per participant
  stream, and `decoder_id`/`source_id` are per *record* — so mixed-state files
  need no new syntax at all, only the lifting of the two prohibitions above.
  "Session" is the right informal unit; the normative rule has to be per stream.
- **Intra-file derivation stays forbidden.** A file holding a raw session *and* a
  decoded session derived from it cannot work: `spans` name a Source carrying a
  `digest`, and a file cannot contain its own hash. Sessions at differing states
  are fine as long as each one's predecessor is external. This needs saying
  explicitly or it will be attempted.
- **A genuinely raw file is available but not free.** "Only packets as
  intercepted" is Finding 5's packet stream moved to the head of the pipeline.
  For UDP it is conformant today. For TCP it collides with the ordering MUST at
  line 1639, since retransmits are not in `seq_start` order; the derived-file
  escape (records carrying no `seq_start`, so the binding clause is *logical
  stream order*) requires a writer willing to omit sequence numbers from a
  capture-sourced file. Worth a paragraph in its own right, not a blocker here.

### The naming

Retire "raw" as a normative term rather than redefining it. The specification's
own prose already carries unambiguous vocabulary on both axes —
**capture-sourced** (line 1666) and **transport layer** / **decoded layer**
(lines 707–716). "Original" reads well for the first link but reintroduces a
single word for a two-axis position, which is the defect being fixed.

Scope: 86 occurrences of "raw". Prose only — no wire change, and every existing
file stays conformant, since this renames what is already true of them. But it
rewrites the conceptual model, the goals, the terminology paragraph and the
conformance section.

---

## Finding 7 — `decoder_id` selects the offset space, and that is the same conflation

Raised by the obvious objection to the design below: **TCP sessionization is a
decoding step, so why is there no `tcp-sessionize` decoder?** Decision 3 rejected
one in a parenthesis and gave no reason. Examined properly, the objection is
right and the rejection was wrong.

### Why it cannot be a decoder today

Line 1256 makes the field the sole discriminator — "a record is *decoded* iff it
carries a `decoder_id`" — and lines 709–716 bind the consequence: a decoded
stream's offset space is "the concatenation of that participant's decoded record
payloads in stored order", explicitly **not** hole-inclusive.

So a `tcp-sessionize` decoder emits records carrying `decoder_id` → decoded layer
→ concatenation space → **inner gaps have nowhere to live**. That is #41's defect
reconstructed, in the one file kind whose purpose is to hold gaps. The
sessionization stage is characterised by the *absence* of `decoder_id` for
exactly one reason: absence is currently the only way to say "hole-inclusive,
`isn`-anchored".

### Why it should be one anyway

- **Reassembly is the purest instance of the specification's own definition.**
  Line 806: "A decoder *frames* — it assembles raw bytes into one logical unit and
  marks its edges." Finding 1 objects that this is too narrow for real decoders,
  because gzip synthesises. Reassembly is the one transform that fits it exactly,
  and it is the one excluded.
- **Finding 5's gap is a `params_digest` gap.** Overlap policy, buffer depth and
  timeout diverge across implementations; two reassemblers give different output
  from one input and the file cannot tell them apart. The Decoder Descriptor
  (lines 793–795) is precisely that machinery. Under F1 as designed, a
  sessionization stage creates a layer **anonymously**.
- **It collapses F1's ugliest artifact.** F1 must newly permit "Undecoded blocks
  but no Decoder Descriptors", leaving Undecoded's `decoder_id` field — "which
  decoder declined the region", line 1335 — with no referent. With a reassembly
  decoder that combination never arises.
- **The reproducibility contract at line 802 is *true* here**, and unusually
  valuable: unlike the decryption case of Finding 2 it needs no key, and unlike
  case G it is not vacuous. Reassembly is exactly the stage where "same input
  `digest` + same `version`/`params_digest` ⇒ identical output" is both checkable
  and currently unstated.
- Decoder `name` is a free string with no registry, so "minting a `decoder_id`"
  costs nothing. F1's "no registry entry" was never a real contrast.

The diagnosis is Finding 6 one level down: **`decoder_id` does two jobs** —
*what produced this and what is it* (identity, `version`, `params_digest`) and
*which offset-space semantics apply* (layer selection). Reassembly wants the
first and wants **transport** for the second. One field cannot say that.

### The fork

**(a) Make it a decoder, and state the layer explicitly.** The Decoder Descriptor
gains an output-layer attribute; the rule becomes *layer = decoder present ? the
decoder's declared layer : transport*. Existing files are unaffected — no decoder
still means transport.

> Cost: one option, one enum, and rewriting "decoded iff `decoder_id`" wherever it
> is load-bearing (lines 82, 1256–1257, 1688, 1704, 2181). **No reader cost:**
> a decode stage MUST declare every Decoder it references (line 1713), so this is
> an in-file lookup, not decoder knowledge. An unrecognised value in the new enum
> is the same condition as an unrecognised Source `kind` and is handled the same
> way (lines 1855–1862).

**(b) Keep F1 as designed, and route the policy gap to #36.** Lines 767–770
already name this gap for filters and merges — "such a transform's own
configuration has no `params_digest` to live in, so a filtered file records
*what* it was derived from but not *how*" — and track it as
[#36](https://github.com/adamkjonsson/zipline/issues/36). Sessionization would be
the third transform with the same gap, which is an argument that #36 is where it
belongs.

> Cost: no new syntax, but the taxonomy stays three-way and the layer remains
> anonymous until #36 lands.

**Recommendation: (a).** Finding 6's argument is that patching a taxonomy costs
more downstream than factoring it. (b) is a third row added to a two-row table
specifically to avoid making a field mean one thing — the shape Finding 6
condemned. Taking F0 there and (b) here applies opposite reasoning to the same
defect twice.

Two things (a) does **not** force. The head-of-pipeline reassembler **MAY**
declare itself the same way — F0 makes capture-sourced plus `decoder_id` legal —
but this should be SHOULD, not MUST, so every existing raw file stays conformant
and the idiom can migrate. And it does not touch C3: QUIC still cannot express
hole widths without the declared-discontinuity block.

### Typing: the two stages differ

Making reassembly a decoder puts `content_type` within reach of a byte-run
record for the first time, so the chain's two new stages need an answer. They do
not get the same one.

**A reassembly record carries no `content_type`.** `prim:bytes` is mechanically
legal — it places no length constraint, unlike the fixed-width tokens whose width
binds `payload_len` (line 1611) — but it is wrong on the merits. `content_type`
types a *value*: line 806 frames it as "what they **are** (a PNG, a UTF-8 string,
a 64-bit integer)", and `prim:` is a vocabulary of fixed-width scalars with
`prim:bytes` as its escape hatch, meaning *this unit is one opaque value*. A
reassembly record's boundaries are wherever the reassembler chose to chunk; two
conformant reassemblers chunk one stream differently and both are right, which is
the exact property the logical offset space exists to neutralise (line 676,
"makes the raw side's arbitrary chunking irrelevant"). Labelling an arbitrary
window `prim:bytes` asserts it is a unit when it is a slice. It would also type
identical bytes differently by provenance: raw records carry no `content_type`
today, and since decision 5 keeps the head-of-pipeline reassembler at SHOULD, the
same stream would read `prim:bytes` when derived and untyped when captured
throughout the migration.

Absent already means the right thing — lines 809–811, "the payload is opaque and
a consumer falls back to the decoder `name`; the bytes always stay the source of
truth". The fallback naming the reassembler is **decision 5's point**, not a side
effect of it: the layer stops being anonymous, so a consumer reporting
"reassembled by X" where it previously reported nothing is the intended gain.

**A packet-stream record does carry one, and it should be a `dec:` token.** In
Finding 5's packet-preserving intermediate one record *is* one inner packet — a
real unit with real boundaries, not a slice — so the objection above does not
apply. `dec:` is name-scoped to the decoder that emitted it (lines 820–826) and
can state "one inner packet", which is precisely what distinguishes a packet
stream from a byte stream; `prim:bytes` would say only "opaque" and lose the
distinction. So the decrypt stage emits units and types them, and the
sessionization stage emits windows and does not.

---

## Decisions taken during analysis

Recorded because the design below depends on them.

1. **QUIC is in scope.** The design must fit it. This rules out the
   `isn`/`seq_start` inference outright.
2. **The digest-chained provenance edge matters.** "Decrypt to a new pcap, then
   sessionize it normally" — what tooling does today, and free for the format —
   is rejected, because a synthesized pcap breaks re-derivation and verification.
3. **Case D is modelled as a third derived-file kind: a sessionization stage.**
   Chosen over one-stage-plus-declared-holes (which cannot preserve the packet
   stream at all), over supporting both shapes, and over minting a
   `tcp-reassembly` `decoder_id`. *Superseded twice — in form by decision 4, and
   the parenthesised rejection reversed outright by decision 5. The stage itself
   survives both.*
4. **Provenance and layer are independent axes** (Finding 6). Taken last, and it
   is the one the others should have been derived from: it makes decision 3's
   stage an ordinary position rather than an exception, and it is what admits
   case G.
5. **Reassembly is a decoder, and a decoder declares the layer it emits**
   (Finding 7, option (a)). This reverses decision 3's parenthesis. It is the
   only decision in this document that costs new syntax, and it is taken because
   the alternative applies the opposite of decision 4's reasoning to the same
   defect.

---

## The design that survives

### A sessionization stage

A derived file whose transform reads one or more `.zpf` inputs and produces a
**transport layer**: it reassembles byte runs from its input and emits sessions
of byte-run records. The same operation as the head-of-pipeline sessionizer,
with a different input kind — and the specification's terminology (lines 29–41)
already names that operation.

Its output is a transport-layer file: byte-run records, `isn` on participants,
`seq_start` on records, hole-inclusive `isn`-anchored offsets. Identical to a raw
file except that it is `zpf-input`-sourced rather than capture-sourced.

**As first designed it needed no new syntax.** The three-way discriminator falls
out of existing fields:

| Kind | Test |
|---|---|
| pass-through | participants carry `origin`, records carry no `spans` |
| decode stage | records carry `spans` **and** `decoder_id` |
| **sessionization stage** | records carry `spans` and **no** `decoder_id` |

*Finding 7 supersedes this table.* Under decision 5 the stage is a decode stage
like any other — `spans` **and** `decoder_id`, the decoder being the reassembler —
and what makes its output a transport layer is the layer the Decoder Descriptor
declares, not the absence of a field. The discriminator returns to two rows. The
rest of this section stands as written; only the third row goes.

That third row is precisely the taxonomy hole identified at the start of this
analysis — a `spans`-carrying byte run with no home in a taxonomy where "a byte
run is either raw or pass-through, told apart by the Source's `kind`" (lines 84,
1258, 1689–1690, 1704–1733). Naming the stage fills the hole with fields that
already exist.

**Finding 6 recasts this without changing it.** Under separated axes the table
above is not a list of three kinds but a reading of two independent fields:
`decoder_id` gives the layer, Source `kind` gives the provenance. The
sessionization stage is then the `zpf`-sourced transport-layer cell, arrived at
by construction rather than by being named — and case G is the other empty cell,
which the three-kind framing cannot reach at all.

What it delivers:

- **Case D gets transport semantics by construction** — not by inference, not by
  declaration. The rule at lines 707–716 stops being a problem for tunnels.
- **Inner hole widths come from `seq_start`**, exactly as in a raw file.
- **The provenance chain is intact** — records carry `spans` into the packet
  stream, digest-chained (decision 2).
- **Reassembly becomes auditable**, per Finding 5.

The full tunnel chain is then four files, using existing machinery throughout:

```
raw(tunnel) ──decode──▶ packets ──sessionize──▶ inner transport ──decode──▶ http
```

### Cost of the sessionization stage

No new block, no new option, no registry entry. Prose at roughly seven sites:

| Site | Change |
|---|---|
| Conformance, 1665–1745 | "two things, never a mix" becomes three; new bullet; the record-class list gains a fourth entry |
| 1689–1690 | "whether a decoder-less byte run is raw or pass-through is told by the Source `kind`" is now wrong; needs a third arm |
| 707–716 | "a transport stream is one reassembled from a capture" widens to *reassembled, from a capture or from a packet stream in a `.zpf`*. Notably **smaller** than the rekey #41 proposed |
| Undecoded, 1310 and 1720–1721 | Undecoded blocks permitted here; this is what makes discards auditable |
| Conceptual model, 84–89 | byte runs originate in a raw file *or* a sessionization stage |
| Terminology, 29–41 | name the third transform alongside the decoder and the merge |
| Design decisions not taken | record why a third kind is accepted here after being rejected for the annotation case; the document's convention is to keep that reasoning where the question recurs |

One combination that does not exist today: a sessionization file carries
Undecoded blocks but **no** Decoder Descriptors. The Undecoded `decoder_id`
option (line 1335, "which decoder declined the region") is optional and is simply
omitted, but this needs stating, since Undecoded currently implies a decoder
context. *Finding 7 removes this row: with a reassembly decoder there are
Decoder Descriptors and the field has its natural referent.*

Net: the third file kind is **cheaper on the wire than declared holes and more
expensive in prose** — the opposite of the initial estimate, which is why the
recommendation changed.

**Why seven sites, and what Findings 6 and 7 do to the count.** Six of the seven
are places where the specification says "two kinds" and would have to say
"three" — that is, they are the cost of *patching* a taxonomy rather than fixing
it. Under the axis separation the same sites are still touched, but each is
edited toward a general rule instead of gaining an exception, and the edits are
shared with case G and with spin-off 1 rather than being spent on tunnels alone.

Finding 7 then removes the third kind altogether, so the sites specific to *this
stage* reduce to one — lines 707–716, a transport stream may be reassembled from
a `.zpf` — and are replaced by the decision-5 sites, which are shared with every
other decoder:

| Site | Change under decision 5 |
|---|---|
| Decoder Descriptor, 791–802 | one option: the layer this decoder emits; one enum |
| Typing, 804–829 and 1530 | `content_type` is documented for decoded records only; a transport-layer decoder's output is the case where it is deliberately absent (see [Typing](#typing-the-two-stages-differ)) |
| 82, 1256–1257, 1688, 1704, 2181 | "decoded iff `decoder_id`" — five statements of the sole discriminator, each now two questions: is there a decoder (identity), and what layer does it declare (semantics) |
| Enums, 1855–1862 | the new enum joins Source `kind` as load-bearing: a reader that does not recognise the value cannot read the stream's offsets and MUST NOT guess |
| 806 | "a decoder frames" — already flagged by Finding 1; the reassembler is the instance that fits it |

**Revised net.** F1 is no longer syntax-free: it costs one option and one enum,
and it rewrites a discriminator stated in five places. Against that it drops the
third file kind, gives reassembly a `params_digest` and a reproducibility
contract that Finding 5 wanted and could not site, and removes the
Undecoded-without-Decoder oddity. The trade is a wider edit for a narrower
taxonomy, which is the same trade F0 makes.

### A declared-discontinuity block

Separately, cases B and E need a way for a stage to state a discontinuity in its
**own** output space.

- **B (TLS)** cannot know how many plaintext bytes a lost record held. Width
  **unknown**: the marker states that two numerically adjacent offsets are not
  contiguous, and a decoder MUST NOT parse across it. Offsets after it stay
  computable.
- **E (QUIC)** knows the width from STREAM frame offsets, and a sessionization
  stage cannot derive it from a TCP `seq_start` that does not exist.

These are **the same block at different widths** — width absent = unknown, width
present = a real hole. One block, one optional field, both cases. The positional
range rule (lines 718–732) gains one term: record *k* occupies `[Σ(preceding
payload_len + preceding declared widths), + payload_len)`.

It must be a **block**, not an option: its meaning is positional and stored order
is what defines offsets, so it has to interleave with records. Two candidate
shapes, to be settled at drafting time — a new block type, or a zero-payload
Record with a flag and a width option (reusing the ordering and positional
machinery; the format already has zero-length records for pure ACKs). Overloading
Undecoded (`0x21`) looks tempting and is wrong: its body fields are all defined
as reading against the *input*, and it is deliberately byte-identical to a `spans`
entry (lines 1324–1332).

Note that E's clean answer may be the transport-neutral position hint that SCTP
([#45](https://github.com/adamkjonsson/zipline/issues/45)) also wants — the one
rejected in 0.10 under "Transport-neutral ordering hints". #41 and #45 may share
a mechanism.

---

## Decomposition

| | Item | Delivers | New syntax |
|---|---|---|---|
| **C1** | Byte-transforming decode legal; `spans` = correspondence, not identity | gzip (A); resolves the chain-vector contradiction; makes D affordable | none |
| **C2** | Session fan-out permitted | HTTP/2 (C); hard dependency of [#35](https://github.com/adamkjonsson/zipline/issues/35) | none |
| **C3** | Declared-discontinuity block, width optional | TLS→HTTP splice (B); QUIC widths (E) | one block |
| **F0** | Provenance and layer stated as independent axes; "raw" retired | case G; makes F1 a position rather than a kind; absorbs spin-off 1 | none |
| **F1** | Sessionization stage — the `zpf`-sourced transport cell, built as a reassembly *decoder* that declares the layer it emits | tunnels (D), packet preservation, reassembly audit, reassembly policy recorded | one Decoder Descriptor option + one enum |
| **F2** | Tunnel worked example + fixtures | — | none |

### Release recommendation

- **C1, C2 → 0.13.** Pure corrections. C2 must land *before* #35, whose extents
  option has to be repeatable and fully qualified by `(source_id, session_id,
  pid)` if fan-out is legal — otherwise #35 is reopened later.
- **C3 → 0.13.** One self-contained block closing a live silent-corruption path
  in the specification's own flagship chain. Justified independently of tunnels.
- **F0 → 0.14, and F1 depends on it.** Prose-only and wire-compatible, but it
  rewrites the conceptual model, the goals, the terminology paragraph and the
  conformance section. Landing F1 without it means paying most of the same prose
  cost for one of the three things it delivers.
- **F1 → 0.14, after F0.** It rewrites the normative taxonomy and reverses two
  documented decisions, and under Finding 7 it is the one item here carrying new
  syntax. This is the piece to let slip under the ship rule #41 already carries;
  F0 is the piece that makes slipping it cheap, since F0 alone still delivers
  case G. Note the ordering constraint is real and not merely tidy: F0 states
  that provenance and layer are independent, and decision 5 is what gives the
  layer axis somewhere to be written down. Shipping F1 first would mean adding
  the option and then immediately restating what it means.
- **F2 → follows F1.**

Nothing in the 0.13 set is tunnel work, and every 0.13 item is justified by a
case with no tunnel in it. That is a more comfortable position than "#41 ships or
it doesn't".

---

## Spin-offs — not #41's business

1. ~~**A raw file cannot state what its reassembler discarded.**~~ **Absorbed
   into F0 by Finding 6** — the prohibition rests on the same conflation, so it
   is fixed by the same edit rather than separately. Retained here as the record
   of where it was first noticed.
2. **QUIC connection migration versus `endpoint` ordering.** A QUIC connection
   changes its outer 4-tuple mid-connection, so a participant has two outer
   addresses over time; `endpoint` is ordered by tunnel layer, not by time (lines
   1166–1173). An endpoint-modelling problem, independent of offset spaces.

---

## Not yet checked

- **F1 against the merge.** A sessionization stage's output is a transport layer,
  so merging two of them should work unchanged, but this has not been tested
  against [Sequenced files](zipline-payload-format.md) (lines 425+) or the
  `SEQUENCED` / `sequenced_basis` rules.
- **Whether `isn` is already legal on a derived participant.** Line 1706 reads
  "TCP participants **MUST** carry `isn` when the handshake was observed", which
  is not scoped to raw files — but the sentence sits inside the *raw record*
  bullet, so the scope is ambiguous. F1 needs this stated explicitly either way.
- **Whether C3's block should be a new type or a flagged zero-payload Record.**
  A drafting decision, deliberately left open.
- **F0 against the JSONL projection and `vectors/check.py`.** No block or option
  changes, but the checker classifies files, not streams, and would need to
  classify per stream. Expected small; not attempted.
- **Whether a capture-sourced *packet* stream should be legal for TCP** (the
  genuinely-raw file of Finding 6). It needs either an exemption from the
  ordering MUST at line 1639 or a writer that omits `seq_start`. Related to
  Finding 5 and to F0, but not required by either.
- ~~**What a reassembly decoder's `content_type` is, if anything.**~~ **Resolved
  — see below.**
- **Whether decision 5 subsumes part of
  [#36](https://github.com/adamkjonsson/zipline/issues/36).** Reassembly gets a
  `params_digest` under (a); merge and filter still do not. If #36's answer is a
  general per-transform config digest, one of the two mechanisms is redundant and
  the choice should be made deliberately rather than by arrival order.
- **Whether the head-of-pipeline reassembler should eventually be MUST.** Kept at
  SHOULD here for compatibility, which leaves the same logical layer labelled in
  derived files and unlabelled in capture-sourced ones — tolerable, but it is a
  deliberate asymmetry and should be recorded as one.
