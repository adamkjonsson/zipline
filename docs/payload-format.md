# Zipline Payload Format (design sketch)

> Status: **design proposal**, not yet implemented. This document sketches the
> **Zipline Payload Format** (`.zpf`), a file format for the *payload* output of
> a network sessionizer: the bytes that flow between endpoints once packets have
> been reassembled into sessions, plus the metadata needed to consume them. The
> format is tool-independent — any program can read or write it.

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
participant, a packet-time timestamp, the payload bytes, and ordering hints. A
record may be either a *raw byte run* (transport-truthful; boundaries fall where
reassembly produced them) or a *decoder-imposed unit* (boundaries set by an app
decoder). A `boundary` field says which — `0` for a raw byte run, non-zero for a
decoder-imposed unit — so a generic consumer can fall back to byte runs when no
decoder ran. What a non-zero boundary *means* (HTTP message, TLS record, …) comes
from the record's `decoder_id`, not from the number itself.

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
| 0x21 | Gap                     | an uncovered/undecodable region (see Layers)    |
| 0x30 | Name/Identity Resolution| optional: map participant ids → human labels    |
| 0xFF | Custom                  | vendor/experimental, namespaced                 |

A single **Source Descriptor** type covers both a raw capture and a derived input
(`kind = capture` vs `kind = zpf-input`), so a record references its origin the
same way whether the file is raw or decoded. The Decoder Descriptor and Gap
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
reads, exactly as the writer built them. (A future [index block](#open-questions)
could gather descriptor offsets for random access without changing this
streaming contract.)

### Record block fields

| Field             | Type   | Notes                                                  |
|-------------------|--------|--------------------------------------------------------|
| `session_id`      | u64    | refers to a Session Descriptor                         |
| `sender_pid`      | u16    | participant id within that session                     |
| `source_id`       | u16    | which Source Descriptor these bytes came from          |
| `timestamp`       | i64    | packet time, in the file's time units                  |
| `boundary`        | u8     | `0` = raw byte run, `≥1` = decoder-imposed unit         |
| `flags`           | u16    | PSH/FIN/RST/SYN seen, datagram boundary, etc.          |
| `payload_len`     | u32    | length of raw payload                                  |
| `payload`         | bytes  | raw reassembled bytes (source of truth)                |
| TLV options       | …      | TCP ordering hints, provenance (below)                 |

Per-record TLV options of interest:

- **TCP ordering hints** (`seq_start`, `seq_end`, `ack`) — absolute wire sequence
  numbers; see next section.
- **Provenance** (`spans`) — the byte ranges of a `source_id` these bytes were
  built from. For a *raw* record the source is a capture (`spans` give frame /
  byte ranges, invaluable for debugging the sessionizer); for a *decoded* record
  the source is a `.zpf` input (`spans` give stream offsets) and a `decoder_id`
  names the decoder. One `spans` option serves both. See
  [Layers](#layers-raw-and-decoded-live-in-separate-files).

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
| `isn`         | the SYN's sequence number, recorded **for information** when the handshake was seen; *not* used as an offset base |
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
         *peer* whose seq_end <= a   (serial-number comparison)
     (R's sender had already received those peer bytes, so they precede R.)

3. Topologically sort the resulting DAG.

4. Where the topo order is free (concurrent records with no causal edge
   between them), break ties by timestamp; if clocks are known-skewed,
   fall back to round-robin / source order.
```

Step 2 is the payoff: it stitches the two separately-captured directions
together on causality, using timestamps only as a tie-breaker rather than the
primary key.

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
- A **mid-stream** capture (handshake never seen) needs no special handling:
  because the hints are absolute wire numbers, ordering works without the ISN.
  The writer simply omits `isn`. (The writer is responsible for confirming the
  SYN is genuinely absent rather than merely delayed before declaring a
  participant ISN-less.)

## JSON-Lines projection

One object per line. `type` discriminates. Payloads are base64.

```jsonl
{"type":"file","format":"zipline-payload/1","time_units":"us"}
{"type":"source","source_id":1,"uri":"sideA.pcap"}
{"type":"source","source_id":2,"uri":"sideB.pcap"}

{"type":"session","session_id":7,"proto":"tcp",
 "key":"10.0.0.1:51000 <-> 93.184.216.34:80"}
{"type":"participant","session_id":7,"pid":0,"endpoint":"10.0.0.1:51000","isn":1000}
{"type":"participant","session_id":7,"pid":1,"endpoint":"93.184.216.34:80","isn":5000}

{"type":"record","session_id":7,"sender_pid":0,"source_id":1,"ts":1000,
 "boundary":0,"seq_start":1001,"seq_end":1019,"ack":5001,
 "payload":"R0VUIC8gSFRUUC8xLjENCg0K"}
{"type":"record","session_id":7,"sender_pid":1,"source_id":2,"ts":995,
 "boundary":0,"seq_start":5001,"seq_end":5101,"ack":1019,
 "payload":"SFRUUC8xLjEgMjAwIE9LDQouLi4="}
```

These are raw records (`boundary:0`). The sequence numbers are absolute (client
ISN 1000 → first data byte 1001; server ISN 5000 → first data byte 5001). Note
the server record's `ts` (995) is *earlier* than the client request it answers
(1000) — the two capture clocks are skewed. The server's `ack:1019` nonetheless
places it **after** the client's `[1001,1019)` request via the causal edge, so
the merge is correct despite the timestamp inversion.

A 3-party chat room in the same file — sessions are just additional descriptors,
participants beyond two, and records with no TCP hints (ordering falls back to
timestamps, since a single chat server saw all messages on one clock):

Participants are declared as they appear (see
[declare-on-first-use](#declaration-order-declare-on-first-use)) — `dave` joins
mid-stream and is declared only at that point:

```jsonl
{"type":"session","session_id":8,"proto":"irc","key":"#zipline@irc.example.net"}
{"type":"participant","session_id":8,"pid":0,"endpoint":"alice"}
{"type":"participant","session_id":8,"pid":1,"endpoint":"bob"}
{"type":"participant","session_id":8,"pid":2,"endpoint":"carol"}

{"type":"record","session_id":8,"sender_pid":0,"source_id":1,"ts":2000,
 "boundary":0,"payload":"aGksIGFsbCE="}
{"type":"record","session_id":8,"sender_pid":2,"source_id":1,"ts":2100,
 "boundary":0,"payload":"aGV5IGFsaWNl"}
{"type":"record","session_id":8,"sender_pid":1,"source_id":1,"ts":2150,
 "boundary":0,"payload":"bW9ybmluZw=="}

{"type":"participant","session_id":8,"pid":3,"endpoint":"dave"}
{"type":"record","session_id":8,"sender_pid":3,"source_id":1,"ts":2300,
 "boundary":0,"payload":"YW0gSSBsYXRlPw=="}
```

And a *decoded* file derived from the TCP capture above — the build provenance
(`produced_by`/`produced_at`) sits on the `file` header, the input `.zpf` is a
`source` of `kind:"zpf-input"`, and each record cites the `spans` of that source
it was built from rather than carrying transport offsets of its own. Span offsets
are **logical 0-based stream offsets** (the Nth byte of that participant's
reassembled stream), independent of the absolute TCP numbers used for ordering:

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

{"type":"record","session_id":7,"sender_pid":0,"ts":1000,"boundary":1,"decoder_id":1,
 "spans":[{"source_id":1,"session_id":7,"pid":0,"off_start":0,"off_end":18}],
 "payload":"…decoded request…"}
{"type":"record","session_id":7,"sender_pid":1,"ts":995,"boundary":1,"decoder_id":1,
 "spans":[{"source_id":1,"session_id":7,"pid":1,"off_start":0,"off_end":100}],
 "payload":"…decoded response…"}
{"type":"gap","session_id":7,"pid":1,"off_start":100,"off_end":139,
 "reason":"undecodable","decoder_id":1}
```

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
another (byte runs). Each file stands alone for *consumption* — reading
`decoded.zpf` never requires `raw.zpf` to be present. The link between them is
**provenance**, used for verification and re-derivation, not for reading.

This generalizes: `raw → tls-records → http → …` is the same mechanism applied
N times. Nothing special-cases "raw"; each stage just derives from the previous
file's spans.

### Referencing the source by stream offset

The crux of the "2.5 records" problem: a decoded record points at **byte ranges
in the reassembled stream** by a **logical 0-based stream offset** (byte 0 is the
first reassembled payload byte of that participant's stream) — *not* at raw
record ids, and *not* at the absolute TCP sequence numbers used for ordering.
This logical offset is deliberately TCP-independent, so the same mechanism works
for a decoded UDP or chat stream that has no sequence numbers. It makes the raw
side's arbitrary chunking irrelevant; a fractional, multi-record span is just one
contiguous range. The provenance of a decoded record is a **span set**:

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

### Source Descriptor (which input)

A derived file declares each input `.zpf` as a Source of `kind = zpf-input`:

| Field            | Meaning                                                     |
|------------------|-------------------------------------------------------------|
| `source_id`      | local id referenced by record `spans`                       |
| `kind`           | `zpf-input` (the input is another `.zpf`)                   |
| `uri`            | where the input file lives                                  |
| `digest`         | content hash (e.g. SHA-256) of the input file               |

The same block type describes a raw **capture** source (`kind = capture`, with a
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

The decoder is a first-class, referenceable entity:

| Field           | Meaning                                                      |
|-----------------|-------------------------------------------------------------|
| `decoder_id`    | local id referenced per-record                              |
| `name`          | e.g. `http/1.1`                                             |
| `version`       | decoder version                                             |
| `params_digest` | hash of the decoder config, so the decode is reproducible   |

Every decoder-imposed record (`boundary ≥ 1`) carries an **explicit**
`decoder_id` — there is no implicit "primary" default. The reference is
per-record, not per-file, because one decoded file legitimately mixes decoders:
HTTP on one session, TLS-then-HTTP on another, a raw fallback on a session that
did not parse. A record's `decoder_id` is exactly what gives its non-zero
`boundary` meaning. **Reproducibility contract:** same input `digest` + same
decoder `version`/`params_digest` ⇒ identical output.

### Coverage honesty: Gap blocks

A decoder can fail partway, or hit a TCP gap (where it can only decode the
gap-free runs on either side). The decoded file states what it did *not* cover
with an explicit **Gap block** rather than silently dropping bytes:

```jsonl
{"type":"gap","session_id":7,"pid":1,"off_start":100,"off_end":139,
 "reason":"undecodable","decoder_id":1}
```

A consumer can then distinguish "no message here" from "a message we could not
parse," and a re-derivation can target just the gaps.

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
wall-clock build time in Unix seconds), `comment`.

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
`flow_key` (string), `comment`.

**Participant Descriptor (`0x11`)**

| Field            | Type | Notes                                   |
|------------------|------|-----------------------------------------|
| `session_id`     | u64  | session this participant belongs to     |
| `participant_id` | u16  | id within that session (the `pid`)      |
| `_reserved`      | u16  | 0                                       |

Options: `endpoint` (string, **may repeat** — see below), `isn` (u32, the SYN's
TCP sequence number, **informational only** — recorded when the handshake was
seen; ordering uses absolute sequence numbers and does not rely on it),
`tcp_role` (u8, see enums), `identity` (string), `comment`.

`tcp_role` records, **when the handshake was observed**, which side opened the
connection: the participant that sent the initial SYN is the *initiator* (active
open), its peer the *responder* (passive open). Omit it when the capture began
mid-stream and the opener is unknown — absence means "unknown", not "responder".

**Tunnelled endpoints.** When the traffic was carried through one or more
tunnels (VXLAN, GRE, IP-in-IP, a VPN, …), a participant has an address at each
layer. The `endpoint` option therefore MAY appear more than once, and the order
is significant: the **outermost** (carrier) address comes first, each subsequent
`endpoint` is one layer further in, and the **last** is the innermost — the
address at which the participant actually speaks the session protocol. A reader
that wants "the" address uses the last `endpoint`; the earlier ones describe the
delivery path. A single un-tunnelled participant has exactly one `endpoint`.

### Record (`0x20`)

Body (fixed part), matching [Record block fields](#record-block-fields):

| Field         | Type  | Notes                                              |
|---------------|-------|----------------------------------------------------|
| `session_id`  | u64   | refers to a Session Descriptor                     |
| `sender_pid`  | u16   | participant id within that session                 |
| `source_id`   | u16   | refers to a Source Descriptor — a `capture` for a raw record, a `zpf-input` for a decoded one |
| `timestamp`   | i64   | packet time, in `tick_hz` ticks (see timestamp rule)|
| `boundary`    | u8    | see enum (`0` raw, `≥1` decoder-imposed)            |
| `_reserved`   | u8    | 0                                                  |
| `flags`       | u16   | see bit table                                      |
| `payload_len` | u32   | length of `payload`                                |
| `payload`     | bytes | `payload_len` raw bytes (source of truth)          |

`payload` is zero-padded to a multiple of 4 bytes; options then follow (TCP
hints, provenance — see registry). `payload_len` gives the unpadded length and
MAY be 0 (e.g. a pure-ACK record carrying only an `ack` hint). A record with
`boundary ≥ 1` MUST carry a `decoder_id`; a record with `boundary = 0` MUST NOT.
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
- A **decoded** record's `timestamp` is the time of the last raw byte in its
  span set — when the decoded message was complete.

The first-packet time is recoverable from capture-source `spans` provenance; a
writer that wants it without full provenance MAY add an optional `ts_first` TLV.
The canonical `timestamp` is always the completion (last-packet) time.

`timestamp` is **signed** (i64, as are `ts_first`, `time_epoch`, and
`produced_at`) for two reasons: the configurable `time_epoch` origin admits
times *before* it (negative ticks), and inter-record deltas — central to the
skew-tolerant ordering — are inherently signed, so the same width holds both an
instant and a difference without underflow. The range given up versus u64 is
immaterial: i64 ticks span centuries around the epoch at the resolutions
`tick_hz` is meant for.

### Gap (`0x21`)

Derived files only.

| Field            | Type | Notes                                              |
|------------------|------|----------------------------------------------------|
| `session_id`     | u64  | session the uncovered region belongs to            |
| `participant_id` | u16  | participant (stream) the region is in              |
| `_reserved`      | u16  | 0                                                  |
| `off_start`      | u64  | logical 0-based stream offset, first byte = 0      |
| `off_end`        | u64  | one past the last byte (half-open `[start, end)`)  |

Offsets are logical 0-based stream offsets, the same convention used by `spans`
(*not* absolute sequence numbers). Options: `reason` (string, e.g. `undecodable`
/ `tcp-gap` / `truncated`), `decoder_id` (u16).

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

### TLV option framing & id registry

`id: u16, len: u16, value` (then pad to 4 bytes). Options run until the block
`length` is consumed; there is no end-of-options sentinel. `id 0x0001` is
`comment` (UTF-8) on any block. Ids are grouped by the block they belong to but
an id never changes meaning across blocks where it is reused (e.g. `decoder_id`).

An option id appears **at most once** per block unless its registry entry marks
it repeatable (e.g. `endpoint`). For a repeatable id, **the order of occurrences
is significant** and readers MUST preserve it; for any other id a reader MAY use
the first occurrence and ignore the rest.

| Id       | Name             | Value type | Used in                  | Meaning                                                        |
|----------|------------------|------------|--------------------------|----------------------------------------------------------------|
| `0x0001` | comment          | string     | any                      | free-text human note attached to the block                     |
| `0x0010` | time_epoch       | i64        | File Header              | origin for record timestamps (Unix-epoch ticks); default 0     |
| `0x0011` | creator          | string     | File Header              | tool + version that wrote the file                             |
| `0x0012` | produced_by      | string     | File Header              | tool + version that ran the transform (derived files)          |
| `0x0013` | produced_at      | i64        | File Header              | wall-clock build time of this artifact (Unix seconds)          |
| `0x0020` | uri              | string     | Source                   | where the referenced capture/input file lives                  |
| `0x0021` | digest           | string     | Source                   | content hash of the referenced file — the dependency edge      |
| `0x0022` | link_type        | u16        | Source (capture)         | link-layer type of the capture (e.g. a pcap LINKTYPE)          |
| `0x0041` | name             | string     | Decoder                  | decoder identifier, e.g. `http/1.1`                            |
| `0x0042` | version          | string     | Decoder                  | decoder version                                                |
| `0x0043` | params_digest    | string     | Decoder                  | hash of the decoder config, so the decode is reproducible      |
| `0x0050` | proto            | string     | Session                  | session protocol, lowercase (`tcp`/`udp`/`irc`/`http`/`tls`)   |
| `0x0051` | flow_key         | string     | Session                  | human-readable flow key, e.g. `a:port <-> b:port`              |
| `0x0060` | endpoint         | string     | Participant              | participant address, e.g. `ip:port` or a nick; **repeatable**, outermost tunnel layer first → innermost last |
| `0x0061` | isn              | u32        | Participant              | the SYN's sequence number, informational; not an offset base   |
| `0x0062` | identity         | string     | Participant              | stable identity distinct from a transient endpoint             |
| `0x0063` | tcp_role         | u8         | Participant (TCP)        | active/passive opener when the handshake was seen (see enums)  |
| `0x0070` | seq_start        | u32        | Record (TCP)             | absolute sequence number of the first payload byte             |
| `0x0071` | seq_end          | u32        | Record (TCP)             | absolute sequence number one past the last payload byte (mod 2³²) |
| `0x0072` | ack              | u32        | Record (TCP)             | highest absolute peer sequence number the sender had received  |
| `0x0073` | ts_first         | i64        | Record                   | optional packet time of the *first* contributing packet        |
| `0x0080` | spans            | span-list  | Record, Gap              | source ranges these bytes were built from (see below)          |
| `0x0090` | decoder_id       | u16        | Record, Gap (decoded)    | which Decoder Descriptor produced this record/gap              |
| `0x00A0` | reason           | string     | Gap                      | why the region is uncovered (`undecodable`/`tcp-gap`/…)        |
| `0x00B0` | label            | string     | Name/Identity Resolution | the human-readable name being assigned                         |
| `0x00B1` | kind             | string     | Name/Identity Resolution | source/kind of the label (`nick`/`dns`/`tls-sni`)              |

A **span-list** value is `count` packed entries, each 28 bytes:
`source_id: u16, pid: u16, session_id: u64, off_start: u64, off_end: u64`
(`count = len / 28`). The two u16s lead so the u64 fields stay 4-byte aligned
within the packed entry. The **interpretation of the offsets is keyed by the
referenced source's `kind`**: for a `zpf-input` source, `off_start`/`off_end` are
**logical 0-based stream offsets** within `(session_id, pid)` of that input; for
a `capture` source, they are **byte offsets into the capture file** and
`session_id`/`pid` are unused (write 0). One option id (`spans`) serves both raw
capture-provenance and decoded derivation-provenance.

### Enums

`boundary` (Record body, u8): `0` = raw byte run (transport-truthful, no
decoder). Any value `≥ 1` = a decoder-imposed unit; the value itself carries no
standardised meaning — *which* boundary scheme it is comes from the record's
`decoder_id` → Decoder `name`. Values `2`–`255` are reserved for future
distinctions but are not defined here. A `boundary ≥ 1` record MUST carry a
`decoder_id`; a `boundary = 0` record MUST NOT.

`kind` (Source body, u8): `0` = capture (a pcap/interface), `1` = zpf-input
(another `.zpf` this file was derived from).

`tcp_role` (Participant option, u8): `0` = unknown (handshake not observed),
`1` = initiator (active open, sent the SYN), `2` = responder (passive open).

`flags` (Record body, u16):

| Bit    | Meaning                                                    |
|--------|------------------------------------------------------------|
| `0x0001` | TCP PSH seen in this run                                 |
| `0x0002` | TCP FIN seen                                             |
| `0x0004` | TCP RST seen                                             |
| `0x0008` | TCP SYN (handshake record)                              |
| `0x0010` | TCP URG seen                                             |
| `0x0040` | retransmission/overlap was resolved inside this record   |
| `0x0080` | datagram boundary (UDP: record is exactly one datagram)  |
| `0xFF20` | reserved, MUST be 0                                      |

### Identifiers & ordering

- `session_id`, `source_id`, and `decoder_id` are unique within a file.
  `participant_id` is scoped to its session. Ids MUST NOT be reused. `0` is a
  legal id value (no id is reserved as a sentinel — optional references like
  `decoder_id` signal "none" by *absence*, never by value 0).
- **Identifier widths.** `session_id` is u64; every other id
  (`participant_id`, `source_id`, `decoder_id`) is u16. The width
  mirrors the population each id counts. A `session_id` is file-global and names
  an entity from an *unbounded, streaming* source: a flush-and-forget writer
  mints a fresh id for every sessionized flow over a capture that may run
  indefinitely, and because ids MUST NOT be reused the counter only ever grows.
  A 16- or even 32-bit space could plausibly wrap on a long, busy capture; u64
  removes that ceiling. The width is also deliberately large enough that a writer
  MAY draw `session_id`s from a single *global*, monotonic sequence — a
  process-wide or fleet-wide counter — rather than restarting per file. The
  format only requires uniqueness *within* a file, but a globally-allocated id is
  never reused across files either, so a cross-file reference (a decoded file's
  `spans` into a `zpf-input`, a chained derivation) names exactly one session
  with no ambiguity and no risk of collision when files are later merged or
  cross-linked. u64 makes that practically inexhaustible. The other ids count
  small, *bounded*, per-file sets — participants within a session (two for TCP, a
  handful for a chat room), sources (captures and `.zpf` inputs), decoders —
  none of which approach the u16 limit, so a wider field would only waste space.
- On-disk block order is unconstrained beyond declare-on-first-use; in
  particular a participant's records need **not** be stored in `seq_start`
  order — the [merge algorithm](#merge-algorithm) sorts them. Within one source,
  records SHOULD be emitted in capture order to keep the timestamp tie-breaker
  meaningful.

### Conformance

Every file MUST start with exactly one File Header as its first block, and MUST
declare each Source, Session, and Participant before any block references it.

Raw and decoded are **per-record** properties, not whole-file modes (a file MAY
mix them — e.g. a decoder that emits decoded records directly while falling back
to raw on what it cannot parse):

- A **raw** record has `boundary = 0`, carries no `decoder_id`, and its
  `source_id`/`spans` reference a `capture` Source. TCP raw records SHOULD carry
  `seq_start`/`seq_end` (and `ack` where known); TCP participants SHOULD carry
  `isn` when the handshake was seen; UDP records SHOULD set the datagram-boundary
  flag.
- A **decoded** record has `boundary ≥ 1`, MUST carry a `decoder_id`, and its
  `source_id`/`spans` reference a `zpf-input` Source. A file containing any
  decoded record MUST declare every Decoder it references and every `zpf-input`
  Source, set the File Header `produced_by`/`produced_at`, and state uncovered
  regions as **Gap** blocks rather than dropping them. Decoder, Gap, and
  `zpf-input` Sources appear only in files that carry decoded records.

Readers MUST skip unknown block types (via frame `length`) and unknown option
ids (via `len`), and MUST treat reserved fields/bits as ignored-on-read.

**Concatenation is not supported.** A `.zpf` file has exactly one File Header,
at its very start; bytes after the last complete block are not a new section.
Concatenating two `.zpf` files does **not** yield a valid `.zpf`. To split a
streaming intercept across several files, the producer is responsible for making
their order recoverable out-of-band (a naming convention, a manifest, etc.).

### Truncation

There is no global trailer — the format is forward-only and streamable. A reader
that finds fewer than `length` bytes remaining for a block MUST treat the file
as **truncated at that block** (a writer crash mid-flush) and discard the
partial tail; all complete prior blocks remain valid. Detecting *intentional*
completeness (vs. truncation) requires the optional index discussed in
[Open questions](#open-questions).

### JSONL ↔ binary field mapping

The JSON-Lines projection (above) is **semantically** lossless for the fields
below; the `type` string selects the block. Names differ where JSONL favours
brevity:

| JSONL key            | Binary field / option        |
|----------------------|------------------------------|
| `format`             | `version_major.version_minor`|
| `time_units`         | `tick_hz`                    |
| `ts`                 | Record `timestamp`           |
| `pid`                | Participant `participant_id` |
| `proto`, `key`       | `proto`, `flow_key` options  |
| `kind`               | Source `kind` (`capture`/`zpf-input`) |
| `spans`              | `spans` (entries `{source_id, session_id, pid, off_start, off_end}`) |
| `payload` (base64)   | `payload` (raw bytes)        |

`payload` uses **standard** base64 (RFC 4648 §4, with `=` padding) in JSONL.
Options not in this table round-trip through a generic `options` array so the
converter stays lossless.

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
`GET / HTTP/1.1\r\n\r\n` from the [JSONL example](#json-lines-projection)
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
0078  E8 03 00 00              isn = 1000  (informational)

# ── Record (0x20) ───────────────────────────────────────────────────
007C  20 00                    type   = 0x0020  Record
007E  00 00                    reserved
0080  48 00 00 00              length = 72
0084  07 00 00 00 00 00 00 00  session_id = 7  (u64)
008C  00 00                    sender_pid = 0
008E  01 00                    source_id  = 1
0090  E8 03 00 00 00 00 00 00  timestamp  = 1000
0098  00                       boundary   = 0  (raw byte run)
0099  00                       _reserved
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

- Index block (offsets of each Session Descriptor) for random access, vs.
  strict streaming?
- Compression: per-record, per-session, or whole-file?
- Should a `zpf-input` Source reference a whole input file, or also pin a
  per-session digest, so a single changed session forces re-derivation of only
  that session?
- Do decoded records keep their own packet-time `ts` (copied from the spanning
  raw bytes), or only the File Header `produced_at`? Probably both: `ts` for
  ordering, `produced_at` for provenance.
