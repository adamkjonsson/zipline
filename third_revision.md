# Revision of Zipline Payload Format

**Git commit version**: `c21baa17d17a5e258c1acbdd643d48a2daafc9de`

**Date**: 2026-07-08

The standard for Zipline Payload Format is function complete for version 1.0. It has already
undergone two revisions, if no major gaps or mistakes are uncovered in this revision, it
will be named 1.0.

Read the standard with a critical mindset as an implementor for a language would.

Answer the following questions:

1. Is the spec clearly written? 
2. Is the intent and purpose of the format clear?
3. Is it easy to understand what possible use cases it has?
4. Do you think the spec will provide a good solution for these use cases?
5. One of the design goals is that the file format should be easy and fast to use for readers, thus allowing more work for writers. Has that goal been fulfilled? Can anything be changed so that simplify more for readers?
6. Does the spec have any gaps? Is anything missing in it that makes it difficult to implement language support for it?
7. Are there any inconsistencies in the format?
8. Are there features that in your opinion add more complexity than usefulness? Can the standard be simplified with only minor loss in functionality?
9. Does the standard lack useful features given the use cases?
10. The standard has UDP and TCP in mind as transport layer protocols for raw data. Would anything have to change in order to make it useful for SCTP as well?

Provide a list of suggested improvements.

## Claude's review

*Reviewed at commit `c21baa1` against `docs/payload-format.md` (v1.0 beta), as an
engineer who would have to write a from-scratch reader and writer from the
normative binary section.*

### Summary

The spec is in very good shape for 1.0 — the conceptual model is coherent, the
normative binary section is nailed down to the byte, and the worked hex example
removes most of the ambiguity that usually sinks a format spec. I found **one
inconsistency I consider blocking** (the merge transform described in
"Sequenced files" produces a file that is non-conformant under the spec's own
raw/decoded rules — I‑1 below), one namespace ambiguity in the Undecoded block
(I‑2), and a handful of smaller gaps. Separately, two changes would materially
advance the "cheap readers, writers do the work" goal: mandating a single byte
order, and adding a session-end marker so streaming readers get the same
bounded-memory guarantee writers already enjoy.

None of this threatens the design. Fix I‑1 and I‑2, decide on the two
reader-simplification changes (both are breaking, so now — before 1.0 final —
is the last cheap moment), and the document is ready to be called 1.0.

### 1. Is the spec clearly written?

Yes. The split between explanatory narrative and a normative section that
explicitly wins on conflict is the right structure, and the two worked JSONL
examples plus the annotated hex walkthrough are excellent — an implementor can
validate a first reader against the 204-byte example directly.

Two clarity nits:

- The narrative sections remain dense; sentences routinely carry three
  normative-feeling claims at once (the "Sequenced files" and `SINGLE_CLOCK`
  paragraphs especially). Tolerable, since the normative section is the
  contract.
- The Undecoded body table says its `source_id` "resolves the **G1
  ambiguity**" — a dangling reference to a label that exists only in
  `second_review.md`, not in the spec. A reader of the spec alone cannot know
  what G1 is. Replace with a self-contained phrase ("names which input stream
  the offsets index").

### 2. Is the intent and purpose of the format clear?

Yes, unambiguously. The opening paragraph, the Goals list, the terminology
block (producer/reassembler/writer/decoder/consumer), and the "Prior art"
section together make both the purpose and the non-goals (not a capture
format; payload after reassembly, never raw retransmits) clear within the
first page.

### 3. Is it easy to understand what possible use cases it has?

Yes. The three-row table (TCP both directions / chat room / one-way UDP)
anchors the N-participant abstraction immediately, and the two worked examples
show the format doing its two hardest jobs: causally merging a skewed two-file
capture, and deriving a decoded file with honest coverage. The derived-file
chain (`raw → tls → http`) makes the pipeline use case obvious.

### 4. Will the spec provide a good solution for these use cases?

Largely yes. The two standout decisions still hold up: absolute wire seq/ack
as a clock-independent happens-before (with timestamps demoted to
tie-breaker), and decoding as a file→file transform with offset-based
provenance, which genuinely solves the boundary-mismatch ("2.5 records")
problem. The new-since-last-revision pieces — `SEQUENCED`, `SINGLE_CLOCK`, the
last-packet timestamp rule, RFC 1982 arithmetic, `isn` as stream origin — are
well reasoned and mostly well integrated.

One reservation: the **merge transform** (`sideA.zpf + sideB.zpf →
merged.zpf`), which the spec presents as the way two-tap captures get
sequenced, cannot currently be written conformantly (I‑1 below). Since
sequenced two-tap TCP is one of the format's flagship use cases, this needs to
be resolved before 1.0.

### 5. Has the "easy/fast for readers, work on writers" goal been fulfilled?

Mostly, and the spec is explicit about the mechanisms: declare-on-first-use
(readers build tables incrementally, no back-patching), the per-participant
`seq_start` ordering that collapses the merge to a streaming k-way merge,
`SEQUENCED` sessions that eliminate reader-side ordering entirely, 4-byte
alignment for cheap field access, and skip-by-length forward compatibility.
The merge-transform idea — "the expensive logic exists in exactly one tool,
never in every reader" — is exactly the right instinct.

Three places still put work on readers that writers could absorb:

- **Dual byte order.** Every reader must implement the BOM bootstrap and carry
  two decode paths (or byte-swap wrappers) forever, so that writers on
  big-endian hosts can avoid a swap. That is writer convenience purchased with
  reader complexity — precisely backwards relative to the stated goal.
  **Mandate little-endian**, keep the BOM at offset 8 purely as magic/sanity
  check. Writers on BE hardware (rare) swap; every reader gets simpler. This
  is a breaking change, which is why it should happen now.
  **→ RESOLVED** — little-endian is mandated without exception; `bom` is
  renamed `magic` (a plain file signature at offset 8) and the endianness
  bootstrap is deleted. The `prim:` `-be`/`-le` suffixes were dropped in the
  same change: fixed-width `prim:` payloads are stored little-endian,
  normalized by the emitting decoder.
- **Per-participant ordering is only SHOULD.** A conformant reader must
  therefore implement the sort fallback for out-of-order per-participant
  records — code that in practice never runs. The spec itself argues the
  ordering "costs the writer nothing — each participant's byte stream is
  monotonic by construction." If it costs the writer nothing, make it a
  **MUST** and let readers reject or best-effort a violating file instead of
  carrying a dead sort path.
  **→ RESOLVED** — upgraded to MUST at all four sites (merge algorithm, merge
  cost, Identifiers & ordering, Conformance). A reader meeting an out-of-order
  record MAY reject the file or discard the session and is never required to
  reorder; the committed-gap corner is pinned down (late-arriving bytes for an
  already-committed gap are dropped, never emitted out of order).
- **No session-end marker** (see question 9): writers are flush-and-forget,
  but a streaming reader can never free a session's state, so on unbounded
  input the reader's session table grows without bound. The bounded-memory
  guarantee currently exists on the write side only.

### 6. Does the spec have any gaps?

Beyond I‑1/I‑2 (filed under inconsistencies), the gaps are small:

- **Reader behavior on conformance violations is unspecified.** What MUST a
  reader do when a record references an undeclared `session_id`/`pid`/
  `source_id`, an id is reused, `seq_end ≠ seq_start + payload_len`, an
  Undecoded block appears in a raw file, or bytes follow the End block? The
  spec is thorough about *writer* obligations but silent on whether a reader
  rejects the file, skips the block, or may proceed. One short paragraph — a
  general rule such as "a reader that detects a violation of a MUST may either
  reject the file or discard the offending block, but MUST NOT silently
  reinterpret it" — would keep implementations from diverging.
  **→ RESOLVED** — a two-tier "Error handling" passage was added to
  Conformance: structural corruption (bad magic, misplaced/absent header,
  unsupported major version, `tick_hz = 0`, unaligned `length`, TLV overrun)
  MUST reject the file, with truncation explicitly carved out as an expected
  condition; semantic violations in well-framed blocks (undeclared/duplicate
  ids, misplaced blocks, coverage failures) MAY be isolated per block or
  session, never silently reinterpreted or repaired, with tolerated
  violations SHOULD-reported. Bytes after a valid End block leave the file
  complete but MUST NOT be interpreted and SHOULD be reported.
- **The 64 KB TLV value cap is never acknowledged.** `len: u16` caps every
  option value at 65 535 bytes — in particular `spans` at ⌊65535/28⌋ = 2340
  entries per record. Probably ample, but the spec should state the limit and
  say what a writer with more spans does (split the record).
  **→ RESOLVED** — the 64 KB cap is stated in the TLV framing section, and
  `spans` became a repeatable id: successive occurrences concatenate into one
  list, lifting the per-occurrence 2340-entry ceiling (writers SHOULD coalesce
  adjacent ranges first).
- **SYN-flag records are underspecified.** The `syn` record flag exists, but
  nothing says what such a record looks like (zero-length? what `seq_start` —
  the ISN itself, occupying sequence space?). Either specify it in one
  sentence or drop the flag (the handshake is already captured by `isn` +
  `tcp_role`).
  **→ RESOLVED** — specified: a "Handshake records" paragraph defines the
  `syn` record as zero-length, `timestamp` = the SYN packet's time,
  `seq_start` = `isn + 1`, so causal edges and ordering work unchanged; it
  carries handshake *timing*, identity stays on the participant.
- **`proto` is an open vocabulary.** `tcp`/`udp`/`irc`/`http`/`tls` are given
  as examples, not a registry. Interop nit: one tool's `http` is another's
  `http/1.1`. A short "well-known values" list with a rule for private values
  would be cheap insurance.
  **→ RESOLVED** — well-known values `tcp`/`udp`/`http`/`tls`/`irc`/`dns` in
  both the Session Descriptor text and the registry; other values permitted,
  MUST be lowercase, unrecognized treated as opaque.

### 7. Are there any inconsistencies in the format?

- **I‑1 (blocking): the merge transform's output file is non-conformant.**
  "Sequenced files" says two separately-captured directions are combined by a
  merge transform that "reuses the existing derived-file machinery" —
  `zpf-input` Sources, digests, provenance. But the merged file's records are
  still raw byte runs: no decoder ran, so they carry no `decoder_id`. The
  Conformance section then forbids the result twice over: "a **raw** record
  carries no `decoder_id`, and its `source_id`/`spans` reference a **capture**
  Source; it appears only in a raw file" (the merged records reference
  `zpf-input` Sources), and "Decoder, Undecoded, and `zpf-input` Sources
  appear only in files that carry decoded records" (the merged file carries
  none). As written, `merged.zpf` is neither a valid raw file nor a valid
  derived file, and an implementor cannot know what to emit. Fix options:
  (a) generalize "derived file" to "the output of any file→file transform" and
  allow decoder-less records whose `source_id` is a `zpf-input` (spelling out
  how such a file expresses gaps — implicitly like a raw file, or via
  Undecoded); or (b) model the merger as a degenerate identity "decoder" (this
  strains the decoder concept and forces 1:1 spans, so (a) is better).
  **→ RESOLVED** — option (a) adopted. A derived file is now the output of any
  file→file transform and is exactly one of a *decode stage* or a *pass-through
  transform*; the merge writes **pass-through records** (decoder-less byte runs
  referencing `zpf-input` Sources) with gaps kept implicit, stream bytes and
  logical offsets preserved, and each participant carrying a new `origin`
  option (`0x0064`) that maps it to its input stream in the source's id
  namespace. See the reworked Conformance section and the merged-file example
  under "Sequenced files".
- **I‑2: the Undecoded block straddles two id namespaces.** Its body declares
  `session_id` as "in *this* file" and `participant_id` likewise, yet
  `off_start`/`off_end` are offsets in the **input** (`source_id`) stream —
  and the spec elsewhere insists a span's `session_id`/`pid` are read "in the
  referenced *source's* id namespace, never the current file's." So which
  input stream do an Undecoded block's offsets index? It works only while
  output ids coincide with input ids, which the spec explicitly does not
  require — and the `SINGLE_CLOCK` discussion even anticipates transforms that
  *regroup* input streams into new sessions, where the implicit mapping breaks
  outright. The coverage guarantee ("every offset of each **input**
  participant stream is covered by `spans` or Undecoded") is then unverifiable.
  Fix: make Undecoded name the input stream the way `spans` already does —
  its `session_id`/`pid` should be in the *source's* namespace (or carry both
  pairs explicitly).
  **→ RESOLVED** — source-namespace option adopted. The Undecoded body now
  names the input stream in the referenced source's id namespace and was
  reordered to be byte-identical to a packed `spans` entry (`source_id, pid,
  session_id, off_start, off_end`); the this-file link is gone (consumers
  correlate holes via decoded records' `spans` citing the same input stream),
  and the coverage guarantee is restated over source-namespace streams. The
  dangling "G1 ambiguity" reference was removed in the same edit.
- **I‑3: `ack` is defined off by one.** Prose and registry say "highest
  absolute peer sequence number the sender had received," but the worked
  example stores `ack:1019` for a peer stream whose highest received byte is
  1018 — i.e. the field holds the raw wire ACK (next expected byte, one past
  the last received), which is also what the merge rule `seq_end ≤ ack`
  assumes. The value and algorithm are right; the English definition is wrong.
  Define it as "the acknowledgement number from the wire: one past the highest
  contiguous peer byte received."
  **→ RESOLVED** — both definition sites (the "Fields used" table and registry
  id `0x0072`) now carry the wire-ack wording; the guarantee, merge rule, and
  examples were already consistent with it.
- **I‑4: `seq_end` is redundant and its failure mode is undefined.** It is
  *defined* as `seq_start + payload_len (mod 2³²)`, so it carries no
  information, costs 8 bytes of TLV per record, and creates an inconsistency
  class the spec never addresses (what does a reader do when it disagrees?).
  Drop it, or make it optional-and-checked. (Contrast the `prim:` width rule,
  which does specify its mismatch behavior — the spec already knows redundant
  fields need one.)
  **→ RESOLVED** — dropped entirely. A record's end is defined once (under
  "Fields used") as the computed `seq_start + payload_len` (mod 2³²); the
  merge algorithm, examples, conformance bullets, and hex walkthrough (now
  196 bytes) use the derived value, and registry id `0x0071` is removed.
- **I‑5: JSONL examples omit the Source `kind` body field.** The mapping rule
  says body fields project under their canonical names and only *options* may
  be absent, yet the chat and two-file examples write
  `{"type":"source","source_id":1,"uri":"…"}` with no `"kind"`. Either fix the
  examples or (better, given `capture` is the common case) state a JSONL
  default: absent `kind` means `capture`.
  **→ RESOLVED** — always-explicit chosen (no default): the three capture
  `source` lines now carry `"kind":"capture"`, and the mapping rule states
  body fields always project (only options may be absent).
- **I‑6 (editorial): the flag-boolean keys are undeclared aliases.** The
  mapping section promises the brevity-alias table lists *the only* keys whose
  JSON name differs from the binary name, but the `flags` bitfields project as
  `"single_clock"`/`"sequenced"` booleans — a rename declared only in the
  value-encoding bullet. Add them to the alias table or note the exception.
  **→ RESOLVED** — both added as alias-table rows; the table's "the only
  keys" claim is now accurate (a Record's `flags` array keeps its own key).

### 8. Do any features add more complexity than usefulness?

The format is lean overall; nothing here is bloated. In descending order of
my confidence that it could go:

- **`seq_end`** — pure redundancy (I‑4). Cut it.
- **The `prim:` content-type scheme** plus its `payload_len`-binding rule is
  the least-earning feature: a closed 17-token vocabulary, a width-consistency
  conformance rule, and a mandated mismatch behavior, all to label a record as
  "a u32". A decoder that frames fixed-width scalars can label them with its
  own `dec:` tokens at zero spec cost. Cutting `prim:` loses only
  cross-decoder scalar interop — minor.
- **`ts_first`** — recoverable from capture-source `spans` provenance, as the
  spec itself notes. Harmless (one optional TLV), but a cut candidate if you
  want maximal leanness.
- **Name/Identity Resolution (`0x30`)** overlaps Participant
  `identity`/`endpoint`, but its append-only after-the-fact labelling is a
  real capability the inline options cannot replicate. Keep.

Everything else earns its keep — including `SEQUENCED`/`SINGLE_CLOCK`, which
add prose weight but move real work off readers.

### 9. Does the standard lack useful features given the use cases?

One real omission: a **session-end marker**. The writer's contract is
"flush a finished session and forget it," but nothing in the stream tells a
reader the session is finished. Consequences: a streaming consumer of an
unbounded intercept can never free per-session state (unbounded reader
memory, mirroring the exact problem the format solves for writers); and a
tailing consumer cannot distinguish "session idle" from "session over."
An optional block (say `0x12`, body `session_id` + a `reason`/`how-it-ended`
option: fin/rst/timeout/eof) that a writer emits when it flushes-and-forgets
would close this cheaply and stays fully append-only. Strongly recommended;
after 1.0 it can only be a SHOULD that old files lack forever.
**→ RESOLVED** — Session End block `0x12` added (body `session_id`, optional
`reason` `0x00C0` with open vocabulary `fin`/`rst`/`timeout`/`capture-end`).
Writers SHOULD emit it on flush-and-forget; it is a hard barrier (no later
block of any kind may reference the session — late Name/Identity labels go
first); readers MAY free session state on sight, MUST NOT require it, and
EOF/End closes remaining sessions. Integrity counts deferred to "Possible
future extensions".

Smaller wishes, all fine to defer: the compression story (already an open
question), the random-access index (already sketched), and a capture-drop
counter (packets the capture layer lost — today only inferable as TCP gaps).

### 10. What would have to change for SCTP?

The container survives untouched — new TLVs and enum values suffice, no frame
or block changes — but four SCTP realities don't fit the current *semantics*:

1. **Multiple streams per association.** An SCTP association carries many
   independent ordered streams (stream ids), each with its own SSN. The format
   models one logical byte/message stream per participant: per-participant
   ordering, and crucially the **logical-offset space** that `spans`/Undecoded
   index, both assume it. Decoding a multi-stream association needs a
   per-record `stream_id` (new u16 TLV) and offset spaces scoped to
   `(session, pid, stream_id)`. Modelling each SCTP stream as its own session
   or participant technically works today but scatters one association across
   entities and misrepresents the participant concept.
2. **Ordering hints are TCP-byte-shaped.** `seq_start`/`seq_end`/`ack` count
   bytes; SCTP sequences *chunks* (32-bit TSNs) and acks with a cumulative TSN
   in SACKs. The good news: TSNs are serial-number arithmetic like TCP seqs,
   acks are cumulative, and the merge algorithm generalizes directly — "peer
   record precedes R iff its `tsn ≤ R.cum_tsn_ack`." Needed: `tsn` and
   `cum_tsn_ack` record options (and the merge text rephrased over an abstract
   "sequence/ack hint" rather than TCP fields). `seq_end` has no SCTP meaning
   at all — one more argument for cutting it (I‑4).
3. **The `isn` anchor has an analogue** (the initial TSN from the INIT chunk)
   but it anchors *chunk* numbering, not a byte offset, so the "first byte =
   isn+1 / leading hole `[0, K)`" mechanism doesn't transfer; pre-capture loss
   detection would be in messages, not bytes.
4. **Multi-homing collides with the tunnel convention.** An SCTP endpoint has
   several addresses, but repeated `endpoint` options already mean tunnel
   layers, outermost→innermost — the two meanings cannot share the option. A
   new repeatable option (e.g. `endpoint_alt`) or an address-set convention is
   needed.

Message orientation itself is a non-issue — the `datagram` flag already says
"record = one message" (just reword its UDP-specific description). My
recommendation for 1.0: don't add SCTP, but (a) cut `seq_end`, (b) reword the
`datagram` flag and the merge algorithm in transport-neutral terms, and
(c) note `stream_id`/`tsn`/`cum_tsn_ack` as the reserved extension path. That
makes SCTP a pure minor-version addition later.

### Suggested improvements

Prioritized; 1–4 are the ones I would not ship 1.0 without.

1. ~~**Resolve the merge-transform contradiction (I‑1).**~~ **DONE** — derived
   files generalized to any file→file transform; a merge now writes a
   *pass-through* file (decoder-less byte runs referencing `zpf-input` Sources,
   per-participant `origin` provenance, offsets preserved, gaps implicit). See
   the I‑1 resolution note above.
2. ~~**Fix the Undecoded namespace (I‑2).**~~ **DONE** — Undecoded body ids
   are now in the source's namespace, the body layout is span-entry-identical,
   and the coverage guarantee is restated in those terms. See the I‑2
   resolution note above.
3. ~~**Mandate little-endian.**~~ **DONE** — the container is little-endian
   without exception, `bom` is now the `magic` file signature, the bootstrap
   is gone, and the `prim:` `-be`/`-le` suffixes were dropped (fixed-width
   `prim:` payloads are little-endian, decoder-normalized). See the resolution
   note under question 5.
4. ~~**Correct the `ack` definition (I‑3)**~~ **DONE** — defined at both sites
   as the wire acknowledgement number, one past the highest contiguous peer
   byte received.
5. ~~**Drop `seq_end`** (I‑4)~~ **DONE** — dropped entirely; readers compute
   the record end as `seq_start + payload_len` (mod 2³²). See the I‑4
   resolution note above.
6. ~~**Add an optional Session End block**~~ **DONE** — block `0x12` with
   SHOULD-on-flush, hard barrier, and optional `reason`. See the resolution
   note under question 9.
7. ~~**Upgrade per-participant `seq_start` order from SHOULD to MUST**~~
   **DONE** — MUST at all four sites, with the violation rule (reader MAY
   reject file or session, never required to reorder). See the resolution
   note under question 5.
8. ~~**Add a reader error-handling paragraph**~~ **DONE** — two-tier rule in
   Conformance (structural → MUST reject; semantic → MAY isolate, never
   reinterpret; SHOULD report), with truncation carved out and the after-End
   rule specified. See the resolution note under question 6.
9. ~~**Fix the JSONL examples / define a `kind` default (I‑5)** and add the
   flag-boolean keys to the alias table (I‑6).~~ **DONE** — examples made
   explicit (no default), alias rows added. See the I‑5/I‑6 resolution notes.
10. ~~**State the 64 KB TLV cap**~~ **DONE** — cap stated; `spans` made
    repeatable (occurrences concatenate) as the overflow rule.
11. ~~**Editorial:**~~ **DONE** — the "G1 ambiguity" reference was fixed with
    I‑2; the `syn` flag is now specified ("Handshake records"); `proto` has a
    well-known-values list.
12. **Future-proofing for SCTP (question 10):** reword the `datagram` flag and
    merge algorithm transport-neutrally, and note `stream_id`/`tsn`/
    `cum_tsn_ack` as the reserved extension path.
