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
- **Alignment / padding.** Every item is zero-padded so the next one begins on a
  **4-byte boundary measured from the start of the block content** (the byte
  after `length`). Concretely: each block's fixed body is a multiple of 4 bytes
  (reserved fields ensure this); a Record's `payload` is zero-padded to a
  multiple of 4 before its options begin; and each TLV option `value` is
  zero-padded to a multiple of 4. Padding is counted in the block `length` only
  — never in a TLV `len` or in `payload_len`, which always give the true value
  size.
- **Reserved** fields and reserved bits MUST be written as 0 and MUST be ignored
  on read.

### Block frame

Every block, without exception:

```
+--------+----------+-------------------------------+
| type   | length   | content  (length bytes)       |
| u16    | u32      | = body ++ options ++ padding  |
+--------+----------+-------------------------------+
```

`length` counts the bytes **after** the `length` field — i.e. body + options +
padding. The next block begins at `offset_of_type + 6 + length`. A reader that
does not recognise `type` MUST skip the block using `length`; this is how
unknown block types stay forward-compatible, exactly as unknown option ids do.

### File Header (`0x01`)

MUST be the first block in the file. Body:

| Field           | Type | Value                                                        |
|-----------------|------|--------------------------------------------------------------|
| `bom`           | u32  | byte-order magic `0x5A495046` (`"ZIPF"`), written in the file's order |
| `version_major` | u16  | `1` for this document                                        |
| `version_minor` | u16  | `0`                                                          |
| `tick_hz`       | u64  | time units per second (e.g. `1000000` = µs, `1000000000` = ns)|

A reader detects endianness by reading `bom` both ways and seeing which yields
`0x5A495046`. Tools may sniff a ZPF file by the leading `type=0x01` followed,
six bytes in, by the BOM — `5A 49 50 46` (`"ZIPF"`, big-endian file) or
`46 50 49 5A` (little-endian file). Suggested file extension `.zpf`. A **minor**
version bump only adds blocks/options (old readers keep working); a **major**
bump may break frame/body layout.

Header options: `time_epoch` (i64, `tick_hz` ticks; default Unix epoch
1970-01-01T00:00:00Z), `creator` (string), `comment`.

### Descriptor blocks

Each fixed body ends with a `_reserved: u16` (0) where needed to round it to a
multiple of 4 bytes. The `Options` line under each table lists that block's TLV
options (see the [id registry](#tlv-option-framing--id-registry)).

**Source Descriptor (`0x02`)**

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `source_id`  | u16  | id referenced by records    |
| `_reserved`  | u16  | 0                           |

Options: `uri`, `capture_digest`, `link_type` (u16, e.g. a pcap LINKTYPE),
`comment`.

**Derivation (`0x03`)** — derived files only

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `input_id`   | u16  | id referenced by record `spans` |
| `_reserved`  | u16  | 0                           |

Options: `uri`, `digest`, `produced_by` (string), `produced_at` (i64,
**wall-clock** Unix seconds — the artifact's build time, not packet time),
`comment`.

**Decoder Descriptor (`0x04`)** — derived files only

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `decoder_id` | u16  | id referenced per-record    |
| `_reserved`  | u16  | 0                           |

Options: `name`, `version`, `params_digest`, `dec_boundary` (u8, see enums),
`comment`.

**Session Descriptor (`0x10`)**

| Field        | Type | Notes                       |
|--------------|------|-----------------------------|
| `session_id` | u32  | id referenced by participants and records |

Options: `proto` (string, lowercase, e.g. `tcp`/`udp`/`irc`/`http`/`tls`),
`flow_key` (string), `comment`.

**Participant Descriptor (`0x11`)**

| Field            | Type | Notes                                   |
|------------------|------|-----------------------------------------|
| `session_id`     | u32  | session this participant belongs to     |
| `participant_id` | u16  | id within that session (the `pid`)      |
| `_reserved`      | u16  | 0                                       |

Options: `endpoint` (string, **may repeat** — see below), `isn` (u32, TCP
initial sequence number), `tcp_role` (u8, see enums), `identity` (string),
`comment`.

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
| `session_id`  | u32   | refers to a Session Descriptor                     |
| `sender_pid`  | u16   | participant id within that session                 |
| `source_id`   | u16   | refers to a Source Descriptor                      |
| `timestamp`   | i64   | packet time, in `tick_hz` ticks (see timestamp rule)|
| `boundary`    | u8    | see enum                                           |
| `_reserved`   | u8    | 0                                                  |
| `flags`       | u16   | see bit table                                      |
| `payload_len` | u32   | length of `payload`                                |
| `payload`     | bytes | `payload_len` raw bytes (source of truth)          |

`payload` is zero-padded to a multiple of 4 bytes; options then follow (TCP
hints, provenance — see registry). `payload_len` gives the unpadded length and
MAY be 0 (e.g. a pure-ACK record carrying only an `ack` hint).

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

The first-packet time is recoverable from `capture_spans` provenance; a writer
that wants it without full provenance MAY add an optional `ts_first` TLV. The
canonical `timestamp` is always the completion (last-packet) time.

### Gap (`0x21`)

Derived files only.

| Field            | Type | Notes                                              |
|------------------|------|----------------------------------------------------|
| `session_id`     | u32  | session the uncovered region belongs to            |
| `participant_id` | u16  | participant (stream) the region is in              |
| `_reserved`      | u16  | 0                                                  |
| `off_start`      | u64  | ISN-relative stream offset, first byte = 1         |
| `off_end`        | u64  | one past the last byte (half-open `[start, end)`)  |

Offsets use the same convention as `seq_start`/`seq_end`. Options: `reason`
(string, e.g. `undecodable` / `tcp-gap` / `truncated`), `decoder_id` (u16).

### Name/Identity Resolution (`0x30`)

Optional.

| Field            | Type | Notes                                   |
|------------------|------|-----------------------------------------|
| `session_id`     | u32  | the session, or `0` for file-global     |
| `participant_id` | u16  | participant being labelled              |
| `_reserved`      | u16  | 0                                       |

Options: `label` (string, the human name), `kind` (string, e.g. `nick` / `dns` /
`tls-sni`), `comment`. Use this to attach labels *after the fact*; the inline
`endpoint`/`identity` on a Participant Descriptor is preferred when known at
declaration time.

### Custom (`0xFF`)

| Field       | Type  | Notes                                            |
|-------------|-------|--------------------------------------------------|
| `pen`       | u32   | IANA Private Enterprise Number (vendor namespace)|
| `subtype`   | u16   | vendor-defined block subtype                     |
| `_reserved` | u16   | 0                                                |
| `payload`   | bytes | opaque, vendor-defined (runs to end of block)    |

Readers without knowledge of `pen`/`subtype` skip via the frame `length`.

### TLV option framing & id registry

`id: u16, len: u16, value` (then pad to 4 bytes). `id 0x0000` is the optional
end-of-options sentinel; `id 0x0001` is `comment` (UTF-8) on any block. Ids are
grouped by the block they belong to but an id never changes meaning across
blocks where it is reused (e.g. `decoder_id`).

An option id appears **at most once** per block unless its registry entry marks
it repeatable (e.g. `endpoint`). For a repeatable id, **the order of occurrences
is significant** and readers MUST preserve it; for any other id a reader MAY use
the first occurrence and ignore the rest.

| Id       | Name             | Value type | Used in                  | Meaning                                                        |
|----------|------------------|------------|--------------------------|----------------------------------------------------------------|
| `0x0000` | end-of-options   | —          | any                      | optional sentinel marking the end of a block's options         |
| `0x0001` | comment          | string     | any                      | free-text human note attached to the block                     |
| `0x0010` | time_epoch       | i64        | File Header              | origin for record timestamps (Unix-epoch ticks); default 0     |
| `0x0011` | creator          | string     | File Header              | tool + version that wrote the file                             |
| `0x0020` | uri              | string     | Source, Derivation       | where the referenced capture/input file lives                  |
| `0x0021` | capture_digest   | string     | Source                   | content hash of the originating capture                        |
| `0x0022` | link_type        | u16        | Source                   | link-layer type of the capture (e.g. a pcap LINKTYPE)          |
| `0x0031` | digest           | string     | Derivation               | content hash of the input file — the dependency edge           |
| `0x0032` | produced_by      | string     | Derivation               | tool + version that ran the transform                          |
| `0x0033` | produced_at      | i64        | Derivation               | wall-clock build time of this artifact (Unix seconds)          |
| `0x0041` | name             | string     | Decoder                  | decoder identifier, e.g. `http/1.1`                            |
| `0x0042` | version          | string     | Decoder                  | decoder version                                                |
| `0x0043` | params_digest    | string     | Decoder                  | hash of the decoder config, so the decode is reproducible      |
| `0x0044` | dec_boundary     | u8         | Decoder                  | boundary scheme the decoder imposes (see enums)                |
| `0x0050` | proto            | string     | Session                  | session protocol, lowercase (`tcp`/`udp`/`irc`/`http`/`tls`)   |
| `0x0051` | flow_key         | string     | Session                  | human-readable flow key, e.g. `a:port <-> b:port`              |
| `0x0060` | endpoint         | string     | Participant              | participant address, e.g. `ip:port` or a nick; **repeatable**, outermost tunnel layer first → innermost last |
| `0x0061` | isn              | u32        | Participant              | TCP initial sequence number; `offset = abs_seq - isn`          |
| `0x0062` | identity         | string     | Participant              | stable identity distinct from a transient endpoint             |
| `0x0063` | tcp_role         | u8         | Participant (TCP)        | active/passive opener when the handshake was seen (see enums)  |
| `0x0070` | seq_start        | u64        | Record (TCP)             | sender stream offset of the first payload byte                 |
| `0x0071` | seq_end          | u64        | Record (TCP)             | offset one past the last payload byte                          |
| `0x0072` | ack              | u64        | Record (TCP)             | highest peer-stream offset the sender had received when sent   |
| `0x0073` | ts_first         | i64        | Record                   | optional packet time of the *first* contributing packet        |
| `0x0080` | capture_spans    | span-list  | Record (raw provenance)  | byte ranges in the source capture these bytes came from        |
| `0x0090` | decoder_id       | u16        | Record, Gap (decoded)    | which Decoder Descriptor produced this record/gap              |
| `0x0091` | derive_spans     | span-list  | Record (decoded prov.)   | source stream ranges this decoded record was built from        |
| `0x00A0` | reason           | string     | Gap                      | why the region is uncovered (`undecodable`/`tcp-gap`/…)        |
| `0x00B0` | label            | string     | Name/Identity Resolution | the human-readable name being assigned                         |
| `0x00B1` | kind             | string     | Name/Identity Resolution | source/kind of the label (`nick`/`dns`/`tls-sni`)              |

A **span-list** value is `count` packed entries, each 24 bytes:
`input_id: u16, session_id: u32, pid: u16, off_start: u64, off_end: u64`
(`count = len / 24`). `capture_spans` instead references source-capture byte
ranges; entries use the same 24-byte shape with `input_id` naming a Source.

### Enums

`boundary` (Record body, u8): `0` = byte run, `1` = protocol message.

`dec_boundary` (Decoder option, u8): `0` = byte-run / raw fallback,
`1` = protocol-message, `2` = record-layer (e.g. TLS records).

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
| `0x0020` | a decoded view exists for these bytes in some derived file|
| `0x0040` | retransmission/overlap was resolved inside this record   |
| `0x0080` | datagram boundary (UDP: record is exactly one datagram)  |
| `0xFF00` | reserved, MUST be 0                                      |

### Identifiers & ordering

- `session_id` and `source_id`/`decoder_id`/`input_id` are unique within a
  file. `participant_id` is scoped to its session. Ids MUST NOT be reused.
- On-disk block order is unconstrained beyond declare-on-first-use; in
  particular a participant's records need **not** be stored in `seq_start`
  order — the [merge algorithm](#merge-algorithm) sorts them. Within one source,
  records SHOULD be emitted in capture order to keep the timestamp tie-breaker
  meaningful.

### Conformance

A **raw** file MUST: start with one File Header; declare each Source, Session,
and Participant before any block references it; contain **no** Derivation,
Decoder, or Gap blocks. TCP participants SHOULD carry `isn`; TCP records SHOULD
carry `seq_start`/`seq_end` (and `ack` where known). UDP records SHOULD set the
datagram-boundary flag.

A **derived** file MUST: contain ≥1 Derivation and every Decoder it references;
give each record a `derive_spans` (or inherit the file's primary `decoder_id`);
state uncovered regions as Gap blocks rather than dropping them.

Readers MUST skip unknown block types (via frame `length`) and unknown option
ids (via `len`), and MUST treat reserved fields/bits as ignored-on-read.

### Truncation

There is no global trailer — the format is forward-only and streamable. A reader
that finds fewer than `length` bytes remaining for a block MUST treat the file
as **truncated at that block** (a writer crash mid-flush) and discard the
partial tail; all complete prior blocks remain valid. Detecting *intentional*
completeness (vs. truncation) requires the optional index discussed in
[Open questions](#open-questions).

### JSONL ↔ binary field mapping

The JSON-Lines projection (above) is lossless for the fields below; the
`type` string selects the block. Names differ where JSONL favours brevity:

| JSONL key            | Binary field / option        |
|----------------------|------------------------------|
| `format`             | `version_major.version_minor`|
| `time_units`         | `tick_hz`                    |
| `ts`                 | Record `timestamp`           |
| `pid`                | Participant `participant_id` |
| `proto`, `key`       | `proto`, `flow_key` options  |
| `spans`              | `derive_spans` / `capture_spans` |
| `payload` (base64)   | `payload` (raw bytes)        |

`payload` uses **standard** base64 (RFC 4648 §4, with `=` padding) in JSONL.
Options not in this table round-trip through a generic `options` array so the
converter stays lossless.

### Worked example: a minimal raw file

A complete, conformant **raw** `.zpf` file (194 bytes, **little-endian**) holding
one TCP session with one declared participant and one record — the client's
`GET / HTTP/1.1\r\n\r\n` from the [JSONL example](#json-lines-projection)
(`session_id 7`, `pid 0`, `ts 1000`, `seq [1,19)`, `ack 1`). Offsets are hex;
each line is annotated.

```text
# ── File Header (0x01) ──────────────────────────────────────────────
0000  01 00                    type   = 0x0001  File Header
0002  10 00 00 00              length = 16
0006  46 50 49 5A              bom    = 0x5A495046  ("ZIPF", LE on disk)
000A  01 00                    version_major = 1
000C  00 00                    version_minor = 0
000E  40 42 0F 00 00 00 00 00  tick_hz = 1_000_000  (microseconds)

# ── Source Descriptor (0x02) ────────────────────────────────────────
0016  02 00                    type   = 0x0002  Source Descriptor
0018  14 00 00 00              length = 20
001C  01 00                    source_id = 1
001E  00 00                    _reserved
0020  20 00 0A 00              option 0x0020 uri, len = 10
0024  73 69 64 65 41 2E 70 63  "sideA.pc
002C  61 70                     ap"
002E  00 00                    value padding → 4-byte boundary

# ── Session Descriptor (0x10) ───────────────────────────────────────
0030  10 00                    type   = 0x0010  Session Descriptor
0032  0C 00 00 00              length = 12
0036  07 00 00 00              session_id = 7
003A  50 00 03 00              option 0x0050 proto, len = 3
003E  74 63 70                 "tcp"
0041  00                       value padding

# ── Participant Descriptor (0x11) ───────────────────────────────────
0042  11 00                    type   = 0x0011  Participant Descriptor
0044  24 00 00 00              length = 36
0048  07 00 00 00              session_id = 7
004C  00 00                    participant_id = 0
004E  00 00                    _reserved
0050  60 00 0E 00              option 0x0060 endpoint, len = 14
0054  31 30 2E 30 2E 30 2E 31  "10.0.0.1
005C  3A 35 31 30 30 30        :51000"
0062  00 00                    value padding
0064  61 00 04 00              option 0x0061 isn, len = 4
0068  E8 03 00 00              isn = 1000

# ── Record (0x20) ───────────────────────────────────────────────────
006C  20 00                    type   = 0x0020  Record
006E  50 00 00 00              length = 80
0072  07 00 00 00              session_id = 7
0076  00 00                    sender_pid = 0
0078  01 00                    source_id  = 1
007A  E8 03 00 00 00 00 00 00  timestamp  = 1000
0082  01                       boundary   = 1  (protocol message)
0083  00                       _reserved
0084  01 00                    flags      = 0x0001  (PSH seen)
0086  12 00 00 00              payload_len = 18
008A  47 45 54 20 2F 20 48 54  "GET / HT
0092  54 50 2F 31 2E 31 0D 0A  TP/1.1\r\n
009A  0D 0A                    \r\n"
009C  00 00                    payload padding → 4-byte boundary
009E  70 00 08 00              option 0x0070 seq_start, len = 8
00A2  01 00 00 00 00 00 00 00  seq_start = 1
00AA  71 00 08 00              option 0x0071 seq_end, len = 8
00AE  13 00 00 00 00 00 00 00  seq_end = 19
00B6  72 00 08 00              option 0x0072 ack, len = 8
00BA  01 00 00 00 00 00 00 00  ack = 1
00C2                           (end of file, 194 bytes)
```

Things to read off it: the BOM resolves endianness; `length` jumps a reader from
each block to the next (`0x0006 + 16 = 0x0016`, `… + 20 = 0x0030`, …); the
`GET` payload is 18 bytes but is padded to 20 so the option stream resumes on a
4-byte boundary; and the record references `session_id 7` / `sender_pid 0` /
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
- Should a Derivation reference a whole input file, or also pin a per-session
  digest, so a single changed session forces re-derivation of only that session?
- Do decoded records keep their own packet-time `ts` (copied from the spanning
  raw bytes), or only the derivation `produced_at`? Probably both: `ts` for
  ordering, `produced_at` for provenance.
