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
record may be either a *byte run* (transport-truthful; boundaries fall where
reassembly produced them) or a *protocol message* (boundaries imposed by an app
decoder). A `boundary` flag says which, so a generic consumer can fall back to
byte runs when no decoder ran.

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
+--------+--------+-----------------------+----------------+
| type   | length | body                  | options (TLV)  |
| u16    | u32    | (block-specific)      | until length   |
+--------+--------+-----------------------+----------------+
```

Block types:

| Type | Name                    | Purpose                                        |
|------|-------------------------|------------------------------------------------|
| 0x01 | File Header             | magic, format version, byte order, time units  |
| 0x02 | Source Descriptor       | one capture origin (file/interface); has an id  |
| 0x03 | Derivation              | input file(s) + digests this file was built from |
| 0x04 | Decoder Descriptor      | a decoder's id, name, version, params digest    |
| 0x10 | Session Descriptor      | session id, protocol, flow key, metadata        |
| 0x11 | Participant Descriptor  | participant id within a session, endpoint, TCP ISN |
| 0x20 | Record                  | a directed payload unit (see fields below)      |
| 0x21 | Gap                     | an uncovered/undecodable region (see Layers)    |
| 0x30 | Name/Identity Resolution| optional: map participant ids → human labels    |
| 0xFF | Custom                  | vendor/experimental, namespaced                 |

The Derivation, Decoder Descriptor, and Gap blocks only appear in *derived*
(decoded) files; a raw file omits them. See
[Layers](#layers-raw-and-decoded-live-in-separate-files).

TLV options are `id: u16, len: u16, value: bytes`, repeated until the block
ends. Unknown option ids are skipped, so the format extends without a version
bump: new per-session / per-participant attributes are just new TLVs, and old
readers ignore what they do not understand.

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
| `session_id`      | u32    | refers to a Session Descriptor                         |
| `sender_pid`      | u16    | participant id within that session                     |
| `source_id`       | u16    | which Source Descriptor these bytes came from          |
| `timestamp`       | i64    | packet time, in the file's time units                  |
| `boundary`        | u8     | `0` = byte run, `1` = protocol message                 |
| `flags`           | u16    | PSH/FIN/RST seen, decoded-view-present, etc.            |
| `payload_len`     | u32    | length of raw payload                                   |
| `payload`         | bytes  | raw reassembled bytes (source of truth)                |
| TLV options       | …      | TCP ordering hints, provenance (below)                 |

Per-record TLV options of interest:

- **TCP ordering hints** (`seq_start`, `seq_end`, `ack`) — see next section.
- **Capture provenance** — for a *raw* record, a back-reference into the source
  capture: frame numbers / byte ranges. Cheap, invaluable for debugging the
  sessionizer.
- **Derivation provenance** (`spans`, `decoder_id`) — for a *decoded* record,
  the source byte ranges it was built from and which decoder produced it. See
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

To make seq/ack comparable across directions we store, per participant, the
**ISN** (Initial Sequence Number) in its Participant Descriptor, and express
record `seq_start`/`seq_end`/`ack` as **stream offsets relative to the ISN**
(first data byte = 1). That also sidesteps the 32-bit seq wraparound.

### Fields used

Per **Participant Descriptor** (TCP):

| Option        | Meaning                                              |
|---------------|------------------------------------------------------|
| `isn`         | initial sequence number; offset = `abs_seq - isn`    |
| `endpoint`    | `ip:port`                                             |

Per **Record** (TCP):

| Option       | Meaning                                                       |
|--------------|---------------------------------------------------------------|
| `seq_start`  | sender stream offset of first payload byte                    |
| `seq_end`    | `seq_start + payload_len` (one past last byte)                |
| `ack`        | highest peer-stream offset the sender had received when sent  |

### Merge algorithm

```text
INPUT:  records of a session, grouped by sender participant
OUTPUT: one interleaved, causally-consistent sequence

1. Within each participant, order records by seq_start (a total order;
   the participant's own byte stream is monotonic).

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
 "boundary":1,"seq_start":1,"seq_end":19,"ack":1,
 "payload":"R0VUIC8gSFRUUC8xLjENCg0K"}
{"type":"record","session_id":7,"sender_pid":1,"source_id":2,"ts":995,
 "boundary":1,"seq_start":1,"seq_end":101,"ack":19,
 "payload":"SFRUUC8xLjEgMjAwIE9LDQouLi4="}
```

Note the server record's `ts` (995) is *earlier* than the client request it
answers (1000) — the two capture clocks are skewed. The `ack:19` on the server
record nonetheless places it **after** the client's `[1,19)` request via the
causal edge, so the merge is correct despite the timestamp inversion.

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
 "boundary":1,"payload":"aGksIGFsbCE="}
{"type":"record","session_id":8,"sender_pid":2,"source_id":1,"ts":2100,
 "boundary":1,"payload":"aGV5IGFsaWNl"}
{"type":"record","session_id":8,"sender_pid":1,"source_id":1,"ts":2150,
 "boundary":1,"payload":"bW9ybmluZw=="}

{"type":"participant","session_id":8,"pid":3,"endpoint":"dave"}
{"type":"record","session_id":8,"sender_pid":3,"source_id":1,"ts":2300,
 "boundary":1,"payload":"YW0gSSBsYXRlPw=="}
```

And a *decoded* file derived from the TCP capture above — note the `derivation`
and `decoder` headers, and that each record cites the source `spans` it was
built from rather than carrying transport offsets of its own:

```jsonl
{"type":"file","format":"zipline-payload/1","time_units":"us"}
{"type":"derivation","input_id":1,"uri":"raw.zpf",
 "digest":"sha256:9f2c…","produced_by":"zpf-decode 0.4","produced_at":1719500000}
{"type":"decoder","decoder_id":1,"name":"http/1.1","version":"0.4",
 "params_digest":"sha256:00ab…","boundary":"protocol-message"}

{"type":"session","session_id":7,"proto":"http"}
{"type":"participant","session_id":7,"pid":0,"endpoint":"10.0.0.1:51000"}
{"type":"participant","session_id":7,"pid":1,"endpoint":"93.184.216.34:80"}

{"type":"record","session_id":7,"sender_pid":0,"ts":1000,"decoder_id":1,
 "spans":[{"input":1,"session_id":7,"pid":0,"off_start":1,"off_end":19}],
 "payload":"…decoded request…"}
{"type":"record","session_id":7,"sender_pid":1,"ts":995,"decoder_id":1,
 "spans":[{"input":1,"session_id":7,"pid":1,"off_start":1,"off_end":101}],
 "payload":"…decoded response…"}
{"type":"gap","session_id":7,"pid":1,"off_start":101,"off_end":140,
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
in the reassembled stream**, using the same ISN-relative offsets as the TCP
ordering hints — *not* at raw record ids. That makes the raw side's arbitrary
chunking irrelevant; a fractional, multi-record span is just one contiguous
range. The provenance of a decoded record is a **span set**:

```
provenance = {
  input:   <derivation input id>,            // which source file
  decoder: <decoder_id>,                      // which decoder produced this
  spans:   [ { session_id, pid, off_start, off_end }, … ]
}
```

Usually a single span (one participant, one contiguous range). The list covers
the rare gapped or cross-direction message. Offset-based references survive the
raw file being re-chunked or re-written.

### Derivation block (which input)

A derived file declares its input(s) once:

| Field            | Meaning                                                     |
|------------------|-------------------------------------------------------------|
| `input_id`       | local id referenced by record `spans`                       |
| `uri`            | where the source file lives                                 |
| `digest`         | content hash (e.g. SHA-256) of the source file              |
| `produced_by`    | tool + version that ran the transform                       |
| `produced_at`    | wall-clock time of the transform (the artifact, not the     |
|                  | packet stream — packet-time does not apply here)            |

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
| `boundary`      | the scheme it imposes (e.g. `protocol-message`)             |

Records carry a `decoder_id` (defaulting to the file's primary). Per-record —
not just per-file — because one decoded file legitimately mixes decoders: HTTP
on one session, TLS-then-HTTP on another, a raw fallback on a session that did
not parse. **Reproducibility contract:** same input `digest` + same decoder
`version`/`params_digest` ⇒ identical output.

### Coverage honesty: Gap blocks

A decoder can fail partway, or hit a TCP gap (where it can only decode the
gap-free runs on either side). The decoded file states what it did *not* cover
with an explicit **Gap block** rather than silently dropping bytes:

```jsonl
{"type":"gap","session_id":7,"pid":1,"off_start":101,"off_end":140,
 "reason":"undecodable","decoder_id":1}
```

A consumer can then distinguish "no message here" from "a message we could not
parse," and a re-derivation can target just the gaps.

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
- Should a Derivation reference a whole input file, or also pin a per-session
  digest, so a single changed session forces re-derivation of only that session?
- Do decoded records keep their own packet-time `ts` (copied from the spanning
  raw bytes), or only the derivation `produced_at`? Probably both: `ts` for
  ordering, `produced_at` for provenance.
