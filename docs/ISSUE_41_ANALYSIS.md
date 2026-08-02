# Issue #41 — analysis

*Analysis of [#41](https://github.com/adamkjonsson/zipline/issues/41) ("Decrypted
tunnels: key the offset space on what a stream is") against **v0.12**, 2026-08-02.
Line references are to `docs/zipline-payload-format.md` at that version.*

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

The four findings, in the order they were reached:

1. The format already permits and ships byte-transforming decode, in its own
   conformance vector, while the prose says decoders only frame.
2. `spans` cannot mean "what these bytes were computed from" — gzip and HPACK
   make that O(n). It has to mean correspondence.
3. A lost TCP segment under TLS produces a silent splice in `raw → tls-records →
   http`, and the coverage guarantee does not catch it.
4. Sessionization is destructive, the spec says so, and the file records almost
   nothing about what was destroyed.

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

Three distinct problems fall out, and only one is about tunnels:

1. **Bytes that don't exist upstream** — A, B, C, D, E. Five of six, including a
   plain HTTP feature. A property of decoding, not of tunnels.
2. **Session fan-out** — C, D, E. Required by HTTP/2, which involves no tunnel.
3. **Transport semantics in a derived file** — D and E only. This is
   #41-proper, and it is the narrowest of the three.

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
   `tcp-reassembly` `decoder_id`.

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

**It needs no new syntax.** The three-way discriminator falls out of existing
fields:

| Kind | Test |
|---|---|
| pass-through | participants carry `origin`, records carry no `spans` |
| decode stage | records carry `spans` **and** `decoder_id` |
| **sessionization stage** | records carry `spans` and **no** `decoder_id` |

That third row is precisely the taxonomy hole identified at the start of this
analysis — a `spans`-carrying byte run with no home in a taxonomy where "a byte
run is either raw or pass-through, told apart by the Source's `kind`" (lines 84,
1258, 1689–1690, 1704–1733). Naming the stage fills the hole with fields that
already exist.

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
context.

Net: the third file kind is **cheaper on the wire than declared holes and more
expensive in prose** — the opposite of the initial estimate, which is why the
recommendation changed.

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
| **F1** | Sessionization stage — third derived kind | tunnels (D), packet preservation, reassembly audit | none |
| **F2** | Tunnel worked example + fixtures | — | none |

### Release recommendation

- **C1, C2 → 0.13.** Pure corrections. C2 must land *before* #35, whose extents
  option has to be repeatable and fully qualified by `(source_id, session_id,
  pid)` if fan-out is legal — otherwise #35 is reopened later.
- **C3 → 0.13.** One self-contained block closing a live silent-corruption path
  in the specification's own flagship chain. Justified independently of tunnels.
- **F1 → 0.14.** Prose-only, but it rewrites the normative taxonomy and reverses
  a documented decision. This is the piece to let slip under the ship rule #41
  already carries.
- **F2 → follows F1.**

Nothing in the 0.13 set is tunnel work, and every 0.13 item is justified by a
case with no tunnel in it. That is a more comfortable position than "#41 ships or
it doesn't".

---

## Spin-offs — not #41's business

1. **A raw file cannot state what its reassembler discarded.** Undecoded blocks
   are forbidden there (lines 1720–1721) and their presence is a listed semantic
   violation (lines 1827–1828). Capture-source spans are capture-file byte
   offsets (lines 1858–1860), so the reference mechanism exists; only the
   permission is missing. The audit property from Finding 5 is therefore
   available to re-sessionization but not to the head of the pipeline, which is
   odd.
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
