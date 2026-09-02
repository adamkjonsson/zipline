# Zipline Payload Format (v0.18)

> Status: **version 0.18** — a design in progress. **`0.x` means exactly what it
> says**: any minor release may change anything, including in ways that break
> existing readers. Do not build production on it. `1.0` is reserved for a
> specification that has survived implementation, and this one has not yet.
> `0.10` was the first revision informed by a real implementation; `0.11`,
> `0.12`, `0.14`, `0.16` and `0.18` corrected what successive reviews of them
> found; `0.13` was the first since `0.9` to *add* capability rather than only
> correct, `0.15` is the first to change what already-written files mean, and
> `0.17` the first driven by an implementation decoding at field granularity.
> More are expected.
>
> **On the renumbering.** A release was designated `1.0` in July 2026, before any
> implementation existed. That was premature, and the work that followed —
> collected here — breaks it. Rather than disguise that as a minor bump, the July
> release is retroactively designated **`0.9`**; `0.10` through `0.18`
> followed. Note `0.18` is *greater* than `0.9`: the components are independent integers, never a
> decimal fraction. See [CHANGELOG.md](../CHANGELOG.md) for the delta and
> [implementation-review-response.md](implementation-review-response.md) for the
> reasoning.
>
> While `version_major` is `0`, a reader **MUST reject** a `version_minor` it does
> not implement — nothing is guaranteed to survive a `0.x` bump (see
> [File Header](#file-header-0x01)).
>
> This document specifies the **Zipline Payload Format** (`.zpf`), a file format
> for the *payload* output of a network sessionizer: the bytes that flow between
> endpoints once packets have been reassembled into sessions, plus the metadata
> needed to consume them. The format is tool-independent — any program can read or
> write it.

**Terminology.** The **producer** (a *sessionizer*) writes a `.zpf`; a
**consumer** (or *reader*) reads one. Two producer stages are named where the
distinction matters. The **reassembler** turns each direction's raw TCP segment
stream — out-of-order, retransmitted, overlapping — into one clean, in-order byte
stream; the **writer** emits that result as blocks. Reassembly always completes
*before* a record is written, so a `.zpf` holds the reassembled bytes, never raw
retransmits (see [Caveats](#caveats)). A **transform** is a separate, later stage
that derives a new `.zpf` from one or more existing ones. This spec defines two:
the **decoder**, which derives a decoded stream from a transport one (see
[Layers](#layers-transport-and-decoded-live-in-separate-streams)), and the **merge**,
which combines separately-captured directions into one sequenced `.zpf` (see
[Sequenced files](#sequenced-files-precomputed-order)).

## Goals

- Hold **more than one session** per file.
- Model a session as **N participants**, not two "sides". Both directions of a
  TCP connection is the `N = 2` case; a chat room is `N > 2`; a one-way UDP
  feed is `N = 1`.
- Keep the **reassembled transport bytes** as the source of truth. A decoded view
  is a *separate stream*, derived and held in its own file, not a layer inside the
  record (see
  [Layers](#layers-transport-and-decoded-live-in-separate-streams)).
- Be **append-only / streamable** so a writer can flush a finished session and
  forget it, keeping memory bounded on unbounded input — and so a reader can do
  the same, dropping a session's state at its
  [Session End](#session-end-0x12) marker.
- Carry timestamps on a **packet-time clock** (capture time), never wall clock,
  so replay is deterministic and live/offline captures order identically.
- Reconstruct cross-participant **interleaving from TCP seq/ack**, not just
  timestamps, so two sides captured in *separate files with skewed clocks* can
  still be ordered correctly (see [Causal ordering](#causal-ordering-from-tcp-seqack)).

## Conceptual model

Three nesting levels:

```
File
└── Session            (id, protocol, key, metadata)
    ├── Participant     (local id, endpoint/identity, per-side metadata)
    ├── Participant
    └── Record …        (sender participant, timestamp, payload, ordering hints)
```

A **record** is one directed payload unit: it names the session, the **sender**
participant, a packet-time timestamp, the payload bytes, and ordering hints. It
names no recipient — a record is implicitly addressed to **every other
participant in its session**: the single peer when `N = 2`, the whole room when
`N > 2`, and no modelled party for a one-way `N = 1` feed. ("Directed" here means
the record has a sender and a direction, not a specific addressee.) A
record may be either a *byte run* (transport-truthful; boundaries fall where
reassembly produced them) or a *decoder-imposed unit* (boundaries set by an app
decoder). Which one a record is follows from its stream's **layer**, defined
below: a transport-shaped stream holds byte runs, a decoded-shaped one holds
units. It does **not** follow from whether the record carries a `decoder_id` —
reassembly is a decoder too, so a reassembly record carries one and is a byte run
all the same. What a unit *means* (HTTP message, TLS record, …) comes from the
referenced decoder, not from any separate marker on the record.

**Provenance and layer are independent axes, and this document keys on both.**
Where a stream's bytes came from and what shape they have are different
questions, and neither answers the other. **This is the statement; everywhere
else refers to it.**

- **Provenance** — was this stream *captured* or *derived*? Told by the `kind` of
  the [Source](#source-descriptor-0x02) its records reference: `capture` or
  `zpf-input`.
- **Layer** — is this stream *transport*-shaped or *decoded*-shaped? Two questions,
  because `decoder_id` answers only the first: **is there a decoder**, and **what
  layer does that decoder declare**. The rule is *layer = decoder present ? the
  decoder's declared [`output_layer`](#decoder-descriptor-0x03) : transport*.
  Every Decoder Descriptor carries an `output_layer`, so the first question has no
  undefined answer and the second has no default. The layer fixes the stream's **offset
  space**, which is the consequence that matters (see
  [Layers](#layers-transport-and-decoded-live-in-separate-streams)).

  Splitting the question is what lets **reassembly be a decoder**. `decoder_id`
  was doing two jobs — *what produced this and what is it*, and *which offset-space
  semantics apply* — and a reassembler wants the first while wanting **transport**
  for the second. One field could not say that, so a sessionization stage was
  characterised by the *absence* of `decoder_id`, purely because absence was the
  only way to say "hole-inclusive, `isn`-anchored". Its configuration then had
  nowhere to live and the layer it created had no name.

All four combinations occur, and none implies another:

|                     | capture-sourced | `zpf`-sourced |
|---------------------|-----------------|---------------|
| **transport layer** | a capture's reassembled streams | a **sessionization stage** — a reassembler run over a `.zpf`, declaring `output_layer = transport`; or a pass-through preserving one |
| **decoded layer**   | a decoder with no predecessor file: a TLS-terminating proxy, an `SSL_write` uprobe, a QUIC library's own stream log | a decode stage's output, or a pass-through preserving one |

Reading the layer off the provenance is the mistake this table exists to prevent,
and the bottom-left cell is where it bit: a proxy's decoded output has no
predecessor `.zpf` and never will, so a rule that inferred "decoded" from
"derived" left it with no honest encoding at all.

**The unit is the stream, not the file.** `decoder_id` and `source_id` are
per-record, so one file MAY hold streams at different positions in that table and
needs no syntax to say so. What a file MUST NOT do is derive one of its own
streams from another: every derived stream's predecessor is a *different* file.
The reason is not the `digest` — that option is optional, so a file could omit it
and the prohibition still holds. It is that a stage reads its input and then
writes its output, so a file cannot be among its own inputs without the offsets
its `spans` name having been fixed before the file that contains them existed.

**Detecting it needs a name the file does not carry.** There is no in-band
self-identifier: the only signal is a `zpf-input` Source's `uri`, so a reader
handed a **path** compares the two after normalisation and MAY isolate on a match,
while a reader handed a file object — stdin, a socket, a tar member, all of which
a reader may legitimately accept — cannot, and is **not obliged to detect it**.
The rule binds the writer either way. This is stated so that a reader which cannot
check is not thought non-conformant, and so that one which can knows what to
compare.

A byte-preserving transform (a [merge](#sequenced-files-precomputed-order))
re-emits byte runs into its output, where they are *pass-through records*. Such a
transform preserves whatever layer it was handed, so one applied to a *decoded*
stream re-emits decoded records instead, `decoder_id`s and all (see
[Conformance](#conformance)).

Transport and decoded records rarely share boundaries, so decoding is a
*stream → stream* transform carried out file to file, not a layer inside a record
(see [Layers](#layers-transport-and-decoded-live-in-separate-streams)). A decode
stage holds decoder-imposed records, and regions a decoder *could not* parse
become **[Undecoded](#undecoded-0x21)** markers pointing back at the
predecessor's bytes (nothing is silently dropped).

This single shape expresses all the target cases:

| Case                       | Participants | Record sender |
|----------------------------|--------------|---------------|
| TCP, both directions       | 2            | A or B        |
| Chat room, 5 people        | 5            | whoever spoke |
| One-way UDP / multicast    | 1            | the source    |

## Encoding: two faces of one model

The canonical format is a **framed binary container** (pcapng-style: typed
blocks, each carrying TLV options for forward compatibility). A documented
**JSON-Lines projection** is the "easily consumed" face — one JSON object per
line, payloads base64-encoded — for debugging and small captures. Both encode
the same model; a converter is lossless binary → JSONL → binary for the core
fields.

### Binary container layout

A file is a sequence of length-prefixed blocks:

```
+--------+----------+--------+-----------------------+----------------+
| type   | reserved | length | body                  | options (TLV)  |
| u16    | u16 (=0) | u32    | (block-specific)      | until length   |
+--------+----------+--------+-----------------------+----------------+
```

Block types:

| Type | Name                    | Purpose                                        |
|------|-------------------------|------------------------------------------------|
| 0x01 | File Header             | magic, format version, time units, build provenance |
| 0x02 | Source Descriptor       | one input these bytes came from — a *capture* (file/interface) or another *`.zpf`* this file was derived from; has an id and a `kind` |
| 0x03 | Decoder Descriptor      | a decoder's id, name, version, params digest    |
| 0x10 | Session Descriptor      | session id, protocol, flow key, metadata        |
| 0x11 | Participant Descriptor  | participant id within a session, endpoint, TCP ISN |
| 0x12 | Session End             | optional: no further blocks reference this session; how it ended |
| 0x20 | Record                  | a directed payload unit (see fields below)      |
| 0x21 | Undecoded               | a region the transform did not decode, referencing the predecessor's bytes (see Layers) |
| 0x22 | Discontinuity           | a break in *this* file's own output stream — the records either side are not contiguous, whether or not the gap's width is knowable |
| 0x30 | Name/Identity Resolution| optional: map participant ids → human labels    |
| 0x41 | End                     | optional; if present, the last block — marks the file complete |
| 0xFF | Custom                  | vendor/experimental, namespaced                 |

A single **Source Descriptor** type covers both a capture and a derived input
(`kind = capture` vs `kind = zpf-input`), so a record references its origin the
same way whether it was captured or derived. The Decoder Descriptor belongs to
wherever a `decoder_id` is referenced and the Undecoded block to wherever a stage
names an input it did not fully consume; the
[Discontinuity](#discontinuity-0x22) block is the one restricted to a *decoded*
layer (see [Conformance](#conformance)). See
[Layers](#layers-transport-and-decoded-live-in-separate-streams).

TLV options are `id: u16, len: u16, value: bytes`, repeated until the block
ends. Unknown option ids are skipped, so the format extends without a version
bump: new per-session / per-participant attributes are just new TLVs, and old
readers ignore what they do not understand.

The tables above are the *overview*; exact widths, alignment, the option-id
registry, and conformance rules are pinned down in
[Binary encoding (normative reference)](#binary-encoding-normative-reference).

### Declaration order: declare-on-first-use

The nesting in [Conceptual model](#conceptual-model) is *logical*, not a
physical layout requirement. Descriptors are ordinary blocks in the stream; the
only rule is that **a descriptor must precede the first block that references
it**. Nothing has to be listed up front.

This is what makes the format genuinely append-only and matches a
flush-and-forget writer — a writer never has to buffer a roster of sessions or
participants to emit up front:

- A **session** is declared the moment its first packet is sessionized, not in a
  table at the head of the file.
- A **participant** is declared when it first *appears*. The two sides of a TCP
  connection are typically known at the SYN, but a **chat room grows**: when a
  fourth person joins mid-capture, emit a Participant Descriptor at that point
  and start referencing it. No back-patching, no placeholder entries.
- The same holds for **Decoder** and **Source** descriptors in derived files.

A consumer therefore builds its session/participant tables incrementally as it
reads, exactly as the writer built them — and tears them down incrementally
too: the mirror of declare-on-first-use is **end-on-flush**, a
[Session End](#session-end-0x12) block the writer SHOULD emit at the moment it
flushes-and-forgets a session, after which nothing references that session
again and a reader may drop its state. (A future
[random-access index](https://github.com/adamkjonsson/zipline/issues/44) could gather descriptor
offsets without changing this streaming contract.)

### A first example

In the JSON-Lines face — one object per line, `type` discriminating the block,
payloads base64 — a small multi-party capture shows the shape. A 3-party chat
room is just additional descriptors, participants beyond two, and records with no
TCP hints (ordering falls back to timestamps, since a single chat server saw all
messages on one clock). Participants are declared as they appear: `dave` joins
mid-stream and is declared only at that point. When the writer later evicts the
idle room it says so with a `session_end` — nothing references session 8 after
that line.

```jsonl
{"type":"file","format":"zipline-payload/0.18","tick_hz":1000000}
{"type":"source","source_id":1,"kind":"capture","uri":"chat.pcap"}

{"type":"session","session_id":8,"proto":"irc","key":"#zipline@irc.example.net"}
{"type":"participant","session_id":8,"pid":0,"endpoint":["alice"]}
{"type":"participant","session_id":8,"pid":1,"endpoint":["bob"]}
{"type":"participant","session_id":8,"pid":2,"endpoint":["carol"]}

{"type":"record","session_id":8,"sender_pid":0,"source_id":1,"ts":2000,
 "payload":"aGksIGFsbCE="}
{"type":"record","session_id":8,"sender_pid":2,"source_id":1,"ts":2100,
 "payload":"aGV5IGFsaWNl"}
{"type":"record","session_id":8,"sender_pid":1,"source_id":1,"ts":2150,
 "payload":"bW9ybmluZw=="}

{"type":"participant","session_id":8,"pid":3,"endpoint":["dave"]}
{"type":"record","session_id":8,"sender_pid":3,"source_id":1,"ts":2300,
 "payload":"YW0gSSBsYXRlPw=="}

{"type":"session_end","session_id":8,"reason":"timeout"}
```

## Causal ordering from TCP seq/ack

When the two directions of a TCP connection are captured separately (e.g. one
file per tap point), their clocks may be slightly out of sync. Merging records
purely by `timestamp` can then invert cause and effect. TCP's sequence and
acknowledgement numbers give a **clock-independent happens-before** relation we
can exploit instead.

### The guarantee

Each direction has its own sequence space. A segment from **B** carrying
`ack = N` proves that, *at the moment B built that segment*, B had already
received **A**'s stream up to byte `N` (exclusive). Therefore:

> A's send of the bytes below `N`  →  B receives them  →  B sends this segment

That is a causal edge `A_record → B_record` that holds **regardless of either
capture clock**. Symmetrically for A's acks of B. The result is a partial order
(a DAG); timestamps are used only to break ties *within* what the partial order
leaves free (genuinely concurrent records).

We store `seq_start`/`ack` as the **absolute TCP sequence numbers from
the wire** — exactly the values in the packets. This is the key to ordering two
*separately-captured* directions: the absolute numbers are consistent across
captures *by construction* (they are the same bytes on the wire), so no shared
base or agreed origin is needed, and a mid-stream capture that never saw the SYN
works the same as one that did. An `ack` is natively an absolute number in the
peer's sequence space, so it compares directly against the peer record's
computed end (`seq_start + payload_len`).

Because absolute TCP sequence numbers are 32-bit and **wrap**, all comparisons of
`seq_start`/`ack` — and of the derived record end — use **serial-number
arithmetic** ([RFC 1982](https://www.rfc-editor.org/rfc/rfc1982)):
`a < b` iff `((a - b) mod 2³²)` has its high bit set. This is well-defined for
any two values within 2³¹ of each other — vastly more than any in-flight window —
so it never misorders real traffic.

### Fields used

Per **Participant Descriptor** (TCP):

| Option        | Meaning                                                        |
|---------------|----------------------------------------------------------------|
| `isn`         | the SYN's sequence number; present when the handshake was seen. Fixes the stream's absolute origin (first byte = `isn+1`) for detecting post-handshake loss and anchoring logical offset 0; *not* used for ordering |
| `endpoint`    | `ip:port`                                                       |

Per **Record** (TCP):

| Option       | Meaning                                                        |
|--------------|----------------------------------------------------------------|
| `seq_start`  | absolute sequence number of the sender's first payload byte    |
| `ack`        | the acknowledgement number from the wire: one past the highest contiguous peer byte the sender had received |

A record's **end** — one past its last byte, the value an `ack` is compared
against — is not stored: it is always `seq_start + payload_len` (mod 2³²). A
zero-length pure-ACK record's end is simply its `seq_start`.

### Merge algorithm

```text
INPUT:  records of a session, grouped by sender participant
OUTPUT: one interleaved, causally-consistent sequence

1. Take each participant's records in file order — the writer MUST have
   stored them in seq_start order (see Identifiers & ordering), so no
   sorting is ever needed. All seq comparisons below are serial-number
   (RFC 1982) comparisons, since the sequence space wraps.

2. Build edges between participants from acks:
     for each record R from participant P with ack value a:
         add edge  Q_record -> R   for every record Q_record from the
         *peer* whose end (seq_start + payload_len, mod 2^32) <= a
     (R's sender had already received those peer bytes, so they precede R.)

3. Topologically sort the resulting DAG.

4. Where the topo order is free (concurrent records with no causal edge
   between them), break ties by timestamp; where timestamps are equal,
   by ascending `participant_id`.
```

Step 2 is the payoff — it stitches the two separately-captured directions
together on causality rather than the skew-prone clock.

**The merge never reorders one participant's records against each other.** Step
1 takes each participant's records in file order and nothing later disturbs it:
the merge is a k-way interleaving of already-sorted streams, so step 4's
tie-break chooses only *between* participants. This matters most where
there is least to go on — a hint-less session has no causal edges at all, so
every record is concurrent and the whole order is step 4. Even there, a
participant's own records keep their stored order, and a timestamp that runs
backwards within one participant changes nothing. The merge is *stable* with
respect to stored order.

**Hint-less**, used throughout this document, means: **a session in which no
record carries `seq_start` or `ack`.** A single such hint anywhere in the session
yields causal edges, so the session is not hint-less. Chat rooms and one-way UDP
feeds are the usual examples; a TCP session is hint-less only if its writer
recorded no sequence numbers at all.

Note what this is a property of: the session's **records**, not its Session
Descriptor. Because [declare-on-first-use](#declaration-order-declare-on-first-use)
places the descriptor before them, a reader cannot decide it when the session is
declared — only at [Session End](#session-end-0x12) or end-of-stream. Any check
that depends on it defers to that point, which costs one boolean per open session
and composes with the state a reader already keeps.

**A producer computing a sequenced order MAY choose a different tie-break** —
round-robin, source order, anything deterministic — if it knows the clocks are
unreliable. That choice belongs to the producer, which knows how the capture was
taken; the stored order is authoritative however it was reached, and a reader
never re-derives it. On a **hint-less** session the producer records what the
order rests on in
[`sequenced_basis`](#sequenced-files-precomputed-order); on a session with hints
there is nothing to record, since the causal edges already account for the order
and only genuinely concurrent records reach the tie-break at all. A **reader** cannot make
it: skew is not a property a file asserts, and the absence of
[`SINGLE_CLOCK`](#file-header-0x01) says nothing either way. So a reader
breaking ties always uses the timestamp.

**Cost, and why a reader rarely pays it in full.** Stated naively, step 2 is
O(N·M) per session — every record weighed against every peer record — plus the
topological sort. Two things tame it, and a reader should rely on both:

- **Sorted inputs (guaranteed).** Because a writer **MUST** store each
  participant's records in `seq_start` order (see
  [Identifiers & ordering](#identifiers--ordering)), the per-participant streams
  arrive sorted: by `seq_start`, and by **stored order** where two records share
  one — which is a total order on the pair, since stored order is total. Step 1 is
  always a no-op and the merge *is* a
  **streaming k-way merge**: hold one frontier per participant and release a
  stream's next record once every peer record it acks (end ≤ `ack`) has been
  emitted — a single-watermark, O(1)-amortised check. Total work is ~O(N) and
  memory is bounded by the in-flight window, not the session. No reader ever
  implements the quadratic form — or a sort.
- **A sequenced session (no merge at all).** A producer MAY commit the resolved
  order to disk and mark the session *sequenced* (see
  [Sequenced files](#sequenced-files-precomputed-order)); a reader then consumes
  its records in stored order and skips this algorithm entirely.

The merge is **optional, consumer-side** work. Reassembly *within* a direction is
the producer's job — a reader never does it — and a reader that only wants one
participant's stream (already `seq_start`-ordered) need not merge at all. Only a
consumer that wants the single cross-participant timeline of a *non-sequenced*
file runs the algorithm above.

**Transport neutrality.** Though stated in TCP's terms, the algorithm needs
only two properties of a transport's ordering hints: (a) a **per-sender
monotonic sequence position** compared with the serial-number rule, and (b) a
**cumulative acknowledgement** of the peer's positions. TCP instantiates them
with `seq_start` (plus the computed record end) and `ack`. SCTP's TSNs — the
same 32-bit serial-number space — and its cumulative TSN ack meet the identical
contract, so supporting a new transport means adding option ids (see
[Design decisions not taken](#design-decisions-not-taken)), never changing the
algorithm.

### Caveats

- Acks are **cumulative** and may be **delayed**, so `ack` is a *lower bound* on
  what the peer had received — it yields a sound partial order (no false
  edges), just not a total one. That is exactly why timestamps remain as a
  tie-breaker.
- Pure ACK segments (no payload) carry ordering information but no bytes; store
  them as zero-length records (or fold their `ack` into the next data record)
  so their happens-before edges aren't lost.
- SACK/retransmission/overlap are resolved by the *reassembler* before records
  are emitted; the format records the reassembled result and its favor-old
  overlap policy, not raw retransmits.
- A **mid-stream** capture (handshake never seen) needs no special handling for
  *ordering* — the writer simply omits `isn` (it is responsible for confirming the
  SYN is genuinely absent rather than merely delayed before declaring a
  participant ISN-less). The only consequence is that the stream's absolute origin
  is then unknown, so logical offset 0 falls back to the first captured byte and a
  pre-first-byte loss is not representable (see
  [Referencing the source by stream offset](#referencing-the-source-by-stream-offset)).

### Worked example: a skewed two-file capture

The canonical case for seq/ack ordering — the two directions captured to
*separate files* with skewed clocks:

```jsonl
{"type":"file","format":"zipline-payload/0.18","tick_hz":1000000}
{"type":"source","source_id":1,"kind":"capture","uri":"sideA.pcap"}
{"type":"source","source_id":2,"kind":"capture","uri":"sideB.pcap"}

{"type":"session","session_id":7,"proto":"tcp",
 "key":"10.0.0.1:51000 <-> 93.184.216.34:80"}
{"type":"participant","session_id":7,"pid":0,"endpoint":["10.0.0.1:51000"],"isn":1000}
{"type":"participant","session_id":7,"pid":1,"endpoint":["93.184.216.34:80"],"isn":5000}

{"type":"record","session_id":7,"sender_pid":0,"source_id":1,"ts":1000,
 "seq_start":1001,"ack":5001,
 "payload":"R0VUIC8gSFRUUC8xLjENCg0K"}
{"type":"record","session_id":7,"sender_pid":1,"source_id":2,"ts":995,
 "seq_start":5001,"ack":1019,
 "payload":"SFRUUC8xLjEgMjAwIE9LDQouLi4="}
```

These are transport-layer records (no `decoder_id`). The sequence numbers are absolute (client
ISN 1000 → first data byte 1001; server ISN 5000 → first data byte 5001). Note
the server record's `ts` (995) is *earlier* than the client request it answers
(1000) — the two capture clocks are skewed. The server's `ack:1019` nonetheless
places it **after** the client's `[1001,1019)` request via the causal edge, so
the merge is correct despite the timestamp inversion.

### Sequenced files (precomputed order)

The merge is consumer work, and a file is read far more often than written — so a
producer that has already resolved the cross-participant order MAY *bake it in* and
let every downstream reader skip the merge. Sequencing is marked **per session**, on the
[Session Descriptor](#session-descriptor-0x10): a session carrying the
`SEQUENCED` flag stores its records so that the order of its Record blocks in the
file is a valid causal linearization — every record appears after all records
that causally precede it, with the producer's tie-break already applied to
concurrent records. The flag is per session because *whether a session can be
soundly sequenced is itself a per-session fact* (a TCP session can always be; a
hint-less one needs a basis — see below). A file may therefore mix
sequenced and unsequenced sessions, and a reader decides per session — records of
different sessions interleave freely, and a reader recovers one session's order by
filtering. In the JSONL projection the flag is a boolean `"sequenced":true` on the
`session` line.

A reader consumes a sequenced session's records in stored order and does **no
ordering work at all** for it — the [merge algorithm](#merge-algorithm) lives
only in the producer. The `seq_start`/`ack` hints stay present, so a
reader MAY still verify the order, or recover the true partial order (which
records were genuinely concurrent); the flag only asserts that *stored order is
one correct answer*, not that it is the only one.

**A [sessionization stage's](#conformance) output sequences and merges like any
other transport stream**, and this is worth stating because its records carry a
`decoder_id` and might be mistaken for a decoded stream's. They carry `seq_start`
and `ack` exactly as a capture's do, so such a session is **not hint-less**, needs
no `sequenced_basis`, and its causal order comes from the hints rather than from
timestamps. Merging two of them is the ordinary two-direction merge: the merge
preserves the transport layer, carries the hints forward, and carries the
reassembler's `decoder_id` and its Decoder Descriptor forward with them.

Who sets the flag depends on the capture:

- A **single tap that sees both directions** emits a sequenced session directly,
  holding only a bounded reorder window (≈ the in-flight data) before releasing
  each record — this keeps the flush-and-forget, bounded-memory contract intact.
- **Two separately-captured directions** cannot be sequenced by either
  per-direction writer alone (neither sees the peer's acks). They are combined by
  a **merge transform** — `sideA.zpf + sideB.zpf → merged.zpf` — that runs the
  streaming merge once and writes sequenced sessions. The expensive logic thus
  exists in exactly one tool, never in every reader. Its output is a
  **pass-through** derived file (see [Conformance](#conformance)): it declares
  each input as a [Source](#source-descriptor-which-input) of `kind = zpf-input`
  (with `digest` and provenance, exactly as a decoder does), mints its own
  session/participant ids and maps each participant back to its input stream
  with an [`origin`](#participant-descriptor-0x11) option, and re-emits the
  inputs' records as **pass-through records** — here byte runs with no
  `decoder_id`, since the inputs are at the transport layer; their payload bytes,
  logical offsets,
  and TCP ordering hints preserved. Gaps stay implicit (sequence
  discontinuities), exactly as in the inputs.

Concretely, merging the
[skewed two-file capture](#worked-example-a-skewed-two-file-capture) (here as two
single-direction capture-sourced files: `sideA.zpf` holds the client as its session 7 /
pid 0, `sideB.zpf` the server as its session 3 / pid 0) yields the pass-through
file below. The merge mints its own ids — which is exactly why each
participant's `origin` mapping is required — and stores the two records in
causal order despite the inverted timestamps:

```jsonl
{"type":"file","format":"zipline-payload/0.18","tick_hz":1000000,
 "produced_by":"zpf-merge 1.2","produced_at":1719510000}
{"type":"source","source_id":1,"kind":"zpf-input","uri":"sideA.zpf","digest":"sha256:11aa…"}
{"type":"source","source_id":2,"kind":"zpf-input","uri":"sideB.zpf","digest":"sha256:22bb…"}

{"type":"session","session_id":1,"proto":"tcp",
 "key":"10.0.0.1:51000 <-> 93.184.216.34:80","sequenced":true}
{"type":"participant","session_id":1,"pid":0,"endpoint":["10.0.0.1:51000"],"isn":1000,
 "origin":{"source_id":1,"session_id":7,"pid":0}}
{"type":"participant","session_id":1,"pid":1,"endpoint":["93.184.216.34:80"],"isn":5000,
 "origin":{"source_id":2,"session_id":3,"pid":0}}

{"type":"record","session_id":1,"sender_pid":0,"source_id":1,"ts":1000,
 "seq_start":1001,"ack":5001,"payload":"R0VUIC8gSFRUUC8xLjENCg0K"}
{"type":"record","session_id":1,"sender_pid":1,"source_id":2,"ts":995,
 "seq_start":5001,"ack":1019,"payload":"SFRUUC8xLjEgMjAwIE9LDQouLi4="}
```

Sequencing is **optional** and orthogonal to both
[axes](#conceptual-model). A reader MUST still
accept unsequenced sessions (and run the merge itself if it wants their
interleaved view). Sequencing is an optimisation, not a correctness fix: **the
merge is fully deterministic either way.** Step 4 orders concurrent records by
`(timestamp, participant_id)`, and `participant_id` is unique within its session,
so the frontiers are totally ordered and every reader of the same file computes
the same interleaving. A producer that bakes the order in saves each reader the
work; it does not change the answer.

**What a sequenced session rests on.** A session's causal order comes from
whatever ordering hints its records carry. A **TCP** session has `seq`/`ack`, so
its sequenced order is clock-independent — sound regardless of capture skew. A
session **without** such hints (a chat room, a one-way UDP feed) has no causal
edges, so its order is purely the timestamp tie-break (non-decreasing
`timestamp`, ties resolved by the producer's fixed rule, e.g. source/pid order).
That is a *sound* order only when all the session's records share **one
trustworthy clock** — the normal case when a single observer (one chat server,
one receiver) saw the whole session.

A producer therefore **MUST NOT** mark a hint-less session `SEQUENCED` unless it
has a **sound basis** for the order it stores. A single trustworthy clock is the
common basis, but not the only one: a producer may hold ordering knowledge this
format does not model — a chat server that assigns its own total order, an
application-layer sequence number, an ordering recorded out of band. Two cases
meet the soundness bar **trivially**: a session with **one participant** (a
one-way UDP feed), and one where **only one participant ever sends**, since
neither has a cross-participant order to get wrong.

Trivially sound is still a basis, and it is still recorded. The producer owns
the soundness of its claim and a reader cannot check it, so the producer
**MUST** say what the claim rests on — including when the answer is "nothing to
get wrong". See [`sequenced_basis`](#tlv-option-framing--id-registry) below.

**The basis requirement applies to hint-less sessions only.** A session *with*
causal hints has **no** timestamp requirement whatsoever: its sequenced order is
derived from `seq`/`ack`, so it is sound however badly the capture clocks
disagree, and its stored records may freely run backwards in time. That is not a
tolerated edge case but the central one — the
[worked example](#worked-example-a-skewed-two-file-capture) sequences exactly
such a pair, storing a record stamped `ts 995` *after* the one at `ts 1000` that
causes it. Sequencing never means "sorted by timestamp"; it means "stored in a
valid causal order", and only a hint-less session is reduced to using timestamps
to find one.

**Recording the basis.** A producer that sets `SEQUENCED` on a hint-less session
**MUST** also set **`sequenced_basis`** (string, Session Descriptor), saying what
the order rests on. The vocabulary is open; the defined values are:

| Value      | The order rests on                                                  |
|------------|---------------------------------------------------------------------|
| `clock`    | one trustworthy clock shared by every record — the `SINGLE_CLOCK` case |
| `protocol` | ordering carried by the application protocol itself, e.g. a server-assigned sequence |
| `external` | an order the producer knows out of band, recorded nowhere in the file |
| `trivial`  | nothing to get wrong — one participant, or only one that ever sends |

**Recording is unconditional; soundness may be trivial.** These are two
requirements and they are easy to conflate. A hint-less `SEQUENCED` session
always carries `sequenced_basis`, whatever the order rests on; `trivial` is what
a producer writes when the answer is that there was never anything to get wrong.

Keeping the recording unconditional is what makes the rule decidable at the
moment it must be applied. `SEQUENCED` is written on the Session Descriptor,
which [declare-on-first-use](#declaration-order-declare-on-first-use) places
*before* the session's records — so a streaming producer cannot yet know whether
only one participant will ever send. It can always know what it is relying on.
A producer that cannot justify triviality yet simply is not relying on it, and
records the basis it *is* relying on.

The same asymmetry settles a question the rule otherwise raises. Whether a
session is [hint-less](#merge-algorithm) is a property of its records, which the
producer cannot confirm when it writes the descriptor either — but it does not
need to. It decides by *what it is relying on*: a producer relying on transport
hints expects them and writes no basis, and one relying on anything else writes
that. The reader, which cannot see the producer's reasoning, is the side that
must wait until Session End to conclude the session was hint-less at all.

The requirement is on the producer, not the consumer: a reader **MUST NOT**
reject a session for an unrecognised value, and a value it does not know simply
means an unknown basis.

**What the field is for.** Mostly *not* something a consumer branches on — it is
an explanation kept for when something turns out to be wrong, in the same family
as `creator`, `produced_by` and `params_digest`. Records in an order that makes
no sense are a different investigation depending on whether the producer claimed
`clock` (look at capture skew), `protocol` (look at the producer's protocol
assumptions) or `external` (look outside the file entirely). Requiring it also
puts the obligation where the knowledge is: a producer that must name a basis has
to decide what the basis *is* at the moment it sets the bit, which is the point —
`SEQUENCED` is a strong assertion, not a default.

There is one mechanical check it enables. A hint-less session claiming
`basis = clock` in a file that draws on several `capture` Sources and does **not**
set [`SINGLE_CLOCK`](#file-header-0x01) is self-contradictory: the session asserts
one trustworthy clock while the file declines to. A consumer MAY report that, and
`clock` being the common basis makes it worth checking.

**File-level `SINGLE_CLOCK`.** That clock precondition has a file-wide form, the
`SINGLE_CLOCK` flag on the [File Header](#file-header-0x01): it asserts that
*every record in the file was stamped against one trustworthy clock*, so
timestamps are globally comparable across sessions and sources (no inter-source
skew). Its value is forward-looking. A capture-sourced writer often cannot tell
that a handful of one-way UDP streams are really one `N`-party session (the `N=5`
case), so it emits them as separate, unsequenced streams — it can commit no
cross-stream order. But it *can* honestly assert `SINGLE_CLOCK` if it was a single
capture point, and a later decoder that regroups those streams into one session
can then rely on the bit to sequence the regrouped session by timestamp soundly.
`SINGLE_CLOCK` set also satisfies the per-session clock requirement above for
every hint-less session in the file.

The two flags are independent. A **merged two-tap TCP file** carries per-session
`SEQUENCED` but **not** `SINGLE_CLOCK` (it used seq/ack precisely because the
clocks were skewed); a **single-tap UDP capture** carries `SINGLE_CLOCK` but its
sessions are **not** yet `SEQUENCED` (no writer has committed an order). A reader
that wants "is this whole file already ordered?" simply ANDs the `SEQUENCED` bits
of the sessions it sees.

## Layers: transport and decoded live in separate streams

Transport and decoded payloads describe the same bytes at different
granularities, and they **rarely share boundaries**. A transport record is a byte
run keyed by transport offsets; a decoded record is a protocol message keyed by
application semantics. A single decoded message can span *two and a half*
transport records — starting and ending mid-record. Forcing both into one record
means either duplicating bytes or imposing an alignment that fits neither side.

So decoding is a **stream → stream transform**, carried out file to file rather
than as an in-record layer:

```
transport.zpf  ──[ http/1.1 decoder ]──▶  decoded.zpf
```

The output is one coherent boundary scheme (protocol messages); the input is
another (byte runs). A decoded stream stands alone for its **decoded** content —
reading its records never requires the predecessor. The exception is regions a
decoder could not parse: a decode stage does not copy their bytes, it records an
**[Undecoded](#undecoded-0x21)** marker referencing them, so recovering *those*
bytes does mean consulting the predecessor (ultimately the capture). The link
between files is otherwise **provenance**, used for verification and
re-derivation, not for reading.

**The layer is a property of the stream, not of the file it arrived in** — see
[the two axes](#conceptual-model). A transport stream is not "a captured one" and
a decoded stream is not "a derived one"; a decode stage can produce either, and a
capture can be the direct source of either. What the layer decides is the offset
space, which is the subject of the rest of this section.

This generalizes: `capture → tls-records → http → …` is the same mechanism
applied N times. No stage is special-cased; each just derives from the previous
file's spans.

**A stage's sessions need not line up with its input's.** The mapping from input
participant streams to output sessions is **many-to-many**, and both directions
are ordinary. One input stream MAY feed several output sessions — an HTTP/2
decoder demultiplexes one connection into a session per stream — and one output
session MAY draw on several input streams, which every two-direction decode
already does. A stage MAY also mint sessions with no counterpart upstream at all.
What binds an output record to its input is its [`spans`](#tlv-option-framing--id-registry),
never a shared `session_id`: ids belong to the file that declares them, so the
same number in two files means nothing (see [the namespace
rule](#tlv-option-framing--id-registry)). The
[coverage guarantee](#coverage-honesty-undecoded-blocks) is what keeps this
honest, and it is stated per *input participant stream* precisely so that it
still holds when one stream's bytes end up spread across several output sessions.

Decoding is also not the *only* file → file stage: **all derivation is
file → file**. The [merge](#sequenced-files-precomputed-order) is a
*byte-preserving* transform — it re-emits its inputs' byte runs as
**pass-through records** rather than imposing new units — and it uses the same
`zpf-input` Source / `digest` / provenance machinery. A derived **stream** is
therefore exactly one of a *decode stage*'s output or a *pass-through
transform*'s, never half of each — and the discriminator binds **per
participant**, so one file MAY hold a created stream beside a preserved one (see
[Conformance](#conformance), which states the test).

**Transforms that change no data.** A tool that only *adds* something — a
[label](#nameidentity-resolution-0x30), a `comment`, a session-level annotation —
is a pass-through transform as well: it alters no bytes and no offsets, so it
preserves whatever layer its input was at, and the merge's rules already cover
it. Two consequences are worth spelling out, since neither is obvious:

- Its output is a **derived** file, not a copy of its input. Annotating a
  *capture-sourced* file yields a file whose records reference a `zpf-input`
  Source, so
  capture-level provenance — `link_type`, the capture's `uri`/`digest` — now sits
  one level away, reached through that Source instead of directly. Nothing is
  lost; it is read one hop further down, as with any derivation.
- Because a pass-through preserves the *layer* rather than the file kind, an
  annotator works at any stage. Annotating a decode stage's output yields a
  pass-through file carrying the decoded layer forward: same records, same
  `decoder_id`s, same Undecoded blocks, plus the annotation.

### Referencing the source by stream offset

The crux of the "2.5 records" problem: a decoded record points at **byte ranges
in the reassembled stream** by a **logical 0-based stream offset** — *not* at
input record ids, and *not* at the absolute TCP sequence numbers used for ordering.
**Byte 0 is the stream's first application byte.** When the TCP handshake was
observed (the participant carries an `isn`), that byte is absolute seq `isn + 1`,
so any bytes lost *between the handshake and the first captured byte* occupy the
leading offsets and stay representable (see below); with no `isn` — UDP, chat, or
a mid-stream TCP capture whose true origin is unknowable — byte 0 is instead the
first reassembled byte. Apart from fixing that origin the offset is deliberately
TCP-independent, so the same mechanism works for a decoded UDP or chat stream that
has no sequence numbers. It makes the input side's arbitrary chunking irrelevant; a
fractional, multi-record span is just one contiguous range. The provenance of a
decoded record is a **span set**:

```
provenance = {
  decoder: <decoder_id>,                       // which decoder produced this
  spans:   [ { source_id, session_id, pid, off_start, off_end }, … ]
}
```

Each span names the input `source_id` (a Source of `kind = zpf-input`), the
session/participant within it, and a half-open `[off_start, off_end)` logical
range. Usually a single span (one participant, one contiguous range); the list
covers the rare gapped or cross-direction message. Offset-based references
survive the predecessor being re-chunked or re-written.

**The offset space is contiguous, holes included.** A participant's logical
offset is its **true position in the stream**, counting any bytes that are
*missing* (a TCP gap, a truncation) as if they were present — it is **not** a
running count of delivered bytes. So a 39-byte gap occupies a 39-wide offset
range that no record's payload covers, and the next delivered byte resumes at the
offset past it. This is what lets an undecoded or missing region be named by a
single `[off_start, off_end)` range (see [Undecoded](#undecoded-0x21)); a span
whose range falls in such a hole resolves to no bytes. A gap at the very *start*
is no different **when the origin is `isn`-anchored**: bytes lost between the
handshake and the first captured byte are the leading hole `[0, K)`
(`K = first seq_start − (isn + 1)`), named like any other. Without an `isn` there
is no room below the first captured byte, so a pre-first-byte loss simply is not
representable — one more reason `isn` is mandatory once the handshake is seen.

**The origin is a floor: a record's `seq_start` MUST NOT precede it.** The origin
is `isn + 1` where the participant carries an `isn`, and the first captured byte
otherwise. Everything above measures from it — the leading hole is
`first seq_start − (isn + 1)`, and a record's offset is `seq_start − (isn + 1)` —
so a record below the origin has a negative offset in a space with none, and the
modular subtraction does not report that. It returns a number just under 2³²
instead: one zero-length record at `isn` rather than `isn + 1` puts that record at
offset 4294967295 and makes the stream measure 4294967295 bytes, whatever its data
actually spans.

**The floor binds meaningfully only on an `isn`-anchored participant.** Without an
`isn` the origin *is* the first record's `seq_start`, and the ordering MUST stores
that record first, so nothing can precede it and the rule cannot be violated. It
is stated for both cases anyway, because the rule is about the origin rather than
about `isn` — but an implementer who writes the check and cannot make it fire on
an unanchored stream should know the rule is unreachable there by construction,
not that they have misread the origin.

**Unplaceable records, and where they go.** A record is **unplaceable** when this
offset space cannot say where it belongs. Two shapes are: one whose `seq_start`
precedes the origin, and one carrying **no `seq_start`** on a stream whose other
records carry them. A reader **MUST** treat an unplaceable record as occupying a
**zero-width range at the highest `off_end` any earlier record of that participant
reached** — `0` where there is none — contributing nothing to the extent and
covering no byte of the stream. A reader **MUST NOT** place a below-origin record
at the wrapped offset the arithmetic yields.

The position is a **running maximum** rather than "where the previous record
ended", and the two differ: records within a participant may overlap — the
favor-old policy exists for exactly that — so the record stored last is not always
the one that reached furthest. Stating the weaker of the two would leave an
unplaceable record inside a range already covered, and two readers taking the two
readings would disagree about the offset space, which is the disagreement this
rule exists to end. A run of unplaceable records is well defined by the same
sentence: each contributes nothing, so each sits where the last placed record
left off.

**Violating the floor is advisory, not isolating**, the treatment
[`content_type` at the transport layer](#typing-a-decoded-record) gets: the reader
**accepts the file**, applies the rule above, and SHOULD report. This is the
specific rule for this violation, in the sense [Conformance](#conformance) gives
that phrase, and it binds instead of the general licence to isolate. The reason is
the reason that licence exists — isolation is for damage a reader cannot bound,
and here it can: one record is unplaceable and every other byte of the stream is
exactly where it was. A reader that discarded the session over it would lose the
whole capture to fix one offset, and two readers taking different options would
disagree about the stream, which is what this rule exists to stop.

Zero width is what makes the rule safe to apply: a record the reader cannot place
is one whose bytes it cannot attribute to any offset, and a zero-width range is
the only claim that stays true whatever the writer meant. Note that it is not
*deletion* — the record's `timestamp`, `flags` and payload remain readable, and a
consumer indexing by anything other than offset still sees it.

**Where such a record carries payload, this costs bytes, and the cost is
deliberate.** A handshake record written one below the origin is zero-length and
loses nothing. A converter with an off-by-one on `isn` instead produces a
below-origin record *with a payload*, and those bytes are then excluded from the
extent and from every coverage answer the file supports: they are not in the
offset space at all. The alternative is to trust the wrapped offset, which places
them near 2³² and corrupts the extent for every other record too — so the bytes
are kept and only their **placement** is refused. "Data must never vanish
silently" is discharged by the SHOULD-report and by the record remaining readable,
not by pretending it was placed.

**The floor is decidable only within the serial-arithmetic half-space.** The
comparison is the [RFC 1982 one](#causal-ordering-from-tcp-seqack) every other
`seq_start` comparison uses, so a `seq_start` more than 2³¹ below the origin is
indistinguishable from one above it and no checker can raise it. That is a
property of the sequence space, not a gap in this rule: the same limit governs
record ordering and every `ack` edge, and it is far beyond any distance real
traffic travels.

**Each layer has its own offset space.** Everything above describes a
**transport** stream — one whose offsets are true positions with holes counted,
however it was produced: reassembled from a capture, reassembled from a `.zpf` by
a [sessionization stage](#conceptual-model), or re-emitted by a pass-through. A
**decoded** stream is a different object. Which one a stream is comes from the
[layer rule](#conceptual-model) and never from where its bytes came from.

**This is the definition; everywhere else refers to it.** A decoded stream's
offset space is the **concatenation of that participant's decoded record payloads
in stored order, plus the declared `width` of any
[Discontinuity](#discontinuity-0x22) between them**, with byte 0 the first byte of
the first such record.

It follows that a decoded stream is hole-inclusive **only** where a Discontinuity
declares a width — unlike a transport stream, which is hole-inclusive throughout.
Two things contribute nothing:

- **Undecoded regions**, which name ranges in the *input's* space, never in the
  output's;
- a Discontinuity with **no** `width`, whose extent is unknowable, so it marks
  that two records do not join without moving anything after it.

A **pass-through** output defines no space of its own; it keeps its input's
unchanged, whichever kind that was.

**A decoded record's own range is therefore positional.** A Record block carries
no offset field; its place in the stream is implied by the concatenation above.
Record *k* of a participant occupies

```
[ Σ(preceding payload_len + preceding declared widths), + its own payload_len )
```

counting that participant's records **and its
[Discontinuity](#discontinuity-0x22) blocks** in stored order — which is the
offset space defined above, walked. With no Discontinuity blocks, the ordinary
case, the sum is exactly the preceding payload lengths. Nothing else states this
arithmetic, so a consumer resolving a decoded record — to a range in its own file,
or one level down — computes it that way.

*Cost.* Forward reading pays nothing: one running counter per participant. But
resolving a single record's range **without** reading from the start costs O(k)
in that participant's preceding records, and since records interleave across
participants there is no shortcut. A reader that needs random access should build
the per-participant prefix sums on a first pass and keep them. A
[random-access index](https://github.com/adamkjonsson/zipline/issues/44) would make that cheaper, and
is not part of this version.

This is the space a second decode stage references when it decodes a decoded
file — `capture → tls-records → http` is two stages, and the second one's `spans`
name offsets in the first one's output — and the space a layer-preserving
pass-through is obliged to preserve. Note the consequence: because stored order
*defines* a decoded stream's offsets, a transform that reorders, re-chunks or
**drops** a decoded participant's records changes them, and is therefore not a
pass-through (see [Conformance](#conformance)).

**Filtering a decoded stream is a decode stage, not a pass-through.** Dropping
one decoded record shifts every later offset in that participant's space, so the
output cannot claim to preserve it. Such a transform instead *creates* a layer:
its records carry `spans` naming the input ranges they came from, and every
region it dropped is marked [Undecoded](#undecoded-0x21) with
`reason = skipped` — a deliberate decision not to carry data forward, which is
exactly what that reason is for. The coverage guarantee then applies as it does
to any decode stage, and the filter is answerable for the whole input. Dropped
content also means the surviving records either side of it no longer join, which
[Discontinuity](#discontinuity-0x22) obliges the filter to declare.

**`decoder_id` names a layer, not a stage**, so such a transform does *not*
declare a decoder of its own. It **inherits** its input's `decoder_id`s and
re-declares the Decoder Descriptors they reference, exactly as a pass-through
does — a filtered or reordered HTTP message is still an HTTP message, and saying
otherwise would misdescribe the payload. The transform identifies *itself* the
way every derived file does, through `produced_by`/`produced_at` on the File
Header.

The same holds for any stage that rearranges records without decoding them. A
transform that **reorders** a participant's decoded records is a decode stage for
the same reason a filter is — stored order defines the offsets, so reordering
changes them — and its records carry `spans` naming the input ranges they came
from. Those spans will not ascend with stored order, which is expected: nothing
requires them to, and coverage depends only on which ranges are covered, not on
the order they appear in. Records it stores as neighbours that were not neighbours
in the stream no longer join, which
[Discontinuity](#discontinuity-0x22) obliges it to declare at each such seam.

One consequence follows: because every `params_digest` in such a file belongs to
an *inherited* decoder, the transform's own configuration has none to live in.
The File Header option
[`transform_params_digest`](#file-header-0x01) is where it goes, and a merge —
which declares no Decoder at all — uses the same option for the same reason.

### Source Descriptor (which input)

A derived file declares each input `.zpf` as a Source of `kind = zpf-input`,
carrying a `source_id` (referenced by record `spans`), the `uri` where the input
lives, and a `digest` (its content hash). The same block type describes a
**capture** source (`kind = capture`, with a
`link_type` instead of pointing at a `.zpf`); a capture-sourced stream is declared
this way, a derived one by its `.zpf` inputs. One `source_id` space, one
referencing mechanism.

The build provenance of the *transform itself* — `produced_by` (tool + version)
and `produced_at` (wall-clock build time of the artifact, not packet time) — is
not per-input; it lives once on the **File Header**, since one transform can read
several inputs.

The `digest` is the real dependency edge: a consumer can confirm the decoded
file still matches its source, and a build-style tool can re-derive when the
predecessor changes. It is `source → object` with a Makefile dependency, not a copy.

### Decoder Descriptor (which decoding)

The decoder is a first-class, referenceable entity: a `decoder_id` (referenced
per-record), a `name` (e.g. `http/1.1`), a `version`, and a `params_digest` (hash
of the decoder config, so the decode is reproducible).

Every record produced by a decoder carries an **explicit** `decoder_id` — there is
no implicit "primary" default. Its presence names the decoder; what **layer** the
record is at then comes from that decoder's declared `output_layer`, per the
[layer rule](#conceptual-model). The
reference is per-record, not per-file, because one decoded file legitimately mixes
decoders: HTTP on one session, TLS-then-HTTP on another. A record's `decoder_id`
is exactly what gives the record its meaning. **Reproducibility contract:** same
input `digest` + same decoder `version`/`params_digest` ⇒ identical output.

Where a stage needs a **secret** — a decryption key, a keylog — that secret is
part of the config the `params_digest` covers, so the contract still holds; it
becomes a statement only a key-holder can act on. Verification of the digest
chain is unaffected, because it rests on the input `digest` rather than on
re-running the stage. Third-party *regeneration* is not possible, and a consumer
without the key should expect none.

### Typing a decoded record

A decoder **frames, and may transform**. Framing is the common case — assembling
raw bytes into one logical unit and marking its edges — but it is not the
definition: a decoder MAY emit bytes that do not appear in its input, and in a
different quantity. Decompressing a `Content-Encoding: gzip` body, decrypting a
TLS record, and expanding an HPACK header block all produce output that exists
nowhere upstream. What a record's `spans` name is therefore the input region the
unit **corresponds to**, not a region holding the same bytes (see
[`spans`](#tlv-option-framing--id-registry)).

Either way the assembled bytes are still just bytes. What they **are** (a PNG, a
UTF-8 string, a 64-bit integer) is a separate, optional label the decoder may
attach: a `content_type` on the record. Absent, the payload is opaque and a
consumer falls back to the decoder `name`; the bytes always stay the source of
truth — the label never replaces them.

`content_type` is a `<scheme>:<value>` string with three schemes:

- `mime:<media-type>` — an IANA media type: `mime:image/png`,
  `mime:application/json`, `mime:text/plain;charset=utf-8`.
- `prim:<primitive>` — a fixed-width integer or raw byte string from a small,
  closed spec-defined vocabulary (`prim:u64`, `prim:i32`, `prim:bytes`;
  full list in [Enums](#enums)), for values media types describe poorly.
- `dec:<token>` — a type **private to the record's decoder**, meaning whatever
  that decoder documents. Its namespace is the decoder's `name` — the same
  `decoder_id` → Decoder `name` resolution that already gives a decoded record its
  meaning — and is **name-scoped**, not versioned: an incompatible type change
  means a new decoder `name`. Two decoders may reuse a token without colliding,
  since each is read in its own namespace; a decoder wanting a globally-unique
  type simply gives itself a globally-unique `name`.

An unknown scheme is treated as opaque. This lets the decoder say *what each unit
is* without the format having to parse it.

**A type is not a name, and a record needs both.** `content_type` says what a
record's bytes *are*. It does not say *which* record this is, and for a decoder
emitting one record per protocol field the difference is total: four `u32` fields
decode to four records typed `prim:u32`, contiguous, non-overlapping, each with
`payload_len` binding exactly — a conformant, well-formed decoded stream in which
nothing says which one is the checksum. Position is not a contract, since a
decoder that later emits an optional field, or omits one it could not parse,
renumbers everything after it.

Before `0.17` the two available spellings each destroyed the other's information.
`dec:checksum` names the field and discards the normative typing that let a
generic reader read the value — and it types a *value*, so `dec:checksum` and
`dec:seq_no` become two distinct types that happen both to be `u64`, with nothing
left saying they share one. `comment` is defined as a free-text human note, so a
consumer parsing it relies on something this document says means nothing.

**`role`** is the name: a string saying what this record **is**, within its
decoder's vocabulary. It is independent of `content_type` — a record may carry
both, either, or neither — which is the whole point: the type and the name stop
competing for one field. Three properties, each borrowed from a mechanism already
here:

- **Name-scoped to the record's decoder**, exactly as a `dec:` token is: the
  namespace is the Decoder `name` that `decoder_id` resolves to, so two decoders
  may both use `checksum` without colliding. This is the whole of what makes it
  more than a `comment` — not that a reader can verify the meaning, since it
  cannot verify a `dec:` token either, but that the **scope is declared**, so a
  consumer knows exactly how far the name travels.
- **Opaque to the format.** It names a record; it does **not** assert a tree. A
  producer writing `dns.flags.qr` is using a convention this document does not
  parse, the same way a `dec:` value is unparsed. Whether a **nested**
  decomposition — a record naming bytes a record before it already emitted — is a
  well-formed decoded stream at all is a separate question this version does not
  settle
  ([#106](https://github.com/adamkjonsson/zipline/issues/106)); `role` is
  compatible with any answer to it, which is why it did not wait for one.
- **Advisory, and decoded layer only** — the treatment `content_type` gets, below,
  and for the same reasons.

**A record at the transport layer MUST NOT carry a `content_type`, and MUST NOT
carry a `role`**, including one emitted by a reassembly decoder, where
`prim:bytes` is now mechanically legal and is the obvious wrong answer. Both are
labels on a *unit* — one saying what it is, one saying which it is — and a
reassembly record's boundaries are wherever the reassembler happened to chunk the
stream. Two conformant reassemblers chunk one stream differently and both
are right, which is exactly the property the
[logical offset space](#referencing-the-source-by-stream-offset) exists to
neutralise; labelling an arbitrary window `prim:bytes` asserts it is a unit when it
is a slice. It would also type identical bytes differently by provenance, since a
capture-sourced reassembler declaring itself is only a SHOULD.

**Violating this is advisory, not isolating** — a deliberately unusual strength
for a MUST NOT, which this document gives only where it can say exactly what a
reader does instead (the [origin floor](#referencing-the-source-by-stream-offset)
is the other). Dropping the label loses nothing and the record stays
fully readable, so there is no unit a reader could soundly discard and nothing it
would gain by discarding one — the treatment `tcp_role` gets, not the one an
`origin` on a capture-sourced stream gets. A reader meeting one **MUST ignore the
label** and SHOULD report it; what it MUST NOT do is take the label as evidence
that the stream is decoded after all, which would put every later offset in that
participant in the wrong space.

Absent already says the right thing, and says something new here: the fallback is
the decoder `name`, so a consumer that used to report nothing about how a stream
was reassembled can now report *which reassembler produced it*. Naming the layer
was the point of giving reassembly a decoder at all.

The contrast that makes the rule legible is a **packet-preserving** stage, where
one record is one inner packet — a real unit with real boundaries. That stage does
type its records, and with a `dec:` token, because "one inner packet" is precisely
what distinguishes a packet stream from a byte stream and `prim:bytes` would say
only "opaque".

### Coverage honesty: Undecoded blocks

A decoder can fail partway, or hit a TCP gap (where it can only decode the
gap-free runs on either side). The decoded file states what it did *not* cover
with an explicit **[Undecoded block](#undecoded-0x21)** rather than silently
dropping bytes. An Undecoded block names a `[off_start, off_end)` range of a
predecessor stream and a `reason`; it carries **no payload**, only a reference, so
a consumer that wants the bytes follows the span back toward the capture. This
gives the **coverage guarantee**: in a decode stage's output, every region of an
input participant stream is covered **at least once** by a decoded record's
`spans` *or* marked Undecoded — never silently dropped, and never both. *At least
once* is deliberate: two records MAY cite one region (see
[`spans`](#tlv-option-framing--id-registry)), and overlap drops nothing. *Never
both* is the part that stays absolute, because a region that is simultaneously
decoded and declared undecoded is a contradiction rather than a duplication. Both
sides name the input stream in the input's own id namespace, so the guarantee is
checkable stream by stream. A consumer can thus distinguish bytes that exist upstream — "a
message we could not parse" (`reason` = `undecodable`) or "bytes we chose not to
interpret" (`skipped`) — from "no data here" (`gap`/`truncated`, the offset
range is a hole with no bytes anywhere), and a re-derivation can target just the
undecoded ranges. A plain **gap** is simply the no-data case of an Undecoded
block. (The `undecoded` line in the example below shows one.) The `reason`
vocabulary is open, but every value sits in one of those two recoverability
classes. The **class** determines what a consumer can do about the region —
whether the bytes are fetchable at all — and is the part it must get right; the
**word** carries the producer's intent, which a consumer is free to use for its
own ends, as one counting genuinely unparsed bytes does when it separates
`undecodable` from `skipped` (see [Undecoded](#undecoded-0x21)).

### A decoded file, end to end

Putting the pieces together — a decoded file derived from the TCP capture in
the [skewed two-file worked example](#worked-example-a-skewed-two-file-capture).
The input `.zpf` is a
`source` of `kind:"zpf-input"`, each record cites the `spans` it was built from
(logical stream offsets, not transport offsets) and a `content_type` saying what
its bytes are (here the http decoder's own `dec:` types), and the undecodable
tail is stated as an explicit `undecoded` block (referencing the input span whose
bytes it could not parse — its ids read in `transport.zpf`'s namespace, coincidentally
equal to the output's here — not copying them):

```jsonl
{"type":"file","format":"zipline-payload/0.18","tick_hz":1000000,
 "produced_by":"zpf-decode 0.4","produced_at":1719500000}
{"type":"source","source_id":1,"kind":"zpf-input","uri":"transport.zpf",
 "digest":"sha256:9f2c…"}
{"type":"decoder","decoder_id":1,"output_layer":"decoded","name":"http/1.1","version":"0.4",
 "params_digest":"sha256:00ab…"}

{"type":"session","session_id":7,"proto":"http"}
{"type":"participant","session_id":7,"pid":0,"endpoint":["10.0.0.1:51000"]}
{"type":"participant","session_id":7,"pid":1,"endpoint":["93.184.216.34:80"]}

{"type":"record","session_id":7,"sender_pid":0,"source_id":1,"ts":1000,
 "decoder_id":1,
 "spans":[{"source_id":1,"session_id":7,"pid":0,"off_start":0,"off_end":18}],
 "content_type":"dec:request","payload":"…decoded request…"}
{"type":"record","session_id":7,"sender_pid":1,"source_id":1,"ts":995,
 "decoder_id":1,
 "spans":[{"source_id":1,"session_id":7,"pid":1,"off_start":0,"off_end":100}],
 "content_type":"dec:response","payload":"…decoded response…"}
{"type":"undecoded","source_id":1,"session_id":7,"pid":1,
 "off_start":100,"off_end":139,"reason":"undecodable","decoder_id":1}
```

### Annotating a decoded file

The subtler pass-through: a tool that adds a label to the decoded file above and
changes nothing else. It is a **pass-through transform preserving a decoded
layer** — records keep their `decoder_id` and `content_type` but carry no `spans`
of their own, provenance is the participants' `origin`, and the Undecoded block
rides along unchanged.

Note the two Sources. `decoded.zpf` is the immediate input, which `origin` names
and the records reference. `transport.zpf` is declared as well — not as a second input,
but because the inherited `undecoded` line has always been a statement about
`transport.zpf`'s stream, and it must keep resolving there. Numbering it as it was in
the input lets the block be copied verbatim:

```jsonl
{"type":"file","format":"zipline-payload/0.18","tick_hz":1000000,
 "produced_by":"zpf-annotate 0.2","produced_at":1719520000}
{"type":"source","source_id":1,"kind":"zpf-input","uri":"transport.zpf",
 "digest":"sha256:9f2c…"}
{"type":"source","source_id":2,"kind":"zpf-input","uri":"decoded.zpf",
 "digest":"sha256:44dd…"}
{"type":"decoder","decoder_id":1,"output_layer":"decoded","name":"http/1.1","version":"0.4",
 "params_digest":"sha256:00ab…"}

{"type":"session","session_id":7,"proto":"http"}
{"type":"participant","session_id":7,"pid":0,"endpoint":["10.0.0.1:51000"],
 "origin":{"source_id":2,"session_id":7,"pid":0}}
{"type":"participant","session_id":7,"pid":1,"endpoint":["93.184.216.34:80"],
 "origin":{"source_id":2,"session_id":7,"pid":1}}

{"type":"name","session_id":7,"pid":1,"label":"example.com","kind":"tls-sni"}

{"type":"record","session_id":7,"sender_pid":0,"source_id":2,"ts":1000,
 "decoder_id":1,"content_type":"dec:request","payload":"…decoded request…"}
{"type":"record","session_id":7,"sender_pid":1,"source_id":2,"ts":995,
 "decoder_id":1,"content_type":"dec:response","payload":"…decoded response…"}
{"type":"undecoded","source_id":1,"session_id":7,"pid":1,
 "off_start":100,"off_end":139,"reason":"undecodable","decoder_id":1}
```

The `name` line is the whole point of the transform, and it is the only line the
input did not already have. Had the same tool annotated `transport.zpf` instead, the
result would look like the merge's output: a pass-through preserving a
*transport* layer, with byte-run records, no `decoder_id`s, and no Undecoded
blocks.

**Records and inherited Undecoded blocks resolve differently here, and the
difference is easy to misread.** `transport.zpf` is declared in this file, which makes
it look as though the records relate to it. They do not:

- The **`undecoded` line names `transport.zpf` directly** and resolves in **one hop**.
  Its offsets have always been in `transport.zpf`'s stream, which is why that Source
  must be declared at all.
- A **record** resolves through the **immediate** input. It carries `source_id 2`
  (`decoded.zpf`) and no `spans`, so a consumer takes its participant's `origin`
  to the corresponding stream in `decoded.zpf`, computes the record's
  [positional range](#referencing-the-source-by-stream-offset) — offsets are
  preserved, so it is the same range there — and reads the `spans` on the record
  it finds, which name `transport.zpf`. Two hops, and **this file alone cannot say
  which transport bytes a record came from**.

That asymmetry is deliberate. `spans` is the discriminator between a stage that
*built* a record and one that *re-emitted* it (see [Conformance](#conformance)),
so a pass-through cannot carry its input's spans forward without destroying the
test that tells the two apart. The Undecoded block is exempt because it is not
provenance for anything this file produced — it is a statement *about* `transport.zpf`,
carried along intact.

### Worked example: a decrypted tunnel

The case the two axes and the declared layer exist for. A WireGuard tunnel is
captured as UDP datagrams; decrypting them yields inner IP packets; reassembling
those yields inner TCP streams — *transport* streams, with `isn`, `seq_start` and
real holes — and decoding one of those yields HTTP messages. One direction is
shown; a second adds nothing but symmetry.

```
wg.pcap ──[capture]──▶ outer.zpf ──[wireguard-decrypt]──▶ packets.zpf
                       UDP datagrams                      inner IP packets
                       capture / transport                zpf / decoded

packets.zpf ──[tcp-reassembly]──▶ inner.zpf ──[http/1.1]──▶ http.zpf
                                  two TCP flows             messages
                                  zpf / TRANSPORT           zpf / decoded
```

The complete four-file artifact is `vectors/tunnel/`. Two hops are ordinary decode
stages this document has already shown, and are described rather than transcribed:

- **`outer.zpf`** holds four 80-byte ciphertext datagrams at `[0,80)` … `[240,320)`
  — a transport stream with no `isn`, so byte 0 is the first captured byte.
- **`packets.zpf`** decrypts them, one record per inner packet, typed
  `dec:ip-packet`. Each record spans the **whole** datagram, nonce and tag
  included, because those fed the computation — so tunnel coverage closes with no
  `skipped` blocks at all (see
  [correspondence, not proximity](#undecoded-0x21)). The third datagram will not
  decrypt: it is Undecoded `decrypt-failed`, bytes-class, and because an inner
  packet is therefore missing from this output, the records either side **do not
  join** and the file declares a [Discontinuity](#discontinuity-0x22). Its own
  offset space is the payload concatenation `[0,60) [60,100) [100,150)`, the
  widthless block contributing 0.

The two hops worth transcribing follow.

**`inner.zpf` — reassembly, and the cell the axes opened.** Its Decoder declares
`output_layer = transport`, so this is a `zpf`-sourced **transport** stream: the
records are byte runs, the participants carry `isn`, and the offsets are
hole-inclusive. It also **fans out** — one input stream becomes two sessions:

```jsonl
{"type":"file","format":"zipline-payload/0.18","tick_hz":1000000,
 "produced_by":"zpf-sessionize 1.0","produced_at":1719700100}
{"type":"source","source_id":1,"kind":"zpf-input","uri":"packets.zpf","digest":"sha256:…"}
{"type":"decoder","decoder_id":1,"output_layer":"transport","name":"tcp-reassembly",
 "version":"1.1","params_digest":"sha256:2f60"}

{"type":"session","session_id":10,"proto":"tcp","key":"10.8.0.2:44300 -> 10.8.0.9:80"}
{"type":"participant","session_id":10,"pid":0,"endpoint":["10.8.0.2:44300"],"isn":1000}
{"type":"record","session_id":10,"sender_pid":0,"source_id":1,"ts":1000,"payload":"…40 B…",
 "decoder_id":1,"spans":[{"source_id":1,"session_id":5,"pid":0,"off_start":0,"off_end":60}],
 "seq_start":1001}
{"type":"record","session_id":10,"sender_pid":0,"source_id":1,"ts":1300,"payload":"…30 B…",
 "decoder_id":1,"spans":[{"source_id":1,"session_id":5,"pid":0,"off_start":100,"off_end":150}],
 "seq_start":1081}
{"type":"session_end","session_id":10,
 "input_extents":[{"source_id":1,"session_id":5,"pid":0,"extent":150}]}

{"type":"session","session_id":11,"proto":"tcp","key":"10.8.0.2:44301 -> 10.8.0.9:53"}
{"type":"participant","session_id":11,"pid":0,"endpoint":["10.8.0.2:44301"],"isn":5000}
{"type":"record","session_id":11,"sender_pid":0,"source_id":1,"ts":1100,"payload":"…20 B…",
 "decoder_id":1,"spans":[{"source_id":1,"session_id":5,"pid":0,"off_start":60,"off_end":100}],
 "seq_start":5001}
{"type":"session_end","session_id":11,
 "input_extents":[{"source_id":1,"session_id":5,"pid":0,"extent":150}]}
```

Four things to read off it:

- **The layer is declared, not inferred.** A decode stage produced this file, and
  its records carry `decoder_id`, yet the stream is *transport*. Reading the layer
  from the provenance — or from the presence of `decoder_id` alone — gets it wrong,
  which is what the [layer rule](#conceptual-model) exists to prevent.
- **The hole is in the sequence numbers.** Flow A's second record starts at
  `seq_start 1081` where 1041 would be contiguous, so `[40,80)` is a 40-byte hole
  no record covers — the lost inner packet, expressed exactly as in a capture.
  There is **no** Discontinuity, and there could not be: a transport stream is
  forbidden one because its offsets already say this.
- **The crossing is left undone.** `packets.zpf` declared a break at its offset
  100, and no record here spans across it — the second record *starts* there. A
  stage that cannot express its input's break in its own output does not satisfy
  the [no-splice duty](#discontinuity-0x22) by staying silent; it declines the
  crossing, which is what this is.
- **Fan-out, and what each session may claim.** Neither session covers `[0,150)`
  alone; the union does, which is why the coverage guarantee is stated per *input
  participant stream*. Both Session Ends declare the same extent **150** — under
  fan-out a consuming session declares the whole input stream, not its share.

**`http.zpf` — where the loss becomes visible again.** Decoding flow A only;
session 11 is simply not an input to this hop, which is ordinary.

```jsonl
{"type":"record","session_id":20,"sender_pid":0,"source_id":1,"ts":1000,
 "payload":"…REQ:GET /…","decoder_id":1,
 "spans":[{"source_id":1,"session_id":10,"pid":0,"off_start":0,"off_end":40}],
 "content_type":"dec:request"}
{"type":"undecoded","source_id":1,"session_id":10,"pid":0,"off_start":40,"off_end":80,
 "reason":"gap","decoder_id":1}
{"type":"discontinuity","session_id":20,"pid":0,"reason":"stream-gap"}
{"type":"record","session_id":20,"sender_pid":0,"source_id":1,"ts":1300,
 "payload":"…RESP:200…","decoder_id":1,
 "spans":[{"source_id":1,"session_id":10,"pid":0,"off_start":80,"off_end":110}],
 "content_type":"dec:response"}
```

This is the [origination duty](#discontinuity-0x22) at the end of four hops. The
`hole`-class Undecoded region lies between the input regions of two adjacent
output units, so no content can have been carried across it: the two messages do
not join, and this file must say so. Delete that one line and the file becomes
`isolate-unmarked-break` — well-framed, coverage complete, and quietly claiming
that a request and a response met on the wire.

Follow the loss back up and every hop has its own account of it: a `stream-gap`
here, a 40-byte sequence hole in `inner.zpf`, a `decrypt-failed` break in
`packets.zpf`, and 80 bytes of ciphertext in `outer.zpf` that are still there and
still unreadable. That is what the chain is for.

## Binary encoding (normative reference)

This section is **normative**: a conformant reader/writer pair must agree on
everything here. Keywords **MUST**, **SHOULD**, **MAY** are used in the usual
sense. The narrative sections above are explanatory; where they disagree with
this one, this one wins.

### Primitives

- **Integers** are fixed-width two's-complement. Every multi-byte integer in
  the container is **little-endian**, without exception — there is no per-file
  or per-block byte order, and nothing in a file changes it. (A writer on
  big-endian hardware byte-swaps; readers never do.)
- **Strings** are UTF-8, **not** NUL-terminated. A string carried in a TLV
  option occupies exactly the option's `len` bytes. A string in a fixed body
  field is `len: u16` followed by that many bytes.
- **Digests** are strings of the form `"<alg>:<hex>"`, e.g.
  `"sha256:9f2c…"`. `sha256` MUST be supported; other algorithms MAY be used.
- **Alignment / padding.** The block frame is **8 bytes** (below) and every
  block's content is a multiple of 4 bytes, so — starting from a file offset of
  0 — **every block begins on a 4-byte boundary and every block's content begins
  on a 4-byte boundary in the file**. A reader may therefore index multi-byte
  fields at their natural 4-byte alignment. (8-byte fields such as `timestamp`
  are only 4-byte aligned, so portable readers should still use alignment-safe
  loads for `u64`/`i64`.) Concretely: each block's fixed body is a multiple of 4
  bytes (reserved fields ensure this); a Record's `payload` is zero-padded to a
  multiple of 4 before its options begin; and each TLV option `value` is
  zero-padded to a multiple of 4. Padding is counted in the block `length` only
  — never in a TLV `len` or in `payload_len`, which always give the true value
  size.
- **Reserved** fields and reserved bits MUST be written as 0 and MUST be ignored
  on read.

### Block frame

Every block, without exception, has an **8-byte frame**:

```
+--------+----------+----------+-------------------------------+
| type   | reserved | length   | content  (length bytes)       |
| u16    | u16 (=0) | u32      | = body ++ options ++ padding  |
+--------+----------+----------+-------------------------------+
```

The 8-byte frame (vs. a 6-byte one) keeps every block — and therefore every
block's content — 4-byte aligned in the file. `reserved` MUST be written 0 and
ignored on read. `length` counts the bytes **after** the `length` field — i.e.
body + options + padding, a multiple of 4. The next block begins at
`offset_of_type + 8 + length`. A reader that does not recognise `type` MUST skip
the block using `length`; this is how unknown block types stay
forward-compatible, exactly as unknown option ids do.

### File Header (`0x01`)

MUST be the first block in the file. Body:

| Field           | Type | Value                                                        |
|-----------------|------|--------------------------------------------------------------|
| `magic`         | u32  | file signature `0x5A495046` (`"ZIPF"`); on disk always the little-endian bytes `46 50 49 5A` |
| `version_major` | u16  | `0` for this document                                        |
| `version_minor` | u16  | `18` for this document                                       |
| `tick_hz`       | u64  | time units per second (e.g. `1000000` = µs, `1000000000` = ns); MUST be non-zero |

**File signature.** `magic` sits at **fixed file offset 8** (the frame is a
constant 8 bytes). A reader MUST check that those four bytes are exactly
`46 50 49 5A` and reject the file otherwise — this is a sanity check, not a
byte-order probe: the container is little-endian by definition and nothing in a
file can change that. Tools sniff a ZPF file by the same four bytes. (The
byte-swapped pattern `5A 49 50 46` marks a byte-swapped — invalid — file, and
recognising it makes for a useful diagnostic message.)
Suggested file extension `.zpf`.

**Version numbering.** `version_major` and `version_minor` are independent
non-negative integers, compared **componentwise**. They are never a decimal
number: `0.18` is the eighteenth minor and is **greater** than `0.9`. A writer stamps
the version it implements — there is no obligation to compute the lowest version
whose features the file happens to use, which a streaming writer could not do
anyway, since the File Header is written before the file's content is known.

**A writer stamps the version it implements, and nothing re-stamps a file
afterwards.** While `version_major` is `0`, converting an existing file's bytes to
carry a later `version_minor` is **out of scope** for this format: there is no
option, no transform and no procedure for it, and a file that claims a version it
was not written against is claiming something untrue. A `0.x` file is
**disposable** — where one still matters, regenerate it from the capture rather
than transcoding it. That is cheap precisely because the provenance chain records
what it was derived from and how.

The compatibility rules have **two regimes**:

- **While `version_major` is `0`** — the current regime — anything may change
  between minors, including in ways that break readers. The pair `(0, minor)` is
  the compatibility identity: a reader **MUST reject** a file whose
  `version_minor` it does not implement, exactly as it rejects an unknown
  `version_major`. Nothing is guaranteed to survive a `0.x` bump.
- **From `1.0` onward**, a **minor** bump only adds blocks and options that are
  *safe to skip*, and old readers keep working — guaranteed by the skip rules, not by inspection. A
  reader **MUST NOT** gate parsing on `version_minor`; it discovers what it does
  not know locally, as it meets it. Anything that would break a reader requires a
  **major** bump, which may also change frame or body layout, and which a reader
  MUST reject if it does not implement it.

`version_minor` therefore stops mattering to readers at `1.0`. That transition is
what `1.0` is *for*.

**"Safe to skip" is the whole of the minor-bump test, and it is not automatic.**
The skip rules make an unknown block or option *parseable* by an old reader; they
cannot make it *harmless*, because that depends on whether the thing skipped
carried meaning the reader needed. [Discontinuity](#discontinuity-0x22) (`0x22`) is
the worked example: skip it and every later record of that participant gets a
wrong positional range, silently. Adding it in `0.13` is fine — a `0.x` reader
MUST reject a minor it does not implement, so no old reader ever sees it — but the
same block after `1.0` would need a **major** bump. Ask of any proposed minor-bump
addition not "can a reader skip this" but "is a reader that skips this still
correct".

**The version describes the file, not the rendering.** A converter projects any
file into whichever version of the [JSONL face](#jsonl--binary-field-mapping) it
implements, so the `format` string reports what the file says, not what the tool
is. The version answers "what does this file contain", never "which tool wrote
this line".

**Reconstructing wall time.** A record's `timestamp` is in `tick_hz` ticks from
the origin `time_epoch` (itself ticks since the Unix epoch, default 0). The
absolute time is `unix_seconds = (time_epoch + timestamp) / tick_hz` (integer
division truncates; sub-tick precision is intentionally not representable). Both
operands are signed, so times before the origin are representable.

Header options: `time_epoch` (i64, `tick_hz` ticks; default Unix epoch
1970-01-01T00:00:00Z), `creator` (string), `produced_by` (string, derived files —
tool + version that produced this file), `produced_at` (i64, derived files —
wall-clock build time in Unix seconds), `transform_params_digest` (string,
derived files — see below), `flags` (u16, file-level flags; see below),
`comment`.

**`transform_params_digest` — how a transform that did not decode was configured.**
A decoder's configuration has a home already: `params_digest` on the
[Decoder Descriptor](#decoder-descriptor-which-decoding), which is what the
reproducibility contract is stated against. Two kinds of transform fall outside
it, and both were left recording *what* a file was derived from but not *how*:

- A **filter or reordering stage**. It is a decode stage, but
  [`decoder_id` names a layer, not a stage](#layers-transport-and-decoded-live-in-separate-streams):
  it *inherits* its input's decoders and re-declares their descriptors, so every
  `params_digest` in the file describes a stage that ran further up the chain,
  never this one. Its own parameters — the filter predicate, the ordering key —
  had nowhere to go.
- A **pass-through transform**, such as the [merge](#sequenced-files-precomputed-order),
  which declares no Decoder at all.

Both are parameterised, and two runs with different parameters produce different
files from the same input, so `produced_by`/`produced_at` do not settle
reproducibility on their own. The digest is per-*file* because such a stage
applies one configuration to its whole output.

A derived file may therefore carry this option **and** an inherited `decoder_id`
whose descriptor has its own `params_digest`. That is not a duplicate: the two
describe different stages, one upstream and one here.

**A file all of whose streams are capture-sourced MUST NOT carry the option**, and
the reason is placement rather than the absence of a transform. Reassembly *is* a
transform — a destructive one, which is why such a file may declare what its
reassembler discarded — but a reassembler that wants its configuration recorded
declares itself as a Decoder and puts it in that descriptor's `params_digest`,
which `reassembler-declared` demonstrates. This option is for a stage that
produced records **without decoding** and so has no Decoder of its own to hang a
digest on; a capture-sourced file has no such stage. The `produced_by` and
`produced_at` options are different and are **not** restricted this way — every
file was produced by something, and a capture-sourced file may name it.

**File flags.** The `flags` option is a u16 bitfield of file-level assertions;
when absent, every bit is 0. Bit `0x0001` (**SINGLE_CLOCK**) asserts that every
record in the file was stamped against one trustworthy clock, so timestamps are
globally comparable across all sessions and sources with no inter-source skew
(see [Sequenced files](#sequenced-files-precomputed-order)). It is a clock
assertion, *not* an ordering one — per-record/per-session ordering is the
Session Descriptor `SEQUENCED` flag. All other bits are reserved, MUST be written
0, and MUST be ignored on read.

### Descriptor blocks

Each fixed body ends with a `_reserved: u16` (0) where needed to round it to a
multiple of 4 bytes. The `Options` line under each table lists that block's TLV
options (see the [id registry](#tlv-option-framing--id-registry)).

#### Source Descriptor (`0x02`)

One block type for both a **capture** and a derived **`.zpf` input**,
discriminated by `kind`. A record's `source_id` and a span's `source_id` both
reference it.

| Field        | Type | Notes                                          |
|--------------|------|------------------------------------------------|
| `source_id`  | u16  | id referenced by records and spans             |
| `kind`       | u8   | `0` = capture, `1` = zpf-input (see enums)      |
| `_reserved`  | u8   | 0                                              |

Options: `uri`, `digest` (content hash of the referenced file), `link_type`
(u16, capture only — e.g. a pcap LINKTYPE), `comment`. A `capture` source
typically carries `uri`/`digest`/`link_type`; a `zpf-input` source carries
`uri`/`digest`. The transform's own build provenance (`produced_by`/
`produced_at`) is on the File Header, not here.

#### Decoder Descriptor (`0x03`)

Appears wherever a `decoder_id` is referenced — in the file whose stage ran the
decoder, and in any pass-through re-emitting its records — whatever the stream's
provenance. A file MUST declare every Decoder it references.

| Field          | Type | Notes                                        |
|----------------|------|----------------------------------------------|
| `decoder_id`   | u16  | id referenced per-record                     |
| `output_layer` | u8   | the layer this decoder emits (see enums)     |
| `_reserved`    | u8   | 0                                            |

Options: `name`, `version`, `params_digest`, `comment`.

**`output_layer` names the layer this decoder emits** — `0 = decoded`,
`1 = transport` — and is what makes the [layer rule](#conceptual-model)
decidable. It is a **body field, not an option**, so every Decoder Descriptor
states it and there is no absent case to define: a decoder that emits a
**transport** layer is a reassembler, and left undeclared its output would be read
in the wrong offset space entirely.

**Why `decoded` is `0`.** The field occupies two bytes that were `_reserved` before
this version, and a reserved field MUST be written 0. Numbering the common case 0
therefore costs nothing and means nothing has to be rewritten: every Decoder
Descriptor ever written holds 0 there, every one of them emitted a decoded layer,
and each now says so without a byte changing. The ordering is not arbitrary and is
not parallel to Source `kind` — it is chosen to make the old files right.

Declaring the layer is also what gives a reassembler a `params_digest`. Overlap
policy, buffer depth and timeout diverge between implementations, so two
conformant reassemblers turn one input into different output; without a Decoder
of its own the file could not say which one ran. The
[reproducibility contract](#decoder-descriptor-which-decoding) is unusually
valuable here — unlike a decrypting stage it needs no key, and unlike a decoded
stream with no predecessor it is not vacuous.

> **A body field, deliberately, and this is the moment it was affordable.** As an
> option it would have been *not safe to skip* — the second such case after the
> [Discontinuity](#discontinuity-0x22) block — since a reader that retained it but
> ignored it semantically would read a transport stream's offsets as a payload
> concatenation, silently. In the body there is nothing to skip: a reader that
> parses this block parses the field. The cost is that a body-layout change is free
> only while the format is in `0.x` and needs a **major** bump afterwards, which is
> why it is made now rather than later (see
> [Design decisions not taken](#design-decisions-not-taken), where the general form
> of that trade is recorded).

#### Session Descriptor (`0x10`)

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `session_id` | u64  | id referenced by participants and records |

Options: `proto` (string; see below), `flow_key` (string), `flags` (u16,
session-level flags; see below), `sequenced_basis` (string; see
[Sequenced files](#sequenced-files-precomputed-order)), `external_session_id`
(bytes; see below), `comment`.

**`external_session_id` — what the rest of the world calls this conversation.**
`session_id` and this option answer different questions, and reaching for the
wrong one is easy:

| | Assigned by | Answers |
|---|---|---|
| `session_id` | the producer | which session is this, here and in files derived from here |
| `external_session_id` | some other system | what does the rest of the world call this conversation |

A trace id, a UUID from a capture orchestrator, a flow key from a NetFlow
collector, a case number, a span id from a distributed trace. **Nothing in this
format interprets it** — it is carried, compared for equality if a consumer
chooses, and never parsed. `spans` and `origin` keep referring to `session_id`,
because a cross-file reference needs a fixed-width numeric key; `session_id`
therefore stays u64 and this option does not replace it. Note `session_id` is
already global-capable — a writer may draw it from a fleet-wide sequence — so
this is not "the global one", it is the *foreign* one.

It is **opaque and variable-length**: one option per session, so its size costs
nothing per record, and there is no reason to fix a width. That admits a UUID (16
bytes), a SHA-256 (32), a URN, or an arbitrary correlation string with equal ease.

*Choosing an external id — guidance, not a rule this format enforces.* For
**randomly** chosen identifiers the birthday bound bites earlier than people
expect: in a 64-bit space, 2³² ids is where the collision chance reaches 50%, and
a one-in-a-million chance needs only about 6 million ids. A producer picking
random values should choose a width where that bound is comfortable. A producer
using a monotonic counter has no collision problem at any width — which is
exactly why the format declines to pick one for either of them.

`proto` names the session's protocol. Well-known values: `tcp`, `udp`, `http`,
`tls`, `irc`, `dns`. Other values are permitted and MUST be lowercase; a
consumer treats a value it does not recognize as opaque.

**Session flags.** The `flags` option is a u16 bitfield; when absent, every bit
is 0. Bit `0x0001` (**SEQUENCED**) asserts this session is a
[sequenced session](#sequenced-files-precomputed-order) — its Record blocks
appear in the file in a valid causal order, so a reader MAY consume them in stored
order without running the [merge](#merge-algorithm). All other bits are reserved,
MUST be written 0, and MUST be ignored on read.

#### Participant Descriptor (`0x11`)

| Field            | Type | Notes                                   |
|------------------|------|-----------------------------------------|
| `session_id`     | u64  | session this participant belongs to     |
| `participant_id` | u16  | id within that session (the `pid`)      |
| `_reserved`      | u16  | 0                                       |

Options: `endpoint` (string, **may repeat** — see below), `isn` (u32, the SYN's
TCP sequence number — see below), `tcp_role` (u8, see enums), `identity`
(string), `origin` (packed, pass-through files only — see below), `comment`.

`tcp_role` records, **when the handshake was observed**, which side opened the
connection: the participant that sent the initial SYN is the *initiator* (active
open), its peer the *responder* (passive open). Omit it when the capture began
mid-stream and the opener is unknown — absence means "unknown", not "responder".

`isn` **MUST** be present when this participant's SYN was observed, and omitted
when the capture began mid-stream (the writer must first confirm the SYN is
genuinely absent, not merely delayed). Its job is to fix the stream's **absolute
origin**: the first application byte is `isn + 1`, so a consumer can tell whether
bytes were lost between the handshake and the first captured byte, and logical
offset 0 is anchored there (see
[Referencing the source by stream offset](#referencing-the-source-by-stream-offset)).
Ordering does *not* use `isn` — that relies on the absolute `seq`/`ack` numbers.

**Tunnelled endpoints.** When the traffic was carried through one or more
tunnels (VXLAN, GRE, IP-in-IP, a VPN, …), a participant has an address at each
layer. The `endpoint` option therefore MAY appear more than once, and the order
is significant: the **outermost** (carrier) address comes first, each subsequent
`endpoint` is one layer further in, and the **last** is the innermost — the
address at which the participant actually speaks the session protocol. A reader
that wants "the" address uses the last `endpoint`; the earlier ones describe the
delivery path. A single un-tunnelled participant has exactly one `endpoint`.

**Endpoint syntax.** An `endpoint` is free-form UTF-8 — nothing in the format
ever parses one — but two producers naming the *same* address should produce
the *same string*, or a consumer cannot correlate sessions across files
("find every session involving this host"). Writers therefore SHOULD spell the
common forms like this:

- IPv4 with a port: `10.0.0.1:51000`; IPv6 with a port in brackets:
  `[2001:db8::1]:443`. A bare address (no port) omits the brackets.
- An Ethernet address as lowercase colon-hex: `aa:bb:cc:dd:ee:ff`.
- A layer that is not a plain address as `<scheme>:<value>`, e.g. `vni:5001`
  (a VXLAN network identifier) or `gre:0x1234` (a GRE key) — natural for the
  outer entries of a tunnelled participant's endpoint list.
- An application-level name (a chat nick, a username) as a bare string.

This is a naming convention, not a grammar: it buys byte-equality for the
common cases, and a reader MUST NOT reject an endpoint it cannot parse —
unrecognized forms are opaque labels.

**`origin` (pass-through files).** In a pass-through derived file (see
[Conformance](#conformance)), every participant MUST carry exactly one `origin`
option naming the input stream it re-emits: a packed
`source_id: u16, pid: u16, session_id: u64` (12 bytes; the u16s lead so
`session_id` stays 4-byte aligned, exactly as in a `spans` entry). `source_id`
references a `zpf-input` Source declared in *this* file; `session_id`/`pid` are
read in **that source's id namespace**, exactly as a span's are. Because a
pass-through transform preserves each stream's bytes and logical offsets,
`origin` is the entire stream-level provenance — pass-through records carry no
`spans`. `origin` MUST NOT appear on a capture-sourced stream, which is not a
re-emission of anything.

`origin` names the transform's **immediate** input, never a grandparent. Chained
pass-throughs therefore chain their provenance: a consumer walks one level at a
time, exactly as it does for `spans`.

#### Session End (`0x12`)

Optional; any file kind. Declares that **this file contains nothing more for
the session**: the writer SHOULD emit it at the exact moment it
flushes-and-forgets a session — the moment it already knows — and, having
emitted it, MUST NOT emit *any* later block referencing that `session_id`
(records, participants, and Name/Identity labels alike; a late label is
written *before* the Session End). At most one Session End per session, and
only after the session's declaration. A reader that sees it MAY free all
state for that session on the spot; this is the reader-side half of the
bounded-memory contract.

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `session_id` | u64  | the session being ended     |

Options: `reason` (string), `input_extents` (packed, derived files; **repeatable**
— see below), `comment`.

`reason` says *how* the session ended — an open vocabulary with suggested
values `fin` (clean TCP close), `rst` (reset), `timeout` (idle eviction),
`capture-end` (the capture stopped while the session was live). Note the
distinction: the block itself only asserts the **file** is done with the
session; whether the *wire* conversation actually terminated is what `reason`
conveys (`fin`/`rst` = it ended; `timeout`/`capture-end` = the writer merely
stopped tracking). Reaching the [End block](#end-of-file-0x41) or end-of-stream
implicitly closes every still-open session, so a Session End as a file's last
act is redundant but harmless; readers MUST NOT require the block (a crashed
writer never wrote it). A transform SHOULD emit a Session End for an output
session once its input for that session is exhausted.

**`input_extents` — making the coverage guarantee self-verifiable.** The
[coverage guarantee](#coverage-honesty-undecoded-blocks) says every offset of an
input participant stream is covered by a `spans` entry or an Undecoded block. A
consumer holding only the derived file cannot check it: the file states which
ranges are covered but never how long the streams were, so a decode stage that
stopped early and simply said nothing about the tail is indistinguishable from
one that consumed everything. Verifying it meant fetching the input and measuring
it — which defeats the point of a guarantee the file is supposed to make about
itself. This option supplies the missing number. Each entry is:

```
source_id: u16, pid: u16, session_id: u64, extent: u64
```

Entries are **20 bytes** each, so a parser derives their number as
`count = len / 20` — stated here for the same reason a
[span-list](#tlv-option-framing--id-registry) states its 28, since a packed type
whose entry size a reader has to infer is one an off-by-one hides in. The two u16s
lead so the u64s stay 4-byte aligned, as in a span-list entry. The triple
`(source_id, session_id, pid)` names an input participant stream **in the
source's id namespace**, never this file's — the same rule that governs `spans`
and `origin`. `extent` is that stream's length in **its own** offset space, as
[Layers](#layers-transport-and-decoded-live-in-separate-streams) defines it — this
re-states nothing, so there is one place to change if that definition ever moves.

One consequence is worth naming, because it is easy to miss and no vector
exercises it: a **decoded** input stream's offset space includes the declared
`width` of any [Discontinuity](#discontinuity-0x22) in it, so its extent counts
those widths too. A stage reading a decoded input that contains a 25-byte declared
hole declares an extent 25 larger than the sum of that stream's payloads.

It is **repeatable** because a stage reads several input streams per output
session — at minimum both directions of a conversation.

**Under fan-out, every consuming session declares the same full extent.** One
input stream may feed several output sessions, and each writes its own Session
End; each declares that stream's **whole** length, not the portion it happened to
use. A checker therefore unions the covering spans across *all* sessions naming
the stream and compares that union against the one extent. This follows from the
coverage guarantee being stated per input participant stream rather than per
session: the covering spans may come from records in different output sessions,
so the total they must add up to has to be the same number wherever it is
declared. Two sessions declaring **different** extents for one stream is a
contradiction, and a reader MAY treat it as a semantic violation.

**A decode stage that knows an input stream's extent SHOULD declare it.** A writer
that does not know omits the entry. Declaring an extent larger than the file's own
coverage accounts for is the honest way to say "this decode stopped early";
declaring one smaller is a contradiction of the same kind as above. Note Session
End is the moment the writer already knows: declare-on-first-use puts the
Participant Descriptor before any record, when a live decode cannot yet know how
long a stream will be, whereas at Session End it does.

**An absent entry asserts nothing.** It does not mean the extent is unknown, that
the stage consumed the whole stream, or that it did not. A consumer cannot
distinguish a writer that did not know, one that did not bother, and one that
predates this option — and for some time the third will be the common case. So
absence is neither reassurance nor alarm, and a consumer MUST NOT read it as
either. That is also the limit of what this option buys: the self-verifiability it
gives is obtainable only from writers that opt in, which are not the writers whose
output most needs checking. The `SHOULD` is there to narrow that gap, not to close
it.

The option is meaningless on a capture-sourced stream, whose records are the
stream rather than a derivation of one; such a stream MUST NOT carry it.

### Record (`0x20`)

Body (fixed part):

| Field         | Type  | Notes                                              |
|---------------|-------|----------------------------------------------------|
| `session_id`  | u64   | refers to a Session Descriptor                     |
| `sender_pid`  | u16   | sender participant; recipients are implicit (all other participants — see [Conceptual model](#conceptual-model)) |
| `source_id`   | u16   | refers to a Source Descriptor — a `capture` for a capture-sourced record, a `zpf-input` for a derived one |
| `timestamp`   | i64   | packet time, in `tick_hz` ticks (see timestamp rule)|
| `_reserved`   | u16   | 0                                                  |
| `flags`       | u16   | see bit table                                      |
| `payload_len` | u32   | length of `payload`                                |
| `payload`     | bytes | `payload_len` raw bytes (source of truth)          |

`payload` is zero-padded to a multiple of 4 bytes; options then follow (TCP
hints, provenance — see registry). `payload_len` gives the unpadded length and
MAY be 0 (e.g. a pure-ACK record carrying only an `ack` hint). **Whether a record
belongs to a decoded or a transport stream is the
[layer rule](#conceptual-model)**, which asks two questions — is there a decoder,
and what layer does it declare — and is stated there and not here. `decoder_id`
alone answers only the first: a record with no `decoder_id` is a byte run at the
transport layer, and a record *with* one belongs to whatever layer its Decoder
declares, which may be either. A byte run with no `decoder_id` is either a
**capture-sourced** record or a **pass-through** record preserving a transport
layer, told apart by the referenced source's `kind`. (A pass-through preserving a
*decoded* layer re-emits decoded records, `decoder_id`s included — see
[Conformance](#conformance).)
A record at the decoded layer MAY also carry a `content_type` labelling what its
`payload` is, and a `role` naming what the record is within its decoder's
vocabulary (see [Typing a decoded record](#typing-a-decoded-record)); a record at
the transport layer carries neither, whether or not it has a decoder, for the
reason given there.
Because the frame `length` (u32) bounds the whole block, `payload_len` is in
practice capped a little below 4 GiB (it must share the block with the body and
options).

**Timestamp rule.** When a record's payload is reassembled from more than one
packet, `timestamp` is the packet time of the **last** packet that contributed
bytes to the reassembled payload, in capture order — i.e. the moment the unit
became complete. This is the only choice consistent with the causal order: a
peer's `ack` cannot precede arrival of the last segment it acknowledges, so a
last-packet stamp never contradicts a seq/ack happens-before edge (a first-packet
stamp could). Consequences:

- A single-packet record uses that packet's time; a zero-length pure-ACK record
  uses its ACK segment's time.
- Under the favor-old overlap policy, a later retransmit that contributes no
  *accepted* bytes does not move `timestamp`.
- A **decoded** record inherits its `timestamp` from the data it is built from:
  the timestamp of the last source element in its span set — when the unit became
  complete. That source is transport bytes in a one-step decode, or itself a
  decoded record in a chained one (`capture → tls-records → http → …`), so the stamp
  propagates down the chain and is always ultimately the packet time of the
  contributing capture.

**The span set is per unit, not per run.** Where a stage emits **several** units
from one reassembled run — a decoder producing one record per protocol message,
which is the ordinary case rather than the exception — each unit's `timestamp` is
the completion time of the last input record contributing to **that unit**. A
run's own completion time is its *last* unit's; stamping the earlier ones with it
claims they completed after they did. Three messages arriving in three packets
carry three different stamps, though reassembly offered them as one run.

This is what makes ordering decoded records by `timestamp` *reproduce* the input's
timeline rather than approximate it — the property hint-less decoded output leans
on. Under the per-run reading every unit in a run collapses to one key, ordering
within the run becomes whatever the merge's tie-break does, and that property
quietly stops holding.

The first-packet time is recoverable from capture-source `spans` provenance; a
writer that wants it without full provenance MAY add an optional `ts_first` TLV.
It is **per unit in the same way**: the time of the *first* input record
contributing to that unit, not to the run it was carved from. The canonical
`timestamp` is always the completion (last-packet) time.

`timestamp` is **signed** (i64, as are `ts_first`, `time_epoch`, and
`produced_at`): the configurable `time_epoch` origin admits times *before* it
(negative ticks), and inter-record deltas — central to the skew-tolerant
ordering — are inherently signed. The range given up versus u64 is immaterial at
the resolutions `tick_hz` is meant for.

**Handshake records.** A writer MAY record an observed TCP handshake as a
zero-length record carrying the `syn` flag: `timestamp` is the SYN packet's
capture time, and its `seq_start` **MUST** be `isn + 1` — the stream origin, so
its computed end equals it and every causal edge and ordering rule works unchanged
(it precedes the data that starts at the same origin simply by being produced
first — the tie the [ordering rule](#identifiers--ordering) admits, and the reason
it says so). Recording the handshake is the writer's choice; where it does, this is the
record's shape. `isn` itself is one below the origin, and a record there breaks
the [floor rule](#referencing-the-source-by-stream-offset) — the SYN consumes a
sequence number but delivers no byte, which is exactly why the origin is `isn + 1`
and not `isn`.

**Violating this is advisory wherever the record sits**, which is one strength for
the whole MUST rather than one for each side of it. *Below* the origin the record
is unplaceable and the floor rule places it. *Above* the origin — `isn + 7`, say —
it is placeable and ordinary arithmetic places it: a zero-length record a few bytes
up, covering nothing. Either way a reader **accepts the file**, places the record,
and SHOULD report; what it loses is the handshake's timing and nothing else, and
the origin it might have been tempted to re-derive is fixed by `isn` rather than by
this record. Isolating over a misplaced zero-length record would be the strength
inverted — discarding a session for the mild shape while the shape that wrecks the
whole offset space is accepted and repaired.

Two neighbouring shapes follow from the same reasoning. A `syn`-flagged record
carrying **no** `seq_start` is unplaceable like any other and placed by the same
rule. And the **zero length is part of the shape described here**, not an
incidental detail: the flag marks a handshake-*timing* record. A writer with data
on the SYN (TCP Fast Open) emits that data as an ordinary record at the origin,
where it belongs, and leaves the timing record empty; nothing is lost, because the
origin is `isn + 1` and that is exactly where such data starts.

The responder's SYN-ACK is its own zero-length `syn` record, and MAY
carry an `ack` like any record. This is how session-establishment *timing* is
carried; the handshake's identity already lives on the participant (`isn`,
`tcp_role`).

### Undecoded (`0x21`)

Marks a region of an **input** that the stage producing this stream did **not**
turn into a record of its own — because the decoder could not
parse it, or because the bytes are missing/truncated. It is a *reference*, not a
payload: it carries no bytes, only the input span where they do (or would) live.

The input is usually a predecessor `.zpf`, and the block appears wherever a stage
names one. That includes a **capture-sourced** stream, where the input is the
capture itself and the stage is the reassembler: overlap it discarded, a segment
it never saw. What bars the block is having no input to name at all — a
[decoded stream with no predecessor file](#conformance) has none, and the coverage
guarantee it would serve does not apply there either.

| Field            | Type | Notes                                              |
|------------------|------|----------------------------------------------------|
| `source_id`      | u16  | the input Source whose stream the offsets index — either `kind` |
| `participant_id` | u16  | participant (stream) *inside that input*; unused against a `capture` source (write 0) |
| `session_id`     | u64  | session *inside that input*; unused against a `capture` source (write 0) |
| `off_start`      | u64  | first offset of the region, read per the source's `kind` |
| `off_end`        | u64  | one past the last (half-open `[start, end)`)       |

Every body field is read against the **input**, and **the reading is keyed by the
referenced source's `kind`** — exactly as a `spans` entry's is (see
[the span-list rule](#tlv-option-framing--id-registry)). The body is in fact
byte-identical to a single packed `spans` entry (28 bytes, same field order, same
u16s-lead alignment), so one struct parses both; keying the reading the same way
is what lets one *rule* read both as well.

- Against a **`zpf-input`** source: `session_id`/`participant_id` are in that
  input's id namespace — never the current file's — and the offsets are **logical
  0-based stream offsets** within that stream, the same convention used by `spans`
  (*not* absolute sequence numbers), following the hole-inclusive contiguity rule
  (see [Referencing the source by stream offset](#referencing-the-source-by-stream-offset)).
- Against a **`capture`** source: there is no input `.zpf`, so there is no id
  namespace to name. `session_id`/`participant_id` are **unused and MUST be
  written 0**, and the offsets are **byte offsets into the capture file**. The
  block says *this region of the capture did not become a record of mine*, which
  is a statement about the capture and is addressed the way the capture is
  addressed.

Options: `reason` (string, e.g. `undecodable` / `skipped` / `dropped` / `gap` /
`truncated`), `reason_class` (string, `hole` or `bytes` — required with a
non-canonical `reason`), `decoder_id` (u16, which decoder declined the region).

**Against a `capture` source only the bytes-exist class is available.** A
`hole`-class region — `gap`, `truncated` — MUST NOT be declared there, and needs
no block: the stream the reassembler produced is a transport layer, whose offsets
are hole-inclusive, so a missing segment already occupies a range no record covers
and the sequence numbers already carry its extent. Declaring it again would be a
second account of the same missing bytes with no rule for which to believe — the
contradiction that also bars a [Discontinuity](#discontinuity-0x22) from a
transport stream. What the block adds at that position is the other class: bytes
that *are* in the capture and did not reach the output, an overlapping retransmit
the reassembler discarded, which nothing else in the file can express.

**And against a `capture` source it discharges no coverage obligation, nor
creates one.** The [coverage guarantee](#coverage-honesty-undecoded-blocks) is
scoped *within each input participant stream*, and a capture has none — so a block
naming one is purely declarative: it records what a stage discarded, and no rule
consumes it. That is why the permission does not need to be keyed on the layer. A
reassembler declares an overlap it dropped; a decode stage reading a capture
directly declares a region it could not parse; both are honest, and neither is
answerable to a guarantee that has nothing to bind to. A
[decoded stream with no predecessor file](#conformance) carries none for a
different reason — it read no input at all, so it has nothing to declare.

`reason` says *why* the region is undecoded. The vocabulary is **open**, but
every value belongs to one of two **recoverability classes**. The class governs
what a consumer can *do* about the region; the word carries the producer's
intent, which some consumers use for their own purposes:

| Class           | Meaning                                                                                   | Canonical values          |
|-----------------|-------------------------------------------------------------------------------------------|---------------------------|
| **bytes exist** | the bytes are present at that span in `source_id`; a consumer MAY follow the reference to fetch them | `undecodable`, `skipped`, `dropped` |
| **hole**        | the range has no bytes anywhere upstream — a plain *gap*                                    | `gap`, `truncated`        |

Either way the bytes are not in *this* file. What the class promises is the bytes
**of the region the span names**, in the file it names them in — one level down.
That is exact for an Undecoded block, whose region was by definition not decoded.
Following a *record's* `spans` is a weaker thing, because a decoder may have
transformed: it yields the input region the record corresponds to, which is the
provenance of the record's bytes rather than a second copy of them. See
[Recovering the bytes](#undecoded-0x21) below.

None of these names a transport. A hole is the same object whether it was found
from TCP sequence numbers, an SCTP TSN, an RTP sequence number, or an application
protocol's own counter — so the canonical value is plain **`gap`**, and the
transport is read from the session's `proto` where it matters. A producer wanting
to say precisely *how* a hole was detected uses the open vocabulary, which is
what it is for.

The three bytes-exist values differ in **intent**, not in recoverability.
`undecodable` means the decoder tried and failed. `skipped` means it declined on
purpose — data it does not care about, or data carrying no information: a
byte-order mark, a padding or reserved field. That distinction is needed because
the [coverage guarantee](#coverage-honesty-undecoded-blocks) leaves a decoder no
honest third option: without `skipped`, a decoder that ignores a BOM must either
stretch a record's `spans` across a region no output unit corresponds to, or
report them `undecodable`, asserting a failure that did not occur.

**`dropped` means content was removed**: the region carried content of the stream
this stage is producing, and the stage did not carry it forward. A filter that
drops a record writes `dropped`; a decoder that discards a byte-order mark writes
`skipped`. The difference is not how deliberate the decision was — both are
deliberate — but **whether anything of the stream's content went missing with it**.
A BOM carried none, so the text either side of it still runs continuously. A
dropped record carried its own, so the records either side of it do not.

That is what `skipped` alone could not say. Before `0.17` both cases wrote the
same word, and two byte-identical files — one where the survivors join and one
where they do not — were indistinguishable to every consumer and every checker.

**Correspondence is not proximity**, and this is where the difference bites. A
discarded byte-order mark corresponds to no output unit — nothing downstream was
computed from it — so it is `skipped`, and spanning it would be a false claim. A
decryptor's nonce and authentication tag are the opposite case: they are inputs to
the computation that produced the plaintext, so the inner record honestly spans
the whole ciphertext packet, framing included. Tunnel-stream coverage therefore
closes with **no** Undecoded blocks at all, not one per packet. The test is
whether the bytes fed the unit, not whether they sit beside it.

Keeping the two values apart also
keeps `undecodable` usable as a decoder-quality signal — a consumer counting
unparsed bytes should not have deliberate skips folded into the total.

**A non-canonical `reason` MUST carry `reason_class`** (string, `hole` or
`bytes`) naming its class. The vocabulary is open precisely so a producer can be
more specific than the five canonical words; `reason_class` is what keeps that
freedom from costing the consumer its one actionable fact. The canonical five
imply their class and need no `reason_class`; if one carries it anyway, it MUST
agree with the table above.

**An unrecognised `reason` with no `reason_class`** is a writer error, and its
recoverability is **unknown**. A consumer MUST NOT guess a class — in particular
it MUST NOT assume `hole`, which would silently discard bytes that may well
exist. It MAY treat the region as bytes-exist and attempt recovery, and it SHOULD
report the missing `reason_class`.

**Recovering the bytes** — for the bytes-exist class, and only when a consumer
actually wants them; nothing here obliges a consumer that is merely reading the
file to walk anything. It walks the provenance chain one level at a time — if the
referenced span is itself Undecoded in `source_id`, it recurses — until it reaches
the capture-sourced file that holds the bytes of the region it arrived at.

**Those need not be the bytes it set out to find.** Each hop the walk crosses a
*transforming* decode stage, what it recovers is the corresponding input, not the
same content in another file: chasing a plaintext HTTP region down through a TLS
stage reaches ciphertext, and through a gzip stage, compressed bytes. That is the
honest answer — the plaintext exists nowhere upstream, and re-deriving it means
re-running the stage, which needs its `params_digest` config and, for a key-gated
stage, its key. A consumer that reports the recovered bytes as the region's
content is making the same mistake as one that reports a broken chain as an empty
region. Where every stage in the walk merely framed, the bytes are the same ones
and the distinction costs nothing.

A walk can fail for two reasons, and a consumer **MUST NOT** report them
identically:

- **No bytes exist.** The chain resolved completely and the region is genuinely
  empty — a hole, correctly described.
- **The bytes are unavailable.** The chain broke: an intermediate file named by a
  `zpf-input` Source is missing, unreadable, or fails its `digest`. Nothing is
  known about the region's content, and reporting it as empty would assert
  something the consumer did not establish.

Collapsing the second into the first is the exact silent-data-loss the
[coverage guarantee](#coverage-honesty-undecoded-blocks) exists to prevent. Crossing a **pass-through** file costs nothing extra: its participants'
[`origin`](#participant-descriptor-0x11) options map each stream to the
corresponding input stream, and offsets are preserved, so the same
`[off_start, off_end)` range resolves unchanged one level further down.

An Undecoded block has no `timestamp`, and no placement constraint beyond
declare-on-first-use (its `source_id` must already be declared). A region is
identified purely by `(source_id, session_id, participant_id,
[off_start, off_end))`; a consumer locates it relative to the decoded output
via the decoded records whose `spans` cite the same input stream — the same
lookup it already does for provenance.

**A transport-layer stream expresses its gaps in its offsets**, which is why it
may not carry a [Discontinuity](#discontinuity-0x22) — that rule and its reasoning
are stated there. It says nothing about *this* block, and the two are not
alternatives: the offsets describe the shape of the output, an Undecoded block
accounts for an **input**. A transport-layer stream may carry both, and a
capture-sourced one commonly does, for the reason given at the top of this
section.

A decoder writer wanting a transport input's gaps as explicit blocks rather than
as offset arithmetic reconstructs them from the sequence discontinuity via its
software support, and emits Undecoded blocks in the decode stage's output file.
(A pass-through preserving a *decoded* layer is the other case: its input already
had Undecoded blocks, and it re-emits them unchanged.)

### Discontinuity (`0x22`)

Decoded layers only. Marks a break in **this** file's own output stream: the
records either side of it are **not contiguous**, whatever their positional
ranges say. Body:

| Field            | Type | Notes                                              |
|------------------|------|----------------------------------------------------|
| `session_id`     | u64  | session in **this** file                           |
| `participant_id` | u16  | participant (stream) in **this** file              |
| `_reserved`      | u16  | MUST be 0                                          |

Options: `width` (u64 — the gap's extent in this stream's offset space; **absent
means unknown**), `reason` (string, open vocabulary: `tls-record-lost`,
`decrypt-failed`, `stream-gap`, `records-dropped`, `reordered`, …), `comment`.

**This is the mirror image of [Undecoded](#undecoded-0x21), and confusing the two
is the easy mistake.** Every field of an Undecoded block is read against the
*input* — it is deliberately byte-identical to a packed `spans` entry, and it says
"there were bytes over there that I did not decode". A Discontinuity says
"something is missing **here**, in what I produced", and its ids are this file's
own. That is why it cannot be an Undecoded block with different options, and why
it must be a block rather than a record option: its meaning is positional, and
stored order is what defines a decoded stream's offsets, so it has to interleave
with the records it separates.

**Why the output space needs its own marker at all.** Absent this block, a decode
stage's output space is just the concatenation of its record payloads (see
[Layers](#layers-transport-and-decoded-live-in-separate-streams)), so two records either
side of an input gap are *adjacent* in it — the gap does not survive the layer. Nothing obliges a
decode stage to re-emit its input's Undecoded blocks (that duty falls on
pass-throughs), so on the chain `capture → tls-records → http`, one lost TCP segment
under TLS leaves the HTTP stage free to emit a single message spanning the join,
covering it completely, with **coverage passing** and no marker anywhere in the
file the consumer is reading. The information survives only in principle, by
walking down to the capture-sourced file and noticing a gap between two stage-1
spans — which
nothing states as an invariant and no checker tests. This block is what makes the
break visible where it is read.

**Width, and why an absent one still counts.** A `width` present is a real hole of
known extent: QUIC gives stream offsets, so the missing bytes can be counted, and
it contributes `width` to the
[positional arithmetic](#layers-transport-and-decoded-live-in-separate-streams). A `width`
absent is a break of unknowable extent — TLS lost a record, and the *plaintext*
length it would have produced is not recoverable from the ciphertext — and it
contributes **0**.

Contributing 0 is deliberate. Offsets after such a break stay the payload
concatenation, so every later record remains addressable and a downstream stage
can still cite `spans` into this output. The alternative — declaring later offsets
undefined — would end a chain at its first lost record, and a consumer would lose
the whole remainder of a stream rather than one hole in it. What the block asserts
is not a length. It asserts that the two sides **do not join**, which is the actual
defect: a consumer that splices them reads a message that was never sent.

**What a producer owes the block.** A stage **MUST** emit a Discontinuity between
two adjacent units of its own output wherever those two units **do not join** —
wherever the content its output represents did not run continuously from the end
of the first into the start of the second.

**This duty is stated here and nowhere else; every other mention refers to it.**
It binds any stream whose offsets are the **concatenation of its own record
payloads**, which is what makes a break inexpressible in it without this block.
That is the property, not the file kind: a transport stream is exempt for the
mirror-image reason, its hole-inclusive offsets having already expressed the break
(see *A transport-layer stream MUST NOT carry one*, below).

**The exemption assumes the offsets can express it, and one kind of transport
stream cannot.** Hole-inclusive offsets carry a break because something anchors
them — a TCP `isn` and `seq_start`, or another transport's sequence numbers. In a
**message-oriented or `N = 1`** stream with no such anchor, offsets are the
accumulation of the payloads that arrived, and a datagram that never reaches the
output leaves no trace: nothing says a message is missing, and the Discontinuity
that would say so is barred by the layer. `tunnel/outer.zpf` is such a stream —
UDP, no `isn`, four `message` records.

So a stage emitting a **transport** layer **MUST NOT withhold content** from a
stream whose offsets are not sequence-anchored. Before `0.15` this cost nothing to
say, because a transport stream was a capture's reassembled output and nothing
dropped from it; a stage may now declare `output_layer = transport` and filter,
which is what makes the rule necessary. It binds the writer and **no reader can
check it** — a file that withheld and one that did not are byte-identical, which
is precisely the defect. A stage that needs to withhold from such a stream emits a
decoded layer instead, where the break is expressible.

**Do these two join?** is the whole test, and it falls to the producer because
only the producer knows what it did with the input:

| The stage… | Do they join? | Block |
|---|---|---|
| left framing between two units undecoded — a record header, a nonce, a tag | **yes**, the content runs straight on | no |
| found no bytes to decode there: a [`hole`](#undecoded-0x21)-class region (`gap`, `truncated`) | no | **yes** |
| declined or dropped content that was present — a filter's dropped record, a message it would not parse | no | **yes** |
| **reordered** its input's units, so these two were never neighbours | no | **yes** |

Note what the test does **not** key on. Not input coverage: a decryptor leaves
every record header, nonce and tag accounted for without decoding them, and its
plaintext joins perfectly, so a rule keyed on unspanned input bytes would demand a
block that says something false. Not `spans` adjacency either — `spans` assert
[correspondence, not identity](#tlv-option-framing--id-registry), so a
transforming decoder's spans need not abut where its output is continuous, and
they may legally overlap or run downward. The question is only whether content
that belonged between these two units failed to reach the output, or was never
between them at all.

**Reordering is the case that looks like an exception and is not.** A stage that
reorders a participant's records withholds nothing — every byte reaches the output
— but stored order *defines* this offset space, so two records stored as
neighbours assert that they join, and for reordered neighbours that assertion is
false. Such a stage emits a Discontinuity at each seam, with **no** `width`: what
lies between two units that were never adjacent is not a hole to be counted.

**Two cases are decidable from a single file.** Where an Undecoded region of the
**`hole`** class lies between the input regions of two adjacent output units, no
other reading is available — no bytes existed there, so no content can have been
carried forward, and the two units cannot join. The same holds where the region is
bytes-class **`dropped`**, for a different reason: the bytes existed, and the
producer has said in as many words that it removed content of the stream. A
checker may raise either from the file alone.

`dropped` is decidable precisely because it is the producer's own statement, not
an inference from the reason word. The other bytes-exist values decide nothing —
`skipped` is the BOM case, where the survivors join, and `undecodable` says a
parse failed without saying whether anything of the stream went with it.

**The predicate, stated so that two checkers agree.** The sentence above says
which case; this says how to test it. The layer test comes first, because the
whole check is inapplicable without it:

> The check applies only to **decoded-layer** output streams. For each output
> participant, for each adjacent pair of records `(r1, r2)` in stored order, and
> each input stream `S = (source_id, session_id, participant_id)` cited by the
> `spans` of **both**: let `A` be the maximum `off_end` over `r1`'s spans on `S`,
> and `B` the minimum `off_start` over `r2`'s spans on `S`. If `A < B` and some
> Undecoded region naming `S` that is **`hole`-class or carries
> `reason = dropped`** intersects `[A, B)`, then a Discontinuity between `r1` and
> `r2` is **required**. Where `A ≥ B` the pair is not tested.

Each clause is load-bearing. **Decoded-layer only**, because a transport stream
expresses the same break in its offsets and is forbidden the block — a checker
without that clause rejects a conformant sessionization stage. **Cited by both**,
because a unit may span several input streams and fan-out means adjacent units may
cite different ones; a stream only one of them names says nothing about whether
they join. **Max and min**, because `spans` may overlap, which has been legal
since `0.14`. And **`A ≥ B` not tested**, because a stage that reorders or
overlaps its input produces pairs whose input regions run backwards, where "the
region between them" names nothing. And **`dropped` beside the class test**,
because the two decidable cases are one predicate: a checker that tested only the
class would pass the filter that is this rule's own title case, and one that
tested only the word would miss the lost segment.

**Satisfying this predicate is not satisfying the duty.** It is the minimum a
checker owes, not the rule a producer follows: it is deliberately conservative,
and every pair it declines to test may still be one where the duty binds. A
producer that emits a block only where this fires has misread the table above —
the duty is *do these two join*, it rests on producer knowledge, and most of it is
not mechanically decidable at all. That is a reason to state the duty plainly
rather than to narrow it to what a checker can see.

**What a consumer owes the block.** A consumer **MUST NOT** treat the records
either side of a Discontinuity as contiguous. A decode stage reading an input that
carries one **MUST NOT** emit a unit whose `spans` cross it without emitting a
Discontinuity of its own in the corresponding position of its output.

The no-splice sentence is what carries the property down a chain, and it is worth
stating explicitly because it is easy to think the MUST NOT before it covers the
case. It does not: a stage that honours only the first still consumes the break and
emits an output in which nothing records it, so the discontinuity is visible at one
stage and gone at the next — the original defect, one hop along. A stage that
genuinely cannot express the break in its own output has not satisfied this by
staying silent; it has to leave the crossing undone.

Without these, the block is inert. A stage could read a Discontinuity, compute
every offset correctly, splice across it, satisfy the coverage guarantee, and
remain conformant — which would leave the information recorded and nothing obliged
to act on it.

**Originating and carrying are different duties, and a chain needs both.** The
producer's duty starts a break where one first appears; the consumer's carries it
onward. `0.13` shipped only the second, and the gap that left is not subtle: a
stage could lose a TLS record, emit the two surviving units side by side, and hand
a downstream decoder an output with nothing in it to carry. Every rule fired
correctly and the break vanished at the head of the chain.

**Placement and ordering.** A Discontinuity has no `timestamp`; it takes its
position from stored order alone, between the records it separates, and it is not
a record — the [merge](#merge-algorithm) interleaves records and does not emit it
as one. Because the merge never reorders one participant's records against each
other, a Discontinuity keeps its place in that participant's sequence. It sits
under the ordinary declare-on-first-use rule: its session and participant must
already be declared.

**Coverage is unaffected.** The [coverage guarantee](#coverage-honesty-undecoded-blocks)
is a statement about *input* streams, and this block makes none — it neither
discharges a coverage obligation nor creates one. A stage that both fails to
decode an input region and needs to say its output has a break emits **both**: an
Undecoded block naming the input range, and a Discontinuity naming its own.

**A transport-layer stream MUST NOT carry one**, whatever its provenance. Its
offset space is already hole-inclusive — a gap occupies a real range that no
payload covers — so the break is expressible without any block, and the two
mechanisms would contradict each other. That covers a capture's reassembled
streams and a pass-through preserving them alike: the bar is the layer, not where
the bytes came from.

**A pass-through preserving a decoded layer carries these forward, renumbered.**
This is the whole of the rule; *Conformance* refers here rather than restating it.
Such a transform MUST re-emit every Discontinuity in its input, in its position in
the participant's stored order and with its `width` unchanged — a declared width is
a term in the positional arithmetic, so dropping one changes the very offsets a
pass-through exists to preserve.

**But it re-emits these differently from Undecoded blocks, and the difference is
the point.** An Undecoded block is copied *verbatim*, ids and all, because its
statement was always about a file further up the chain. A Discontinuity's ids name
the stream in the file that carries it, so a pass-through **renumbers** them to
its own `session_id`/`participant_id` — the same stream, named in the namespace of
the file now making the statement. Copying them verbatim leaves references into
the *input's* namespace among ids that are all the pass-through's own, and where
it minted fresh ones those references dangle.

> **This block is not safe to skip, and it is the only one that is not.** A reader
> that does not implement type `0x22` MUST skip it by `length` — and then computes
> a wrong positional range for every later record of that participant, silently,
> which is precisely the failure the block exists to prevent. Nothing in the frame
> can fix that: the skip rule works because an unknown block carries no meaning a
> reader needs, and this one does. Today it is covered completely by the `0.x`
> rule that a reader **MUST reject** a `version_minor` it does not implement.
> After `1.0`, adding a block like this would require a **major** bump — it is the
> concrete case of the rule in
> [Version numbering](#file-header-0x01), not an exception to it.

### Name/Identity Resolution (`0x30`)

Optional.

| Field            | Type | Notes                                   |
|------------------|------|-----------------------------------------|
| `session_id`     | u64  | the session being labelled into         |
| `participant_id` | u16  | participant being labelled              |
| `_reserved`      | u16  | 0                                       |

Options: `label` (string, the human name), `kind` (string, e.g. `nick` / `dns` /
`tls-sni`), `comment`. A block always names a concrete `(session_id,
participant_id)`; there is no file-global form (an append-only file cannot know
that a label stays global for the rest of the stream). Use this to attach labels
*after the fact*; the inline `endpoint`/`identity` on a Participant Descriptor is
preferred when known at declaration time.

### Custom (`0xFF`)

| Field       | Type  | Notes                                            |
|-------------|-------|--------------------------------------------------|
| `pen`       | u32   | IANA Private Enterprise Number (vendor namespace)|
| `subtype`   | u16   | vendor-defined block subtype                     |
| `_reserved` | u16   | 0                                                |
| `payload`   | bytes | opaque, vendor-defined (runs to end of block)    |

Readers without knowledge of `pen`/`subtype` skip via the frame `length`.

### End of file (`0x41`)

Optional. If present, it MUST be the **last block** in the file, and its presence
means the writer finished cleanly — the file is **complete**, not truncated. A
writer appends it on a clean close; a still-growing or crashed file simply omits
it. Body:

| Field       | Type | Value                                             |
|-------------|------|---------------------------------------------------|
| `end_magic` | u32  | `0x5A454E44` (`"ZEND"`); on disk the little-endian bytes `44 4E 45 5A` |

Options: `comment`. Bytes after this block are invalid — a `.zpf` is never
concatenated. A reader MUST NOT interpret them as blocks and SHOULD report
them; everything up to and including the End block remains valid and the file
still counts as complete (see [Conformance](#conformance)).

Completeness is detected by **forward reading alone**: reaching a valid End block
as the final block means complete; reaching end-of-stream — or a short, partial
block — without one means the file is still growing, truncated, or the writer
crashed (see [Truncation and completeness](#truncation-and-completeness)). No
seek-to-end is needed; the End block
is found in the normal block walk. In the JSONL projection it is a final
`{"type":"end"}` line.

### TLV option framing & id registry

`id: u16, len: u16, value` (then pad to 4 bytes). Options run until the block
`length` is consumed; there is no end-of-options sentinel. Because `len` is a
u16, **a single option value holds at most 65 535 bytes** (repeatable ids lift
this per-occurrence cap off the logical list — see below). `id 0x0001` is
`comment` (UTF-8) on any block. Ids are grouped by the block they belong to but
an id never changes meaning across blocks where it is reused (e.g. `decoder_id`).

**Preservation is universal; repeatability is only about interpretation.** A
reader MUST retain **every** occurrence of **every** option, in file order,
whether or not it recognises the id — this is what round-trip and forward
compatibility require, and it is *not* conditional on any "repeatable" marker. A
reader never silently drops a repeated option.

Whether an id is *single-valued* or *repeatable* is a **semantic** property in the
registry, consulted only by a consumer that actually interprets the id:

- A **repeatable** id is an ordered list; its occurrences and their order are
  significant. **The repeatable ids are `endpoint`, `spans` and `input_extents`**
  — a closed list; any future repeatable id MUST be added to it.
- A **single-valued** id (every other id) SHOULD appear at most once; a consumer
  that interprets it uses the **first** occurrence. If it nonetheless repeats, a
  faithful reader still preserves the extra occurrences for round-trip.
- The three repeatable ids list differently. Each `endpoint` occurrence is one
  list element (a tunnel layer). Each `spans` occurrence is a **chunk** of
  packed entries: successive occurrences concatenate, in file order, into the
  record's one span list. That is what lifts the per-occurrence value cap
  (⌊65 535 / 28⌋ = 2340 entries) off the logical list — a record needing more
  spans simply carries several `spans` options. Writers SHOULD coalesce
  adjacent ranges before resorting to that. `input_extents` chunks the same way
  as `spans` (⌊65 535 / 20⌋ = 3276 entries per occurrence), for the same reason.

| Id       | Name             | Value type | Used in                  | Meaning                                                        |
|----------|------------------|------------|--------------------------|----------------------------------------------------------------|
| `0x0001` | comment          | string     | any                      | free-text human note attached to the block                     |
| `0x0010` | time_epoch       | i64        | File Header              | origin for record timestamps (Unix-epoch ticks); default 0     |
| `0x0011` | creator          | string     | File Header              | tool + version that wrote the file                             |
| `0x0012` | produced_by      | string     | File Header              | tool + version that wrote this file. **Required** of a file holding a `zpf`-sourced stream; permitted on any file, including a capture-sourced one — a writer exists either way |
| `0x0013` | produced_at      | i64        | File Header              | wall-clock build time of this artifact (Unix seconds)          |
| `0x0014` | flags            | u16        | File Header              | file-level flags bitfield; bit `0x0001` = SINGLE_CLOCK (see [Sequenced files](#sequenced-files-precomputed-order)) |
| `0x0015` | transform_params_digest | string | File Header           | hash of the config of a transform that produced records **without decoding** — a filter, a reordering stage, a merge. A decode stage's config lives on its Decoder (`params_digest`); see [Layers](#layers-transport-and-decoded-live-in-separate-streams) |
| `0x0020` | uri              | string     | Source                   | where the referenced capture/input file lives                  |
| `0x0021` | digest           | string     | Source                   | content hash of the referenced file — the dependency edge      |
| `0x0022` | link_type        | u16        | Source (capture)         | link-layer type of the capture (e.g. a pcap LINKTYPE)          |
| `0x0041` | name             | string     | Decoder                  | decoder identifier, e.g. `http/1.1`                            |
| `0x0042` | version          | string     | Decoder                  | decoder version                                                |
| `0x0043` | params_digest    | string     | Decoder                  | hash of the decoder config, so the decode is reproducible      |
| `0x0050` | proto            | string     | Session                  | session protocol; well-known values `tcp`/`udp`/`http`/`tls`/`irc`/`dns`, other lowercase values permitted (unrecognized = opaque) |
| `0x0051` | flow_key         | string     | Session                  | human-readable flow key, e.g. `a:port <-> b:port`              |
| `0x0052` | flags            | u16        | Session                  | session-level flags bitfield; bit `0x0001` = SEQUENCED (see [Sequenced files](#sequenced-files-precomputed-order)) |
| `0x0053` | sequenced_basis  | string     | Session                  | what a `SEQUENCED` hint-less session's order rests on; **MUST** be present on such a session; open vocabulary, defined values `clock`/`protocol`/`external`/`trivial` (see [Sequenced files](#sequenced-files-precomputed-order)) |
| `0x0054` | external_session_id | bytes   | Session                  | an identity assigned by something *outside* this format — a trace id, a capture orchestrator's UUID, a case number. Opaque: nothing here interprets it (see [Session Descriptor](#session-descriptor-0x10)) |
| `0x0060` | endpoint         | string     | Participant              | participant address, e.g. `ip:port` or a nick (recommended spellings: see [Participant Descriptor](#participant-descriptor-0x11)); **repeatable**, outermost tunnel layer first → innermost last |
| `0x0061` | isn              | u32        | Participant              | the SYN's sequence number; MUST be present when the handshake was seen. Fixes the stream's absolute origin (first byte = `isn+1`); ordering does not use it |
| `0x0062` | identity         | string     | Participant              | stable identity distinct from a transient endpoint             |
| `0x0063` | tcp_role         | u8         | Participant (TCP)        | active/passive opener when the handshake was seen (see enums)  |
| `0x0064` | origin           | packed     | Participant (pass-through) | input stream this participant re-emits: `source_id: u16, pid: u16, session_id: u64` — ids in the source's namespace (see [Participant Descriptor](#participant-descriptor-0x11)) |
| `0x0070` | seq_start        | u32        | Record (TCP)             | absolute sequence number of the first payload byte             |
| `0x0072` | ack              | u32        | Record (TCP)             | the acknowledgement number from the wire: one past the highest contiguous peer byte the sender had received |
| `0x0073` | ts_first         | i64        | Record                   | optional packet time of the *first* contributing packet        |
| `0x0080` | spans            | span-list  | Record                   | source ranges these bytes **correspond to** — the input the unit was computed from, not necessarily a copy of it (see below) |
| `0x0090` | decoder_id       | u16        | Record, Undecoded        | which **decoder** produced or declined this record or region — not necessarily the stage that wrote this file (a pass-through, filter or reordering stage inherits it). The decoder's [`output_layer`](#decoder-descriptor-0x03) then gives the layer, which may be transport |
| `0x0091` | content_type     | string     | Record (**decoded layer only** — MUST NOT appear at the transport layer; advisory) | what the payload *is*: `mime:`/`prim:`/`dec:` (see [Typing a decoded record](#typing-a-decoded-record)) |
| `0x0092` | role             | string     | Record (**decoded layer only** — MUST NOT appear at the transport layer; advisory) | what this record **is**, in a vocabulary scoped to its decoder's `name`; opaque to the format, and independent of `content_type` (see [Typing a decoded record](#typing-a-decoded-record)) |
| `0x00A0` | reason           | string     | Undecoded                | why the region is undecoded; open vocabulary in two recoverability classes — bytes exist (`undecodable`/`skipped`/`dropped`) or hole (`gap`/`truncated`) — see [Undecoded](#undecoded-0x21) |
| `0x00A1` | reason_class     | string     | Undecoded                | `hole` or `bytes`; **MUST** accompany a `reason` outside the canonical five, and MUST agree with the class if it accompanies one of them |
| `0x00B0` | label            | string     | Name/Identity Resolution | the human-readable name being assigned                         |
| `0x00B1` | kind             | string     | Name/Identity Resolution | source/kind of the label (`nick`/`dns`/`tls-sni`)              |
| `0x00C0` | reason           | string     | Session End              | how the session ended: `fin`/`rst`/`timeout`/`capture-end`/… (open vocabulary) |
| `0x00C1` | input_extents    | packed     | Session End (derived)    | length of each input participant stream this session drew on, in that stream's own offset space: `source_id: u16, pid: u16, session_id: u64, extent: u64` — ids in the source's namespace; **repeatable**, occurrences concatenate (see [Session End](#session-end-0x12)) |
| `0x00D0` | width            | u64        | Discontinuity            | extent of the break in this stream's own offset space; **absent means unknown**, and an absent width contributes 0 to positional arithmetic (see [Discontinuity](#discontinuity-0x22)) |
| `0x00D1` | reason           | string     | Discontinuity            | why the stream breaks here: `tls-record-lost`/`decrypt-failed`/`stream-gap`/`records-dropped`/`reordered`/… (open vocabulary) |

A **span-list** value is `count` packed entries, each 28 bytes:
`source_id: u16, pid: u16, session_id: u64, off_start: u64, off_end: u64`
(`count = len / 28`). A record MAY carry several `spans` options; their entry
lists concatenate in file order into the record's single span set (see the
repeatability rules above). The two u16s lead so the u64 fields stay 4-byte aligned
within the packed entry — this packed order (`source_id, pid, session_id, …`)
differs from the logical/JSON field order (`source_id, session_id, pid, …`) *only*
for that alignment; all three faces name the same five fields, and since JSON is
keyed by name the reorder is immaterial there. The **interpretation of the offsets is keyed by the
referenced source's `kind`**: for a `zpf-input` source, `off_start`/`off_end` are
**logical 0-based stream offsets** within `(session_id, pid)` of that input; for
a `capture` source, they are **byte offsets into the capture file** and
`session_id`/`pid` are unused (write 0). One option id (`spans`) serves both
capture-provenance and derivation-provenance, and an
[Undecoded](#undecoded-0x21) block's body — the same five fields, the same packed
layout — is read by this same key.

**What `spans` asserts is correspondence, not identity.** The span set names the
input region the record's bytes were **computed from**; it does not promise that
region holds those bytes, nor that it is the same length. A record of 8 bytes may
span 16, or 16 000. Decoders that transform — gzip, HPACK, any decryption — are
expressible for exactly this reason, and the alternative reading is unimplementable:
deflate is stateful, so a byte mid-stream depends on the whole preceding window,
and a decoder asserting *everything this unit was computed from* would emit O(n)
spans per record, with HPACK worse.

**The workable rule is narrower than "fed".** A region is cited by the output unit
**whose emission it completed** — the one it finished, not every one it
influenced. Under deflate an early region feeds every later unit, so "fed" read
literally is the O(n) explosion this paragraph has just rejected; under the narrow
reading each region is named once, by the unit it delivered. That is what an
implementer will do, and it is what makes the
[coverage guarantee](#coverage-honesty-undecoded-blocks) meaningful without making
it impossible: every input offset is accounted for, by a span or by an Undecoded
block, whatever the decoder did to the bytes in between.

It is stated as what a producer SHOULD do rather than as a hard rule, because the
next paragraph permits the case where it cannot be followed exactly.

**Two records MAY cite the same input region.** The coverage guarantee requires
every offset to be covered **at least once**; it does not require exactly once,
and overlap between two records' span sets is not a violation. What remains
forbidden is a region being both spanned and marked Undecoded, which is a
contradiction rather than a duplication.

The reason to permit it is concrete. A decryptor's nonce and authentication tag
*fed* the plaintext — they are inputs to the computation — so an inner record
honestly spans the whole ciphertext packet, framing included. Where one such
packet decrypts to plaintext carrying **two** output units, both were genuinely
computed from that same framing, and requiring exactly-once would force a producer
to award those bytes to one of them arbitrarily. The guarantee exists to stop
bytes being **silently dropped**; overlap drops nothing, so exactness was doing
work it was never needed for.

**A span's — and an [Undecoded](#undecoded-0x21) body's — `session_id`/`pid` are
in the referenced *source's* id namespace, never the current file's.** They name
a session/participant *inside* `source_id` (the input being cited), which is a
different id space from the file that carries the reference — even when the
numbers happen to coincide. In the [end-to-end decoded
example](#a-decoded-file-end-to-end) the decoded file's own `session_id 7` and
the `session_id 7` cited by its `spans` and its `undecoded` block are the *same
number by coincidence*; resolving either means looking up session 7 in
`transport.zpf`, not in the decoded file. (A writer drawing
`session_id`s from a global sequence — see
[Identifiers & ordering](#identifiers--ordering) — makes them literally identical,
which is convenient but does not change that the span is read in the source's
space.)

### Enums

`kind` (Source body, u8): `0` = capture (a pcap/interface), `1` = zpf-input
(another `.zpf` this file was derived from).

`output_layer` (Decoder **body**, u8): `0` = decoded, `1` = transport. Always
present — it is a body field, so there is no absent case (see
[Decoder Descriptor](#decoder-descriptor-0x03) for why `decoded` is `0`).

**Two enums are load-bearing: Source `kind` and `output_layer`.** Both decide how
offsets are *read*, so a value neither the registry nor this document defines
leaves a reader unable to compute a stream's offset space at all. A reader
**MUST NOT** guess one, and treats the stream as a semantic violation it may
isolate — unlike `tcp_role`, where an unknown value is advisory and carrying the
raw number forward loses nothing.

`tcp_role` (Participant option, u8): `0` = unknown (handshake not observed),
`1` = initiator (active open, sent the SYN), `2` = responder (passive open). In
JSONL it renders as the string `"initiator"`/`"responder"`, and is omitted when
unknown.

`flags` (Record body, u16). The **JSON token** column feeds the JSONL `flags`
array (see [JSONL mapping](#jsonl--binary-field-mapping)):

| Bit      | JSON token   | Meaning                                                  |
|----------|--------------|----------------------------------------------------------|
| `0x0001` | `psh`        | TCP PSH seen in this run                                 |
| `0x0002` | `fin`        | TCP FIN seen                                             |
| `0x0004` | `rst`        | TCP RST seen                                             |
| `0x0008` | `syn`        | TCP SYN — a zero-length handshake-timing record (see [Handshake records](#record-0x20)) |
| `0x0010` | `urg`        | TCP URG seen                                             |
| `0x0040` | `retransmit` | retransmission/overlap was resolved inside this record   |
| `0x0080` | `message`    | message boundary: the record is exactly one transport message (a UDP datagram, an SCTP message, …) |
| `0xFF20` | —            | reserved, MUST be written 0, and MUST be ignored on read; a bit nonetheless set is preserved through a round-trip (as a hex token in JSONL), never interpreted |

`content_type` `prim:` vocabulary (Record option, string): the legal `prim:`
tokens are **exactly** the fixed-width integers below plus `prim:bytes` (an
uninterpreted byte string). `u`/`i` selects unsigned / signed two's-complement.
A fixed-width `prim:` payload is stored **little-endian** — the container's
byte order — and the emitting decoder normalizes it on write (a big-endian wire
value is byte-swapped by the decoder, never by the reader). No other `prim:`
token is legal — `mime:` and `dec:` carry everything else.

| Width   | Unsigned   | Signed     |
|---------|------------|------------|
| 8-bit   | `prim:u8`  | `prim:i8`  |
| 16-bit  | `prim:u16` | `prim:i16` |
| 32-bit  | `prim:u32` | `prim:i32` |
| 64-bit  | `prim:u64` | `prim:i64` |

Plus `prim:bytes`.

**`prim:` width binds `payload_len`.** For a fixed-width `prim:` token, the
record's `payload_len` (the *unpadded* length, not the 4-byte-padded frame size)
MUST equal the token's width: `1` for `prim:u8`/`prim:i8`, `2` for
`prim:u16`/`prim:i16`, `4` for `prim:u32`/`prim:i32`, `8` for
`prim:u64`/`prim:i64`. `prim:bytes` places no length
constraint (any `payload_len`, including 0). A writer MUST NOT emit a fixed-width
`prim:` label whose width disagrees with `payload_len`; a reader that finds a
mismatch MUST treat the `content_type` as unknown (opaque payload, falling back to
the decoder `name`), exactly as for an unknown scheme, and MUST NOT pad, truncate,
or reinterpret — the bytes remain the source of truth.

**`prim:` types storage, not the wire, and this is a decision rather than an
omission.** A protocol field narrower or wider than 8/16/32/64 — a 4-bit flag, a
24-bit length — has **no token**, and the conformant move is to widen to the
smallest that holds it: a 4-bit field is `prim:u8`, a 24-bit one `prim:u32`. The
*value* stays readable by any reader, which is what the width-binding rule above
is for, and the field's true width is then **not recoverable from the file**.
`spans` do not recover it either — a sub-byte field names the byte containing it,
and several such fields name the same byte.

That is the same answer this document already gives for byte order, a few lines
above: a fixed-width `prim:` payload is stored little-endian, and a big-endian
wire value is byte-swapped by the emitting decoder, never by the reader. A field's
true width is likewise the decoder's business, and a consumer that needs it reads
what the decoder documents, exactly
as it does for a `dec:` token or a [`role`](#typing-a-decoded-record). The
alternatives were weighed and declined: a significant-bits option would add a
field no reader can act on, and opening the vocabulary would break the
width-binding rule that is the only thing making `prim:` checkable at all. The
vocabulary stays closed
([#105](https://github.com/adamkjonsson/zipline/issues/105)).

### Identifiers & ordering

- `session_id`, `source_id`, and `decoder_id` are unique within a file.
  `participant_id` is scoped to its session. Ids MUST NOT be reused. `0` is a
  legal id value (no id is reserved as a sentinel — optional references like
  `decoder_id` signal "none" by *absence*, never by value 0).
- **Identifier widths.** `session_id` is u64; every other id
  (`participant_id`, `source_id`, `decoder_id`) is u16 — each width mirrors the
  population it counts. A `session_id` names an entity from an *unbounded,
  streaming* source: a flush-and-forget writer mints a fresh, never-reused id for
  every sessionized flow over a capture that may run indefinitely, so the counter
  only grows and a 16- or 32-bit space could wrap. u64 removes that ceiling, and
  is wide enough that a writer MAY draw `session_id`s from a single *global*
  monotonic sequence (process- or fleet-wide) rather than restarting per file;
  such an id is never reused across files either, so a cross-file reference (a
  decoded file's `spans` into a `zpf-input`, a chained derivation) names exactly
  one session with no risk of collision when files are merged or cross-linked. The
  other ids count small, *bounded*, per-file sets — participants, sources,
  decoders — none near the u16 limit, so a wider field would only waste space.
- On-disk block order is unconstrained beyond declare-on-first-use, with one
  ordering **MUST** that keeps reading cheap: within a given
  `(session_id, participant_id)`, a writer **MUST** emit that participant's
  records in `seq_start` order (logical stream order for non-TCP streams that
  have no sequence numbers) — the order in which it already produced them.
  **Non-descending**, not strictly ascending: two records MAY share a `seq_start`,
  and where they do, **stored order decides which comes first**. That is not a
  corner — a [handshake record](#record-0x20) sits at the stream origin and the
  first data record starts there too, so every file recording an observed
  handshake carries the tie. A reader comparing with `<` rather than `≤` rejects
  most real captures, which is why this says so rather than leaving "in order" to
  be read either way. This
  costs the writer nothing — each participant's byte stream is monotonic by
  construction — and is what lets the cross-participant
  [merge](#merge-algorithm) be a **streaming k-way merge** over already-sorted
  per-participant streams, bounding a reader's working set to the in-flight
  window rather than the whole session (see [merge cost](#merge-algorithm)). The
  one corner a writer must mind: having *committed* a gap (emitted a record past
  missing bytes), it MUST NOT emit the missing bytes if they later turn up —
  they are dropped; a writer that wants them must have buffered longer. A reader
  that meets an out-of-order record MAY reject the file or discard the offending
  session — it is **never required to reorder**, so no reader carries a sort
  path. *Across* participants, records MAY be interleaved in any order (capture
  order is the natural choice and keeps the timestamp tie-breaker meaningful);
  only the *per-participant* subsequence is constrained.

### Conformance

Every file MUST start with exactly one File Header as its first block, and MUST
declare each Source, Session, and Participant before any block references it. A
file MAY end with an [End block](#end-of-file-0x41); if present it MUST be the
last block, and its presence marks the file complete. A file MAY omit it — a
live/streaming or crashed writer does — and readers MUST still accept such a
file, treating it as not-known-complete.

**Provenance and layer are per stream, not per file.** Both are defined once, in
[the two axes](#conceptual-model); this section applies them and does not restate
them. What follows from them here is that a file MAY hold streams of differing
provenance and differing layer side by side, and that every rule below is a rule
about a stream even where a file is the convenient thing to name.

A `zpf`-sourced stream is produced one of two ways, and the difference is whether
its stage **creates** a layer or **preserves** one:

- A **decode stage** creates a layer. It runs decoders over its input's streams
  and emits records whose `spans` name the input ranges they **correspond to**,
  plus [Undecoded](#undecoded-0x21) markers for every region it did not decode.
  A decoder accounts for regions it could not parse by reference, never by
  copying bytes forward. Its records' bytes need not appear in its input: a
  decoder MAY transform (see
  [Typing a decoded record](#typing-a-decoded-record)).
- A **pass-through transform** preserves the layer its input already had. It
  re-emits that input's records with their bytes, logical offsets, `decoder_id`s
  and Undecoded markers **unchanged**, and its provenance is stream-level: an
  [`origin`](#participant-descriptor-0x11) on every participant, no `spans` on
  any record.

**The discriminator between the two is `spans` versus `origin`, not
`decoder_id`.** A record carrying `spans` was built by this file's stage; a
record without `spans`, whose participant carries `origin`, was re-emitted from
the input unchanged. `decoder_id` answers a different question — which decoder's
layer a record belongs to — and a pass-through carries inherited `decoder_id`s
forward, so it does *not* imply the decoder ran in this stage.

**The discriminator binds per participant, so one file MAY do both.** A
participant **MUST NOT** both carry `origin` and hold records carrying `spans`:
one stream is created or preserved, never half of each. Across streams there is no
such rule, and a transform that decodes one session while passing another through
is ordinary — it is what a tool does when it has a decoder for one protocol and
not the other. Forbidding it would leave that tool two dishonest options: pass
everything through, or mark the second stream entirely Undecoded, which drops
those bytes from the output altogether. A file whose streams are a mix declares
every input it drew on and sets `produced_by`/`produced_at` once, as any derived
file does.

**And a `zpf`-sourced participant MUST be one or the other.** The two ways above
are exhaustive, so a participant carrying **neither** `origin` nor records with
`spans` is a violation: its records reference a `zpf-input` Source and say nothing
about which stream inside it they came from, so nothing resolves one level down
and no coverage obligation can be computed either way. A reader MAY isolate it.
The rule binds on `zpf`-sourced streams alone — a capture-sourced participant
carries neither, and its `source_id` is the whole of its provenance.

One decode stage MAY also mix *decoders* per-record (HTTP on one session,
TLS-then-HTTP on another). Every file holding a `zpf`-sourced stream MUST declare
each of its input `.zpf`s as a `zpf-input` Source and set the File Header
`produced_by`/`produced_at`.

**But every record of one participant MUST resolve to the same layer.** Mixing
decoders says what each record *is*; the layer says where the stream's bytes
**are**, and one participant cannot have two answers. A participant holding a
record whose decoder declares `transport` beside one whose decoder declares
`decoded` — or a decoder-less record, which is transport by the
[layer rule](#conceptual-model), beside a decoded one — has an offset space with
two incompatible definitions, and a reader computing `input_extents` or resolving
a downstream `spans` entry against it gets a number that means nothing. Such a
participant is a semantic violation a reader MAY isolate.

This is what makes *the stream's layer* well defined rather than merely intended,
and it is why a reader may resolve the layer **once per participant** and cache
it, rather than per record.

**The head-of-pipeline reassembler SHOULD declare itself, and MUST NOT be required
to.** A capture-sourced transport stream MAY carry a Decoder declaring
`output_layer = transport`, naming the reassembler that produced it and hashing its
configuration — the same statement a sessionization stage makes, one step earlier in
the chain. It is a **SHOULD** so that every file written before this option existed
stays conformant and the idiom can migrate.

*This leaves a deliberate asymmetry, recorded here rather than left to be
rediscovered:* one logical layer — reassembly — is labelled when a stage performs it
over a `.zpf` and usually unlabelled when the same operation runs over a capture. A
consumer therefore cannot assume that an undeclared transport stream had no
reassembler, only that none was named. The alternative was to require the
declaration and make every existing capture-sourced file non-conformant for saying
nothing new.

**Not every `zpf-input` Source is an input.** A file may also declare one so that
an *inherited* reference still resolves — a pass-through carrying Undecoded
blocks that name a file further up the chain does exactly this (see the
[annotator example](#annotating-a-decoded-file)). The two are told apart by what
points at them: a file's **immediate inputs** are the Sources its participants'
`origin` options name, for a pass-through, or its records' `spans` name, for a
decode stage. Anything else declared as `zpf-input` is there to resolve a
reference, not because this file was derived from it.

**The transport layer's own requirements bind on the layer, not on provenance.**
In a **transport-layer** stream, however it was produced: TCP records SHOULD carry
`seq_start` (and `ack` where known); TCP participants **MUST** carry `isn` when the
handshake was observed — it fixes the stream's absolute origin (see
[Referencing the source by stream offset](#referencing-the-source-by-stream-offset))
— and omit it otherwise; and records of message-oriented transports (UDP) SHOULD
set the `message` flag. A sessionization stage's output is `zpf`-sourced and carries
all three exactly as a capture's does, which is the point of it being a transport
layer at all.

Two further requirements bind on the layer, and both are stated in full elsewhere:
such a record carries **no `content_type`** (see
[Typing a decoded record](#typing-a-decoded-record)), and a stage emitting this
layer **MUST NOT withhold content** from a stream whose offsets are not
sequence-anchored, having no way to express the break (see
[Discontinuity](#discontinuity-0x22)).

- A **capture-sourced** record references a `capture` Source. It carries a
  `decoder_id` exactly when its stream has a decoder — which for a head-of-pipeline
  reassembler is a SHOULD, and for the case below is how the stream says what it is.
- A **decoded record with no predecessor file** carries a `decoder_id` and
  references a `capture` Source: a TLS-terminating proxy, an `SSL_write` uprobe, a
  QUIC library's own stream log. The bytes its units were computed from were never
  written to a `.zpf` and never will be, so there is no input stream, no `spans`
  and no `origin`. Two consequences follow and neither is an exception:
  **the coverage guarantee does not apply**, because it is scoped *within each
  input participant stream* and there is none — it degrades on its own rather than
  needing to be excused; and the referenced **Decoder is a claim of identity, not
  a recipe**, so the
  [reproducibility contract](#decoder-descriptor-which-decoding) is vacuous here
  rather than merely key-gated. Nothing can regenerate this output, and tooling
  that assumes re-derivation is available is wrong about this file. The file MUST
  still declare every Decoder it references.
- A **sessionization stage** is a decode stage whose decoder is the reassembler: it
  reads one or more `.zpf` inputs and produces a **transport** layer, its Decoder
  declaring `output_layer = transport`. Its records carry `spans` and `decoder_id`
  like any decode stage's, and everything else about it is a transport stream —
  `isn`-anchored, hole-inclusive offsets, `seq_start` on records, no
  `content_type`, and no [Discontinuity](#discontinuity-0x22), since a hole is
  expressible without one. It is the same operation as the head-of-pipeline
  reassembler with a different input kind, and giving it a Decoder is what gives its
  overlap policy, buffer depth and timeout somewhere to be recorded.
- A **decoded** record carries a `decoder_id` whose Decoder declares
  `output_layer = decoded`. In a **decode stage's**
  output it MUST also carry `spans` and reference a `zpf-input` Source, and that
  file MUST declare every Decoder it references and account for every input
  region it did not decode with an **Undecoded** block rather than dropping it:
  within each input participant stream, every offset MUST be covered **at least
  once** by some decoded record's `spans` or by an Undecoded block naming that
  stream in the source's id namespace, and MUST NOT be both (**the coverage
  guarantee** — see [Coverage honesty](#coverage-honesty-undecoded-blocks)). The covering spans MAY
  come from records in **different output sessions**: the stage's output sessions
  need not correspond one-to-one with its input's, in either direction, and the
  guarantee is per input participant stream rather than per session exactly so
  that it survives that. A decoded record also
  appears in a **pass-through** file preserving a decoded layer, where it
  carries no `spans` (see below). A **Decoder Descriptor** appears wherever a
  `decoder_id` is referenced, whatever the stream's provenance. An **Undecoded**
  block appears wherever a stage declined or could not reach a region of an input
  it names — including a *capture-sourced* stream, where the input is the capture
  and a reassembler is the stage; the older rule barring it there assumed that
  capture-sourced meant no transform had run, and reassembly is a transform with
  things to declare. A [Discontinuity](#discontinuity-0x22) is narrower than
  either: it belongs to **decoded-layer streams only**, for the reason given in
  its own section. A Discontinuity is a statement about the file's **own**
  output stream and discharges no coverage obligation: a stage that could not
  decode an input region *and* needs to say its output breaks emits both blocks.
  When a stage must *originate* one, rather than carry an input's forward, is
  stated in [what a producer owes the block](#discontinuity-0x22) and is
  deliberately not restated here.
- A **pass-through** record is any record a pass-through *stream* re-emits. It
  carries no `spans` — `origin` plus offset preservation is its provenance — and
  it carries a `decoder_id` exactly when the input's record did. Its `source_id`
  references a `zpf-input` Source. A pass-through transform (e.g. the
  [merge](#sequenced-files-precomputed-order)) MUST preserve each participant
  stream it re-emits — payload bytes and logical offsets unchanged, in the
  offset space of whichever layer the input was at, gaps included where that
  layer has them — and MUST put exactly one
  [`origin`](#participant-descriptor-0x11) option on every participant, mapping
  it to its input stream. Preserving a **transport** layer, it MUST carry TCP
  ordering hints (`seq_start`/`ack`) forward (recomputed if records are
  re-chunked) so gap visibility and `SEQUENCED` verification survive.

  **Carrying `decoder_id` forward is keyed on the decoder, not on the layer.**
  Wherever the input's records carry one — a decoded stream, or a transport stream
  whose reassembler declared itself — the pass-through MUST carry it forward and
  MUST re-declare the Decoder Descriptors it references, `output_layer` included.
  Dropping the declaration would change the layer the output reads as, which is the
  one thing a pass-through exists not to do.

  Preserving a **decoded** layer, it MUST additionally carry each record's
  `content_type` forward and
  re-emit every Undecoded block — which is what makes the input's coverage
  guarantee hold of the output too, without the output having any `spans` of its
  own. An inherited Undecoded block names a stream in a file *further up* the
  chain (the decode stage's own input), so the pass-through MUST also declare
  that file as a Source of its own and MUST make the block's `source_id` resolve
  to it. Keeping the inherited ids unchanged and numbering its own immediate
  input around them is the simplest way to satisfy this, and lets the blocks be
  copied verbatim. This is the one place a derived file names something other
  than its immediate input, and it does so because the *statement* being carried
  forward was always about that file.

  It MUST also carry every [Discontinuity](#discontinuity-0x22) block forward,
  **renumbered to its own ids** — unlike the Undecoded blocks above, which are
  copied verbatim. See [Discontinuity](#discontinuity-0x22), which states that
  rule and why the two differ.

**Ordering and sequencing.** A writer **MUST** store each participant's records
in `seq_start` (logical stream) order; this is what guarantees an unsequenced
reader's merge is a streaming pass (see
[Identifiers & ordering](#identifiers--ordering)). A reader that detects a
violation MAY reject the file or discard the offending session; it is never
required to reorder records.
Separately, a session MAY set the Session Descriptor `flags` **SEQUENCED** bit; if
it does, the producer MUST store that session's records so their Record-block file
order is a valid causal linearization (concurrent records ordered by the
producer's tie-break), and a reader MAY then consume them in stored order without
running the [merge](#merge-algorithm). A reader MUST NOT assume a session is
sequenced unless its bit is set, and MUST still accept sessions that omit it. For
a session with no causal hints (no TCP `seq`/`ack` — e.g. chat or one-way UDP),
the producer MUST NOT set SEQUENCED without a **sound basis** for the order it
stores: a single trustworthy clock shared by every record in the session, or
ordering knowledge this format does not model (see
[Sequenced files](#sequenced-files-precomputed-order)), and it **MUST** record
which via `sequenced_basis`. A session with one participant, or with only one
sender, meets the *soundness* bar trivially and records `trivial`; the recording
requirement itself has no exemption. The File Header `flags` **SINGLE_CLOCK** bit is the
file-wide assertion of the clock property (timestamps globally comparable, no
inter-source skew); when set it supplies that basis for every hint-less session,
and a downstream tool may rely on it to sequence streams it regroups. The basis
requirement binds **hint-less sessions only** — a session carrying `seq`/`ack`
may be sequenced whatever its timestamps do, and needs no `sequenced_basis`.

A **missing** `sequenced_basis` on a hint-less `SEQUENCED` session is a semantic
violation, isolatable like any other. A reader can only raise it at
[Session End](#session-end-0x12) or end-of-stream, because until then it does not
know the session is hint-less (see [Merge algorithm](#merge-algorithm)). A reader MUST NOT reject a session merely
for carrying a `sequenced_basis` value it does not recognise — the vocabulary is
open, and an unknown value means an unknown basis, not an invalid one.

**Timestamps are not an ordering invariant.** Record timestamps are **not**
required to be non-decreasing in stored order, in any session, sequenced or not.
A reader therefore:

- **MUST NOT** reject a file, or discard a session, because timestamps run
  backwards in stored order. Inversion is an expected consequence of skewed
  capture clocks and of causal sequencing, not a corruption signal (see the
  [worked example](#worked-example-a-skewed-two-file-capture)).
- **MUST NOT** re-sort a **SEQUENCED** session by timestamp. Its stored order is
  the authoritative order; a timestamp that contradicts it is the clock being
  wrong, not the file.
- Uses timestamps for ordering in exactly one place: as the tie-break between
  causally *concurrent* records while running the [merge](#merge-algorithm) on a
  non-sequenced session (step 4), where `participant_id` settles an exact tie.

The only stored-order guarantee a reader may rely on — and the only one whose
violation it may act on — is the per-participant `seq_start` ordering above,
which is a **sequence** rule, not a time rule.

**Session lifetime.** A writer SHOULD emit a [Session End](#session-end-0x12)
block at the moment it flushes-and-forgets a session. At most one Session End
MAY appear per session, only after that session's declaration; after it the
writer MUST NOT emit any block referencing that `session_id`. Readers MUST NOT
require the block — reaching the End block or end-of-stream closes every
still-open session — but MAY free a session's state the moment they see it.

Readers MUST skip unknown block types (via frame `length`) and unknown option
ids (via `len`), and MUST treat reserved fields/bits as ignored-on-read.

**Error handling.** Writer obligations in this document are enforced by
readers in two tiers, split by what the violation poisons:

- **Structural corruption — the reader MUST reject the file.** When the byte
  stream itself can no longer be trusted, isolating a smaller unit is unsound.
  This tier: a bad or missing [magic](#file-header-0x01); a File Header absent
  or not first; a `version_major` the reader does not implement, **or — while
  `version_major` is `0` — a `version_minor` it does not implement** (see
  [File Header](#file-header-0x01));
  `tick_hz = 0`; a block `length` that is not a multiple of 4; a `payload_len`
  or TLV `len` that overruns its block. One condition that looks structural is not:
  running out of bytes at the **end of the stream** is *truncation*, an
  expected condition with its own lenient rule
  ([Truncation and completeness](#truncation-and-completeness)), which takes
  precedence.
- **Semantic violations — the reader MAY isolate.** When a well-framed block's
  *content* violates a MUST — it references an undeclared
  `session_id`/`pid`/`source_id`/`decoder_id`; an id is declared twice; a
  block appears where its kind is forbidden (an `origin` option on a
  capture-sourced stream, a Discontinuity on a transport-layer one, a `hole`-class
  Undecoded region against a `capture` Source, a stream
  derived from another in the same file, a block referencing a session after its
  [Session End](#session-end-0x12), a second Session End); a participant is
  malformed as a stream (its records resolve to **two layers**; it is
  `zpf`-sourced and carries **neither** `origin` nor records with `spans`; it
  carries `origin` *and* holds records with `spans`); the coverage
  guarantee fails — the reader MAY reject the file, or discard the smallest
  unit it can soundly isolate: the offending block, or the session it belongs
  to. It MUST NOT silently reinterpret or repair the data — no reordering
  records, no inventing missing declarations, no guessing at what the writer
  meant. Where this document states a specific rule for a violation (the
  per-participant [ordering rule](#identifiers--ordering), the `prim:`
  [width-mismatch rule](#enums), the
  [origin floor](#referencing-the-source-by-stream-offset)), that rule
  **displaces this licence**: a reader applies the stated rule instead, whether it
  is stronger or weaker than isolation. Some are weaker — the `prim:` rule and the
  origin floor both keep the record, ignore the part that is wrong, and report —
  so reading them as instances of a tier headed *the reader MAY isolate* gets them
  backwards.

A reader that tolerates a semantic violation or discards data SHOULD surface a
diagnostic — data must never vanish silently. **Bytes after a valid End block**
get the same isolating treatment at file scope: everything up to and including
the End block remains valid and the file still counts as complete, but the
reader MUST NOT interpret the trailing bytes as blocks and SHOULD report them
(they are usually an accidental concatenation — see below). None of this
applies to the *extension mechanism*: an unknown block type, an unknown option
id, or a nonzero reserved field is **not** a violation — the skip/ignore rules
above are the normal, conformant path.

**Unrecognised enum values.** An enum value with no defined label is likewise not
a violation in itself; what follows from it depends on what the enum governs, and
the two enums this document defines differ:

- `tcp_role` is advisory, so an unrecognised value means simply "unknown",
  exactly as an omitted option does. A reader carries it and moves on.
- Source `kind` is **load-bearing**: it fixes a stream's provenance, tells a
  decoder-less record apart as capture-sourced or pass-through, and selects how a
  `spans` entry's offsets are read (capture-file byte offsets vs logical stream
  offsets — see the [span-list rule](#tlv-option-framing--id-registry)). A reader
  that does not recognise a Source's `kind` therefore cannot interpret any record
  or span referencing it, and this **is** an isolatable semantic condition: the
  reader MAY reject the file, or discard that Source together with everything
  referencing it, and SHOULD report it. It MUST NOT guess a kind.

A consequence worth stating for future editors: **`kind` is not a free extension
point.** Adding a value to it is not like adding an option id, which old readers
skip harmlessly; old readers will isolate sources they cannot classify. Any new
`kind` must therefore come with a minor bump and the expectation that pre-existing
readers reject those files.

**Concatenation is not supported.** A `.zpf` file has exactly one File Header,
at its very start; bytes after the last complete block are not a new section.
Concatenating two `.zpf` files does **not** yield a valid `.zpf`. To split a
streaming intercept across several files, the producer is responsible for making
their order recoverable out-of-band (a naming convention, a manifest, etc.).

### Truncation and completeness

The format is forward-only and streamable. A reader that finds fewer than
`length` bytes remaining for a block MUST treat the file as **truncated at that
block** (a writer crash mid-flush) and discard the partial tail; all complete
prior blocks remain valid. Truncation is an expected condition, not structural
corruption — a short *final* block is governed by this rule, never by the
reject rule in [Conformance](#conformance).

Completeness is signalled positively by the optional [End block](#end-of-file-0x41):
a file ending in a valid End block was finalized cleanly, whereas one that reaches
end-of-stream without it is either still growing, truncated, or the product of a
crashed writer. The End block is the only thing that distinguishes "intentionally
finished" from "stops here"; absent it, the two are indistinguishable (which is
fine for a live stream that is legitimately still open).

### JSONL ↔ binary field mapping

The JSON-Lines projection is **semantically** lossless for every field. It is
defined by **one rule plus a short list of exceptions**, so it stays complete as
options are added rather than depending on an enumerated key list — and by a
mirror of the binary face's skip-what-you-don't-know rule
([the four escapes](#unrecognised-data-the-four-escapes)), so it stays complete
as *later versions* add blocks, values and bits.

**The rule.** For any block, its JSON keys are the **canonical names** of its
binary body fields and its TLV options — the field names in the block's body
table and the `Name` column of the
[option registry](#tlv-option-framing--id-registry) — used verbatim as JSON keys,
*except* for the brevity aliases below. **Body fields always project** — an
omitted key can only ever be an absent *option* (the absent-key rule below). An
option a converter does not recognise (a future registry id) round-trips through
a generic `options` array; anything that **is** registered MUST use its canonical
key and MUST NOT be placed in `options`. Everything else a converter may fail to
recognise — a block type, an enum value, a flag bit — has its own escape (see
[the four escapes](#unrecognised-data-the-four-escapes)). The block is selected
by its `type` string.

**`type` string ↔ block.**

| `type`        | Block                             |
|---------------|-----------------------------------|
| `file`        | File Header (`0x01`)              |
| `source`      | Source Descriptor (`0x02`)        |
| `decoder`     | Decoder Descriptor (`0x03`)       |
| `session`     | Session Descriptor (`0x10`)       |
| `participant` | Participant Descriptor (`0x11`)   |
| `session_end` | Session End (`0x12`)              |
| `record`      | Record (`0x20`)                   |
| `undecoded`   | Undecoded (`0x21`)                |
| `discontinuity` | Discontinuity (`0x22`)          |
| `name`        | Name/Identity Resolution (`0x30`) |
| `end`         | End (`0x41`)                      |
| `custom`      | Custom (`0xFF`)                   |

**Brevity aliases** — the only keys whose JSON name differs from the binary
name:

| JSONL key    | Binary field / option                                            |
|--------------|------------------------------------------------------------------|
| `format`     | `version_major`/`version_minor` as `"zipline-payload/<major>[.<minor>]"`; an omitted minor is `0` (so `"zipline-payload/2"` would be major 2, minor 0). Each component is an independent integer — parse them separately and compare componentwise, **never** as one decimal number, or `0.10` sorts below `0.9` |
| `ts`         | `timestamp` (Record)                                            |
| `pid`        | `participant_id` (block body, each `spans` entry, and `origin`)  |
| `key`        | `flow_key` (Session)                                            |
| `single_clock` | File Header `flags` bit `0x0001`, rendered as a boolean        |
| `sequenced`  | Session `flags` bit `0x0001`, rendered as a boolean             |

(`proto` is **not** an alias — its JSON key equals its option name.)

The File Header rate is the key **`tick_hz`**, carrying the same number as the
binary field. It is not an alias and never appears in the table above: the
general naming rule covers it.

**Value encoding.**

- **Integers** → JSON number, with one exception: a **64-bit** field (`session_id`,
  `ts`/`timestamp`, `tick_hz`, `time_epoch`, `produced_at`,
  `ts_first`, `off_start`, `off_end`, `extent`, `width`) MAY be written as a JSON number **or** a
  decimal string, and a writer SHOULD use the string form when the value exceeds
  2⁵³ (beyond JSON's exact-integer range). A reader MUST accept both. 32-bit and
  narrower fields are always plain numbers.
- **Strings** → JSON string; a `digest` keeps its `"<alg>:<hex>"` form.
- **`payload`** and any raw-byte value → **standard base64** (RFC 4648 §4, with
  `=` padding). This covers an option whose registry type is **`bytes`**
  (`external_session_id`) exactly as it covers the Record and Custom bodies: the
  value is opaque, so it projects as base64 rather than being spelled. A reader
  MUST NOT assume a `bytes` option is text, even when it decodes to printable
  ASCII.
- **Enums** render as their defined **string label**: `kind` as
  `"capture"`/`"zpf-input"`, `output_layer` as `"decoded"`/`"transport"` (always
  present, since it is a body field), `tcp_role` as
  `"initiator"`/`"responder"` (omitted
  when unknown). A value with **no defined label** renders as its raw number
  (see [the escapes](#unrecognised-data-the-four-escapes)). For the two
  **load-bearing** enums that number is not a value a reader may act on — it
  preserves the byte through a round-trip and nothing more.
- **Flag bitfields** render by name, never as the raw integer: the single-bit
  file and session flags are booleans (`"single_clock"` on `file`, `"sequenced"`
  on `session`), and a Record's multi-bit `flags` is an **array of set-bit
  tokens** (the JSON-token column of the [flags enum](#enums), e.g.
  `"flags":["psh","fin"]`). A set bit with **no token** renders as a hex token
  (see [the escapes](#unrecognised-data-the-four-escapes)). A zero/unset
  bitfield is omitted.
- **Repeatable options** (`endpoint`) → a JSON **array**, order preserved —
  **always an array, even for a single occurrence** (`["10.0.0.1:51000"]`), so a
  reader never has to branch on the JSON type of a key. (`spans` and
  `input_extents`, whose repetition is chunking rather than listing, have their
  own rules below, and are likewise always arrays.)
- **`spans`** → a JSON array of `{source_id, session_id, pid, off_start, off_end}`
  objects; repeated binary occurrences merge into this one array, and a
  converter back to binary MAY split it into several occurrences.
- **`origin`** → a JSON object `{source_id, session_id, pid}` (a `spans` entry
  without offsets; ids in the referenced source's namespace).
- **`input_extents`** → a JSON array of `{source_id, session_id, pid, extent}`
  objects, always an array; repeated binary occurrences merge into it and a
  converter back to binary MAY split it again, exactly as for `spans`. Ids are in
  the referenced source's namespace.
- An **absent** option is an **omitted** key; a reader treats a missing key as
  "option not present," never as a present option carrying a default.
- **Framing / on-disk-only fields are not projected**: the block
  `type`/`reserved`/`length`, the header `magic`, `end_magic`, `payload_len`, and
  padding have no JSON key — the `type` string, the JSON object structure, and the
  base64 `payload`'s own length stand in for them.

#### Unrecognised data: the four escapes

The binary face has one universal rule for anything a reader does not recognise:
skip it by its stated length, retain it, and do not treat it as an error. The
projection mirrors that rule exactly — **every unrecognised element has a defined
syntactic escape, a converter never invents meaning for one, and a converter
never silently drops one.** None of this is an error path; it is the normal,
conformant behaviour that lets a file written against a later minor version
survive a round-trip through an older converter.

| Unrecognised            | JSONL form                                                                 |
|-------------------------|----------------------------------------------------------------------------|
| **option id** — not in the registry | an entry in the block's `options` array: `{"id":"0x0200","value":"<base64 of the raw option value>"}` |
| **block type** — not in the `type` table | `"type":"0x0042"` plus `"content":"<base64 of the block's whole content>"` |
| **enum value** — no defined label | the raw number in place of the string label                  |
| **flag bit** — no JSON token | a hex token for that single bit, e.g. `"flags":["psh","0x0020"]`  |

A hex form is `0x` followed by exactly four hex digits, spelled as in the
[option registry](#tlv-option-framing--id-registry). It is unambiguous against
every defined `type` string and flag token, all of which are words.

**Unknown block type.** A converter that does not know a `type` cannot split the
block into body and options — the body layout is exactly what it lacks — so it
does not try. `content` is the block's entire content field (body ++ options ++
padding) as one opaque base64 value, and the line carries no other key.
Converting back writes that type number and those bytes verbatim. Since content
is always a whole number of 4-byte units, this particular round-trip is
byte-exact.

**Unknown enum value and unknown flag bit** both carry their number across
unchanged, so a value or bit that gains a name in a later minor version
round-trips through an older converter and is understood by a newer one.
Preserving is not interpreting: a reader still ignores reserved bits
semantically, exactly as it retains but ignores unknown option ids.

**Unknown keys on a known block** are the one case with no escape, by design. A
converter **MUST NOT** invent an option id for a JSON key it does not recognise —
there is no id to write, and guessing would manufacture data. Such a key cannot
come from a binary source (unregistered options project into `options` under
their real id), only from hand-written or third-party JSONL. On the JSONL →
binary path a converter MUST therefore either reject the line or drop the key,
and MUST report it either way; on a JSONL → JSONL path it preserves the key
unchanged.

**`Custom` blocks** are recognised, not unknown: a `custom` line carries `pen`,
`subtype`, and a base64 `payload`.

**Semantic, not byte-exact.** A binary → JSONL → binary round-trip preserves
every field's *value*, but **not** the exact bytes: padding, the ordering of
distinct options within a block, how a `spans` list is split across
occurrences, and the choice of optional/default encodings are
not pinned down by JSONL. (An unrecognised block is the lone exception — its
content survives byte-for-byte, precisely because a converter cannot take it
apart and so cannot re-encode it differently.) Consequently a round-tripped
file's hash differs from the original's. The `digest` dependency-edge (and any
conformance hashing) is
therefore defined over the **binary form only** — never over a file that has been
passed through the JSONL face.

### Worked example: a minimal capture-sourced file

A complete, conformant **capture-sourced** `.zpf` file (196 bytes) holding
one TCP session with one declared participant and one record — the client's
`GET / HTTP/1.1\r\n\r\n` from the
[skewed two-file worked example](#worked-example-a-skewed-two-file-capture)
(`session_id 7`, `pid 0`, `ts 1000`, absolute `seq [1001,1019)`, `ack 5001`).
Offsets are hex; each line is annotated.

```text
# ── File Header (0x01) ──────────────────────────────────────────────
0000  01 00                    type   = 0x0001  File Header
0002  00 00                    reserved
0004  10 00 00 00              length = 16
0008  46 50 49 5A              magic  = 0x5A495046  ("ZIPF")
000C  00 00                    version_major = 0
000E  12 00                    version_minor = 18   (0.18, little-endian)
0010  40 42 0F 00 00 00 00 00  tick_hz = 1_000_000  (microseconds)

# ── Source Descriptor (0x02) ────────────────────────────────────────
0018  02 00                    type   = 0x0002  Source Descriptor
001A  00 00                    reserved
001C  14 00 00 00              length = 20
0020  01 00                    source_id = 1
0022  00                       kind = 0  (capture)
0023  00                       _reserved
0024  20 00 0A 00              option 0x0020 uri, len = 10
0028  73 69 64 65 41 2E 70 63  "sideA.pc
0030  61 70                     ap"
0032  00 00                    value padding → 4-byte boundary

# ── Session Descriptor (0x10) ───────────────────────────────────────
0034  10 00                    type   = 0x0010  Session Descriptor
0036  00 00                    reserved
0038  10 00 00 00              length = 16
003C  07 00 00 00 00 00 00 00  session_id = 7  (u64)
0044  50 00 03 00              option 0x0050 proto, len = 3
0048  74 63 70                 "tcp"
004B  00                       value padding

# ── Participant Descriptor (0x11) ───────────────────────────────────
004C  11 00                    type   = 0x0011  Participant Descriptor
004E  00 00                    reserved
0050  28 00 00 00              length = 40
0054  07 00 00 00 00 00 00 00  session_id = 7  (u64)
005C  00 00                    participant_id = 0
005E  00 00                    _reserved
0060  60 00 0E 00              option 0x0060 endpoint, len = 14
0064  31 30 2E 30 2E 30 2E 31  "10.0.0.1
006C  3A 35 31 30 30 30        :51000"
0072  00 00                    value padding
0074  61 00 04 00              option 0x0061 isn, len = 4
0078  E8 03 00 00              isn = 1000  (stream origin; first byte = 1001)

# ── Record (0x20) ───────────────────────────────────────────────────
007C  20 00                    type   = 0x0020  Record
007E  00 00                    reserved
0080  40 00 00 00              length = 64
0084  07 00 00 00 00 00 00 00  session_id = 7  (u64)
008C  00 00                    sender_pid = 0
008E  01 00                    source_id  = 1
0090  E8 03 00 00 00 00 00 00  timestamp  = 1000
0098  00 00                    _reserved  (u16 = 0)
009A  01 00                    flags      = 0x0001  (PSH seen)
009C  12 00 00 00              payload_len = 18
00A0  47 45 54 20 2F 20 48 54  "GET / HT
00A8  54 50 2F 31 2E 31 0D 0A  TP/1.1\r\n
00B0  0D 0A                    \r\n"
00B2  00 00                    payload padding → 4-byte boundary
00B4  70 00 04 00              option 0x0070 seq_start, len = 4
00B8  E9 03 00 00              seq_start = 1001  (absolute)
00BC  72 00 04 00              option 0x0072 ack, len = 4
00C0  89 13 00 00              ack = 5001
00C4                           (end of file, 196 bytes)
```

Things to read off it: the magic at fixed offset 8 identifies the file; the 8-byte
frame keeps every block 4-byte aligned, and `length` jumps a reader from each
block to the next (`0x18 = 0x00 + 8 + 16`, `0x34 = 0x18 + 8 + 20`, …); the `GET`
payload is 18 bytes but is padded to 20 so the option stream resumes on a 4-byte
boundary; the ordering hints are **absolute** sequence numbers (`seq_start 1001 =
isn 1000 + 1`); and the record references `session_id 7` / `sender_pid 0` /
`source_id 1`, every one of which was declared by an earlier block — the
declare-on-first-use contract holding in the byte stream.

## Prior art this borrows from

- **pcapng** — block container with TLV options; multiple sources per file.
- **WARC (ISO 28500)** — record stream; raw payload + linked derived/metadata
  records (the model for transport-vs-decoded views).
- **Matroska/MP4** — N timestamped, interleaved tracks (the multi-participant
  mental model).
- **HAR** — the ergonomics target for the optional decoded JSON view (not the
  storage format).

## Open questions

- Compression: per-record, per-session, or whole-file?
- Should a `zpf-input` Source reference a whole input file, or also pin a
  per-session digest, so a single changed session forces re-derivation of only
  that session?

## Design decisions not taken

Ideas weighed and **rejected**, kept here with the reasoning because each is a
question that recurs — a reader who wonders why the format does *not* do one of
these finds the answer where the question arises.

This is not a backlog. Planned work lives in the
[issue tracker](https://github.com/adamkjonsson/zipline/issues); see
[Planned, tracked elsewhere](#planned-tracked-elsewhere) below.

- **A File Header option recording that a file's bytes were re-stamped from an
  earlier version.** So a `0.12` file could be relabelled `0.13` and say honestly
  that it had been. *Not adopted, and not deferred:* there is no regime in which
  it is the right tool. **In `0.x`** — now — the format's own position is that a
  file which still matters is regenerated from its capture, so the option would
  exist to support the thing the specification says not to do. **In a `1.x`
  minor** it is unnecessary: a reader MUST NOT gate parsing on `version_minor`,
  so a `1.1` file already reads under `1.3` and there is nothing to re-stamp.
  **Across a major bump** it is insufficient: the frame or a block body may
  change, so the header cannot simply be relabelled — the file is rewritten,
  which is a genuine transform with genuine provenance and belongs in the
  pass-through machinery, not in a header flag. What the option really implies is
  a *transcoding specification*, one rule per version pair, growing without
  bound. See [Version numbering](#file-header-0x01) for the position it would
  have contradicted.

- **A marker saying a record's payload is byte-identical to its span.** Since
  `spans` asserts [correspondence, not identity](#tlv-option-framing--id-registry),
  a consumer cannot tell from a decoded record whether following its span yields
  those same bytes or transformed ones — so a flag, or a `transform: none`
  option, would say. *Not adopted:* the question it answers is not the one a
  consumer acts on. What decides behaviour is whether the bytes are **fetchable
  at all**, and the [recoverability class](#undecoded-0x21) already answers that.
  A consumer that has the bytes in front of it has no use for a second copy, and
  one walking the chain to re-derive must re-run the stage regardless — the
  identity case just makes re-running trivial. The marker would also be
  per-record while the property is per-span-entry (a record may span one region it
  copied and another it rewrote), so an honest version is a parallel array,
  which is real weight for a hint. If it is ever wanted, a `content_type` scheme
  is the cheaper place than a new option.

- **Self-describing repeatability (a `repeatable` id-bit).** Reserve the high bit
  of a TLV `id` to mark an option as an ordered list, so a schema-less tool could
  render an unknown option as scalar-vs-array without consulting the registry.
  *Not adopted:* a reader already preserves every occurrence in order (see
  [TLV framing](#tlv-option-framing--id-registry)), so generic round-trip is
  lossless without it; the bit would only buy prettier rendering of unknown
  single-valued options, at the cost of a permanent framing bit, a per-occurrence
  consistency rule, and duplicating a fact the registry already holds. If ever
  wanted, the `id` high bit (dropping ids to a 15-bit space) is the place — *not*
  the `len` bit, which would halve the 64 KB option-value cap.

- **Promoting frequent options into block bodies.** A TLV costs a 4-byte header
  plus padding, so an option carried by nearly every block of its type is paying
  framing for nothing. *Considered and not adopted*, and the reasoning is worth
  keeping because the question recurs.

  There is no option to promote on correctness grounds: **every mandatory option
  in this document is *conditionally* mandatory** — `isn` when the handshake was
  seen, `decoder_id` when a decoder produced the record, `spans` when the file is a decode
  stage, `origin` when it is a pass-through, `sequenced_basis` on a hint-less
  `SEQUENCED` session, `reason_class` on a non-canonical reason. A body field is
  always present, so each would need a sentinel for "absent" — and absence here
  *carries meaning*: no `isn` means the capture began mid-stream and the origin is
  unknowable, no `decoder_id` means the record is a byte run, no `tcp_role` means
  unknown rather than responder. A sentinel would also collide with a legal value
  (`isn = 0` is a real ISN). The same block type additionally serves several file
  kinds — `origin` is required in a pass-through and forbidden on a
  capture-sourced stream — and a body cannot vary by file kind.

  The strongest *efficiency* candidates are therefore not the mandatory options
  but `seq_start` and `ack`, near-universal in a TCP file and costing 8 bytes each
  as a TLV against 4 inline. In the [worked example](#worked-example-a-minimal-capture-sourced-file)
  that is 16 of the record block's 64 bytes spent framing 8 bytes of ordering
  data; on a pure-ACK record it is 16 bytes of framing in 44. Still not adopted:
  inlining taxes every UDP, chat and decoded record with 8 unused bytes, needs a
  sentinel (`seq_start = 0` is legal), and saves around an eighth of a TCP record
  carrying payload.

  Timing matters if this is ever revisited. Moving an option into a body is a
  **body-layout change**, so it is free while the format is in `0.x` and costs a
  major bump afterwards.

- **Transport-neutral ordering hints.** Generic `seq_pos` / `cum_ack` options,
  letting the [merge](#merge-algorithm) derive causal edges for transports the
  format does not model. *Not adopted in `0.10`:* the merge needs **both** a
  monotonic per-sender position and a *cumulative* peer acknowledgement, and the
  sessions that motivated the request (multi-party UDP, chat) supply neither.
  RTP-style protocols supply only the first, which yields no cross-participant
  edges at all. Those cases are served instead by a producer asserting the order
  and recording `sequenced_basis` (see
  [Sequenced files](#sequenced-files-precomputed-order)). Worth revisiting for any
  transport that genuinely carries both — SCTP is the concrete one, and is
  tracked as an issue.

- **A machine-checkable "annotation" file kind.** A third derived-file kind
  asserting that a transform changed nothing but metadata, so a consumer could
  skip re-verifying the payloads. *Not adopted in `0.10`:* the layer-preserving
  pass-through already covers the case, and the `spans`-versus-`origin`
  distinction (see [Conformance](#conformance)) already tells mechanically
  whether a file's own stage built a record or re-emitted it. A third kind would
  add a permanent branch to a taxonomy whose value is that it has two, to buy a
  guarantee nobody has yet needed to check.

- **Requiring `sequenced_basis` on every `SEQUENCED` session.** The requirement
  binds [hint-less](#merge-algorithm) sessions only, and hint-less is
  all-or-nothing: one record carrying `seq_start` or `ack` among a hundred that
  carry none makes the session hinted, so no basis is required even though nearly
  all of its order still rests on timestamps. Requiring the basis unconditionally
  closes that gap and removes the hint-less dependency from the rule entirely.
  *Filed as a candidate in `0.12` pending evidence the gap mattered, and not
  adopted in `0.15` because none arrived* — three releases and one full external
  implementation later, including a review of `0.14` that returned a single
  finding, about something else.

  The cost was never in doubt: it puts an option on every sequenced TCP session,
  reinstates the `transport` vocabulary value that `0.12` deleted on the grounds
  that it could never legitimately appear, and adds an obligation to files that
  are conformant today. What it buys is narrower than it first looks. A consumer
  can already see which records carry no hints, and that the merge leaves those
  concurrent; what it cannot learn is what the producer relied on for them. The
  loss is **legibility, not correctness**, and the behaviour is pinned by the
  `partially-hinted-sequenced` vector, so it cannot drift unnoticed.

  One variant is worth not proposing a third time: splitting the rule, so that a
  reader checks the hint-less proxy while a producer is obliged to record the
  basis whenever the order does not follow entirely from causal hints. That
  obligation is **undecidable for a streaming producer** — the Session Descriptor
  is written before the session's records, which is the same asymmetry
  [Recording the basis](#sequenced-files-precomputed-order) resolves by keying on
  what the producer relies on. It is the defect `0.11` removed from the previous
  exemption, reproduced inside the fix for it. The full analysis is
  [#42](https://github.com/adamkjonsson/zipline/issues/42), and reopening it costs
  nothing.

### Planned, tracked elsewhere

Additions this document once listed here, now in the
[issue tracker](https://github.com/adamkjonsson/zipline/issues) so they carry
state and a milestone rather than drifting in prose:

| Extension | Issue |
|-----------|-------|
| Per-session integrity counts on Session End | [#43](https://github.com/adamkjonsson/zipline/issues/43) |
| Random-access index block | [#44](https://github.com/adamkjonsson/zipline/issues/44) |
| SCTP support | [#45](https://github.com/adamkjonsson/zipline/issues/45) |
