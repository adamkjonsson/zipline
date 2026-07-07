# Zipline Payload Format (design sketch)

> Status: **design proposal**, not yet implemented. This document sketches the
> **Zipline Payload Format** (`.zpf`), a file format for the *payload* output of
> a network sessionizer: the bytes that flow between endpoints once packets have
> been reassembled into sessions, plus the metadata needed to consume them. The
> format is tool-independent — any program can read or write it.

**Terminology.** The **producer** (a *sessionizer*) writes a `.zpf`; a
**consumer** (or *reader*) reads one. Two producer stages are named where the
distinction matters. The **reassembler** turns each direction's raw TCP segment
stream — out-of-order, retransmitted, overlapping — into one clean, in-order byte
stream; the **writer** emits that result as blocks. Reassembly always completes
*before* a record is written, so a `.zpf` holds the reassembled bytes, never raw
retransmits (see [Caveats](#caveats)). A **decoder** is a separate, later stage
that derives a decoded `.zpf` from a raw one (see
[Layers](#layers-raw-and-decoded-live-in-separate-files)).

## Goals

- Hold **more than one session** per file.
- Model a session as **N participants**, not two "sides". Both directions of a
  TCP connection is the `N = 2` case; a chat room is `N > 2`; a one-way UDP
  feed is `N = 1`.
- Keep **raw reassembled bytes** as the source of truth. A decoded view is a
  *separate file* derived from the raw one, not a layer inside it (see
  [Layers](#layers-raw-and-decoded-live-in-separate-files)).
- Be **append-only / streamable** so a writer can flush a finished session and
  forget it, keeping memory bounded on unbounded input.
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
record may be either a *raw byte run* (transport-truthful; boundaries fall where
reassembly produced them) or a *decoder-imposed unit* (boundaries set by an app
decoder). Which one a record is, is told by a single fact: **whether it carries a
`decoder_id`**. A raw byte run carries none; a decoder-imposed unit always does.
What that unit *means* (HTTP message, TLS record, …) comes from the referenced
decoder, not from any separate marker on the record.

Raw and decoded records rarely share boundaries, so decoding is a *file → file
transform* (`raw.zpf → decoded.zpf`), not a layer inside a record (see
[Layers](#layers-raw-and-decoded-live-in-separate-files)). Raw byte runs live only
in a raw file; a derived file holds decoder-imposed records, and regions a decoder
*could not* parse become **[Undecoded](#undecoded-0x21)** markers pointing back at
the predecessor's bytes (nothing is silently dropped).

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
| 0x01 | File Header             | magic, format version, byte order, time units, build provenance |
| 0x02 | Source Descriptor       | one input these bytes came from — a *capture* (file/interface) or another *`.zpf`* this file was derived from; has an id and a `kind` |
| 0x03 | Decoder Descriptor      | a decoder's id, name, version, params digest    |
| 0x10 | Session Descriptor      | session id, protocol, flow key, metadata        |
| 0x11 | Participant Descriptor  | participant id within a session, endpoint, TCP ISN |
| 0x20 | Record                  | a directed payload unit (see fields below)      |
| 0x21 | Undecoded               | a region the transform did not decode, referencing the predecessor's bytes (see Layers) |
| 0x30 | Name/Identity Resolution| optional: map participant ids → human labels    |
| 0x41 | End                     | optional; if present, the last block — marks the file complete |
| 0xFF | Custom                  | vendor/experimental, namespaced                 |

A single **Source Descriptor** type covers both a raw capture and a derived input
(`kind = capture` vs `kind = zpf-input`), so a record references its origin the
same way whether the file is raw or decoded. The Decoder Descriptor and Undecoded
blocks appear only in *derived* (decoded) files. See
[Layers](#layers-raw-and-decoded-live-in-separate-files).

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
reads, exactly as the writer built them. (A future
[random-access index](#possible-future-extensions) could gather descriptor
offsets without changing this streaming contract.)

### A first example

In the JSON-Lines face — one object per line, `type` discriminating the block,
payloads base64 — a small multi-party capture shows the shape. A 3-party chat
room is just additional descriptors, participants beyond two, and records with no
TCP hints (ordering falls back to timestamps, since a single chat server saw all
messages on one clock). Participants are declared as they appear: `dave` joins
mid-stream and is declared only at that point.

```jsonl
{"type":"file","format":"zipline-payload/1","time_units":"us"}
{"type":"source","source_id":1,"uri":"chat.pcap"}

{"type":"session","session_id":8,"proto":"irc","key":"#zipline@irc.example.net"}
{"type":"participant","session_id":8,"pid":0,"endpoint":"alice"}
{"type":"participant","session_id":8,"pid":1,"endpoint":"bob"}
{"type":"participant","session_id":8,"pid":2,"endpoint":"carol"}

{"type":"record","session_id":8,"sender_pid":0,"source_id":1,"ts":2000,
 "payload":"aGksIGFsbCE="}
{"type":"record","session_id":8,"sender_pid":2,"source_id":1,"ts":2100,
 "payload":"aGV5IGFsaWNl"}
{"type":"record","session_id":8,"sender_pid":1,"source_id":1,"ts":2150,
 "payload":"bW9ybmluZw=="}

{"type":"participant","session_id":8,"pid":3,"endpoint":"dave"}
{"type":"record","session_id":8,"sender_pid":3,"source_id":1,"ts":2300,
 "payload":"YW0gSSBsYXRlPw=="}
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

We store `seq_start`/`seq_end`/`ack` as the **absolute TCP sequence numbers from
the wire** — exactly the values in the packets. This is the key to ordering two
*separately-captured* directions: the absolute numbers are consistent across
captures *by construction* (they are the same bytes on the wire), so no shared
base or agreed origin is needed, and a mid-stream capture that never saw the SYN
works the same as one that did. An `ack` is natively an absolute number in the
peer's sequence space, so it compares directly against the peer's `seq_end`.

Because absolute TCP sequence numbers are 32-bit and **wrap**, all comparisons of
`seq_start`/`seq_end`/`ack` use **serial-number arithmetic** ([RFC 1982](https://www.rfc-editor.org/rfc/rfc1982)):
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
| `seq_end`    | `seq_start + payload_len` (mod 2³²; one past the last byte)     |
| `ack`        | highest absolute peer sequence number the sender had received  |

### Merge algorithm

```text
INPUT:  records of a session, grouped by sender participant
OUTPUT: one interleaved, causally-consistent sequence

1. Within each participant, order records by seq_start (a total order;
   the participant's own byte stream is monotonic). All seq comparisons
   here and below are serial-number (RFC 1982) comparisons, since the
   sequence space wraps.

2. Build edges between participants from acks:
     for each record R from participant P with ack value a:
         add edge  Q_record -> R   for every record Q_record from the
         *peer* whose seq_end <= a
     (R's sender had already received those peer bytes, so they precede R.)

3. Topologically sort the resulting DAG.

4. Where the topo order is free (concurrent records with no causal edge
   between them), break ties by timestamp; if clocks are known-skewed,
   fall back to round-robin / source order.
```

Step 2 is the payoff — it stitches the two separately-captured directions
together on causality rather than the skew-prone clock.

**Cost, and why a reader rarely pays it in full.** Stated naively, step 2 is
O(N·M) per session — every record weighed against every peer record — plus the
topological sort. Two things tame it, and a reader should rely on both:

- **Sorted inputs (always available).** Because a writer **SHOULD** store each
  participant's records in `seq_start` order (see
  [Identifiers & ordering](#identifiers--ordering)), the per-participant streams
  are already totally ordered. Step 1 is then a no-op and the merge becomes a
  **streaming k-way merge**: hold one frontier per participant and release a
  stream's next record once every peer record it acks (`seq_end ≤ ack`) has been
  emitted — a single-watermark, O(1)-amortised check. Total work is ~O(N) and
  memory is bounded by the in-flight window, not the session. No reader needs the
  quadratic form.
- **A sequenced session (no merge at all).** A producer MAY commit the resolved
  order to disk and mark the session *sequenced* (see
  [Sequenced files](#sequenced-files-precomputed-order)); a reader then consumes
  its records in stored order and skips this algorithm entirely.

The merge is **optional, consumer-side** work. Reassembly *within* a direction is
the producer's job — a reader never does it — and a reader that only wants one
participant's stream (already `seq_start`-ordered) need not merge at all. Only a
consumer that wants the single cross-participant timeline of a *non-sequenced*
file runs the algorithm above.

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
{"type":"file","format":"zipline-payload/1","time_units":"us"}
{"type":"source","source_id":1,"uri":"sideA.pcap"}
{"type":"source","source_id":2,"uri":"sideB.pcap"}

{"type":"session","session_id":7,"proto":"tcp",
 "key":"10.0.0.1:51000 <-> 93.184.216.34:80"}
{"type":"participant","session_id":7,"pid":0,"endpoint":"10.0.0.1:51000","isn":1000}
{"type":"participant","session_id":7,"pid":1,"endpoint":"93.184.216.34:80","isn":5000}

{"type":"record","session_id":7,"sender_pid":0,"source_id":1,"ts":1000,
 "seq_start":1001,"seq_end":1019,"ack":5001,
 "payload":"R0VUIC8gSFRUUC8xLjENCg0K"}
{"type":"record","session_id":7,"sender_pid":1,"source_id":2,"ts":995,
 "seq_start":5001,"seq_end":5101,"ack":1019,
 "payload":"SFRUUC8xLjEgMjAwIE9LDQouLi4="}
```

These are raw records (no `decoder_id`). The sequence numbers are absolute (client
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
hint-less one only under a common clock — see below). A file may therefore mix
sequenced and unsequenced sessions, and a reader decides per session — records of
different sessions interleave freely, and a reader recovers one session's order by
filtering. In the JSONL projection the flag is a boolean `"sequenced":true` on the
`session` line.

A reader consumes a sequenced session's records in stored order and does **no
ordering work at all** for it — the [merge algorithm](#merge-algorithm) lives
only in the producer. The `seq_start`/`seq_end`/`ack` hints stay present, so a
reader MAY still verify the order, or recover the true partial order (which
records were genuinely concurrent); the flag only asserts that *stored order is
one correct answer*, not that it is the only one.

Who sets the flag depends on the capture:

- A **single tap that sees both directions** emits a sequenced session directly,
  holding only a bounded reorder window (≈ the in-flight data) before releasing
  each record — this keeps the flush-and-forget, bounded-memory contract intact.
- **Two separately-captured directions** cannot be sequenced by either
  per-direction writer alone (neither sees the peer's acks). They are combined by
  a **merge transform** — `sideA.zpf + sideB.zpf → merged.zpf` — that reuses the
  existing derived-file machinery (a [Source](#source-descriptor-which-input) of
  `kind = zpf-input`, its `digest`, and provenance, exactly as a decoder does):
  it runs the streaming merge once and writes sequenced sessions. The expensive
  logic thus exists in exactly one tool, never in every reader.

Sequencing is **optional** and orthogonal to raw-vs-decoded. A reader MUST still
accept unsequenced sessions (and run the merge itself if it wants their
interleaved view). Determinism is a free side benefit: because the producer fixes
the tie-break for concurrent records, every reader of a sequenced session observes
the *same* order — which independent per-reader merges (step 4's
clock/round-robin tie-break) do not guarantee.

**What a sequenced session rests on.** A session's causal order comes from
whatever ordering hints its records carry. A **TCP** session has `seq`/`ack`, so
its sequenced order is clock-independent — sound regardless of capture skew. A
session **without** such hints (a chat room, a one-way UDP feed) has no causal
edges, so its order is purely the timestamp tie-break (non-decreasing
`timestamp`, ties resolved by the producer's fixed rule, e.g. source/pid order).
That is a *sound* order only when all the session's records share **one
trustworthy clock** — the normal case when a single observer (one chat server,
one receiver) saw the whole session. A producer therefore **MUST NOT** mark a
hint-less session `SEQUENCED` unless its records share a single trustworthy clock.

**File-level `SINGLE_CLOCK`.** That clock precondition has a file-wide form, the
`SINGLE_CLOCK` flag on the [File Header](#file-header-0x01): it asserts that
*every record in the file was stamped against one trustworthy clock*, so
timestamps are globally comparable across sessions and sources (no inter-source
skew). Its value is forward-looking. A raw writer often cannot tell
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

## Layers: raw and decoded live in separate files

Raw and decoded payloads describe the same bytes at different granularities, and
they **rarely share boundaries**. A raw record is a byte run keyed by transport
offsets; a decoded record is a protocol message keyed by application semantics.
A single decoded message can span *two and a half* raw records — starting and
ending mid-record. Forcing both into one record means either duplicating bytes
or imposing an alignment that fits neither side.

So decoding is a **file → file transform**, not an in-record layer:

```
raw.zpf  ──[ http/1.1 decoder ]──▶  decoded.zpf
```

The output is one coherent boundary scheme (protocol messages); the input is
another (byte runs). A decoded file stands alone for its **decoded** content —
reading the decoded records never requires `raw.zpf`. The exception is regions a
decoder could not parse: a derived file does not copy their bytes, it records an
**[Undecoded](#undecoded-0x21)** marker referencing them, so recovering those raw
bytes does mean consulting the predecessor (ultimately the raw file). The link
between files is otherwise **provenance**, used for verification and
re-derivation, not for reading.

This generalizes: `raw → tls-records → http → …` is the same mechanism applied
N times. Nothing special-cases "raw"; each stage just derives from the previous
file's spans.

### Referencing the source by stream offset

The crux of the "2.5 records" problem: a decoded record points at **byte ranges
in the reassembled stream** by a **logical 0-based stream offset** — *not* at raw
record ids, and *not* at the absolute TCP sequence numbers used for ordering.
**Byte 0 is the stream's first application byte.** When the TCP handshake was
observed (the participant carries an `isn`), that byte is absolute seq `isn + 1`,
so any bytes lost *between the handshake and the first captured byte* occupy the
leading offsets and stay representable (see below); with no `isn` — UDP, chat, or
a mid-stream TCP capture whose true origin is unknowable — byte 0 is instead the
first reassembled byte. Apart from fixing that origin the offset is deliberately
TCP-independent, so the same mechanism works for a decoded UDP or chat stream that
has no sequence numbers. It makes the raw side's arbitrary chunking irrelevant; a
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
survive the raw file being re-chunked or re-written.

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

### Source Descriptor (which input)

A derived file declares each input `.zpf` as a Source of `kind = zpf-input`,
carrying a `source_id` (referenced by record `spans`), the `uri` where the input
lives, and a `digest` (its content hash). The same block type describes a raw
**capture** source (`kind = capture`, with a
`link_type` instead of pointing at a `.zpf`); a raw file declares its captures
this way, a derived file declares its `.zpf` inputs. One `source_id` space, one
referencing mechanism.

The build provenance of the *transform itself* — `produced_by` (tool + version)
and `produced_at` (wall-clock build time of the artifact, not packet time) — is
not per-input; it lives once on the **File Header**, since one transform can read
several inputs.

The `digest` is the real dependency edge: a consumer can confirm the decoded
file still matches its source, and a build-style tool can re-derive when the raw
file changes. It is `source → object` with a Makefile dependency, not a copy.

### Decoder Descriptor (which decoding)

The decoder is a first-class, referenceable entity: a `decoder_id` (referenced
per-record), a `name` (e.g. `http/1.1`), a `version`, and a `params_digest` (hash
of the decoder config, so the decode is reproducible).

Every decoded record carries an **explicit** `decoder_id` — its presence is what
*makes* the record decoded, and there is no implicit "primary" default. The
reference is per-record, not per-file, because one decoded file legitimately mixes
decoders: HTTP on one session, TLS-then-HTTP on another. A record's `decoder_id`
is exactly what gives the record its meaning. **Reproducibility contract:** same
input `digest` + same decoder `version`/`params_digest` ⇒ identical output.

### Typing a decoded record

A decoder *frames* — it assembles raw bytes into one logical unit and marks its
edges — but the assembled bytes are still just bytes. What they **are** (a PNG, a
UTF-8 string, a 64-bit integer) is a separate, optional label the decoder may
attach: a `content_type` on the record. Absent, the payload is opaque and a
consumer falls back to the decoder `name`; the bytes always stay the source of
truth — the label never replaces them.

`content_type` is a `<scheme>:<value>` string with three schemes:

- `mime:<media-type>` — an IANA media type: `mime:image/png`,
  `mime:application/json`, `mime:text/plain;charset=utf-8`.
- `prim:<primitive>` — a fixed-width integer or raw byte string from a small,
  closed spec-defined vocabulary (`prim:u64-be`, `prim:i32-le`, `prim:bytes`;
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

### Coverage honesty: Undecoded blocks

A decoder can fail partway, or hit a TCP gap (where it can only decode the
gap-free runs on either side). The decoded file states what it did *not* cover
with an explicit **[Undecoded block](#undecoded-0x21)** rather than silently
dropping bytes. An Undecoded block names a `[off_start, off_end)` range of a
predecessor stream and a `reason`; it carries **no payload**, only a reference, so
a consumer that wants the bytes follows the span back toward the raw file. This
gives the **coverage guarantee**: in a derived file, every region of an input
participant stream is either covered by a decoded record's `spans` *or* marked
Undecoded — never silently dropped, never both. A consumer can thus distinguish
"a message we could not parse" (`reason` = `undecodable`, bytes recoverable
upstream) from "no data here" (`reason` = `tcp-gap`/`truncated`, the offset range
is a hole with no bytes anywhere), and a re-derivation can target just the
undecoded ranges. A plain **gap** is simply the no-data case of an Undecoded
block. (The `undecoded` line in the example below shows one.)

### A decoded file, end to end

Putting the pieces together — a decoded file derived from the raw TCP capture in
the [skewed two-file worked example](#worked-example-a-skewed-two-file-capture).
The input `.zpf` is a
`source` of `kind:"zpf-input"`, each record cites the `spans` it was built from
(logical stream offsets, not transport offsets) and a `content_type` saying what
its bytes are (here the http decoder's own `dec:` types), and the undecodable
tail is stated as an explicit `undecoded` block (referencing the input span whose
bytes it could not parse, not copying them):

```jsonl
{"type":"file","format":"zipline-payload/1","time_units":"us",
 "produced_by":"zpf-decode 0.4","produced_at":1719500000}
{"type":"source","source_id":1,"kind":"zpf-input","uri":"raw.zpf",
 "digest":"sha256:9f2c…"}
{"type":"decoder","decoder_id":1,"name":"http/1.1","version":"0.4",
 "params_digest":"sha256:00ab…"}

{"type":"session","session_id":7,"proto":"http"}
{"type":"participant","session_id":7,"pid":0,"endpoint":"10.0.0.1:51000"}
{"type":"participant","session_id":7,"pid":1,"endpoint":"93.184.216.34:80"}

{"type":"record","session_id":7,"sender_pid":0,"ts":1000,"decoder_id":1,
 "spans":[{"source_id":1,"session_id":7,"pid":0,"off_start":0,"off_end":18}],
 "content_type":"dec:request","payload":"…decoded request…"}
{"type":"record","session_id":7,"sender_pid":1,"ts":995,"decoder_id":1,
 "spans":[{"source_id":1,"session_id":7,"pid":1,"off_start":0,"off_end":100}],
 "content_type":"dec:response","payload":"…decoded response…"}
{"type":"undecoded","session_id":7,"pid":1,"source_id":1,
 "off_start":100,"off_end":139,"reason":"undecodable","decoder_id":1}
```

## Binary encoding (normative reference)

This section is **normative**: a conformant reader/writer pair must agree on
everything here. Keywords **MUST**, **SHOULD**, **MAY** are used in the usual
sense. The narrative sections above are explanatory; where they disagree with
this one, this one wins.

### Primitives

- **Integers** are fixed-width two's-complement. Byte order is fixed for the
  whole file by the File Header (below); every multi-byte integer in the file
  uses it. There is no per-block byte order.
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
| `bom`           | u32  | byte-order magic `0x5A495046` (`"ZIPF"`), written in the file's order |
| `version_major` | u16  | `1` for this document                                        |
| `version_minor` | u16  | `0`                                                          |
| `tick_hz`       | u64  | time units per second (e.g. `1000000` = µs, `1000000000` = ns); MUST be non-zero |

**Endianness bootstrap.** Byte order is not yet known when the reader reaches
the file, so it MUST be fixed *before* any multi-byte integer is interpreted —
including the header's own `type`/`reserved`/`length`. The reader reads the four
bytes of `bom` at their **fixed file offset 8** (the frame is a constant 8 bytes)
both ways; the interpretation that yields `0x5A495046` fixes the byte order for
the whole file, and only then are all integers (the header frame included) read
back in that order. Tools may sniff a ZPF file by the BOM at offset 8 —
`5A 49 50 46` (`"ZIPF"`, big-endian file) or `46 50 49 5A` (little-endian file).
Suggested file extension `.zpf`. A **minor** version bump only adds
blocks/options (old readers keep working); a **major** bump may break frame/body
layout.

**Reconstructing wall time.** A record's `timestamp` is in `tick_hz` ticks from
the origin `time_epoch` (itself ticks since the Unix epoch, default 0). The
absolute time is `unix_seconds = (time_epoch + timestamp) / tick_hz` (integer
division truncates; sub-tick precision is intentionally not representable). Both
operands are signed, so times before the origin are representable.

Header options: `time_epoch` (i64, `tick_hz` ticks; default Unix epoch
1970-01-01T00:00:00Z), `creator` (string), `produced_by` (string, derived files —
tool + version that produced this file), `produced_at` (i64, derived files —
wall-clock build time in Unix seconds), `flags` (u16, file-level flags; see
below), `comment`.

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

**Source Descriptor (`0x02`)**

One block type for both a raw **capture** and a derived **`.zpf` input**,
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

**Decoder Descriptor (`0x03`)** — derived files only

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `decoder_id` | u16  | id referenced per-record    |
| `_reserved`  | u16  | 0                           |

Options: `name`, `version`, `params_digest`, `comment`.

**Session Descriptor (`0x10`)**

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `session_id` | u64  | id referenced by participants and records |

Options: `proto` (string, lowercase, e.g. `tcp`/`udp`/`irc`/`http`/`tls`),
`flow_key` (string), `flags` (u16, session-level flags; see below), `comment`.

**Session flags.** The `flags` option is a u16 bitfield; when absent, every bit
is 0. Bit `0x0001` (**SEQUENCED**) asserts this session is a
[sequenced session](#sequenced-files-precomputed-order) — its Record blocks
appear in the file in a valid causal order, so a reader MAY consume them in stored
order without running the [merge](#merge-algorithm). All other bits are reserved,
MUST be written 0, and MUST be ignored on read.

**Participant Descriptor (`0x11`)**

| Field            | Type | Notes                                   |
|------------------|------|-----------------------------------------|
| `session_id`     | u64  | session this participant belongs to     |
| `participant_id` | u16  | id within that session (the `pid`)      |
| `_reserved`      | u16  | 0                                       |

Options: `endpoint` (string, **may repeat** — see below), `isn` (u32, the SYN's
TCP sequence number — see below), `tcp_role` (u8, see enums), `identity`
(string), `comment`.

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

### Record (`0x20`)

Body (fixed part):

| Field         | Type  | Notes                                              |
|---------------|-------|----------------------------------------------------|
| `session_id`  | u64   | refers to a Session Descriptor                     |
| `sender_pid`  | u16   | sender participant; recipients are implicit (all other participants — see [Conceptual model](#conceptual-model)) |
| `source_id`   | u16   | refers to a Source Descriptor — a `capture` for a raw record, a `zpf-input` for a decoded one |
| `timestamp`   | i64   | packet time, in `tick_hz` ticks (see timestamp rule)|
| `_reserved`   | u16   | 0                                                  |
| `flags`       | u16   | see bit table                                      |
| `payload_len` | u32   | length of `payload`                                |
| `payload`     | bytes | `payload_len` raw bytes (source of truth)          |

`payload` is zero-padded to a multiple of 4 bytes; options then follow (TCP
hints, provenance — see registry). `payload_len` gives the unpadded length and
MAY be 0 (e.g. a pure-ACK record carrying only an `ack` hint). **A record is
*decoded* iff it carries a `decoder_id`** — that presence is the sole raw/decoded
discriminator: a decoded record MUST carry a `decoder_id`, a raw record MUST NOT.
A decoded record MAY also carry a `content_type` labelling what its `payload` is
(see [Typing a decoded record](#typing-a-decoded-record)).
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
  complete. That source is raw bytes in a one-step decode, or itself a decoded
  record in a chained one (`raw → tls-records → http → …`), so the stamp
  propagates down the chain and is always ultimately the packet time of the
  contributing capture.

The first-packet time is recoverable from capture-source `spans` provenance; a
writer that wants it without full provenance MAY add an optional `ts_first` TLV.
The canonical `timestamp` is always the completion (last-packet) time.

`timestamp` is **signed** (i64, as are `ts_first`, `time_epoch`, and
`produced_at`): the configurable `time_epoch` origin admits times *before* it
(negative ticks), and inter-record deltas — central to the skew-tolerant
ordering — are inherently signed. The range given up versus u64 is immaterial at
the resolutions `tick_hz` is meant for.

### Undecoded (`0x21`)

Derived files only. Marks a region of a **predecessor** input stream that this
transform did **not** turn into a decoded record — because the decoder could not
parse it, or because the bytes are missing/truncated. It is a *reference*, not a
payload: it carries no bytes, only the input span where they do (or would) live.

| Field            | Type | Notes                                              |
|------------------|------|----------------------------------------------------|
| `session_id`     | u64  | session the region belongs to (in *this* file)     |
| `participant_id` | u16  | participant (stream) the region is in              |
| `source_id`      | u16  | the input Source (`kind = zpf-input`) whose stream `off_start`/`off_end` index — resolves the G1 ambiguity for multi-input files |
| `off_start`      | u64  | logical 0-based stream offset, first byte = 0      |
| `off_end`        | u64  | one past the last byte (half-open `[start, end)`)  |

Offsets are logical 0-based stream offsets in the `source_id` input, the same
convention used by `spans` (*not* absolute sequence numbers), and follow the
hole-inclusive contiguity rule (see
[Referencing the source by stream offset](#referencing-the-source-by-stream-offset)).
Options: `reason` (string, e.g. `undecodable` / `tcp-gap` / `truncated`),
`decoder_id` (u16, which decoder declined the region).

`reason` signals whether the bytes are recoverable: `undecodable` means the bytes
exist at that span in `source_id` (the decoder simply could not parse them) and a
consumer MAY follow the reference to fetch them; `tcp-gap` / `truncated` mean the
range is a **hole** with no bytes anywhere upstream (a plain *gap*). Either way
the bytes are not in this file. To recover `undecodable` bytes a consumer walks
the provenance chain one level at a time — if the referenced span is itself
Undecoded in `source_id`, it recurses — until it reaches the capture-sourced raw
file that holds the actual bytes; a missing intermediate file stops recovery
there. An Undecoded block has no `timestamp`; order it among a participant's
records by its `off_start`.

A **raw** file expresses its own TCP gaps *implicitly*, as a discontinuity
between consecutive records' sequence numbers — it has no Undecoded blocks (a raw
file ran no decoder). A decoder writer that needs those raw gaps made explicit
reconstructs them from the sequence discontinuity via its software support, and
emits Undecoded blocks in the derived file.

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
| `end_magic` | u32  | `0x5A454E44` (`"ZEND"`), in the file's byte order  |

Options: `comment`. Bytes after this block are invalid — a `.zpf` is never
concatenated (see [Conformance](#conformance)).

Completeness is detected by **forward reading alone**: reaching a valid End block
as the final block means complete; reaching end-of-stream — or a short, partial
block — without one means the file is still growing, truncated, or the writer
crashed (see [Truncation and completeness](#truncation-and-completeness)). No
seek-to-end is needed; the End block
is found in the normal block walk. In the JSONL projection it is a final
`{"type":"end"}` line.

### TLV option framing & id registry

`id: u16, len: u16, value` (then pad to 4 bytes). Options run until the block
`length` is consumed; there is no end-of-options sentinel. `id 0x0001` is
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
  significant. **The only repeatable id in v1.0 is `endpoint`** (any future
  repeatable id MUST be added to this closed list).
- A **single-valued** id (every other id) SHOULD appear at most once; a consumer
  that interprets it uses the **first** occurrence. If it nonetheless repeats, a
  faithful reader still preserves the extra occurrences for round-trip.
- `spans` is **single-valued**: it appears at most once, and its multiplicity
  lives *inside* the packed value (a list of entries), not across occurrences.

| Id       | Name             | Value type | Used in                  | Meaning                                                        |
|----------|------------------|------------|--------------------------|----------------------------------------------------------------|
| `0x0001` | comment          | string     | any                      | free-text human note attached to the block                     |
| `0x0010` | time_epoch       | i64        | File Header              | origin for record timestamps (Unix-epoch ticks); default 0     |
| `0x0011` | creator          | string     | File Header              | tool + version that wrote the file                             |
| `0x0012` | produced_by      | string     | File Header              | tool + version that ran the transform (derived files)          |
| `0x0013` | produced_at      | i64        | File Header              | wall-clock build time of this artifact (Unix seconds)          |
| `0x0014` | flags            | u16        | File Header              | file-level flags bitfield; bit `0x0001` = SINGLE_CLOCK (see [Sequenced files](#sequenced-files-precomputed-order)) |
| `0x0020` | uri              | string     | Source                   | where the referenced capture/input file lives                  |
| `0x0021` | digest           | string     | Source                   | content hash of the referenced file — the dependency edge      |
| `0x0022` | link_type        | u16        | Source (capture)         | link-layer type of the capture (e.g. a pcap LINKTYPE)          |
| `0x0041` | name             | string     | Decoder                  | decoder identifier, e.g. `http/1.1`                            |
| `0x0042` | version          | string     | Decoder                  | decoder version                                                |
| `0x0043` | params_digest    | string     | Decoder                  | hash of the decoder config, so the decode is reproducible      |
| `0x0050` | proto            | string     | Session                  | session protocol, lowercase (`tcp`/`udp`/`irc`/`http`/`tls`)   |
| `0x0051` | flow_key         | string     | Session                  | human-readable flow key, e.g. `a:port <-> b:port`              |
| `0x0052` | flags            | u16        | Session                  | session-level flags bitfield; bit `0x0001` = SEQUENCED (see [Sequenced files](#sequenced-files-precomputed-order)) |
| `0x0060` | endpoint         | string     | Participant              | participant address, e.g. `ip:port` or a nick; **repeatable**, outermost tunnel layer first → innermost last |
| `0x0061` | isn              | u32        | Participant              | the SYN's sequence number; MUST be present when the handshake was seen. Fixes the stream's absolute origin (first byte = `isn+1`); ordering does not use it |
| `0x0062` | identity         | string     | Participant              | stable identity distinct from a transient endpoint             |
| `0x0063` | tcp_role         | u8         | Participant (TCP)        | active/passive opener when the handshake was seen (see enums)  |
| `0x0070` | seq_start        | u32        | Record (TCP)             | absolute sequence number of the first payload byte             |
| `0x0071` | seq_end          | u32        | Record (TCP)             | absolute sequence number one past the last payload byte (mod 2³²) |
| `0x0072` | ack              | u32        | Record (TCP)             | highest absolute peer sequence number the sender had received  |
| `0x0073` | ts_first         | i64        | Record                   | optional packet time of the *first* contributing packet        |
| `0x0080` | spans            | span-list  | Record                   | source ranges these bytes were built from (see below)          |
| `0x0090` | decoder_id       | u16        | Record, Undecoded (decoded) | which Decoder Descriptor produced/declined this record/region |
| `0x0091` | content_type     | string     | Record (decoded)         | what the payload *is*: `mime:`/`prim:`/`dec:` (see [Typing a decoded record](#typing-a-decoded-record)) |
| `0x00A0` | reason           | string     | Undecoded                | why the region is undecoded (`undecodable`/`tcp-gap`/`truncated`/…) |
| `0x00B0` | label            | string     | Name/Identity Resolution | the human-readable name being assigned                         |
| `0x00B1` | kind             | string     | Name/Identity Resolution | source/kind of the label (`nick`/`dns`/`tls-sni`)              |

A **span-list** value is `count` packed entries, each 28 bytes:
`source_id: u16, pid: u16, session_id: u64, off_start: u64, off_end: u64`
(`count = len / 28`). The two u16s lead so the u64 fields stay 4-byte aligned
within the packed entry — this packed order (`source_id, pid, session_id, …`)
differs from the logical/JSON field order (`source_id, session_id, pid, …`) *only*
for that alignment; all three faces name the same five fields, and since JSON is
keyed by name the reorder is immaterial there. The **interpretation of the offsets is keyed by the
referenced source's `kind`**: for a `zpf-input` source, `off_start`/`off_end` are
**logical 0-based stream offsets** within `(session_id, pid)` of that input; for
a `capture` source, they are **byte offsets into the capture file** and
`session_id`/`pid` are unused (write 0). One option id (`spans`) serves both raw
capture-provenance and decoded derivation-provenance.

**A span's `session_id`/`pid` are in the referenced *source's* id namespace, never
the current file's.** They name a session/participant *inside* `source_id` (the
input being cited), which is a different id space from the file that carries the
span — even when the numbers happen to coincide. In the [end-to-end decoded
example](#a-decoded-file-end-to-end) the decoded file's own `session_id 7` and the
span's `session_id 7` are the *same number by coincidence*; resolving the span
means looking up session 7 in `raw.zpf`, not in the decoded file. (A writer drawing
`session_id`s from a global sequence — see
[Identifiers & ordering](#identifiers--ordering) — makes them literally identical,
which is convenient but does not change that the span is read in the source's
space.)

### Enums

`kind` (Source body, u8): `0` = capture (a pcap/interface), `1` = zpf-input
(another `.zpf` this file was derived from).

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
| `0x0008` | `syn`        | TCP SYN (handshake record)                               |
| `0x0010` | `urg`        | TCP URG seen                                             |
| `0x0040` | `retransmit` | retransmission/overlap was resolved inside this record   |
| `0x0080` | `datagram`   | datagram boundary (UDP: record is exactly one datagram)  |
| `0xFF20` | —            | reserved, MUST be 0                                      |

`content_type` `prim:` vocabulary (Record option, string): the legal `prim:`
tokens are **exactly** the fixed-width integers below plus `prim:bytes` (an
uninterpreted byte string). `u`/`i` selects unsigned / signed two's-complement;
the `-be`/`-le` suffix is byte order, omitted for 8-bit (a single byte has none).
No other `prim:` token is legal — `mime:` and `dec:` carry everything else.

| Width   | Unsigned                     | Signed                       |
|---------|------------------------------|------------------------------|
| 8-bit   | `prim:u8`                    | `prim:i8`                    |
| 16-bit  | `prim:u16-be`, `prim:u16-le` | `prim:i16-be`, `prim:i16-le` |
| 32-bit  | `prim:u32-be`, `prim:u32-le` | `prim:i32-be`, `prim:i32-le` |
| 64-bit  | `prim:u64-be`, `prim:u64-le` | `prim:i64-be`, `prim:i64-le` |

Plus `prim:bytes`.

**`prim:` width binds `payload_len`.** For a fixed-width `prim:` token, the
record's `payload_len` (the *unpadded* length, not the 4-byte-padded frame size)
MUST equal the token's width: `1` for `prim:u8`/`prim:i8`, `2` for `prim:u16-*`,
`4` for `prim:u32-*`, `8` for `prim:u64-*`. `prim:bytes` places no length
constraint (any `payload_len`, including 0). A writer MUST NOT emit a fixed-width
`prim:` label whose width disagrees with `payload_len`; a reader that finds a
mismatch MUST treat the `content_type` as unknown (opaque payload, falling back to
the decoder `name`), exactly as for an unknown scheme, and MUST NOT pad, truncate,
or reinterpret — the bytes remain the source of truth.

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
  ordering **SHOULD** that keeps reading cheap: within a given
  `(session_id, participant_id)`, a writer **SHOULD** emit that participant's
  records in `seq_start` order (logical stream order for non-TCP streams that
  have no sequence numbers) — the order in which it already produced them. A
  reader MAY still meet out-of-order records and fall back to sorting, but when
  the SHOULD holds the cross-participant [merge](#merge-algorithm) collapses from
  an all-pairs comparison into a **streaming k-way merge** over already-sorted
  per-participant streams (see [merge cost](#merge-algorithm)). This costs the
  writer nothing — each participant's byte stream is monotonic by construction —
  and bounds a reader's working set to the in-flight window rather than the whole
  session. *Across* participants, records MAY be interleaved in any order (capture
  order is the natural choice and keeps the timestamp tie-breaker meaningful);
  only the *per-participant* subsequence is constrained.

### Conformance

Every file MUST start with exactly one File Header as its first block, and MUST
declare each Source, Session, and Participant before any block references it. A
file MAY end with an [End block](#end-of-file-0x41); if present it MUST be the
last block, and its presence marks the file complete. A file MAY omit it — a
live/streaming or crashed writer does — and readers MUST still accept such a
file, treating it as not-known-complete.

A **raw** file holds raw records; a **derived** (decoded) file holds decoded
records plus Undecoded markers, and contains **no** raw records — regions a
decoder could not parse are recorded as [Undecoded](#undecoded-0x21) references,
not copied back as bytes. **Whether a record is raw or decoded is told solely by
whether it carries a `decoder_id`.** One derived file MAY still mix *decoders*
per-record (HTTP on one session, TLS-then-HTTP on another); the raw-vs-decoded
split, however, falls on the file's level in the `raw → … → decoded` chain.

- A **raw** record carries no `decoder_id`, and its `source_id`/`spans` reference
  a `capture` Source; it appears only in a raw file. TCP raw records SHOULD carry
  `seq_start`/`seq_end` (and `ack` where known); TCP participants **MUST** carry
  `isn` when the handshake was observed (it fixes the stream's absolute origin —
  see [Referencing the source by stream offset](#referencing-the-source-by-stream-offset))
  and omit it otherwise; UDP records SHOULD set the datagram-boundary flag.
- A **decoded** record MUST carry a `decoder_id`, and its `source_id`/`spans`
  reference a `zpf-input` Source. A file containing any decoded record MUST declare
  every Decoder it references and every `zpf-input` Source, set the File Header
  `produced_by`/`produced_at`, and account for every input region it did not decode
  with an **Undecoded** block rather than dropping it: within each input
  participant stream, every offset MUST be covered either by some decoded record's
  `spans` or by an Undecoded block (the coverage guarantee). Decoder, Undecoded,
  and `zpf-input` Sources appear only in files that carry decoded records.

**Ordering and sequencing.** A writer **SHOULD** store each participant's records
in `seq_start` (logical stream) order; this bounds an unsequenced reader's merge
to a streaming pass (see [Identifiers & ordering](#identifiers--ordering)).
Separately, a session MAY set the Session Descriptor `flags` **SEQUENCED** bit; if
it does, the producer MUST store that session's records so their Record-block file
order is a valid causal linearization (concurrent records ordered by the
producer's tie-break), and a reader MAY then consume them in stored order without
running the [merge](#merge-algorithm). A reader MUST NOT assume a session is
sequenced unless its bit is set, and MUST still accept sessions that omit it. For
a session with no causal hints (no TCP `seq`/`ack` — e.g. chat or one-way UDP),
the sequenced order is the timestamp order, so the producer MUST NOT set SEQUENCED
unless every record in that session shares a single trustworthy clock. The File
Header `flags` **SINGLE_CLOCK** bit is the file-wide assertion of that property
(timestamps globally comparable, no inter-source skew); when set it satisfies the
clock requirement for every hint-less session, and a downstream tool may rely on
it to sequence streams it regroups (see
[Sequenced files](#sequenced-files-precomputed-order)).

Readers MUST skip unknown block types (via frame `length`) and unknown option
ids (via `len`), and MUST treat reserved fields/bits as ignored-on-read.

**Concatenation is not supported.** A `.zpf` file has exactly one File Header,
at its very start; bytes after the last complete block are not a new section.
Concatenating two `.zpf` files does **not** yield a valid `.zpf`. To split a
streaming intercept across several files, the producer is responsible for making
their order recoverable out-of-band (a naming convention, a manifest, etc.).

### Truncation and completeness

The format is forward-only and streamable. A reader that finds fewer than
`length` bytes remaining for a block MUST treat the file as **truncated at that
block** (a writer crash mid-flush) and discard the partial tail; all complete
prior blocks remain valid.

Completeness is signalled positively by the optional [End block](#end-of-file-0x41):
a file ending in a valid End block was finalized cleanly, whereas one that reaches
end-of-stream without it is either still growing, truncated, or the product of a
crashed writer. The End block is the only thing that distinguishes "intentionally
finished" from "stops here"; absent it, the two are indistinguishable (which is
fine for a live stream that is legitimately still open).

### JSONL ↔ binary field mapping

The JSON-Lines projection is **semantically** lossless for every field. It is
defined by **one rule plus a short list of exceptions**, so it stays complete as
options are added rather than depending on an enumerated key list.

**The rule.** For any block, its JSON keys are the **canonical names** of its
binary body fields and its TLV options — the field names in the block's body
table and the `Name` column of the
[option registry](#tlv-option-framing--id-registry) — used verbatim as JSON keys,
*except* for the brevity aliases below. A field or option a converter does not
recognise (a future registry id, a `Custom` block's contents) round-trips through
a generic `options` array (below); anything that **is** registered MUST use its
canonical key and MUST NOT be placed in `options`. The block is selected by its
`type` string.

**`type` string ↔ block.**

| `type`        | Block                             |
|---------------|-----------------------------------|
| `file`        | File Header (`0x01`)              |
| `source`      | Source Descriptor (`0x02`)        |
| `decoder`     | Decoder Descriptor (`0x03`)       |
| `session`     | Session Descriptor (`0x10`)       |
| `participant` | Participant Descriptor (`0x11`)   |
| `record`      | Record (`0x20`)                   |
| `undecoded`   | Undecoded (`0x21`)                |
| `name`        | Name/Identity Resolution (`0x30`) |
| `end`         | End (`0x41`)                      |
| `custom`      | Custom (`0xFF`)                   |

**Brevity aliases** — the *only* keys whose JSON name differs from the binary
name:

| JSONL key    | Binary field / option                                            |
|--------------|------------------------------------------------------------------|
| `format`     | `version_major`/`version_minor` as `"zipline-payload/<major>[.<minor>]"`; an omitted minor is `0` (so `"zipline-payload/1"` ⇒ major 1, minor 0) |
| `time_units` | `tick_hz` (File Header)                                          |
| `ts`         | `timestamp` (Record)                                            |
| `pid`        | `participant_id` (block body, and each `spans` entry)            |
| `key`        | `flow_key` (Session)                                            |

(`proto` is **not** an alias — its JSON key equals its option name.)

**Value encoding.**

- **Integers** → JSON number, with one exception: a **64-bit** field (`session_id`,
  `ts`/`timestamp`, `time_units`/`tick_hz`, `time_epoch`, `produced_at`,
  `ts_first`, `off_start`, `off_end`) MAY be written as a JSON number **or** a
  decimal string, and a writer SHOULD use the string form when the value exceeds
  2⁵³ (beyond JSON's exact-integer range). A reader MUST accept both. 32-bit and
  narrower fields are always plain numbers.
- **Strings** → JSON string; a `digest` keeps its `"<alg>:<hex>"` form.
- **`payload`** and any raw-byte value → **standard base64** (RFC 4648 §4, with
  `=` padding).
- **Enums** render as their defined **string label**: `kind` as
  `"capture"`/`"zpf-input"`, `tcp_role` as `"initiator"`/`"responder"` (omitted
  when unknown).
- **Flag bitfields** render by name, never as the raw integer: the single-bit
  file and session flags are booleans (`"single_clock"` on `file`, `"sequenced"`
  on `session`), and a Record's multi-bit `flags` is an **array of set-bit
  tokens** (the JSON-token column of the [flags enum](#enums), e.g.
  `"flags":["psh","fin"]`). A zero/unset bitfield is omitted.
- **Repeatable options** (`endpoint`) → a JSON **array**, order preserved.
- **`spans`** → a JSON array of `{source_id, session_id, pid, off_start, off_end}`
  objects.
- An **absent** option is an **omitted** key; a reader treats a missing key as
  "option not present," never as a present option carrying a default.
- **Framing / on-disk-only fields are not projected**: the block
  `type`/`reserved`/`length`, the header `bom`, `end_magic`, `payload_len`, and
  padding have no JSON key — the `type` string, the JSON object structure, and the
  base64 `payload`'s own length stand in for them.

**Unrecognised data and `Custom` blocks.** A converter MUST round-trip what it
does not recognise, mirroring the binary skip-by-`length`/`len` rule: an
unregistered option becomes an entry in the block's `options` array, each
`{"id":"0x0091","value":"<base64 of the raw option value>"}`; an unknown `type`
string, or unknown keys on a known block, are preserved unchanged; a `Custom`
block carries `pen`, `subtype`, and a base64 `payload`.

**Semantic, not byte-exact.** A binary → JSONL → binary round-trip preserves
every field's *value*, but **not** the exact bytes: padding, the ordering of
distinct options within a block, and the choice of optional/default encodings are
not pinned down by JSONL. Consequently a round-tripped file's hash differs from
the original's. The `digest` dependency-edge (and any conformance hashing) is
therefore defined over the **binary form only** — never over a file that has been
passed through the JSONL face.

### Worked example: a minimal raw file

A complete, conformant **raw** `.zpf` file (204 bytes, **little-endian**) holding
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
0008  46 50 49 5A              bom    = 0x5A495046  ("ZIPF", LE on disk)
000C  01 00                    version_major = 1
000E  00 00                    version_minor = 0
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
0080  48 00 00 00              length = 72
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
00BC  71 00 04 00              option 0x0071 seq_end, len = 4
00C0  FB 03 00 00              seq_end = 1019
00C4  72 00 04 00              option 0x0072 ack, len = 4
00C8  89 13 00 00              ack = 5001
00CC                           (end of file, 204 bytes)
```

Things to read off it: the BOM at fixed offset 8 resolves endianness; the 8-byte
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
  records (the model for raw-vs-decoded views).
- **Matroska/MP4** — N timestamped, interleaved tracks (the multi-participant
  mental model).
- **HAR** — the ergonomics target for the optional decoded JSON view (not the
  storage format).

## Open questions

- Compression: per-record, per-session, or whole-file?
- Should a `zpf-input` Source reference a whole input file, or also pin a
  per-session digest, so a single changed session forces re-derivation of only
  that session?

## Possible future extensions

- **Random-access index.** An optional `Index` block near the end (just before
  the [End block](#end-of-file-0x41)) mapping `session_id` → the byte offset of
  its Session Descriptor, so a reader can seek to a session instead of scanning
  from the start. *Benefit:* O(1) lookup on finished files at rest. *Cost:* the
  writer must hold a session→offset map until finalize (O(#sessions) memory,
  unbounded for indefinite live captures), and — because records interleave — it
  locates a session's *declaration*, not its scattered records. Stays fully
  optional and streaming-compatible: a skippable block, absent on live or
  truncated files, found via a back-pointer from the End block.

- **Self-describing repeatability (a `repeatable` id-bit).** Reserve the high bit
  of a TLV `id` to mark an option as an ordered list, so a schema-less tool could
  render an unknown option as scalar-vs-array without consulting the registry.
  *Not adopted now:* a reader already preserves every occurrence in order (see
  [TLV framing](#tlv-option-framing--id-registry)), so generic round-trip is
  lossless without it; the bit would only buy prettier rendering of unknown
  single-valued options, at the cost of a permanent framing bit, a per-occurrence
  consistency rule, and duplicating a fact the registry already holds. If ever
  wanted, the `id` high bit (dropping ids to a 15-bit space) is the place — *not*
  the `len` bit, which would halve the 64 KB option-value cap.
