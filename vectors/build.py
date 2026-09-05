#!/usr/bin/env python3
"""Build the Zipline Payload Format conformance vectors.

Hand-written from docs/zipline-payload-format.md. This is NOT a reader or a
writer for the format, and no vector here is produced by round-tripping through
an implementation -- see README.md for why that distinction is the whole point.

Every block is spelled out field by field, with an annotation per field. The
binary and the annotated hex dump come from that one description, so the dump
can never drift from the bytes. The expected JSONL is written separately, by
hand, so that the two faces of each vector are independent statements about the
same file rather than derivations of one another.

Usage:  python3 build.py          # regenerate every vector
        python3 build.py --check  # verify the tree matches (no writes)
"""

import base64
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def read_bytes(path: str) -> bytes:
    """Read a file whole, in binary."""
    with open(path, "rb") as f:
        return f.read()


def read_text(path: str) -> str:
    """Read a file whole, as UTF-8 text."""
    with open(path, encoding="utf-8") as f:
        return f.read()


# The version this tree stamps. Every vector's File Header, every JSONL `format`
# string and the manifest read these, so a version bump is a one-line change and
# no site can be missed.
MAJOR, MINOR = 0, 19
FORMAT = f"zipline-payload/{MAJOR}.{MINOR}"

# ---------------------------------------------------------------- primitives


def u8(v: int) -> bytes:
    return struct.pack("<B", v)


def u16(v: int) -> bytes:
    return struct.pack("<H", v)


def u32(v: int) -> bytes:
    return struct.pack("<I", v)


def u64(v: int) -> bytes:
    return struct.pack("<Q", v)


def i64(v: int) -> bytes:
    return struct.pack("<q", v)


def pad4(n: int) -> int:
    """Bytes of padding needed to reach a 4-byte boundary."""
    return (-n) % 4


# A "piece" is (bytes, annotation). Annotation "" means it is padding or a
# continuation line and needs no separate explanation.
Piece = tuple[bytes, str]
Opt = list[Piece]  # what an o_*() helper returns
Blk = list[Piece]  # what a block builder returns


def P(b: bytes, ann: str = "") -> Piece:
    return (b, ann)


def option(oid: int, value: bytes, name: str, note: str = "") -> Opt:
    """TLV option: id u16, len u16, value, padded to a 4-byte boundary.

    len counts the value only, never the 4-byte option header or the padding.
    """
    ann = f"option 0x{oid:04X} {name}, len = {len(value)}"
    if note:
        ann += f"  ({note})"
    out = [P(u16(oid) + u16(len(value)), ann)]
    if value:
        out.append(P(value, _describe(value)))
    pad = pad4(4 + len(value))
    if pad:
        out.append(P(b"\x00" * pad, "value padding"))
    return out


def _describe(value: bytes) -> str:
    try:
        s = value.decode("ascii")
        if s.isprintable():
            return f'"{s}"'
    except UnicodeDecodeError:
        pass
    return ""


def block(
    btype: int, name: str, body: list[Piece], options: tuple[Opt, ...] | list[Opt] = ()
) -> Blk:
    """Frame a block: type u16, reserved u16, length u32, then content.

    length counts body + options + padding -- everything after the length
    field -- and is always a multiple of 4.
    """
    content = []
    for p in body:
        content.append(p)
    for opt in options:
        content.extend(opt)
    size = sum(len(b) for b, _ in content)
    pad = pad4(size)
    if pad:
        content.append(P(b"\x00" * pad, "content padding"))
        size += pad
    head = [
        P(u16(btype), f"type   = 0x{btype:04X}  {name}"),
        P(u16(0), "reserved"),
        P(u32(size), f"length = {size}"),
    ]
    return head + content


# --------------------------------------------------------------- block kinds


def file_header(
    tick_hz: int = 1_000_000,
    major: int = MAJOR,
    minor: int = MINOR,
    options: tuple[Opt, ...] | list[Opt] = (),
    magic: int = 0x5A495046,
) -> Blk:
    body = [
        P(u32(magic), f'magic  = 0x{magic:08X}  ("ZIPF")'),
        P(u16(major), f"version_major = {major}"),
        P(u16(minor), f"version_minor = {minor}"),
        P(u64(tick_hz), f"tick_hz = {tick_hz:_}"),
    ]
    return block(0x01, "File Header", body, options)


def source(source_id: int, kind: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    kind_name = {0: "capture", 1: "zpf-input"}.get(kind, "UNDEFINED")
    body = [
        P(u16(source_id), f"source_id = {source_id}"),
        P(u8(kind), f"kind = {kind}  ({kind_name})"),
        P(u8(0), "_reserved"),
    ]
    return block(0x02, "Source Descriptor", body, options)


_LAYER = {0: "decoded", 1: "transport"}


def decoder(
    decoder_id: int, options: tuple[Opt, ...] | list[Opt] = (), output_layer: int = 0
) -> Blk:
    """Build a Decoder Descriptor (0x03).

    output_layer is a BODY field, not an option: 0 = decoded, 1 = transport.
    Numbering decoded 0 is what makes it fit the old _reserved u16 without
    changing a byte of any file written before it existed -- every one of those
    holds 0 there, and every one of them meant decoded.
    """
    body = [
        P(u16(decoder_id), f"decoder_id = {decoder_id}"),
        P(u8(output_layer), f"output_layer = {output_layer}  ({_LAYER.get(output_layer, '?')})"),
        P(u8(0), "_reserved"),
    ]
    return block(0x03, "Decoder Descriptor", body, options)


def session(session_id: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    body = [P(u64(session_id), f"session_id = {session_id}  (u64)")]
    return block(0x10, "Session Descriptor", body, options)


def session_end(session_id: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    body = [P(u64(session_id), f"session_id = {session_id}  (u64)")]
    return block(0x12, "Session End", body, options)


def participant(session_id: int, pid: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    body = [
        P(u64(session_id), f"session_id = {session_id}  (u64)"),
        P(u16(pid), f"participant_id = {pid}"),
        P(u16(0), "_reserved"),
    ]
    return block(0x11, "Participant Descriptor", body, options)


def record(
    session_id: int,
    sender_pid: int,
    source_id: int,
    timestamp: int,
    payload: bytes,
    flags: int = 0,
    options: tuple[Opt, ...] | list[Opt] = (),
    payload_len: int | None = None,
) -> Blk:
    """Build a Record block.

    payload_len defaults to len(payload); override it to build a deliberately
    corrupt vector.
    """
    declared = len(payload) if payload_len is None else payload_len
    body = [
        P(u64(session_id), f"session_id = {session_id}  (u64)"),
        P(u16(sender_pid), f"sender_pid = {sender_pid}"),
        P(u16(source_id), f"source_id  = {source_id}"),
        P(i64(timestamp), f"timestamp  = {timestamp}"),
        P(u16(0), "_reserved  (u16 = 0)"),
        P(u16(flags), f"flags      = 0x{flags:04X}"),
        P(u32(declared), f"payload_len = {declared}"),
    ]
    if payload:
        body.append(P(payload, _describe(payload)))
        pad = pad4(len(payload))
        if pad:
            body.append(P(b"\x00" * pad, "payload padding"))
    return block(0x20, "Record", body, options)


def undecoded(
    source_id: int,
    pid: int,
    session_id: int,
    off_start: int,
    off_end: int,
    options: tuple[Opt, ...] | list[Opt] = (),
    capture: bool = False,
) -> Blk:
    """Build an Undecoded (0x21) block.

    `capture` says the referenced Source is a capture, which changes what every
    remaining field MEANS: the ids are unused and the offsets are byte offsets
    into the capture file rather than logical stream offsets. The annotation used
    to say "in the input's namespace" unconditionally, which was wrong on exactly
    the one vector where a reader most needed it right (#87).
    """
    if capture and (pid or session_id):
        raise ValueError("against a capture source the ids are unused and MUST be 0")
    where = "the capture file" if capture else "the input's namespace"
    body = [
        P(u16(source_id), f"source_id = {source_id}  (in {where})"),
        P(u16(pid), f"participant_id = {pid}" + ("  (unused)" if capture else "")),
        P(u64(session_id), f"session_id = {session_id}" + ("  (unused)" if capture else "")),
        P(
            u64(off_start),
            f"off_start = {off_start}" + ("  (capture byte offset)" if capture else ""),
        ),
        P(u64(off_end), f"off_end   = {off_end}" + ("  (capture byte offset)" if capture else "")),
    ]
    return block(0x21, "Undecoded", body, options)


def discontinuity(session_id: int, pid: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    """Build a Discontinuity (0x22) block.

    A break in THIS file's own output stream. Note the ids are this file's,
    unlike Undecoded's, which are the input's.
    """
    body = [
        P(u64(session_id), f"session_id = {session_id}  (in THIS file)"),
        P(u16(pid), f"participant_id = {pid}  (in THIS file)"),
        P(u16(0), "_reserved"),
    ]
    return block(0x22, "Discontinuity", body, options)


def name_block(session_id: int, pid: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    body = [
        P(u64(session_id), f"session_id = {session_id}"),
        P(u16(pid), f"participant_id = {pid}"),
        P(u16(0), "_reserved"),
    ]
    return block(0x30, "Name/Identity Resolution", body, options)


def custom(pen: int, subtype: int, payload: bytes) -> Blk:
    """Build a Custom (0xFF) vendor block.

    Recognised, not unknown: a reader without knowledge of pen/subtype skips it
    by length, but a converter still projects it as `custom` rather than through
    the unknown-block escape.
    """
    body = [
        P(u32(pen), f"pen = {pen}  (IANA Private Enterprise Number)"),
        P(u16(subtype), f"subtype = {subtype}  (vendor-defined)"),
        P(u16(0), "_reserved"),
        P(payload, _describe(payload)),
    ]
    return block(0xFF, "Custom", body)


def end_block() -> Blk:
    body = [P(u32(0x5A454E44), 'end_magic = 0x5A454E44  ("ZEND")')]
    return block(0x41, "End of file", body)


def unknown_block(btype: int, content_bytes: bytes) -> Blk:
    """Build a block of a type this document does not define.

    The forward-compatibility case a reader must skip by length.
    """
    return block(btype, "UNKNOWN to this version", [P(content_bytes, "opaque content")])


# ------------------------------------------------------------ option helpers


def s(x: str) -> bytes:
    return x.encode("utf-8")


def o_comment(v: str) -> Opt:
    return option(0x0001, s(v), "comment")


def o_creator(v: str) -> Opt:
    return option(0x0011, s(v), "creator")


def o_produced_by(v: str) -> Opt:
    return option(0x0012, s(v), "produced_by")


def o_produced_at(v: str) -> Opt:
    return option(0x0013, i64(v), "produced_at", str(v))


def o_file_flags(v: str) -> Opt:
    return option(0x0014, u16(v), "flags", f"0x{v:04X}")


def o_transform_params_digest(v: str) -> Opt:
    return option(0x0015, s(v), "transform_params_digest")


def o_uri(v: str) -> Opt:
    return option(0x0020, s(v), "uri")


def o_digest(v: str) -> Opt:
    return option(0x0021, s(v), "digest")


def o_dec_name(v: str) -> Opt:
    return option(0x0041, s(v), "name")


def o_dec_version(v: str) -> Opt:
    return option(0x0042, s(v), "version")


def o_params_digest(v: str) -> Opt:
    return option(0x0043, s(v), "params_digest")


def o_proto(v: str) -> Opt:
    return option(0x0050, s(v), "proto")


def o_flow_key(v: str) -> Opt:
    return option(0x0051, s(v), "flow_key")


def o_sess_flags(v: str) -> Opt:
    return option(0x0052, u16(v), "flags", f"0x{v:04X}")


def o_seq_basis(v: str) -> Opt:
    return option(0x0053, s(v), "sequenced_basis")


def o_external_sid(v: str) -> Opt:
    return option(0x0054, v, "external_session_id", f"{len(v)} opaque bytes")


def o_endpoint(v: str) -> Opt:
    return option(0x0060, s(v), "endpoint")


def o_time_epoch(v: str) -> Opt:
    return option(0x0010, i64(v), "time_epoch", str(v))


def o_link_type(v: str) -> Opt:
    return option(0x0022, u16(v), "link_type", str(v))


def o_identity(v: str) -> Opt:
    return option(0x0062, s(v), "identity")


def o_ts_first(v: str) -> Opt:
    return option(0x0073, i64(v), "ts_first", str(v))


def o_isn(v: str) -> Opt:
    return option(0x0061, u32(v), "isn", str(v))


def o_tcp_role(v: str) -> Opt:
    return option(0x0063, u8(v), "tcp_role", str(v))


def o_origin(src: int, pid: int, sess: int) -> Opt:
    return option(
        0x0064,
        u16(src) + u16(pid) + u64(sess),
        "origin",
        f"source {src}, pid {pid}, session {sess}",
    )


def o_seq_start(v: str) -> Opt:
    return option(0x0070, u32(v), "seq_start", str(v))


def o_ack(v: str) -> Opt:
    return option(0x0072, u32(v), "ack", str(v))


def o_spans(entries: list[tuple[int, int, int, int, int]]) -> Opt:
    packed = b"".join(
        u16(sr) + u16(pid) + u64(se) + u64(a) + u64(b) for sr, pid, se, a, b in entries
    )
    return option(0x0080, packed, "spans", f"{len(entries)} entry/entries")


def o_decoder_id(v: str) -> Opt:
    return option(0x0090, u16(v), "decoder_id", str(v))


def o_content_type(v: str) -> Opt:
    return option(0x0091, s(v), "content_type")


def o_role(v: str) -> Opt:
    return option(0x0092, s(v), "role")


def o_reason(v: str) -> Opt:
    return option(0x00A0, s(v), "reason")


def o_reason_class(v: str) -> Opt:
    return option(0x00A1, s(v), "reason_class")


def o_end_reason(v: str) -> Opt:
    return option(0x00C0, s(v), "reason")


def o_input_extents(entries: list[tuple[int, int, int, int]]) -> Opt:
    packed = b"".join(u16(src) + u16(pid) + u64(sess) + u64(ext) for src, pid, sess, ext in entries)
    return option(0x00C1, packed, "input_extents", f"{len(entries)} entry/entries")


def o_width(v: str) -> Opt:
    return option(0x00D0, u64(v), "width", str(v))


def o_disc_reason(v: str) -> Opt:
    return option(0x00D1, s(v), "reason")


def o_label(v: str) -> Opt:
    return option(0x00B0, s(v), "label")


def o_name_kind(v: str) -> Opt:
    return option(0x00B1, s(v), "kind")


def o_unregistered(oid: int, v: bytes) -> Opt:
    return option(oid, v, "UNREGISTERED")


# ------------------------------------------------------------------- vectors

GET = b"GET / HTTP/1.1\r\n\r\n"


def b64(x: bytes) -> str:
    return base64.b64encode(x).decode("ascii")


VECTORS = []


def vector(
    name: str,
    tier: str,
    summary: str,
    spec: str,
    blocks: list[Blk],
    jsonl: list[dict] | None = None,
    expect: str | None = None,
    *,
    violations: int,
    advisory: bool = False,
) -> None:
    """Register a vector.

    `violations` is keyword-only and has NO default, deliberately: a negative
    vector must carry exactly one violation, and the only way to keep that true
    is to make every author state the number. Omitting it is a TypeError, so
    build.py will not run at all -- which is a better moment to find out than a
    downstream port. check.py then verifies the declared count against the
    declared tier; nothing here or there inspects the file to count them, because
    a checker that ruled on semantics would become a second normative authority.

    `advisory` marks the accept-tier case where the file breaks a rule and a
    reader accepts it anyway, having reported it -- 0.16's content_type at the
    transport layer. Such a vector declares 1 violation, not 0. It is a flag on
    accept rather than a fourth tier because a tier names what a READER does, and
    a reader accepts these completely.
    """
    if advisory and tier != "accept":
        raise ValueError(f"{name}: advisory is meaningless off the accept tier")
    VECTORS.append(
        {
            "name": name,
            "tier": tier,
            "summary": summary,
            "spec": spec,
            "blocks": blocks,
            "jsonl": jsonl,
            "expect": expect,
            "violations": violations,
            "advisory": advisory,
        }
    )


# --- baseline -------------------------------------------------------------

vector(
    "raw-minimal",
    "accept",
    "The minimal conformant capture-sourced file: one TCP session, one "
    "participant, one record. Byte-for-byte the worked example in the "
    "specification. The vector's NAME keeps the retired word because external "
    "harnesses reference it; the file is a capture-sourced transport stream.",
    "Worked example: a minimal capture-sourced file",
    [
        file_header(),
        source(1, 0, [o_uri("sideA.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(7, 0, 1, 1000, GET, flags=0x0001, options=[o_seq_start(1001), o_ack(5001)]),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "sideA.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "flags": ["psh"],
            "payload": b64(GET),
            "seq_start": 1001,
            "ack": 5001,
        },
    ],
    violations=0,
)

vector(
    "decoded-basic",
    "accept",
    "A decode stage's output: decoded records citing spans in the input, plus "
    "an Undecoded block covering the tail the decoder could not parse. Its "
    "Session End declares input_extents, so the coverage guarantee is "
    "checkable from this file alone -- spans plus Undecoded meet the declared "
    "length of each input stream exactly. Also the suite's only Session End.",
    "A decoded file, end to end",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719500000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4"), o_params_digest("sha256:00ab")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        record(
            7,
            0,
            1,
            1000,
            b"REQ",
            options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 18)]), o_content_type("dec:request")],
        ),
        record(
            7,
            1,
            1,
            995,
            b"RESP",
            options=[o_decoder_id(1), o_spans([(1, 1, 7, 0, 100)]), o_content_type("dec:response")],
        ),
        undecoded(1, 1, 7, 100, 139, [o_reason("undecodable"), o_decoder_id(1)]),
        # Extents make the coverage guarantee checkable from this file alone:
        # pid 0 spans [0,18), pid 1 spans [0,100) + undecoded [100,139).
        session_end(7, [o_end_reason("fin"), o_input_extents([(1, 0, 7, 18), (1, 1, 7, 139)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-decode 0.4",
            "produced_at": 1719500000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "raw.zpf",
            "digest": "sha256:9f2c",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "http/1.1",
            "version": "0.4",
            "params_digest": "sha256:00ab",
        },
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {"type": "participant", "session_id": 7, "pid": 1, "endpoint": ["93.184.216.34:80"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"REQ"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 18}],
            "content_type": "dec:request",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 995,
            "payload": b64(b"RESP"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 1, "off_start": 0, "off_end": 100}],
            "content_type": "dec:response",
        },
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 7,
            "pid": 1,
            "off_start": 100,
            "off_end": 139,
            "reason": "undecodable",
            "decoder_id": 1,
        },
        {
            "type": "session_end",
            "session_id": 7,
            "reason": "fin",
            "input_extents": [
                {"source_id": 1, "session_id": 7, "pid": 0, "extent": 18},
                {"source_id": 1, "session_id": 7, "pid": 1, "extent": 139},
            ],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "decoded-field-roles",
    "accept",
    "One record per protocol FIELD, each named by 0.17's role. The case #107 "
    "was filed for, and deliberately the case with none of the confounders: "
    "four u32 fields, contiguous, non-overlapping, in stored order, each a "
    "token in the closed prim: vocabulary with payload_len binding exactly, "
    "and the decoded stream is a well-defined 16 bytes. "
    "WHAT ROLE ADDS: before it, this file could carry the TYPE or the NAME and "
    "not both. content_type = prim:u32 leaves a generic reader able to read "
    "every value and unable to tell which field is the checksum; dec:checksum "
    "names it and throws away the normative typing, and makes dec:checksum and "
    "dec:seq_no two distinct types that happen both to be u32. Position is not "
    "a contract either -- an optional field the decoder later emits renumbers "
    "everything after it. The two options are INDEPENDENT, and every record "
    "here carries both. "
    "SCOPE: role is read in the namespace of the decoder name that decoder_id "
    "resolves to, exactly as a dec: token is, so another decoder's `checksum` "
    "is a different name. It is opaque to the format: it names a record and "
    "asserts no tree. "
    "Session End declares input_extents, so the coverage guarantee is "
    "checkable from this file alone -- four spans, [0,16), meeting the "
    "declared extent exactly.",
    "Typing a decoded record -- a type is not a name",
    [
        file_header(options=[o_produced_by("zpf-fielddecode 0.1"), o_produced_at(1719800000)]),
        source(1, 1, [o_uri("frames.zpf"), o_digest("sha256:5e7a")]),
        decoder(1, [o_dec_name("acme-hdr"), o_dec_version("2.0")]),
        session(31, [o_proto("acme")]),
        participant(31, 0, [o_endpoint("10.0.0.1:9000")]),
        record(
            31,
            0,
            1,
            1000,
            struct.pack("<I", 1),
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 30, 0, 4)]),
                o_content_type("prim:u32"),
                o_role("version"),
            ],
        ),
        record(
            31,
            0,
            1,
            1000,
            struct.pack("<I", 16),
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 30, 4, 8)]),
                o_content_type("prim:u32"),
                o_role("length"),
            ],
        ),
        # The record the whole issue is about: without a role, nothing in the
        # file says THIS is the checksum -- and its type says only prim:u32,
        # which is also what the other three say.
        record(
            31,
            0,
            1,
            1000,
            struct.pack("<I", 0xDEADBEEF),
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 30, 8, 12)]),
                o_content_type("prim:u32"),
                o_role("checksum"),
            ],
        ),
        record(
            31,
            0,
            1,
            1000,
            struct.pack("<I", 42),
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 30, 12, 16)]),
                o_content_type("prim:u32"),
                o_role("seq_no"),
            ],
        ),
        session_end(31, [o_input_extents([(1, 0, 30, 16)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-fielddecode 0.1",
            "produced_at": 1719800000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "frames.zpf",
            "digest": "sha256:5e7a",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "acme-hdr",
            "version": "2.0",
        },
        {"type": "session", "session_id": 31, "proto": "acme"},
        {"type": "participant", "session_id": 31, "pid": 0, "endpoint": ["10.0.0.1:9000"]},
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(struct.pack("<I", 1)),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 0, "off_end": 4}],
            "content_type": "prim:u32",
            "role": "version",
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(struct.pack("<I", 16)),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 4, "off_end": 8}],
            "content_type": "prim:u32",
            "role": "length",
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(struct.pack("<I", 0xDEADBEEF)),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 8, "off_end": 12}],
            "content_type": "prim:u32",
            "role": "checksum",
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(struct.pack("<I", 42)),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 12, "off_end": 16}],
            "content_type": "prim:u32",
            "role": "seq_no",
        },
        {
            "type": "session_end",
            "session_id": 31,
            "input_extents": [
                {"source_id": 1, "session_id": 30, "pid": 0, "extent": 16},
            ],
        },
        {"type": "end"},
    ],
    violations=0,
)


# --- the four escapes ------------------------------------------------------

vector(
    "escape-unknown-block",
    "accept",
    "A block of an undefined type. A reader MUST skip it by length and carry "
    "on; a converter projects it as a hex type plus its whole content in base64.",
    "Unrecognised data: the four escapes",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        unknown_block(0x0042, b"\xde\xad\xbe\xef\x01\x02\x03\x04"),
        session(7, [o_proto("tcp")]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "c.pcap"},
        {"type": "0x0042", "content": b64(b"\xde\xad\xbe\xef\x01\x02\x03\x04")},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "escape-unknown-option",
    "accept",
    "A record carrying an unregistered option id. A reader MUST skip it by len "
    "and retain it; a converter projects it into the generic options array.",
    "Unrecognised data: the four escapes",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"hi", options=[o_unregistered(0x0200, b"\xaa\xbb")]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "c.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"hi"),
            "options": [{"id": "0x0200", "value": b64(b"\xaa\xbb")}],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "escape-unknown-enum",
    "accept",
    "A participant whose tcp_role holds an undefined value. tcp_role is "
    "advisory, so this is not a violation: it renders as the raw number.",
    "Unrecognised enum values",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_tcp_role(7)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "c.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "tcp_role": 7,
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "escape-reserved-flag-bit",
    "accept",
    "A record with a reserved flags bit set. A reader MUST ignore it "
    "semantically but preserve it; a converter renders it as a hex token.",
    "Unrecognised data: the four escapes",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"hi", flags=0x0021),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "c.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "flags": ["psh", "0x0020"],
            "payload": b64(b"hi"),
        },
        {"type": "end"},
    ],
    violations=0,
)

# --- 0.10 constructs -------------------------------------------------------


vector(
    "broken-chain",
    "accept",
    "The provenance walk that FAILS. This file is conformant and reads fine on "
    "its own -- what is absent is its input: missing.zpf is not in the tree and "
    "never was. Its Undecoded block is the bytes-exist class, so it promises a "
    "consumer MAY follow the reference and fetch those bytes; the walk hits the "
    "first hop and cannot. The two outcomes a consumer MUST NOT report "
    "identically are 'no bytes exist' (chain resolved, region genuinely empty) "
    "and 'bytes unavailable' (chain broke). chain/ tests the walk that "
    "succeeds; this tests the one that does not.",
    "Undecoded (0x21) -- Recovering the bytes",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719600000)]),
        # The digest is real for a file that is simply not here. A consumer
        # cannot verify it, and MUST NOT conclude anything from that.
        source(1, 1, [o_uri("missing.zpf"), o_digest("sha256:d1e5")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            7,
            0,
            1,
            1000,
            b"REQ",
            options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 18)]), o_content_type("dec:request")],
        ),
        undecoded(1, 0, 7, 18, 60, [o_reason("undecodable"), o_decoder_id(1)]),
        session_end(7, [o_input_extents([(1, 0, 7, 60)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-decode 0.4",
            "produced_at": 1719600000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "missing.zpf",
            "digest": "sha256:d1e5",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "http/1.1",
            "version": "0.4",
        },
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"REQ"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 18}],
            "content_type": "dec:request",
        },
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 7,
            "pid": 0,
            "off_start": 18,
            "off_end": 60,
            "reason": "undecodable",
            "decoder_id": 1,
        },
        {
            "type": "session_end",
            "session_id": 7,
            "input_extents": [{"source_id": 1, "session_id": 7, "pid": 0, "extent": 60}],
        },
        {"type": "end"},
    ],
    expect="ACCEPT the file and produce the .jsonl projection -- it is "
    "conformant, and a decoded file stands alone for its decoded "
    "content. The test is what happens NEXT, if a consumer chooses to "
    "recover the undecoded region's bytes: the walk resolves source_id "
    "1 to missing.zpf, which is not there, so it MUST report the region "
    "as BYTES UNAVAILABLE and MUST NOT report it as empty or as a hole. "
    "Reporting 'no bytes here' asserts something the consumer never "
    "established, and is the silent data loss the coverage guarantee "
    "exists to prevent. A reader that never walks provenance passes "
    "this vector trivially and has tested nothing -- the distinction is "
    "only observable in a consumer that recovers bytes.",
    violations=0,
)

vector(
    "undecoded-skipped",
    "accept",
    "A decode stage that deliberately declines a region -- a byte-order mark -- "
    "and says so with reason = skipped rather than claiming a parse failure. "
    "It is also the case that must NOT carry a Discontinuity: a discarded BOM "
    "withholds no content, so the text either side joins and the origination "
    "duty is not triggered. A rule keyed on unspanned input bytes would demand "
    "a block here and it would be a lie.",
    "Undecoded (0x21)",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719540000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("text/utf8"), o_dec_version("1.0")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        undecoded(1, 0, 7, 0, 3, [o_reason("skipped"), o_decoder_id(1), o_comment("UTF-8 BOM")]),
        record(7, 0, 1, 1000, b"body", options=[o_decoder_id(1), o_spans([(1, 0, 7, 3, 7)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-decode 0.4",
            "produced_at": 1719540000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "raw.zpf",
            "digest": "sha256:9f2c",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "text/utf8",
            "version": "1.0",
        },
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 7,
            "pid": 0,
            "off_start": 0,
            "off_end": 3,
            "reason": "skipped",
            "decoder_id": 1,
            "comment": "UTF-8 BOM",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"body"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 3, "off_end": 7}],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "undecoded-reason-class",
    "accept",
    "A non-canonical reason, which MUST carry reason_class so a consumer can "
    "still tell whether the bytes exist upstream.",
    "Undecoded (0x21)",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719550000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("http/1.1")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        undecoded(
            1, 0, 7, 0, 40, [o_reason("rtp-seq-gap"), o_reason_class("hole"), o_decoder_id(1)]
        ),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-decode 0.4",
            "produced_at": 1719550000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "raw.zpf",
            "digest": "sha256:9f2c",
        },
        {"type": "decoder", "decoder_id": 1, "output_layer": "decoded", "name": "http/1.1"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 7,
            "pid": 0,
            "off_start": 0,
            "off_end": 40,
            "reason": "rtp-seq-gap",
            "reason_class": "hole",
            "decoder_id": 1,
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "discontinuity-unknown-width",
    "accept",
    "Finding 3's stage 1: a tls-records decoder that lost one TCP segment. The "
    "plaintext length the lost ciphertext would have produced is unknowable, so "
    "the Discontinuity carries NO width and contributes 0 to the positional "
    "arithmetic -- output offsets stay [0,50) and [50,80). The block's job is "
    "to say those two records DO NOT JOIN. Without it they are simply adjacent "
    "and a downstream decoder splices them silently -- which is exactly "
    "isolate-unmarked-break, this file with the block deleted. The two are a "
    "pair: same stage, same loss, one declaring the break its output has and "
    "one not.",
    "Discontinuity (0x22)",
    [
        file_header(options=[o_produced_by("zpf-tls 0.2"), o_produced_at(1719580000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("tls-records"), o_dec_version("0.2")]),
        session(7, [o_proto("tls")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"A" * 50, options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 100)])]),
        # The input-side loss and the output-side break are two statements.
        undecoded(1, 0, 7, 100, 139, [o_reason("gap"), o_decoder_id(1)]),
        discontinuity(7, 0, [o_disc_reason("tls-record-lost")]),
        record(7, 0, 1, 1100, b"B" * 30, options=[o_decoder_id(1), o_spans([(1, 0, 7, 139, 200)])]),
        session_end(7, [o_input_extents([(1, 0, 7, 200)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-tls 0.2",
            "produced_at": 1719580000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "raw.zpf",
            "digest": "sha256:9f2c",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "tls-records",
            "version": "0.2",
        },
        {"type": "session", "session_id": 7, "proto": "tls"},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"A" * 50),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 100}],
        },
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 7,
            "pid": 0,
            "off_start": 100,
            "off_end": 139,
            "reason": "gap",
            "decoder_id": 1,
        },
        {"type": "discontinuity", "session_id": 7, "pid": 0, "reason": "tls-record-lost"},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1100,
            "payload": b64(b"B" * 30),
            "decoder_id": 1,
            "spans": [
                {"source_id": 1, "session_id": 7, "pid": 0, "off_start": 139, "off_end": 200}
            ],
        },
        {
            "type": "session_end",
            "session_id": 7,
            "input_extents": [{"source_id": 1, "session_id": 7, "pid": 0, "extent": 200}],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "session-fan-out",
    "accept",
    "ONE input participant stream demultiplexed into TWO output sessions -- the "
    "capability 0.13 clarified and nothing exercised. A decrypt-and-demux stage: "
    "the ciphertext record at [0,80) carries framing that feeds an inner unit in "
    "EACH session, so both sessions' records span it and the spans OVERLAP. That "
    "is legal since 0.14: coverage requires every offset to be covered at least "
    "once, not exactly once, and both units genuinely needed that record's nonce "
    "and tag to exist. [80,140) is session 100's alone and [140,200) is session "
    "101's, so NEITHER session covers the extent 200 it declares -- only the "
    "union across both does. A checker that accumulates coverage per output "
    "session fails here and passes every other vector in the suite; one keyed on "
    "the input stream passes.",
    "Layers -- a stage's sessions need not line up with its input's",
    [
        file_header(options=[o_produced_by("zpf-demux 0.1"), o_produced_at(1719620000)]),
        source(1, 1, [o_uri("tls.zpf"), o_digest("sha256:5c7e")]),
        decoder(1, [o_dec_name("h2-demux"), o_dec_version("0.1")]),
        # Two output sessions, both drawing on the single input stream (7, 0).
        session(100, [o_proto("http")]),
        participant(100, 0, [o_endpoint("10.0.0.1:51000")]),
        session(101, [o_proto("http")]),
        participant(101, 0, [o_endpoint("10.0.0.1:51000")]),
        # The shared ciphertext record: its framing fed both inner units.
        record(100, 0, 1, 1000, b"S100-a", options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 80)])]),
        record(101, 0, 1, 1010, b"S101-a", options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 80)])]),
        record(
            100, 0, 1, 1100, b"S100-b", options=[o_decoder_id(1), o_spans([(1, 0, 7, 80, 140)])]
        ),
        record(
            101, 0, 1, 1200, b"S101-b", options=[o_decoder_id(1), o_spans([(1, 0, 7, 140, 200)])]
        ),
        # Each consuming session declares the stream's WHOLE extent, not its share.
        session_end(100, [o_input_extents([(1, 0, 7, 200)])]),
        session_end(101, [o_input_extents([(1, 0, 7, 200)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-demux 0.1",
            "produced_at": 1719620000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "tls.zpf",
            "digest": "sha256:5c7e",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "h2-demux",
            "version": "0.1",
        },
        {"type": "session", "session_id": 100, "proto": "http"},
        {"type": "participant", "session_id": 100, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {"type": "session", "session_id": 101, "proto": "http"},
        {"type": "participant", "session_id": 101, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 100,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"S100-a"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 80}],
        },
        {
            "type": "record",
            "session_id": 101,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1010,
            "payload": b64(b"S101-a"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 80}],
        },
        {
            "type": "record",
            "session_id": 100,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1100,
            "payload": b64(b"S100-b"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 80, "off_end": 140}],
        },
        {
            "type": "record",
            "session_id": 101,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1200,
            "payload": b64(b"S101-b"),
            "decoder_id": 1,
            "spans": [
                {"source_id": 1, "session_id": 7, "pid": 0, "off_start": 140, "off_end": 200}
            ],
        },
        {
            "type": "session_end",
            "session_id": 100,
            "input_extents": [{"source_id": 1, "session_id": 7, "pid": 0, "extent": 200}],
        },
        {
            "type": "session_end",
            "session_id": 101,
            "input_extents": [{"source_id": 1, "session_id": 7, "pid": 0, "extent": 200}],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "isolate-extents-disagree",
    "isolate",
    "Two output sessions drawing on ONE input stream, each declaring a DIFFERENT "
    "extent for it: session 100 says 200, session 101 says 160. Both cannot be "
    "true -- an input stream has one length, and under fan-out every consuming "
    "session declares that whole length, so the two Session Ends contradict each "
    "other. Only reachable once fan-out is legal, which is why nothing tested it "
    "before 0.14.",
    "Session End (0x12) -- input_extents under fan-out",
    [
        file_header(options=[o_produced_by("zpf-demux 0.1"), o_produced_at(1719630000)]),
        source(1, 1, [o_uri("tls.zpf"), o_digest("sha256:5c7e")]),
        decoder(1, [o_dec_name("h2-demux"), o_dec_version("0.1")]),
        session(100, [o_proto("http")]),
        participant(100, 0, [o_endpoint("10.0.0.1:51000")]),
        session(101, [o_proto("http")]),
        participant(101, 0, [o_endpoint("10.0.0.1:51000")]),
        record(100, 0, 1, 1000, b"a", options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 100)])]),
        record(101, 0, 1, 1100, b"b", options=[o_decoder_id(1), o_spans([(1, 0, 7, 100, 200)])]),
        session_end(100, [o_input_extents([(1, 0, 7, 200)])]),
        session_end(101, [o_input_extents([(1, 0, 7, 160)])]),
        end_block(),
    ],
    expect="MAY reject the file, or isolate. Input stream (session 7, pid 0) is "
    "declared 200 bytes long by session 100 and 160 by session 101. The "
    "specification says every session consuming a stream declares that "
    "stream's whole extent, so two sessions declaring different extents "
    "for one stream is a contradiction a reader MAY treat as a semantic "
    "violation. A reader that checks extents per session, rather than "
    "unioning across the sessions that name a stream, will not notice.",
    violations=1,
)

vector(
    "discontinuity-known-width",
    "accept",
    "A QUIC stream decoder, where the missing bytes CAN be counted: STREAM "
    "offsets give the gap's exact width. width = 25 is a term in the positional "
    "arithmetic, so the second record occupies [75,105), not [50,80). A reader "
    "that skips the block, or reads it but ignores width, computes a different "
    "range for every later record of this participant -- which is exactly the "
    "silent failure the block exists to prevent.",
    "Discontinuity (0x22)",
    [
        file_header(options=[o_produced_by("zpf-quic 0.1"), o_produced_at(1719590000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("quic-stream"), o_dec_version("0.1")]),
        session(9, [o_proto("quic")]),
        participant(9, 0, [o_endpoint("10.0.0.1:51000")]),
        record(9, 0, 1, 2000, b"C" * 50, options=[o_decoder_id(1), o_spans([(1, 0, 9, 0, 50)])]),
        undecoded(1, 0, 9, 50, 75, [o_reason("gap"), o_decoder_id(1)]),
        discontinuity(9, 0, [o_width(25), o_disc_reason("stream-gap")]),
        record(9, 0, 1, 2100, b"D" * 30, options=[o_decoder_id(1), o_spans([(1, 0, 9, 75, 105)])]),
        session_end(9, [o_input_extents([(1, 0, 9, 105)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-quic 0.1",
            "produced_at": 1719590000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "raw.zpf",
            "digest": "sha256:9f2c",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "quic-stream",
            "version": "0.1",
        },
        {"type": "session", "session_id": 9, "proto": "quic"},
        {"type": "participant", "session_id": 9, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 9,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "payload": b64(b"C" * 50),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 9, "pid": 0, "off_start": 0, "off_end": 50}],
        },
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 9,
            "pid": 0,
            "off_start": 50,
            "off_end": 75,
            "reason": "gap",
            "decoder_id": 1,
        },
        {"type": "discontinuity", "session_id": 9, "pid": 0, "width": 25, "reason": "stream-gap"},
        {
            "type": "record",
            "session_id": 9,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2100,
            "payload": b64(b"D" * 30),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 9, "pid": 0, "off_start": 75, "off_end": 105}],
        },
        {
            "type": "session_end",
            "session_id": 9,
            "input_extents": [{"source_id": 1, "session_id": 9, "pid": 0, "extent": 105}],
        },
        {"type": "end"},
    ],
    violations=0,
)

UUID = bytes.fromhex("3f2504e04f8911d39a0c0305e82c3301")

vector(
    "external-session-id",
    "accept",
    "A session carrying an identity assigned outside this format -- here a "
    "16-byte binary UUID. The value is opaque bytes, not a string: it is "
    "projected as base64 and MUST NOT be spelled out, or one id acquires two "
    "spellings. session_id is untouched and still what spans reference.",
    "Session Descriptor (0x10)",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp"), o_external_sid(UUID)]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"hi"),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "c.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp", "external_session_id": b64(UUID)},
        {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"hi"),
        },
        {"type": "end"},
    ],
    violations=0,
)


vector(
    "descriptive-metadata",
    "accept",
    "Five optional descriptive options, one per block that defines one: "
    "time_epoch on the File Header, link_type on a capture Source, flow_key on "
    "a Session, identity on a Participant, ts_first on a Record. None changes "
    "how anything else is read -- they project straight through, and the point "
    "is that a converter carries them rather than dropping them. time_epoch "
    "arrived here in 0.19: it moves the clock ORIGIN, so wall time is "
    "(time_epoch + timestamp) / tick_hz, and it was previously carried only by "
    "file-clock-metadata, whose other half was the SINGLE_CLOCK flag that 0.19 "
    "removed. The option outlived its vector.",
    "TLV option framing & id registry",
    [
        file_header(options=[o_time_epoch(1719500000)]),
        source(1, 0, [o_uri("c.pcap"), o_link_type(1)]),
        session(7, [o_proto("tcp"), o_flow_key("10.0.0.1:51000 <-> 93.184.216.34:80")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_identity("alice@example.com")]),
        # ts_first is the FIRST contributing packet; timestamp is the last, so
        # the reassembled record spans 1000..1100.
        record(7, 0, 1, 1100, b"hi", options=[o_ts_first(1000)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000, "time_epoch": 1719500000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "c.pcap", "link_type": 1},
        {
            "type": "session",
            "session_id": 7,
            "proto": "tcp",
            "key": "10.0.0.1:51000 <-> 93.184.216.34:80",
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "identity": "alice@example.com",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1100,
            "payload": b64(b"hi"),
            "ts_first": 1000,
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "custom-block",
    "accept",
    "A Custom (0xFF) vendor block. It is RECOGNISED, not unknown: a reader "
    "without knowledge of this pen/subtype skips it by frame length, but a "
    "converter still projects it as a `custom` line carrying pen, subtype and "
    "a base64 payload -- not through the unknown-block escape, which would "
    "lose the field structure.",
    "Custom (0xFF)",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        custom(32473, 7, b"\x01\x02\x03\x04"),  # 32473 = the example-use PEN
        session(7, [o_proto("tcp")]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "c.pcap"},
        {"type": "custom", "pen": 32473, "subtype": 7, "payload": b64(b"\x01\x02\x03\x04")},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {"type": "end"},
    ],
    violations=0,
)


vector(
    "reordered-decoded",
    "accept",
    "A stage that reorders a participant's decoded records without decoding "
    "them. It is a decode stage -- stored order defines the offsets, so "
    "reordering changes them -- and its spans run DOWNWARD against stored "
    "order. A reader that assumes spans ascend fails here. The declared Decoder "
    "is INHERITED (http/1.1, the layer's), so its params_digest describes a "
    "stage further up the chain; this stage's own config lives in the File "
    "Header transform_params_digest. Since 0.15 the seam between the two "
    "records carries a Discontinuity: the stage withholds nothing, but stored "
    "neighbours assert that they join and these two never did. No width -- what "
    "lies between two records that were never adjacent is not a hole to count, "
    "so the output offsets are unchanged at [0,50) and [50,150).",
    "Layers -- filtering and reordering a decoded stream",
    [
        file_header(
            options=[
                o_produced_by("zpf-reorder 0.1"),
                o_produced_at(1719530000),
                o_transform_params_digest("sha256:7c1e"),
            ]
        ),
        source(1, 1, [o_uri("decoded.zpf"), o_digest("sha256:44dd")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        # Input pid 1 held A = [0,100) then B = [100,150). Emitted B first, so
        # the output stream is B = [0,50), A = [50,150) and the spans descend.
        record(
            7,
            1,
            1,
            995,
            b"B" * 50,
            options=[
                o_decoder_id(1),
                o_spans([(1, 1, 7, 100, 150)]),
                o_content_type("dec:response"),
            ],
        ),
        # B's last byte and A's first were nowhere near each other on the wire.
        # Adjacency here would assert that they join, so the seam is declared.
        discontinuity(7, 1, [o_disc_reason("reordered")]),
        record(
            7,
            1,
            1,
            990,
            b"A" * 100,
            options=[o_decoder_id(1), o_spans([(1, 1, 7, 0, 100)]), o_content_type("dec:response")],
        ),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-reorder 0.1",
            "produced_at": 1719530000,
            "transform_params_digest": "sha256:7c1e",
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "decoded.zpf",
            "digest": "sha256:44dd",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "http/1.1",
            "version": "0.4",
        },
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 1, "endpoint": ["93.184.216.34:80"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 995,
            "payload": b64(b"B" * 50),
            "decoder_id": 1,
            "spans": [
                {"source_id": 1, "session_id": 7, "pid": 1, "off_start": 100, "off_end": 150}
            ],
            "content_type": "dec:response",
        },
        {"type": "discontinuity", "session_id": 7, "pid": 1, "reason": "reordered"},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 990,
            "payload": b64(b"A" * 100),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 1, "off_start": 0, "off_end": 100}],
            "content_type": "dec:response",
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "filtered-decoded",
    "accept",
    "A filter over a decoded HTTP file: it keeps two records and drops the one "
    "between them. Like a reordering stage it is a decode stage with an "
    "INHERITED decoder, so its own config lives in transform_params_digest. "
    "The removed region is Undecoded with reason = dropped, which since 0.17 is "
    "the word for content that was removed rather than withheld -- and it is "
    "what makes this a POSITIVE test rather than an example. Before it this "
    "region carried `skipped`, the same value a discarded byte-order mark "
    "carries, so this file and undecoded-skipped were byte-shaped alike and "
    "disagreed about whether a block was owed with nothing in either to tell "
    "them apart. The reason word still does not DECIDE the duty -- the test is "
    "whether the survivors join -- but here the producer has said outright that "
    "it removed content, so a checker can raise the missing block. Its "
    "width is DECLARED as 40: a filter knows the length of what it dropped, "
    "and an absent width would claim that length is unknowable. Declaring it "
    "keeps the output offset space aligned with the input's -- record C sits "
    "at [100,160) in both -- which does not make this a pass-through, since "
    "the spans-versus-origin test is what decides that and these are spans.",
    "Discontinuity (0x22) -- what a producer owes the block",
    [
        file_header(
            options=[
                o_produced_by("zpf-filter 0.1"),
                o_produced_at(1719560000),
                o_transform_params_digest("sha256:3b9a"),
            ]
        ),
        source(1, 1, [o_uri("decoded.zpf"), o_digest("sha256:44dd")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        record(
            7,
            1,
            1,
            1000,
            b"A" * 60,
            options=[
                o_decoder_id(1),
                o_spans([(1, 1, 7, 0, 60)]),
                o_content_type("dec:request"),
            ],
        ),
        undecoded(
            1, 1, 7, 60, 100, [o_reason("dropped"), o_decoder_id(1), o_comment("filtered out")]
        ),
        discontinuity(7, 1, [o_width(40), o_disc_reason("records-dropped")]),
        record(
            7,
            1,
            1,
            1200,
            b"C" * 60,
            options=[
                o_decoder_id(1),
                o_spans([(1, 1, 7, 100, 160)]),
                o_content_type("dec:response"),
            ],
        ),
        session_end(7, [o_input_extents([(1, 1, 7, 160)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-filter 0.1",
            "produced_at": 1719560000,
            "transform_params_digest": "sha256:3b9a",
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "decoded.zpf",
            "digest": "sha256:44dd",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "http/1.1",
            "version": "0.4",
        },
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 1, "endpoint": ["93.184.216.34:80"]},
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"A" * 60),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 1, "off_start": 0, "off_end": 60}],
            "content_type": "dec:request",
        },
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 7,
            "pid": 1,
            "off_start": 60,
            "off_end": 100,
            "reason": "dropped",
            "decoder_id": 1,
            "comment": "filtered out",
        },
        {
            "type": "discontinuity",
            "session_id": 7,
            "pid": 1,
            "width": 40,
            "reason": "records-dropped",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1200,
            "payload": b64(b"C" * 60),
            "decoder_id": 1,
            "spans": [
                {"source_id": 1, "session_id": 7, "pid": 1, "off_start": 100, "off_end": 160}
            ],
            "content_type": "dec:response",
        },
        {
            "type": "session_end",
            "session_id": 7,
            "input_extents": [{"source_id": 1, "session_id": 7, "pid": 1, "extent": 160}],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "sessionization-stage",
    "accept",
    "The cell F0 left empty: a zpf-SOURCED TRANSPORT stream. A reassembler run "
    "over a .zpf input -- what a decrypted tunnel needs -- with its own Decoder "
    "declaring output_layer = transport. Its records carry spans AND "
    "decoder_id, like any decode stage's, and everything else about it is a "
    "transport stream: isn on the participant, seq_start on the records, "
    "hole-inclusive offsets, and NO content_type, because a reassembly "
    "record's boundaries are a slice and not a unit. The 25-byte hole between "
    "the records is expressed by the sequence numbers -- 1001 + 50 ends at "
    "1051 and the next record starts at 1076 -- and NOT by a Discontinuity, "
    "which a transport-layer stream still may not carry whatever produced it. "
    "Before 0.15 this stage had to be characterised by the ABSENCE of "
    "decoder_id, because absence was the only way to say hole-inclusive, so "
    "its overlap policy and buffer depth had nowhere to live; params_digest is "
    "now where they go.",
    "Conformance -- a sessionization stage",
    [
        file_header(options=[o_produced_by("zpf-sessionize 0.2"), o_produced_at(1719630000)]),
        source(1, 1, [o_uri("packets.zpf"), o_digest("sha256:8c4d")]),
        decoder(
            1,
            [
                o_dec_name("tcp-reassembly"),
                o_dec_version("1.1"),
                o_params_digest("sha256:2f60"),
            ],
            output_layer=1,
        ),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(
            7,
            0,
            1,
            1000,
            b"A" * 50,
            options=[o_decoder_id(1), o_spans([(1, 0, 4, 0, 50)]), o_seq_start(1001)],
        ),
        undecoded(1, 0, 4, 50, 75, [o_reason("gap"), o_decoder_id(1)]),
        record(
            7,
            0,
            1,
            1200,
            b"B" * 30,
            options=[o_decoder_id(1), o_spans([(1, 0, 4, 75, 105)]), o_seq_start(1076)],
        ),
        session_end(7, [o_input_extents([(1, 0, 4, 105)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-sessionize 0.2",
            "produced_at": 1719630000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "packets.zpf",
            "digest": "sha256:8c4d",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "transport",
            "name": "tcp-reassembly",
            "version": "1.1",
            "params_digest": "sha256:2f60",
        },
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"A" * 50),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 4, "pid": 0, "off_start": 0, "off_end": 50}],
            "seq_start": 1001,
        },
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 4,
            "pid": 0,
            "off_start": 50,
            "off_end": 75,
            "reason": "gap",
            "decoder_id": 1,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1200,
            "payload": b64(b"B" * 30),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 4, "pid": 0, "off_start": 75, "off_end": 105}],
            "seq_start": 1076,
        },
        {
            "type": "session_end",
            "session_id": 7,
            "input_extents": [{"source_id": 1, "session_id": 4, "pid": 0, "extent": 105}],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "reassembler-declared",
    "accept",
    "The head-of-pipeline reassembler taking up the SHOULD: CAPTURE-sourced, "
    "with a Decoder of its own declaring output_layer = transport. The same "
    "logical layer raw-minimal holds unlabelled, labelled here -- and both are "
    "conformant, which is the deliberate asymmetry 0.15 records rather than "
    "leaves to be rediscovered. What it buys is a name and a params_digest for "
    "the reassembly, so a consumer can say WHICH reassembler produced the "
    "stream and whether two files were built the same way. Note the records "
    "carry no spans: the capture is not a .zpf and there is no input stream to "
    "cite, exactly as in any capture-sourced file.",
    "Conformance -- the head-of-pipeline reassembler",
    [
        file_header(options=[o_creator("zpf-write 2.0")]),
        source(1, 0, [o_uri("sideA.pcap"), o_link_type(1)]),
        decoder(
            1,
            [
                o_dec_name("tcp-reassembly"),
                o_dec_version("1.1"),
                o_params_digest("sha256:2f60"),
            ],
            output_layer=1,
        ),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(7, 0, 1, 1000, GET, flags=0x0001, options=[o_decoder_id(1), o_seq_start(1001)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000, "creator": "zpf-write 2.0"},
        {
            "type": "source",
            "source_id": 1,
            "kind": "capture",
            "uri": "sideA.pcap",
            "link_type": 1,
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "transport",
            "name": "tcp-reassembly",
            "version": "1.1",
            "params_digest": "sha256:2f60",
        },
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "flags": ["psh"],
            "payload": b64(GET),
            "decoder_id": 1,
            "seq_start": 1001,
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "proxy-decoded",
    "accept",
    "CASE G: a decoded stream with NO predecessor file. A TLS-terminating "
    "proxy logging application messages -- the bytes they were computed from "
    "were never written to a .zpf and never will be. Records carry decoder_id "
    "and reference a CAPTURE Source, which is the cell the axes were "
    "conflated to forbid: capture-sourced provenance, decoded layer. No spans "
    "and no origin, because there is no input stream to name. Two consequences "
    "the file demonstrates rather than states: the coverage guarantee does not "
    "apply, since it is scoped within each input participant stream and there "
    "is none; and the Decoder is a claim of IDENTITY, not a recipe -- nothing "
    "can regenerate this output, so a tool that assumes re-derivation is "
    "available is wrong about this file. Under 0.14 the only conformant "
    "encodings were to drop decoder_id and call these byte runs, losing what "
    "the records are, or to fabricate a predecessor that never existed.",
    "Conformance -- a decoded record with no predecessor file",
    [
        file_header(options=[o_produced_by("ssl-tap 0.3"), o_produced_at(1719600000)]),
        source(1, 0, [o_uri("sslkeylog-tap")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(3, [o_proto("http")]),
        participant(3, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            3,
            0,
            1,
            2000,
            b"GET /health HTTP/1.1",
            options=[o_decoder_id(1), o_content_type("dec:request")],
        ),
        record(
            3,
            0,
            1,
            2100,
            b"HTTP/1.1 200 OK",
            options=[o_decoder_id(1), o_content_type("dec:response")],
        ),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "ssl-tap 0.3",
            "produced_at": 1719600000,
        },
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "sslkeylog-tap"},
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "http/1.1",
            "version": "0.4",
        },
        {"type": "session", "session_id": 3, "proto": "http"},
        {"type": "participant", "session_id": 3, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 3,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "payload": b64(b"GET /health HTTP/1.1"),
            "decoder_id": 1,
            "content_type": "dec:request",
        },
        {
            "type": "record",
            "session_id": 3,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2100,
            "payload": b64(b"HTTP/1.1 200 OK"),
            "decoder_id": 1,
            "content_type": "dec:response",
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "undecoded-in-capture",
    "accept",
    "An Undecoded block in a CAPTURE-SOURCED file. The stage is the "
    "reassembler and the input is the capture itself: it discarded an "
    "overlapping retransmit it could not resolve, and says so rather than "
    "leaving the region unaccounted for. Barred before 0.15 on the unstated "
    "assumption that capture-sourced meant no transform had run -- but "
    "reassembly IS a transform, and a destructive one, so the prohibition read "
    "as a design when it was an oversight. "
    "READ THE BODY BY THE SOURCE'S KIND, which is what 0.16 settled (#87): "
    "against this CAPTURE source session_id and pid are UNUSED and written 0, "
    "and off_start/off_end are BYTE OFFSETS INTO tap.pcap -- 4096..4396 is a "
    "position in the pcap, not in this file's 105-byte stream. The 0.15 "
    "vector wrote session_id = 7, this file's own, which no reading of the "
    "text could justify; see VECTOR-DEFECTS.md. "
    "The class is BYTES, and against a capture source it is the only class "
    "available: a hole needs no block here, because the stream stays at the "
    "TRANSPORT layer, where the gap between the two records is already "
    "expressed by the sequence numbers -- which is also why the file may not "
    "carry a Discontinuity.",
    "Undecoded (0x21) -- a capture-sourced stream",
    [
        file_header(),
        source(1, 0, [o_uri("tap.pcap"), o_link_type(1)]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(7, 0, 1, 1000, b"A" * 50, options=[o_seq_start(1001)]),
        undecoded(
            1,
            0,
            0,
            4096,
            4396,
            [o_reason("overlap-discarded"), o_reason_class("bytes")],
            capture=True,
        ),
        record(7, 0, 1, 1200, b"B" * 30, options=[o_seq_start(1076)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {
            "type": "source",
            "source_id": 1,
            "kind": "capture",
            "uri": "tap.pcap",
            "link_type": 1,
        },
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"A" * 50),
            "seq_start": 1001,
        },
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 0,
            "pid": 0,
            "off_start": 4096,
            "off_end": 4396,
            "reason": "overlap-discarded",
            "reason_class": "bytes",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1200,
            "payload": b64(b"B" * 30),
            "seq_start": 1076,
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "mixed-derivation",
    "accept",
    "ONE derived file holding a decode-stage stream BESIDE a pass-through "
    "stream. Session 10 is created: its records carry spans and the file "
    "accounts for the input it decoded. Session 11 is preserved: its "
    "participant carries origin, its records carry no spans, and its bytes and "
    "offsets are the input's unchanged. Before 0.15 a derived file was exactly "
    "one of the two, never a mix, which left a tool with a decoder for one "
    "protocol and not the other two dishonest options -- pass everything "
    "through, or mark the undecodable session's whole stream Undecoded, which "
    "DROPS those bytes from the output. The rule that replaces it binds per "
    "participant: a participant MUST NOT both carry origin and hold records "
    "carrying spans. Across streams there is no such rule.",
    "Conformance -- the discriminator binds per participant",
    [
        file_header(
            options=[
                o_produced_by("zpf-decode 0.4"),
                o_produced_at(1719610000),
                o_transform_params_digest("sha256:5e2f"),
            ]
        ),
        source(1, 1, [o_uri("in.zpf"), o_digest("sha256:6a71")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        # Created: spans, no origin.
        session(10, [o_proto("http")]),
        participant(10, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            10,
            0,
            1,
            1000,
            b"GET /",
            options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 40)]), o_content_type("dec:request")],
        ),
        session_end(10, [o_input_extents([(1, 0, 7, 40)])]),
        # Preserved: an IDENTITY span -- same range in as out -- and no
        # decoder_id, the stage having had no decoder for this protocol and
        # re-emitted it rather than dropping it. Since 0.19 that is what tells a
        # preserved stream from a created one: not which option is present, but
        # whether the spans are identity.
        session(11, [o_proto("smtp")]),
        participant(11, 0, [o_endpoint("10.0.0.2:25"), o_isn(4000)]),
        record(
            11,
            0,
            1,
            1100,
            b"EHLO relay",
            options=[o_seq_start(4001), o_spans([(1, 8, 0, 0, 10)])],
        ),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-decode 0.4",
            "produced_at": 1719610000,
            "transform_params_digest": "sha256:5e2f",
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "in.zpf",
            "digest": "sha256:6a71",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "http/1.1",
            "version": "0.4",
        },
        {"type": "session", "session_id": 10, "proto": "http"},
        {"type": "participant", "session_id": 10, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
        {
            "type": "record",
            "session_id": 10,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"GET /"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 40}],
            "content_type": "dec:request",
        },
        {
            "type": "session_end",
            "session_id": 10,
            "input_extents": [{"source_id": 1, "session_id": 7, "pid": 0, "extent": 40}],
        },
        {"type": "session", "session_id": 11, "proto": "smtp"},
        {
            "type": "participant",
            "session_id": 11,
            "pid": 0,
            "endpoint": ["10.0.0.2:25"],
            "isn": 4000,
        },
        {
            "type": "record",
            "session_id": 11,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1100,
            "payload": b64(b"EHLO relay"),
            "seq_start": 4001,
            "spans": [{"source_id": 1, "session_id": 8, "pid": 0, "off_start": 0, "off_end": 10}],
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "hintless-merge-backwards-ts",
    "accept",
    "A hint-less session with no seq/ack, whose timestamps run backwards "
    "ACROSS participants. Every record is concurrent, so the whole order is "
    "the merge's timestamp tie-break -- but each participant's own records "
    "keep their stored order. A reader that rejects on the inversion, or that "
    "re-sorts one participant's records, fails.",
    "Merge algorithm -- stability",
    [
        file_header(),
        source(1, 0, [o_uri("chat.pcap")]),
        session(8, [o_proto("irc")]),
        participant(8, 0, [o_endpoint("alice")]),
        participant(8, 1, [o_endpoint("bob")]),
        # alice: ts 2000 then 2100 (in order). bob: ts 1900 -- earlier than
        # alice's first, so the interleaving is not stored order.
        record(8, 0, 1, 2000, b"a1"),
        record(8, 1, 1, 1900, b"b1"),
        record(8, 0, 1, 2100, b"a2"),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "chat.pcap"},
        {"type": "session", "session_id": 8, "proto": "irc"},
        {"type": "participant", "session_id": 8, "pid": 0, "endpoint": ["alice"]},
        {"type": "participant", "session_id": 8, "pid": 1, "endpoint": ["bob"]},
        {
            "type": "record",
            "session_id": 8,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "payload": b64(b"a1"),
        },
        {
            "type": "record",
            "session_id": 8,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1900,
            "payload": b64(b"b1"),
        },
        {
            "type": "record",
            "session_id": 8,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2100,
            "payload": b64(b"a2"),
        },
        {"type": "end"},
    ],
    violations=0,
)

vector(
    "sequenced-session",
    "accept",
    "A SEQUENCED session, which nothing else in the suite carries since 0.19 "
    "removed the four sequencing vectors with the basis rule. A single tap that "
    "saw both directions emits one directly, so this is capture-sourced and the "
    "flag is the whole of what it demonstrates. Its point is that SEQUENCED does "
    "NOT mean sorted by timestamp: pid 1's response is stored at ts 995, AFTER "
    "pid 0's request at ts 1000 that caused it, because the causal order comes "
    "from seq/ack and the two taps' clocks are skewed. A reader that re-sorts by "
    "timestamp, or rejects the inversion, has undone the work the flag "
    "announces.",
    "Sequenced files (precomputed order)",
    [
        file_header(),
        source(1, 0, [o_uri("both-directions.pcap")]),
        session(1, [o_proto("tcp"), o_sess_flags(0x0001)]),
        participant(1, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        participant(1, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000)]),
        record(1, 0, 1, 1000, b"GET /", options=[o_seq_start(1001)]),
        record(1, 1, 1, 995, b"HTTP/1.1 200", options=[o_seq_start(5001), o_ack(1006)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "both-directions.pcap"},
        {"type": "session", "session_id": 1, "proto": "tcp", "sequenced": True},
        {
            "type": "participant",
            "session_id": 1,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "participant",
            "session_id": 1,
            "pid": 1,
            "endpoint": ["93.184.216.34:80"],
            "isn": 5000,
        },
        {
            "type": "record",
            "session_id": 1,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"GET /"),
            "seq_start": 1001,
        },
        {
            "type": "record",
            "session_id": 1,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 995,
            "payload": b64(b"HTTP/1.1 200"),
            "seq_start": 5001,
            "ack": 1006,
        },
        {"type": "end"},
    ],
    expect="Accept, and consume the records in STORED order without running the "
    "merge -- that is what SEQUENCED licenses. The timestamps run "
    "backwards across the two records and that is conformant: the "
    "response is caused by the request, its ack 1006 acknowledges the "
    "request's five bytes, and the 5 ms inversion is capture skew "
    "between two taps. A reader that emits the response first has "
    "reordered a causal pair.",
    violations=0,
)

vector(
    "merge-timestamp-tie",
    "accept",
    "Two concurrent records from DIFFERENT participants bearing the SAME "
    "timestamp. Before 0.12 this was a genuine tie the format did not resolve, "
    "so two conformant readers could order the file differently. The merge now "
    "breaks it by ascending participant_id, so pid 0's record precedes pid 1's.",
    "Merge algorithm -- step 4",
    [
        file_header(),
        source(1, 0, [o_uri("chat.pcap")]),
        session(8, [o_proto("irc")]),
        participant(8, 0, [o_endpoint("alice")]),
        participant(8, 1, [o_endpoint("bob")]),
        # Stored bob-first, deliberately: the merge must still emit alice first,
        # because the tie-break is participant_id and not stored order.
        record(8, 1, 1, 2000, b"from-bob"),
        record(8, 0, 1, 2000, b"from-alice"),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "chat.pcap"},
        {"type": "session", "session_id": 8, "proto": "irc"},
        {"type": "participant", "session_id": 8, "pid": 0, "endpoint": ["alice"]},
        {"type": "participant", "session_id": 8, "pid": 1, "endpoint": ["bob"]},
        {
            "type": "record",
            "session_id": 8,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 2000,
            "payload": b64(b"from-bob"),
        },
        {
            "type": "record",
            "session_id": 8,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "payload": b64(b"from-alice"),
        },
        {"type": "end"},
    ],
    violations=0,
)


vector(
    "unplaceable-no-seq-start",
    "accept",
    "The COMMONER unplaceable shape, on its own: a record with no seq_start on "
    "a stream whose earlier record has one, so the offset space cannot say "
    "where it belongs. 0.17 stated a placement rule for a below-origin record "
    "and left this shape silent; 0.18 stated one rule for both and pinned this "
    "half inside partially-hinted-sequenced, which 0.19 removed with the "
    "sequencing basis. The shape has nothing to do with SEQUENCED -- placement "
    "keys on whether a stream is sequence-anchored, not on the flag -- so it is "
    "carried here by an ordinary session, which is where it always belonged. "
    "Its twin is advisory-below-origin-payload, the other shape of one rule.",
    "Referencing the source by stream offset",
    [
        file_header(),
        source(1, 0, [o_uri("mixed.pcap")]),
        session(9, [o_proto("udp")]),
        participant(9, 0, [o_endpoint("10.0.0.1:5000")]),
        participant(9, 1, [o_endpoint("10.0.0.2:5000")]),
        record(9, 0, 1, 3000, b"hinted", options=[o_seq_start(1001)]),
        record(9, 1, 1, 3100, b"plain"),
        record(9, 0, 1, 3200, b"plain2"),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "mixed.pcap"},
        {"type": "session", "session_id": 9, "proto": "udp"},
        {"type": "participant", "session_id": 9, "pid": 0, "endpoint": ["10.0.0.1:5000"]},
        {"type": "participant", "session_id": 9, "pid": 1, "endpoint": ["10.0.0.2:5000"]},
        {
            "type": "record",
            "session_id": 9,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 3000,
            "payload": b64(b"hinted"),
            "seq_start": 1001,
        },
        {
            "type": "record",
            "session_id": 9,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 3100,
            "payload": b64(b"plain"),
        },
        {
            "type": "record",
            "session_id": 9,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 3200,
            "payload": b64(b"plain2"),
        },
        {"type": "end"},
    ],
    expect="Accept. The .jsonl file is the expected projection. On placement: "
    "pid 0's first record is at [0,6) and its second carries no seq_start "
    "on a stream whose first record has one, so it is UNPLACEABLE -- it "
    "covers no byte of the stream and contributes nothing, so the extent "
    "stays 6 and those six bytes are in no offset at all. A reader that "
    "appended them at [6,12) is reading an offset the file does not "
    "state. Since 0.19 the RANGE a reader reports for the unplaceable "
    "record is not pinned, so two readers may differ there while both "
    "give extent 6. pid 1 is NOT this rule's case: no record of that "
    "participant carries a seq_start, so its stream is not "
    "sequence-anchored to begin with.",
    violations=0,
)

# --- negative: the reject tier --------------------------------------------


vector(
    "reject-bad-magic",
    "reject",
    "The File Header magic is the byte-swapped pattern 5A 49 50 46, which marks "
    "a byte-swapped file. The container is little-endian by definition.",
    "Conformance -- structural corruption",
    [file_header(magic=0x46495A5A), source(1, 0, [o_uri("c.pcap")])],
    expect="Reject the file. A reader SHOULD report that the magic looks "
    "byte-swapped, which is a more useful diagnostic than 'not a zpf'.",
    violations=1,
)

vector(
    "reject-unknown-major",
    "reject",
    "version_major is 1, which this document does not define. A reader MUST "
    "reject a major it does not implement.",
    "File Header -- version numbering",
    [file_header(major=1, minor=0), source(1, 0, [o_uri("c.pcap")])],
    expect="Reject the file.",
    violations=1,
)

vector(
    "reject-unknown-minor",
    "reject",
    f"version_minor is {MINOR + 1} while major is 0. In the 0.x regime the pair "
    f"(0, minor) is the compatibility identity, so a {MAJOR}.{MINOR} reader "
    "MUST reject it.",
    "File Header -- version numbering",
    # The next minor, derived, so this vector keeps testing an unimplemented
    # version instead of becoming a valid file at the next version bump.
    [file_header(minor=MINOR + 1), source(1, 0, [o_uri("c.pcap")])],
    expect="Reject the file. This is the vector that distinguishes a 0.x-aware "
    "reader from one that assumes minors are always skippable.",
    violations=1,
)

vector(
    "reject-length-misaligned",
    "reject",
    "A block length that is not a multiple of 4, which breaks the alignment "
    "invariant the whole container rests on.",
    "Conformance -- structural corruption",
    [
        file_header(),
        # Hand-framed: a Source block claiming length 6.
        [
            P(u16(0x02), "type   = 0x0002  Source Descriptor"),
            P(u16(0), "reserved"),
            P(u32(6), "length = 6   (NOT a multiple of 4 -- structural corruption)"),
            P(u16(1), "source_id = 1"),
            P(u8(0), "kind = 0  (capture)"),
            P(u8(0), "_reserved"),
            P(b"\x00\x00", "two bytes to reach the claimed length"),
        ],
    ],
    expect="Reject the file.",
    violations=1,
)

vector(
    "reject-payload-len-overrun",
    "reject",
    "A record whose payload_len runs past the end of its own block.",
    "Conformance -- structural corruption",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"hi", payload_len=9999),
    ],
    expect="Reject the file. payload_len exceeds the bytes the block's own length makes available.",
    violations=1,
)

# --- negative: the isolate tier -------------------------------------------

vector(
    "isolate-undeclared-session",
    "isolate",
    "A record referencing a session_id that was never declared. Well-framed, "
    "so the byte stream is trustworthy: this is a semantic violation.",
    "Conformance -- semantic violations",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"ok"),
        record(99, 0, 1, 1100, b"bad"),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the offending record or session. "
    "MUST NOT silently drop it without a diagnostic, and MUST NOT "
    "invent the missing declaration. A reader that discards only the "
    "second record and keeps the first is behaving correctly.",
    violations=1,
)

vector(
    "isolate-duplicate-id",
    "isolate",
    "A source_id declared twice.",
    "Conformance -- semantic violations",
    [
        file_header(),
        source(1, 0, [o_uri("first.pcap")]),
        source(1, 0, [o_uri("second.pcap")]),
        session(7, [o_proto("tcp")]),
        end_block(),
    ],
    expect="MAY reject the file, or isolate. MUST NOT silently pick one.",
    violations=1,
)

vector(
    "isolate-coverage-gap",
    "isolate",
    "A decode stage whose output leaves part of the input stream neither "
    "covered by a decoded record's spans nor marked Undecoded.",
    "Coverage honesty: Undecoded blocks",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719560000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("http/1.1")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        # covers [0,10) only; [10,50) is accounted for nowhere
        record(7, 0, 1, 1000, b"part", options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 10)])]),
        undecoded(1, 0, 7, 20, 50, [o_reason("undecodable"), o_decoder_id(1)]),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the session. The range [10,20) of "
    "input stream (session 7, pid 0) is covered by neither a record's "
    "spans nor an Undecoded block, so the coverage guarantee fails.",
    violations=1,
)

vector(
    "isolate-extent-exceeds-coverage",
    "isolate",
    "A decode stage whose Session End declares an input stream 40 bytes long "
    "while its spans and Undecoded blocks account for only [0,20). The tail "
    "[20,40) was silently dropped. Without input_extents this file is "
    "indistinguishable from an honest one that consumed a 20-byte stream -- "
    "which is the whole reason the option exists.",
    "Session End (0x12) -- input_extents",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719570000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("http/1.1")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"part", options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 20)])]),
        session_end(7, [o_input_extents([(1, 0, 7, 40)])]),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the session. The declared extent "
    "of input stream (session 7, pid 0) is 40, but spans plus Undecoded "
    "blocks cover only [0,20), so the coverage guarantee fails against "
    "the file's own declaration. A reader that ignores input_extents "
    "sees nothing wrong here, which is what this vector is for.",
    violations=1,
)

vector(
    "isolate-discontinuity-in-raw",
    "isolate",
    "A RAW file carrying a Discontinuity block. A transport stream's offset "
    "space is already hole-inclusive -- a gap occupies a real range no payload "
    "covers, resolvable from seq_start and isn -- so the block is meaningless "
    "there and the two mechanisms contradict each other: is the missing region "
    "the sequence gap, the declared width, or their sum? The block belongs to "
    "decoded layers only.",
    "Discontinuity (0x22)",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(7, 0, 1, 1000, b"A" * 50, options=[o_seq_start(1001)]),
        discontinuity(7, 0, [o_width(25), o_disc_reason("stream-gap")]),
        record(7, 0, 1, 1100, b"B" * 30, options=[o_seq_start(1076)]),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the session. The gap is already "
    "stated implicitly and unambiguously by the sequence numbers -- "
    "seq_start 1001 + 50 bytes ends at 1051, and the next record starts "
    "at 1076 -- so the Discontinuity is a second, redundant and "
    "potentially contradicting account of the same 25 bytes. A reader "
    "MUST NOT sum the two.",
    violations=1,
)

vector(
    "isolate-unmarked-break",
    "isolate",
    "Finding 3 as ONE file: a decode stage whose own output breaks, saying "
    "nothing. It is discontinuity-unknown-width with the Discontinuity deleted "
    "and nothing else changed -- the same tls-records stage, the same lost TCP "
    "segment, the same complete coverage. Every other rule is satisfied, which "
    "is the point: the coverage guarantee is about the INPUT and has no opinion "
    "on the output, so a checker that only accumulates ranges passes this file. "
    "This is the defect 0.13 shipped the block for and 0.15 finally forbids -- "
    "under 0.14 this file was conformant. Unlike splice/ it needs no second "
    "file, because a hole-class Undecoded region lying between the input "
    "regions of two adjacent output units is one of the two shapes of the duty "
    "decidable from a single file -- the other being a bytes-class region "
    "carrying reason = dropped, which isolate-unmarked-drop carries.",
    "Discontinuity (0x22) -- what a producer owes the block",
    [
        file_header(options=[o_produced_by("zpf-tls 0.2"), o_produced_at(1719580000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("tls-records"), o_dec_version("0.2")]),
        session(7, [o_proto("tls")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"A" * 50, options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 100)])]),
        # The input-side loss is declared. THE VIOLATION is what follows it:
        # no Discontinuity, so the two records are simply adjacent at 50 and a
        # downstream stage may splice them with every rule still satisfied.
        undecoded(1, 0, 7, 100, 139, [o_reason("gap"), o_decoder_id(1)]),
        record(7, 0, 1, 1100, b"B" * 30, options=[o_decoder_id(1), o_spans([(1, 0, 7, 139, 200)])]),
        session_end(7, [o_input_extents([(1, 0, 7, 200)])]),
        end_block(),
    ],
    expect="ISOLATE or reject. The Undecoded region is hole-class -- no bytes "
    "existed at [100,139) anywhere upstream -- and it lies between the "
    "input regions of two output units this file stores as neighbours. "
    "No content can have been carried forward across it, so the two "
    "records cannot join and the file MUST say so. Contrast "
    "undecoded-skipped, where a discarded BOM sits between two units "
    "that DO join and no block is owed; the reason word is not what "
    "decides it. Note a reader needs only this file: that is what makes "
    "this the checkable core rather than splice/'s two-file case.",
    violations=1,
)

vector(
    "isolate-self-derived",
    "isolate",
    "INTRA-FILE DERIVATION: a file deriving one of its own streams from "
    "another. Session 20's records span a zpf-input Source whose uri is THIS "
    "file, and session 21 is the stream they claim to come from. Legalising "
    "mixed-state files is what makes this reachable -- streams at differing "
    "positions on the two axes may now sit side by side, so the question of "
    "whether one may feed another arises for the first time and the answer is "
    "no. A stage reads its input and then writes its output, so a file cannot "
    "be among its own inputs: the offsets these spans name would have had to be "
    "fixed before the file holding them existed. Note the reason is NOT the "
    "digest -- that option is optional, and 0.16 restated the prohibition "
    "without it (#93) so it stands on files that omit one. "
    "DETECTION IS PARTIAL BY DESIGN: the only signal is the Source's uri, so a "
    "reader handed a PATH may compare and isolate, while a reader handed a file "
    "object -- stdin, a socket, a tar member -- cannot and is not obliged to. "
    "Session 21 carries an identity span so this file's ONLY violation is the "
    "one it is named for; through 0.15 it also had a zpf-sourced participant "
    "that cited nothing at all, and a reader could pass the vector by isolating "
    "for the wrong reason.",
    "Conceptual model -- the unit is the stream, not the file",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719620000)]),
        # THE VIOLATION: the uri names this vector's own file.
        source(1, 1, [o_uri("isolate-self-derived.zpf"), o_digest("sha256:0000")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(21, [o_proto("tcp")]),
        # An identity span, so session 21 is PRESERVED rather than citing
        # nothing -- #92/#93, restated for 0.19's one-provenance-rule.
        participant(21, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(
            21,
            0,
            1,
            1000,
            b"GET /",
            options=[o_seq_start(1001), o_spans([(1, 0, 21, 0, 5)])],
        ),
        session(20, [o_proto("http")]),
        participant(20, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            20,
            0,
            1,
            1100,
            b"GET /",
            options=[o_decoder_id(1), o_spans([(1, 0, 21, 0, 5)]), o_content_type("dec:request")],
        ),
        end_block(),
    ],
    expect="ISOLATE or reject, WHEN THE READER KNOWS THE PATH it opened. The "
    "Source names the file that contains it, and a stage cannot be among "
    "its own inputs. Streams at differing layers or provenances in one "
    "file are legal since 0.15; one deriving from another in the same "
    "file is not, and the two are easy to confuse. A reader MUST NOT "
    "resolve the spans against the sibling session -- that is the "
    "reinterpretation the isolate tier forbids. A reader with no path "
    "to compare against cannot detect this and is CONFORMANT in "
    "accepting the file; it must still not resolve the spans.",
    violations=1,
)

vector(
    "isolate-hole-against-capture",
    "isolate",
    "A hole-class Undecoded region declared against a CAPTURE Source. "
    "undecoded-in-capture is the conformant shape of this block and this is the "
    "class it may not use: reason = gap, no bytes anywhere upstream. The stream "
    "a reassembler produces from a capture is a TRANSPORT layer, whose offsets "
    "are hole-inclusive, so the missing segment already occupies a range no "
    "record covers and the sequence numbers already give its extent -- 1001 + "
    "50 ends at 1051 and the next record starts at 1076. Declaring it again is "
    "a second account of the same missing bytes with no rule for which to "
    "believe, which is the same contradiction that bars a Discontinuity from a "
    "transport stream. The bytes-exist class stays available and is the half "
    "that adds something: an overlapping retransmit the reassembler discarded "
    "exists in the pcap and is expressible nowhere else.",
    "Undecoded (0x21) -- against a capture source only the bytes-exist class",
    [
        file_header(),
        source(1, 0, [o_uri("tap.pcap"), o_link_type(1)]),
        session(8, [o_proto("tcp")]),
        participant(8, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(8, 0, 1, 1000, b"A" * 50, options=[o_seq_start(1001)]),
        # THE VIOLATION: a hole class against a capture source.
        undecoded(1, 0, 0, 4096, 4121, [o_reason("gap")], capture=True),
        record(8, 0, 1, 1200, b"B" * 30, options=[o_seq_start(1076)]),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the block. A reader MUST NOT "
    "reconcile the two accounts -- neither by preferring the block nor by "
    "preferring the sequence numbers, and neither by treating the capture "
    "byte range as if it were a stream offset range. Contrast "
    "undecoded-in-capture, which is the same block with the bytes-exist "
    "class and is conformant.",
    violations=1,
)

vector(
    "isolate-mixed-layer-participant",
    "isolate",
    "ONE participant whose records resolve to TWO layers: record A carries "
    "decoder 1 (output_layer = decoded), record B carries decoder 2 "
    "(output_layer = transport). Both decoders are declared, both records are "
    "well-formed, declare-before-use holds, and coverage is complete -- 0.15 "
    "broke no stated rule here, which is the point. The layer fixes the "
    "stream's OFFSET SPACE, and this stream has two incompatible answers for "
    "it: hole-inclusive true positions if transport, the concatenation of "
    "record payloads if decoded. Mixing DECODERS per record stays legal (HTTP "
    "on one session, TLS-then-HTTP on another) -- what 0.16 forbids is mixing "
    "the LAYERS those decoders declare, within one participant.",
    "Conformance -- every record of one participant MUST resolve to the same layer",
    [
        file_header(options=[o_produced_by("zpf-mix 0.1"), o_produced_at(1719640000)]),
        source(1, 1, [o_uri("packets.zpf"), o_digest("sha256:11aa")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("1.0")]),
        decoder(2, [o_dec_name("tcp-reassembly"), o_dec_version("1.1")], output_layer=1),
        session(30, [o_proto("tcp")]),
        participant(30, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            30,
            0,
            1,
            1000,
            b"GET /",
            options=[o_decoder_id(1), o_spans([(1, 0, 5, 0, 5)]), o_content_type("dec:request")],
        ),
        # THE VIOLATION: same participant, a decoder declaring the other layer.
        record(
            30,
            0,
            1,
            1100,
            b"C" * 20,
            options=[o_decoder_id(2), o_spans([(1, 0, 5, 5, 25)]), o_seq_start(1001)],
        ),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the participant. Its two records "
    "resolve to different layers, so 'this stream's offset space' has no "
    "single answer and any input_extents or downstream spans computed "
    "against it is meaningless. A reader MUST NOT pick one layer and "
    "proceed -- that is the silent reinterpretation the isolate tier "
    "forbids. Note what is NOT wrong: two decoders in one file, and two "
    "decoders in one SESSION, are both ordinary.",
    violations=1,
)

vector(
    "isolate-unbound-zpf-stream",
    "isolate",
    "A zpf-SOURCED participant that is NEITHER created NOR preserved: its "
    "record references a zpf-input Source, carries no spans, and its "
    "participant carries no origin. Nothing says which stream inside the input "
    "its bytes came from, so nothing resolves one level down and no coverage "
    "obligation can be computed in either direction. The two ways of producing "
    "a zpf-sourced stream are exhaustive and 0.15 never said so -- the "
    "discriminator rule forbade being BOTH and was silent on being neither, "
    "which is how isolate-self-derived shipped carrying this as a second, "
    "unintended violation. Contrast mixed-derivation, where one participant is "
    "created and the other preserved and both say which.",
    "Conformance -- a zpf-sourced participant MUST be one or the other",
    [
        file_header(options=[o_produced_by("zpf-tool 0.1"), o_produced_at(1719650000)]),
        source(1, 1, [o_uri("upstream.zpf"), o_digest("sha256:22bb")]),
        session(40, [o_proto("tcp")]),
        # THE VIOLATION: zpf-sourced, and no origin here nor spans below.
        participant(40, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(40, 0, 1, 1000, b"D" * 30, options=[o_seq_start(1001)]),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the participant. A reader MUST NOT "
    "guess the missing provenance -- neither by assuming the input's ids "
    "match this file's, nor by treating the record as capture-sourced. "
    "The Source's kind is zpf-input and that is what makes the omission a "
    "violation; a capture-sourced participant correctly carries neither.",
    violations=1,
)

vector(
    "advisory-transport-content-type",
    "accept",
    "A transport-layer record carrying a content_type, which 0.16 makes a MUST "
    "NOT whose violation is ADVISORY -- one of two, the other being 0.17's "
    "origin floor (advisory-seq-start-below-origin). The "
    "reassembly decoder declares output_layer = transport and labels its record "
    "prim:bytes, which is mechanically legal and is the wrong answer: the "
    "record's boundaries are wherever the reassembler chunked the stream, so "
    "the label asserts a unit where there is a slice. "
    "WHY ADVISORY AND NOT ISOLATE: dropping the label loses nothing and the "
    "record stays fully readable, so there is no unit a reader could soundly "
    "discard. This is the tcp_role treatment, not the origin-on-a-capture "
    "treatment. The one thing a reader MUST NOT do is read the label as "
    "evidence that the stream is decoded after all, which would put every "
    "later offset in this participant into the wrong space. "
    "The manifest marks it advisory: true, so it declares 1 violation on the "
    "ACCEPT tier -- the file breaks a rule and a conformant reader accepts it "
    "anyway, having reported it.",
    "Typing a decoded record -- a transport-layer record carries no content_type",
    [
        file_header(options=[o_produced_by("zpf-sessionize 0.2"), o_produced_at(1719660000)]),
        source(1, 1, [o_uri("packets.zpf"), o_digest("sha256:33cc")]),
        decoder(1, [o_dec_name("tcp-reassembly"), o_dec_version("1.1")], output_layer=1),
        session(50, [o_proto("tcp")]),
        participant(50, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        # THE VIOLATION: content_type at the transport layer.
        record(
            50,
            0,
            1,
            1000,
            b"E" * 40,
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 6, 0, 40)]),
                o_seq_start(1001),
                o_content_type("prim:bytes"),
            ],
        ),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-sessionize 0.2",
            "produced_at": 1719660000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "packets.zpf",
            "digest": "sha256:33cc",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "transport",
            "name": "tcp-reassembly",
            "version": "1.1",
        },
        {"type": "session", "session_id": 50, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 50,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "record",
            "session_id": 50,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"E" * 40),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 6, "pid": 0, "off_start": 0, "off_end": 40}],
            "seq_start": 1001,
            "content_type": "prim:bytes",
        },
        {"type": "end"},
    ],
    expect="ACCEPT, and REPORT. The projection is the .jsonl file -- the label "
    "round-trips, because a reader preserves what it does not act on. A "
    "reader MUST ignore the label semantically and SHOULD report it, and "
    "MUST NOT conclude from it that the stream is decoded. Rejecting or "
    "isolating this file is NOT conformant: the advisory strength is "
    "stated in Typing a decoded record.",
    violations=1,
    advisory=True,
)

vector(
    "handshake-at-origin",
    "accept",
    "The mandated shape of a recorded TCP handshake, both directions, and the "
    "TIE it necessarily produces. Each SYN sits at isn + 1 -- the stream origin, "
    "which is where 0.17 made it a MUST -- and the first data record of that "
    "direction starts at the same origin, because that is what the origin IS. So "
    "each participant here has TWO records at one seq_start, ordered by nothing "
    "but stored order. "
    "WHY THIS FILE EXISTS: the per-participant ordering MUST is non-descending, "
    "and a reader that reads `in seq_start order` as strictly ascending -- which "
    "is what a `<` comparison produces without anyone deciding anything -- "
    "rejects or isolates this file, and with it every conformant capture whose "
    "handshake was observed. Until 0.18 no vector in the suite carried a "
    "seq_start tie at all, so that reader passed the whole suite and failed on "
    "real traffic. It is the positive twin of advisory-seq-start-below-origin, "
    "which is the same record written one below the origin. "
    "It also carries the responder's SYN-ACK as its own zero-length syn record "
    "with an ack, which the specification describes and nothing else exercises.",
    "Record (0x20) -- handshake records",
    [
        file_header(),
        source(1, 0, [o_uri("tcp.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(0)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000), o_tcp_role(1)]),
        # The client's SYN, at the origin. Zero length, so its computed end
        # equals its seq_start and every causal edge works unchanged.
        record(7, 0, 1, 1000, b"", flags=0x0008, options=[o_seq_start(1001)]),
        # The responder's SYN-ACK: its own zero-length syn record, acking the
        # client's SYN, whose end is 1001.
        record(7, 1, 1, 1100, b"", flags=0x0008, options=[o_seq_start(5001), o_ack(1001)]),
        # THE TIE: the same seq_start as the SYN above it, in each direction.
        # Stored order is what puts the handshake record first.
        record(7, 0, 1, 1200, GET, flags=0x0001, options=[o_seq_start(1001), o_ack(5001)]),
        record(
            7,
            1,
            1,
            1300,
            b"HTTP/1.1 200 OK\r\n\r\n",
            flags=0x0001,
            options=[o_seq_start(5001), o_ack(1019)],
        ),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "tcp.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
            "tcp_role": "initiator",
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "endpoint": ["93.184.216.34:80"],
            "isn": 5000,
            "tcp_role": "responder",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "flags": ["syn"],
            "payload": "",
            "seq_start": 1001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1100,
            "flags": ["syn"],
            "payload": "",
            "seq_start": 5001,
            "ack": 1001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1200,
            "flags": ["psh"],
            "payload": b64(GET),
            "seq_start": 1001,
            "ack": 5001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1300,
            "flags": ["psh"],
            "payload": b64(b"HTTP/1.1 200 OK\r\n\r\n"),
            "seq_start": 5001,
            "ack": 1019,
        },
        {"type": "end"},
    ],
    expect="ACCEPT. The two records of each participant share a seq_start and "
    "that is conformant: the ordering MUST is NON-DESCENDING, and stored "
    "order decides which comes first. A reader that treats equal seq_start "
    "as out-of-order and rejects or isolates is NOT conformant, and is the "
    "reader this vector exists to catch -- it would reject most real "
    "captures. Offsets: each SYN is zero-length at offset 0 and covers no "
    "byte, so pid 0's stream is [0,18) and pid 1's is [0,19). The merge "
    "needs no sort: step 1 takes each participant's records in file order.",
    violations=0,
)


vector(
    "advisory-transport-role",
    "accept",
    "advisory-transport-content-type's twin, for the other label. A reassembly "
    "decoder declaring output_layer = transport labels its record `role: "
    '"segment"`, which 0.17 makes a MUST NOT alongside content_type and with '
    "the same advisory strength. "
    "WHY role IS THE MORE TEMPTING MISTAKE: prim:bytes at least LOOKS wrong -- it "
    "says `opaque` about a slice. role's vocabulary is open, so a plausible word "
    "always exists and `segment` reads as helpful. It is the same error either "
    "way: the record's boundaries are wherever the reassembler chunked the "
    "stream, so a label asserting a unit where there is a slice types identical "
    "bytes differently by provenance. "
    "WHY ADVISORY AND NOT ISOLATE: dropping the label loses nothing and the "
    "record stays fully readable, so there is no unit a reader could soundly "
    "discard. The one thing a reader MUST NOT do is read the label as evidence "
    "that the stream is decoded after all, which would put every later offset in "
    "this participant into the wrong space. "
    "The manifest marks it advisory: true, so it declares 1 violation on the "
    "ACCEPT tier.",
    "Typing a decoded record -- a transport-layer record carries no label",
    [
        file_header(options=[o_produced_by("zpf-sessionize 0.2"), o_produced_at(1719660000)]),
        source(1, 1, [o_uri("packets.zpf"), o_digest("sha256:33cc")]),
        decoder(1, [o_dec_name("tcp-reassembly"), o_dec_version("1.1")], output_layer=1),
        session(51, [o_proto("tcp")]),
        participant(51, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        # THE VIOLATION: role at the transport layer.
        record(
            51,
            0,
            1,
            1000,
            b"E" * 40,
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 6, 0, 40)]),
                o_seq_start(1001),
                o_role("segment"),
            ],
        ),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-sessionize 0.2",
            "produced_at": 1719660000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "packets.zpf",
            "digest": "sha256:33cc",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "transport",
            "name": "tcp-reassembly",
            "version": "1.1",
        },
        {"type": "session", "session_id": 51, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 51,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "record",
            "session_id": 51,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"E" * 40),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 6, "pid": 0, "off_start": 0, "off_end": 40}],
            "seq_start": 1001,
            "role": "segment",
        },
        {"type": "end"},
    ],
    expect="ACCEPT, and REPORT. The projection is the .jsonl file -- the label "
    "round-trips, because a reader preserves what it does not act on. A "
    "reader MUST ignore the label semantically and SHOULD report it, and "
    "MUST NOT conclude from it that the stream is decoded. Rejecting or "
    "isolating this file is NOT conformant: the advisory strength is "
    "stated in Typing a decoded record, and covers both labels in one "
    "sentence. Its twin is advisory-transport-content-type; the pair exist "
    "because the strength is the part implementations guess wrong.",
    violations=1,
    advisory=True,
)

vector(
    "unplaceable-below-origin",
    "accept",
    "A below-origin record CARRYING PAYLOAD: seq_start 1000 on a stream whose "
    "origin is isn + 1 = 1001. Since 0.19 that is not a violation -- the floor "
    "stopped being a MUST NOT when the advisory tier stopped pinning repairs -- "
    "but the EFFECT survives and is what this vector pins: the record is "
    "UNPLACEABLE, so it covers no byte of the stream and its eight bytes are "
    "outside the offset space, excluded from the extent and from every coverage "
    "answer. What 0.19 dropped is the exact range a reader reports for it; two "
    "readers may differ there and still agree on every extent. A reader that "
    "trusts the wrapped offset places it near 2**32 and corrupts the extent for "
    "every other record, which is the reading this vector exists to fail.",
    "Referencing the source by stream offset -- unplaceable records",
    [
        file_header(),
        source(1, 0, [o_uri("offbyone.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(0)]),
        # THE VIOLATION: one below the origin, and carrying payload -- so the
        # zero-width placement costs eight bytes rather than nothing.
        record(7, 0, 1, 1000, b"LOSTBYTE", flags=0x0001, options=[o_seq_start(1000)]),
        record(7, 0, 1, 2000, b"AAAABBBB", flags=0x0001, options=[o_seq_start(1001)]),
        record(7, 0, 1, 3000, b"CCCCDDDD", flags=0x0001, options=[o_seq_start(1009)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "offbyone.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
            "tcp_role": "initiator",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "flags": ["psh"],
            "payload": b64(b"LOSTBYTE"),
            "seq_start": 1000,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "flags": ["psh"],
            "payload": b64(b"AAAABBBB"),
            "seq_start": 1001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 3000,
            "flags": ["psh"],
            "payload": b64(b"CCCCDDDD"),
            "seq_start": 1009,
        },
        {"type": "end"},
    ],
    expect="ACCEPT, and REPORT. The first record is unplaceable: zero-width at "
    "offset 0, contributing nothing to the extent and covering no byte, so "
    "the participant's stream is [0,16) -- the two later records -- and the "
    "eight bytes of the first are in no offset at all. It is NOT deleted: "
    "a reader still lists it, still reports its timestamp and payload, and "
    "a consumer indexing by anything but offset still sees it. Two wrong "
    "readings diverge visibly here and not on "
    "advisory-seq-start-below-origin: one places the record at 4294967295 "
    "and reports an extent to match, the other drops it and reports two "
    "records where the file has three. Rejecting or isolating is NOT "
    "conformant.",
    violations=0,
)

vector(
    "isolate-unmarked-drop",
    "isolate",
    "#78's own title case, as ONE file, and the half of it that could not be "
    "tested until 0.17. It is filtered-decoded with the Discontinuity deleted "
    "and nothing else changed: the same filter, the same removed record, the "
    "same complete coverage. The survivors do not join -- 40 bytes of content "
    "went missing between them -- and the file says nothing, so a downstream "
    "stage may splice records A and C into one run that never existed. "
    "WHY THIS IS NOW CHECKABLE: the region carries reason = dropped, the word "
    "0.17 adds for content that was REMOVED rather than withheld. Before it "
    "this file wrote `skipped`, which is also what a discarded byte-order mark "
    "writes -- and a BOM owes no block, because it withholds no content. The "
    "two cases were byte-shaped alike, so a checker raising this one would "
    "have raised undecoded-skipped too and been wrong. The hole-class twin of "
    "this vector is isolate-unmarked-break, which was decidable all along "
    "because no bytes existed there at all.",
    "Discontinuity (0x22) -- what a producer owes the block",
    [
        file_header(
            options=[
                o_produced_by("zpf-filter 0.1"),
                o_produced_at(1719560000),
                o_transform_params_digest("sha256:3b9a"),
            ]
        ),
        source(1, 1, [o_uri("decoded.zpf"), o_digest("sha256:44dd")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        record(
            7,
            1,
            1,
            1000,
            b"A" * 60,
            options=[
                o_decoder_id(1),
                o_spans([(1, 1, 7, 0, 60)]),
                o_content_type("dec:request"),
            ],
        ),
        # The removal is declared, and honestly: reason = dropped says content
        # of the stream went with it. THE VIOLATION is what does not follow --
        # no Discontinuity, so records A and C are simply adjacent at 60.
        undecoded(
            1, 1, 7, 60, 100, [o_reason("dropped"), o_decoder_id(1), o_comment("filtered out")]
        ),
        record(
            7,
            1,
            1,
            1200,
            b"C" * 60,
            options=[
                o_decoder_id(1),
                o_spans([(1, 1, 7, 100, 160)]),
                o_content_type("dec:response"),
            ],
        ),
        session_end(7, [o_input_extents([(1, 1, 7, 160)])]),
        end_block(),
    ],
    expect="ISOLATE or reject. The Undecoded region carries reason = dropped "
    "and lies between the input regions of two output units this file "
    "stores as neighbours -- A ends at 60, C starts at 100 -- so the "
    "producer has stated that content of this stream was removed between "
    "two records it presents as joining. A Discontinuity is required and "
    "there is none. Contrast undecoded-skipped, where the withheld region "
    "is a BOM carrying no content of the stream and no block is owed: the "
    "reason word does not decide the duty, but `dropped` is the "
    "producer's own statement that it does bind here. Note a reader needs "
    "only this file, as with isolate-unmarked-break.",
    violations=1,
)

vector(
    "isolate-unknown-output-layer",
    "isolate",
    "A Decoder declaring an output_layer this version does not define. The "
    "load-bearing twin of isolate-unknown-source-kind, and the second enum of "
    "which that is true: the value decides whether this stream's offsets are "
    "hole-inclusive positions or a payload concatenation, so a reader that "
    "does not recognise it cannot compute a single record's range. Contrast "
    "escape-unknown-enum, where an unknown tcp_role is advisory and carrying "
    "the raw number forward loses nothing. Note the file is otherwise "
    "conformant -- the failure is entirely in what the reader cannot conclude.",
    "Enums -- load-bearing values",
    [
        file_header(options=[o_produced_by("zpf-sessionize 0.2"), o_produced_at(1719630000)]),
        source(1, 1, [o_uri("packets.zpf"), o_digest("sha256:8c4d")]),
        decoder(1, [o_dec_name("tcp-reassembly"), o_dec_version("1.1")], output_layer=7),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(
            7,
            0,
            1,
            1000,
            b"A" * 50,
            options=[o_decoder_id(1), o_spans([(1, 0, 4, 0, 50)]), o_seq_start(1001)],
        ),
        end_block(),
    ],
    expect="MAY reject the file, or discard the streams whose records "
    "reference decoder 1. MUST NOT guess a layer, and MUST NOT fall "
    "back to the absent-means-decoded default -- absence and an "
    "unrecognised value are different statements, and treating them "
    "alike would read a transport stream's offsets as a payload "
    "concatenation. This is the same condition as an unknown Source "
    "kind and is handled the same way.",
    violations=1,
)

vector(
    "isolate-unknown-source-kind",
    "isolate",
    "A Source whose kind is undefined. Unlike tcp_role this is load-bearing: "
    "kind decides how a span's offsets are read, so anything referencing this "
    "Source is uninterpretable.",
    "Unrecognised enum values",
    [
        file_header(),
        source(1, 7, [o_uri("mystery")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"hi"),
        end_block(),
    ],
    expect="MAY reject the file, or discard the Source together with "
    "everything referencing it. MUST NOT guess a kind. Note this is "
    "the enum case that is NOT a free extension point.",
    violations=1,
)


# ------------------------------------------------------------------- the chain
#
# Three files whose digests and offsets genuinely agree, so the provenance walk
# can be exercised end to end:
#
#   cap.pcap --[sessionize]--> raw.zpf --[http decode]--> decoded.zpf
#                                                             |
#                                                     [annotate]--> annotated.zpf
#
# Byte budget, fixed here so every offset below is checkable by hand:
#   session 7, pid 0 (client): "GET /\r\n\r\n"        9 bytes, offsets [0,9)
#   session 7, pid 1 (server): "HTTP/1.1 200\r\n\r\n" 16 bytes, offsets [0,16)
#                              4 opaque bytes           offsets [16,20)
# The decoder parses the response head and cannot parse the 4-byte tail, so
# decoded.zpf covers [0,16) with a record and [16,20) with an Undecoded block --
# which is the whole of pid 1's 20-byte stream, and the coverage guarantee holds.

REQ = b"GET /\r\n\r\n"  # 9
RESP = b"HTTP/1.1 200\r\n\r\n"  # 16
TAIL = b"\x00\x01\x02\x03"  # 4, undecodable
DEC_REQ = b"REQ:GET /"  # 9  -> decoded pid 0 offsets [0,9)
DEC_RESP = b"RESP:200"  # 8  -> decoded pid 1 offsets [0,8)

# Multi-file fixtures. Some things a single file cannot express -- a provenance
# walk, or one stage's output being another stage's input -- so a fixture is a
# directory of files that only mean anything together. FIXTURES maps the
# directory to its manifest entry; each member file is appended by member().
FIXTURES: dict[str, dict] = {}


def member(fixture: str, name: str, summary: str, blocks: list[Blk], jsonl: list[dict]) -> bytes:
    """Add one file to a multi-file fixture.

    Returns its bytes, so the next file in the fixture can cite its digest.
    """
    FIXTURES[fixture]["members"].append(
        {"name": name, "summary": summary, "blocks": blocks, "jsonl": jsonl}
    )
    return to_bytes(assemble(blocks))


def fixture(name: str, tier: str, summary: str, spec: str, expect: str, *, violations: int) -> None:
    """Declare a multi-file fixture. Its files are added by member()."""
    FIXTURES[name] = {
        "name": name,
        "tier": tier,
        "summary": summary,
        "spec": spec,
        "expect": expect,
        "violations": violations,
        "members": [],
    }


def chain_file(name: str, summary: str, blocks: list[Blk], jsonl: list[dict]) -> bytes:
    return member("chain", name, summary, blocks, jsonl)


def build_chain() -> None:
    """Build the three files in order, hashing each so the next can cite it."""
    fixture(
        "chain",
        "accept",
        "A three-file provenance chain whose digests and offsets genuinely "
        "agree: raw.zpf -> decoded.zpf -> annotated.zpf. The only fixture where "
        "the recovery walk, two-hop resolution and digest verification can be "
        "exercised.",
        "Layers; Coverage honesty; Annotating a decoded file",
        "Accept all three. Each .jsonl is the expected projection. Each declared "
        "digest is the real SHA-256 of the sibling file it names, so a reader "
        "can verify the chain.",
        violations=0,
    )
    raw_blocks = [
        file_header(options=[o_creator("zpf-sessionize 1.0")]),
        source(1, 0, [o_uri("cap.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000)]),
        record(7, 0, 1, 1000, REQ, flags=0x0001, options=[o_seq_start(1001), o_ack(5001)]),
        record(7, 1, 1, 1100, RESP, flags=0x0001, options=[o_seq_start(5001), o_ack(1010)]),
        record(7, 1, 1, 1200, TAIL, options=[o_seq_start(5017), o_ack(1010)]),
        end_block(),
    ]
    raw = chain_file(
        "raw",
        "The capture-sourced file the chain starts from.",
        raw_blocks,
        [
            {"type": "file", "format": FORMAT, "tick_hz": 1000000, "creator": "zpf-sessionize 1.0"},
            {"type": "source", "source_id": 1, "kind": "capture", "uri": "cap.pcap"},
            {"type": "session", "session_id": 7, "proto": "tcp"},
            {
                "type": "participant",
                "session_id": 7,
                "pid": 0,
                "endpoint": ["10.0.0.1:51000"],
                "isn": 1000,
            },
            {
                "type": "participant",
                "session_id": 7,
                "pid": 1,
                "endpoint": ["93.184.216.34:80"],
                "isn": 5000,
            },
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "flags": ["psh"],
                "payload": b64(REQ),
                "seq_start": 1001,
                "ack": 5001,
            },
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 1,
                "source_id": 1,
                "ts": 1100,
                "flags": ["psh"],
                "payload": b64(RESP),
                "seq_start": 5001,
                "ack": 1010,
            },
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 1,
                "source_id": 1,
                "ts": 1200,
                "payload": b64(TAIL),
                "seq_start": 5017,
                "ack": 1010,
            },
            {"type": "end"},
        ],
    )
    raw_dg = "sha256:" + hashlib.sha256(raw).hexdigest()

    dec_blocks = [
        file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719500000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest(raw_dg)]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        record(
            7,
            0,
            1,
            1000,
            DEC_REQ,
            options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 9)]), o_content_type("dec:request")],
        ),
        record(
            7,
            1,
            1,
            1100,
            DEC_RESP,
            options=[o_decoder_id(1), o_spans([(1, 1, 7, 0, 16)]), o_content_type("dec:response")],
        ),
        undecoded(1, 1, 7, 16, 20, [o_reason("undecodable"), o_decoder_id(1)]),
        end_block(),
    ]
    dec = chain_file(
        "decoded",
        "A decode stage over raw.zpf. Its spans and Undecoded "
        "block together cover every byte of both input streams.",
        dec_blocks,
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-decode 0.4",
                "produced_at": 1719500000,
            },
            {
                "type": "source",
                "source_id": 1,
                "kind": "zpf-input",
                "uri": "raw.zpf",
                "digest": raw_dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "http/1.1",
                "version": "0.4",
            },
            {"type": "session", "session_id": 7, "proto": "http"},
            {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
            {"type": "participant", "session_id": 7, "pid": 1, "endpoint": ["93.184.216.34:80"]},
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "payload": b64(DEC_REQ),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 9}
                ],
                "content_type": "dec:request",
            },
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 1,
                "source_id": 1,
                "ts": 1100,
                "payload": b64(DEC_RESP),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 7, "pid": 1, "off_start": 0, "off_end": 16}
                ],
                "content_type": "dec:response",
            },
            {
                "type": "undecoded",
                "source_id": 1,
                "session_id": 7,
                "pid": 1,
                "off_start": 16,
                "off_end": 20,
                "reason": "undecodable",
                "decoder_id": 1,
            },
            {"type": "end"},
        ],
    )
    dec_dg = "sha256:" + hashlib.sha256(dec).hexdigest()

    ann_blocks = [
        file_header(options=[o_produced_by("zpf-annotate 0.2"), o_produced_at(1719520000)]),
        # Source 1 is the GRANDPARENT, declared only so the inherited Undecoded
        # block still resolves. Source 2 is the immediate input.
        source(1, 1, [o_uri("raw.zpf"), o_digest(raw_dg)]),
        source(2, 1, [o_uri("decoded.zpf"), o_digest(dec_dg)]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        name_block(7, 1, [o_label("example.com"), o_name_kind("tls-sni")]),
        # Identity spans: same range in as out, which is what a pass-through's
        # provenance looks like since 0.19.
        record(
            7,
            0,
            2,
            1000,
            DEC_REQ,
            options=[
                o_decoder_id(1),
                o_spans([(2, 0, 7, 0, len(DEC_REQ))]),
                o_content_type("dec:request"),
            ],
        ),
        record(
            7,
            1,
            2,
            1100,
            DEC_RESP,
            options=[
                o_decoder_id(1),
                o_spans([(2, 1, 7, 0, len(DEC_RESP))]),
                o_content_type("dec:response"),
            ],
        ),
        undecoded(1, 1, 7, 16, 20, [o_reason("undecodable"), o_decoder_id(1)]),
        end_block(),
    ]
    chain_file(
        "annotated",
        "A pass-through preserving decoded.zpf's layer, adding only a "
        "label. Its records carry IDENTITY spans -- the same range in as out, "
        "which is how a preserved stream states its provenance since 0.19 -- "
        "and the inherited Undecoded block still names raw.zpf, so raw.zpf is "
        "declared too.",
        ann_blocks,
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-annotate 0.2",
                "produced_at": 1719520000,
            },
            {
                "type": "source",
                "source_id": 1,
                "kind": "zpf-input",
                "uri": "raw.zpf",
                "digest": raw_dg,
            },
            {
                "type": "source",
                "source_id": 2,
                "kind": "zpf-input",
                "uri": "decoded.zpf",
                "digest": dec_dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "http/1.1",
                "version": "0.4",
            },
            {"type": "session", "session_id": 7, "proto": "http"},
            {
                "type": "participant",
                "session_id": 7,
                "pid": 0,
                "endpoint": ["10.0.0.1:51000"],
            },
            {
                "type": "participant",
                "session_id": 7,
                "pid": 1,
                "endpoint": ["93.184.216.34:80"],
            },
            {"type": "name", "session_id": 7, "pid": 1, "label": "example.com", "kind": "tls-sni"},
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 2,
                "ts": 1000,
                "payload": b64(DEC_REQ),
                "decoder_id": 1,
                "spans": [
                    {
                        "source_id": 2,
                        "session_id": 7,
                        "pid": 0,
                        "off_start": 0,
                        "off_end": len(DEC_REQ),
                    },
                ],
                "content_type": "dec:request",
            },
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 1,
                "source_id": 2,
                "ts": 1100,
                "payload": b64(DEC_RESP),
                "decoder_id": 1,
                "spans": [
                    {
                        "source_id": 2,
                        "session_id": 7,
                        "pid": 1,
                        "off_start": 0,
                        "off_end": len(DEC_RESP),
                    },
                ],
                "content_type": "dec:response",
            },
            {
                "type": "undecoded",
                "source_id": 1,
                "session_id": 7,
                "pid": 1,
                "off_start": 16,
                "off_end": 20,
                "reason": "undecodable",
                "decoder_id": 1,
            },
            {"type": "end"},
        ],
    )


def build_splice() -> None:
    """Build Finding 3 end to end: a stage splicing across a declared break.

    This cannot be a standalone vector. The break lives in stage 1's OUTPUT, so
    a reader handed only stage 2's file has nothing to detect the violation
    from -- which is why it needs two files and why it waited for a fixture
    shape that supports them.
    """
    fixture(
        "splice",
        "isolate",
        "A decode stage reading across a declared Discontinuity without "
        "declaring one of its own. tls-records.zpf is stage 1 and is entirely "
        "conformant: two records with a Discontinuity between them, no width, "
        "because a lost TLS record's plaintext length is unknowable. http.zpf "
        "is stage 2, and it is the violation: one record whose spans cover "
        "[0,80) of stage 1's output -- straight across the break at 50 -- with "
        "no Discontinuity of its own anywhere. The break is visible at stage 1 "
        "and gone at stage 2, which is the original defect one hop along.",
        "Discontinuity (0x22) -- what a consumer owes the block",
        "Accept tls-records.zpf; it breaks no rule. ISOLATE or reject "
        "http.zpf: its record splices two regions the input declared "
        "non-contiguous, so it reads as one HTTP message where the wire "
        "carried two fragments of different ones. Note a reader handed ONLY "
        "http.zpf cannot judge it -- the file is well-framed, its coverage is "
        "complete, and nothing in it is wrong on its face. The violation is "
        "only visible with tls-records.zpf in hand, which is exactly why this "
        "is a two-file fixture.",
        violations=1,
    )

    # Stage 1: the tls-records decoder. Conformant.
    stage1_blocks = [
        file_header(options=[o_produced_by("zpf-tls 0.2"), o_produced_at(1719640000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("tls-records"), o_dec_version("0.2")]),
        session(7, [o_proto("tls")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        record(7, 0, 1, 1000, b"A" * 50, options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 100)])]),
        undecoded(1, 0, 7, 100, 139, [o_reason("gap"), o_decoder_id(1)]),
        # No width: the plaintext length the lost ciphertext would have
        # produced is not recoverable, so it contributes 0 and the two records
        # remain numerically adjacent at 50 -- which is the whole hazard.
        discontinuity(7, 0, [o_disc_reason("tls-record-lost")]),
        record(7, 0, 1, 1100, b"B" * 30, options=[o_decoder_id(1), o_spans([(1, 0, 7, 139, 200)])]),
        session_end(7, [o_input_extents([(1, 0, 7, 200)])]),
        end_block(),
    ]
    stage1 = member(
        "splice",
        "tls-records",
        "Stage 1. Conformant: it declares the break its decoder found.",
        stage1_blocks,
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-tls 0.2",
                "produced_at": 1719640000,
            },
            {
                "type": "source",
                "source_id": 1,
                "kind": "zpf-input",
                "uri": "raw.zpf",
                "digest": "sha256:9f2c",
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "tls-records",
                "version": "0.2",
            },
            {"type": "session", "session_id": 7, "proto": "tls"},
            {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "payload": b64(b"A" * 50),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 100}
                ],
            },
            {
                "type": "undecoded",
                "source_id": 1,
                "session_id": 7,
                "pid": 0,
                "off_start": 100,
                "off_end": 139,
                "reason": "gap",
                "decoder_id": 1,
            },
            {"type": "discontinuity", "session_id": 7, "pid": 0, "reason": "tls-record-lost"},
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1100,
                "payload": b64(b"B" * 30),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 7, "pid": 0, "off_start": 139, "off_end": 200}
                ],
            },
            {
                "type": "session_end",
                "session_id": 7,
                "input_extents": [{"source_id": 1, "session_id": 7, "pid": 0, "extent": 200}],
            },
            {"type": "end"},
        ],
    )
    stage1_dg = "sha256:" + hashlib.sha256(stage1).hexdigest()

    # Stage 2: the http decoder, reading stage 1's OUTPUT space. The violation.
    stage2_blocks = [
        file_header(options=[o_produced_by("zpf-http 0.4"), o_produced_at(1719650000)]),
        source(1, 1, [o_uri("tls-records.zpf"), o_digest(stage1_dg)]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        # THE VIOLATION: [0,80) crosses the break at 50, and this file declares
        # no Discontinuity of its own.
        record(
            7,
            0,
            1,
            1000,
            b"GET /spliced",
            options=[o_decoder_id(1), o_spans([(1, 0, 7, 0, 80)]), o_content_type("dec:request")],
        ),
        session_end(7, [o_input_extents([(1, 0, 7, 80)])]),
        end_block(),
    ]
    member(
        "splice",
        "http",
        "Stage 2. The violation: one record spanning [0,80) of stage 1's "
        "output, straight across the break at 50, declaring nothing.",
        stage2_blocks,
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-http 0.4",
                "produced_at": 1719650000,
            },
            {
                "type": "source",
                "source_id": 1,
                "kind": "zpf-input",
                "uri": "tls-records.zpf",
                "digest": stage1_dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "http/1.1",
                "version": "0.4",
            },
            {"type": "session", "session_id": 7, "proto": "http"},
            {"type": "participant", "session_id": 7, "pid": 0, "endpoint": ["10.0.0.1:51000"]},
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "payload": b64(b"GET /spliced"),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 80}
                ],
                "content_type": "dec:request",
            },
            {
                "type": "session_end",
                "session_id": 7,
                "input_extents": [{"source_id": 1, "session_id": 7, "pid": 0, "extent": 80}],
            },
            {"type": "end"},
        ],
    )


# ------------------------------------------------------------------- the tunnel
#
# Four files, one direction of a WireGuard tunnel. #41's case D, and the fixture
# that walks every part of 0.15 at once:
#
#   wg.pcap --[capture]--> outer.zpf --[wireguard-decrypt]--> packets.zpf
#                          UDP datagrams                      inner IP packets
#                          capture / transport                zpf / decoded
#
#   packets.zpf --[tcp-reassembly]--> inner.zpf --[http/1.1]--> http.zpf
#                                     two TCP flows             messages
#                                     zpf / TRANSPORT           zpf / decoded
#
# One direction only: a one-way feed is the N = 1 case the format already models,
# and nothing here needs a second direction. The offsets below are worked out in
# the release plan and re-derived by check_tunnel(), so a drift shows up as a
# failure rather than as a fixture nobody rechecked.

WG1, WG2, WG3, WG4 = (bytes([c]) * 80 for c in b"WXYZ")  # 4 ciphertext datagrams
IP_A1, IP_B1, IP_A2 = b"P" * 60, b"Q" * 40, b"R" * 50  # inner packets, once decrypted
TCP_A1, TCP_A2, TCP_B1 = b"a" * 40, b"b" * 30, b"c" * 20  # inner TCP payloads


def build_tunnel() -> None:
    """Build the four-file decrypted-tunnel chain."""
    fixture(
        "tunnel",
        "accept",
        "A decrypted tunnel, end to end: outer.zpf -> packets.zpf -> inner.zpf "
        "-> http.zpf. #41's case D, and the fixture that exercises the whole of "
        "0.15 at once. FOUR THINGS TO READ IT FOR. (1) CORRESPONDENCE, NOT "
        "IDENTITY: each inner packet spans the WHOLE outer datagram, nonce and "
        "tag included, because those fed the computation -- so tunnel coverage "
        "closes with no skipped Undecoded blocks at all. (2) FAN-OUT: one input "
        "stream (packets.zpf session 5, pid 0) feeds TWO output sessions in "
        "inner.zpf; neither covers the extent alone and both Session Ends "
        "declare the same 150 for the shared input. (3) A zpf-SOURCED TRANSPORT "
        "STREAM: inner.zpf declares output_layer = transport, carries isn and "
        "seq_start, and expresses its 40-byte hole in the SEQUENCE NUMBERS -- no "
        "Discontinuity, no content_type. (4) ORIGINATION, AND THE CROSSING LEFT "
        "UNDONE: packets.zpf withholds an inner packet and declares the break; "
        "inner.zpf reads that break and CANNOT express one, so no record crosses "
        "packets offset 100 and the loss survives as a TCP gap instead; http.zpf "
        "then meets a hole-class region between two adjacent output units and "
        "originates its own block.",
        "Layers; Conformance; Discontinuity; Worked example: a decrypted tunnel",
        "Accept all four. Each .jsonl is the expected projection, and each "
        "declared digest is the real SHA-256 of the sibling it names, so the "
        "whole chain verifies. A reader that infers a stream's layer from its "
        "Source kind gets inner.zpf wrong; one that assumes a decode stage's "
        "output sessions mirror its input's gets inner.zpf wrong too.",
        violations=0,
    )

    # ---- 1. outer.zpf -- the capture. UDP, so no seq_start and no isn. -------
    outer_blocks = [
        file_header(options=[o_creator("zpf-sessionize 1.0")]),
        source(1, 0, [o_uri("wg.pcap"), o_link_type(1)]),
        session(1, [o_proto("udp"), o_flow_key("198.51.100.7:51820 -> 203.0.113.9:51820")]),
        participant(1, 0, [o_endpoint("198.51.100.7:51820")]),
        record(1, 0, 1, 1000, WG1, flags=0x0080),
        record(1, 0, 1, 1100, WG2, flags=0x0080),
        record(1, 0, 1, 1200, WG3, flags=0x0080),
        record(1, 0, 1, 1300, WG4, flags=0x0080),
        end_block(),
    ]
    outer = member(
        "tunnel",
        "outer",
        "The capture: four encrypted WireGuard datagrams, 80 bytes each. A "
        "transport stream with no isn, so byte 0 is the first captured byte and "
        "the four occupy [0,80) [80,160) [160,240) [240,320).",
        outer_blocks,
        [
            {"type": "file", "format": FORMAT, "tick_hz": 1000000, "creator": "zpf-sessionize 1.0"},
            {
                "type": "source",
                "source_id": 1,
                "kind": "capture",
                "uri": "wg.pcap",
                "link_type": 1,
            },
            {
                "type": "session",
                "session_id": 1,
                "proto": "udp",
                "key": "198.51.100.7:51820 -> 203.0.113.9:51820",
            },
            {"type": "participant", "session_id": 1, "pid": 0, "endpoint": ["198.51.100.7:51820"]},
            *(
                {
                    "type": "record",
                    "session_id": 1,
                    "sender_pid": 0,
                    "source_id": 1,
                    "ts": ts,
                    "flags": ["message"],
                    "payload": b64(p),
                }
                for ts, p in ((1000, WG1), (1100, WG2), (1200, WG3), (1300, WG4))
            ),
            {"type": "end"},
        ],
    )
    outer_dg = "sha256:" + hashlib.sha256(outer).hexdigest()

    # ---- 2. packets.zpf -- decrypt. One record per inner packet. ------------
    packets_blocks = [
        file_header(options=[o_produced_by("zpf-wg 0.3"), o_produced_at(1719700000)]),
        source(1, 1, [o_uri("outer.zpf"), o_digest(outer_dg)]),
        decoder(
            1,
            [o_dec_name("wireguard-decrypt"), o_dec_version("0.3"), o_params_digest("sha256:aa10")],
        ),
        session(5, [o_proto("ip")]),
        participant(5, 0, [o_endpoint("10.8.0.2")]),
        # Each inner packet spans the WHOLE datagram: the nonce and tag are
        # inputs to the computation, so they are honestly spanned rather than
        # marked skipped. That is what closes tunnel coverage with no Undecoded
        # blocks for framing.
        record(
            5,
            0,
            1,
            1000,
            IP_A1,
            options=[o_decoder_id(1), o_spans([(1, 0, 1, 0, 80)]), o_content_type("dec:ip-packet")],
        ),
        record(
            5,
            0,
            1,
            1100,
            IP_B1,
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 1, 80, 160)]),
                o_content_type("dec:ip-packet"),
            ],
        ),
        # Datagram 3 will not decrypt. The ciphertext exists, so this is
        # bytes-class, not a hole -- and "decrypt-failed" is outside the
        # canonical four, so reason_class is mandatory.
        undecoded(
            1,
            0,
            1,
            160,
            240,
            [o_reason("decrypt-failed"), o_reason_class("bytes"), o_decoder_id(1)],
        ),
        # An inner packet is missing from this output, so the records either
        # side of it do not join and this file MUST say so. No width: the lost
        # plaintext's length is not recoverable from ciphertext we cannot read.
        discontinuity(5, 0, [o_disc_reason("decrypt-failed")]),
        record(
            5,
            0,
            1,
            1300,
            IP_A2,
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 1, 240, 320)]),
                o_content_type("dec:ip-packet"),
            ],
        ),
        session_end(5, [o_input_extents([(1, 0, 1, 320)])]),
        end_block(),
    ]
    packets = member(
        "tunnel",
        "packets",
        "The decrypt stage. One record per inner IP packet, typed dec:ip-packet "
        "because a packet IS a unit -- unlike a reassembly window, which is a "
        "slice. Its own offset space is the payload concatenation: [0,60) "
        "[60,100) [100,150), the Discontinuity contributing 0.",
        packets_blocks,
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-wg 0.3",
                "produced_at": 1719700000,
            },
            {
                "type": "source",
                "source_id": 1,
                "kind": "zpf-input",
                "uri": "outer.zpf",
                "digest": outer_dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "wireguard-decrypt",
                "version": "0.3",
                "params_digest": "sha256:aa10",
            },
            {"type": "session", "session_id": 5, "proto": "ip"},
            {"type": "participant", "session_id": 5, "pid": 0, "endpoint": ["10.8.0.2"]},
            {
                "type": "record",
                "session_id": 5,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "payload": b64(IP_A1),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 1, "pid": 0, "off_start": 0, "off_end": 80}
                ],
                "content_type": "dec:ip-packet",
            },
            {
                "type": "record",
                "session_id": 5,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1100,
                "payload": b64(IP_B1),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 1, "pid": 0, "off_start": 80, "off_end": 160}
                ],
                "content_type": "dec:ip-packet",
            },
            {
                "type": "undecoded",
                "source_id": 1,
                "session_id": 1,
                "pid": 0,
                "off_start": 160,
                "off_end": 240,
                "reason": "decrypt-failed",
                "reason_class": "bytes",
                "decoder_id": 1,
            },
            {"type": "discontinuity", "session_id": 5, "pid": 0, "reason": "decrypt-failed"},
            {
                "type": "record",
                "session_id": 5,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1300,
                "payload": b64(IP_A2),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 1, "pid": 0, "off_start": 240, "off_end": 320}
                ],
                "content_type": "dec:ip-packet",
            },
            {
                "type": "session_end",
                "session_id": 5,
                "input_extents": [{"source_id": 1, "session_id": 1, "pid": 0, "extent": 320}],
            },
            {"type": "end"},
        ],
    )
    packets_dg = "sha256:" + hashlib.sha256(packets).hexdigest()

    # ---- 3. inner.zpf -- reassembly. TRANSPORT layer, and it fans out. ------
    inner_blocks = [
        file_header(options=[o_produced_by("zpf-sessionize 1.0"), o_produced_at(1719700100)]),
        source(1, 1, [o_uri("packets.zpf"), o_digest(packets_dg)]),
        decoder(
            1,
            [o_dec_name("tcp-reassembly"), o_dec_version("1.1"), o_params_digest("sha256:2f60")],
            output_layer=1,
        ),
        # Flow A: the HTTP connection, and the one with the hole.
        session(10, [o_proto("tcp"), o_flow_key("10.8.0.2:44300 -> 10.8.0.9:80")]),
        participant(10, 0, [o_endpoint("10.8.0.2:44300"), o_isn(1000)]),
        record(
            10,
            0,
            1,
            1000,
            TCP_A1,
            options=[o_decoder_id(1), o_spans([(1, 0, 5, 0, 60)]), o_seq_start(1001)],
        ),
        # seq 1081, not 1041: the 40 bytes the lost packet carried occupy
        # [40,80) and no record covers them. The hole is in the NUMBERS -- this
        # stream is forbidden a Discontinuity, and does not need one.
        record(
            10,
            0,
            1,
            1300,
            TCP_A2,
            options=[o_decoder_id(1), o_spans([(1, 0, 5, 100, 150)]), o_seq_start(1081)],
        ),
        session_end(10, [o_input_extents([(1, 0, 5, 150)])]),
        # Flow B: a second inner connection out of the SAME input stream.
        session(11, [o_proto("tcp"), o_flow_key("10.8.0.2:44301 -> 10.8.0.9:53")]),
        participant(11, 0, [o_endpoint("10.8.0.2:44301"), o_isn(5000)]),
        record(
            11,
            0,
            1,
            1100,
            TCP_B1,
            options=[o_decoder_id(1), o_spans([(1, 0, 5, 60, 100)]), o_seq_start(5001)],
        ),
        # The same extent 150 as session 10 declares: under fan-out every
        # consuming session declares the WHOLE input stream, not its share.
        session_end(11, [o_input_extents([(1, 0, 5, 150)])]),
        end_block(),
    ]
    inner = member(
        "tunnel",
        "inner",
        "The sessionization stage, and the file this whole release was for. A "
        "zpf-SOURCED TRANSPORT stream: its Decoder declares output_layer = "
        "transport, so isn-anchored hole-inclusive offsets apply even though a "
        "decode stage produced it. It FANS OUT -- one input stream into sessions "
        "10 and 11, neither covering [0,150) alone. Flow A's lost packet is a "
        "40-byte hole at [40,80), visible as seq 1081 where 1041 would be "
        "contiguous. No Discontinuity: a transport stream may not carry one, and "
        "no record crosses the break its input declared at packets offset 100.",
        inner_blocks,
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-sessionize 1.0",
                "produced_at": 1719700100,
            },
            {
                "type": "source",
                "source_id": 1,
                "kind": "zpf-input",
                "uri": "packets.zpf",
                "digest": packets_dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "transport",
                "name": "tcp-reassembly",
                "version": "1.1",
                "params_digest": "sha256:2f60",
            },
            {
                "type": "session",
                "session_id": 10,
                "proto": "tcp",
                "key": "10.8.0.2:44300 -> 10.8.0.9:80",
            },
            {
                "type": "participant",
                "session_id": 10,
                "pid": 0,
                "endpoint": ["10.8.0.2:44300"],
                "isn": 1000,
            },
            {
                "type": "record",
                "session_id": 10,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "payload": b64(TCP_A1),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 0, "off_end": 60}
                ],
                "seq_start": 1001,
            },
            {
                "type": "record",
                "session_id": 10,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1300,
                "payload": b64(TCP_A2),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 100, "off_end": 150}
                ],
                "seq_start": 1081,
            },
            {
                "type": "session_end",
                "session_id": 10,
                "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": 150}],
            },
            {
                "type": "session",
                "session_id": 11,
                "proto": "tcp",
                "key": "10.8.0.2:44301 -> 10.8.0.9:53",
            },
            {
                "type": "participant",
                "session_id": 11,
                "pid": 0,
                "endpoint": ["10.8.0.2:44301"],
                "isn": 5000,
            },
            {
                "type": "record",
                "session_id": 11,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1100,
                "payload": b64(TCP_B1),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 60, "off_end": 100}
                ],
                "seq_start": 5001,
            },
            {
                "type": "session_end",
                "session_id": 11,
                "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": 150}],
            },
            {"type": "end"},
        ],
    )
    inner_dg = "sha256:" + hashlib.sha256(inner).hexdigest()

    # ---- 4. http.zpf -- decode flow A. The origination duty fires here. -----
    http_blocks = [
        file_header(options=[o_produced_by("zpf-http 0.4"), o_produced_at(1719700200)]),
        source(1, 1, [o_uri("inner.zpf"), o_digest(inner_dg)]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(20, [o_proto("http")]),
        participant(20, 0, [o_endpoint("10.8.0.2:44300")]),
        record(
            20,
            0,
            1,
            1000,
            b"REQ:GET /",
            options=[o_decoder_id(1), o_spans([(1, 0, 10, 0, 40)]), o_content_type("dec:request")],
        ),
        # The transport hole, named in the input's space. hole-class, canonical.
        undecoded(1, 0, 10, 40, 80, [o_reason("gap"), o_decoder_id(1)]),
        # ORIGINATION: a hole-class region between the input regions of two
        # adjacent output units. No content can have crossed it, so these two
        # records do not join and this file must say so.
        discontinuity(20, 0, [o_disc_reason("stream-gap")]),
        record(
            20,
            0,
            1,
            1300,
            b"RESP:200",
            options=[
                o_decoder_id(1),
                o_spans([(1, 0, 10, 80, 110)]),
                o_content_type("dec:response"),
            ],
        ),
        session_end(20, [o_input_extents([(1, 0, 10, 110)])]),
        end_block(),
    ]
    member(
        "tunnel",
        "http",
        "The last hop, decoding flow A only -- session 11 is simply not an "
        "input here, which is legal and ordinary. This is where Finding 3's "
        "duty fires at the end of four hops: the transport hole is a hole-class "
        "Undecoded region between two adjacent output units, so the records "
        "either side cannot join and this file ORIGINATES a Discontinuity. "
        "isolate-unmarked-break is this file with that block deleted.",
        http_blocks,
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-http 0.4",
                "produced_at": 1719700200,
            },
            {
                "type": "source",
                "source_id": 1,
                "kind": "zpf-input",
                "uri": "inner.zpf",
                "digest": inner_dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "http/1.1",
                "version": "0.4",
            },
            {"type": "session", "session_id": 20, "proto": "http"},
            {"type": "participant", "session_id": 20, "pid": 0, "endpoint": ["10.8.0.2:44300"]},
            {
                "type": "record",
                "session_id": 20,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "payload": b64(b"REQ:GET /"),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 10, "pid": 0, "off_start": 0, "off_end": 40}
                ],
                "content_type": "dec:request",
            },
            {
                "type": "undecoded",
                "source_id": 1,
                "session_id": 10,
                "pid": 0,
                "off_start": 40,
                "off_end": 80,
                "reason": "gap",
                "decoder_id": 1,
            },
            {"type": "discontinuity", "session_id": 20, "pid": 0, "reason": "stream-gap"},
            {
                "type": "record",
                "session_id": 20,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1300,
                "payload": b64(b"RESP:200"),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 10, "pid": 0, "off_start": 80, "off_end": 110}
                ],
                "content_type": "dec:response",
            },
            {
                "type": "session_end",
                "session_id": 20,
                "input_extents": [{"source_id": 1, "session_id": 10, "pid": 0, "extent": 110}],
            },
            {"type": "end"},
        ],
    )


# ------------------------------------------------------------------ emitters


def assemble(blocks: list[Blk]) -> list[Piece]:
    pieces = []
    for b in blocks:
        pieces.extend(b)
        pieces.append(P(b"", ""))  # blank line between blocks in the dump
    return pieces


# Which block types and option ids a vector actually emits, read back out of the
# annotations that option() and block() generate from those very ids. Recovering
# them this way rather than tracking them in a global keeps it exact: the
# annotation is produced *from* the id, so the two cannot drift, and it works
# identically for the chain fixture, whose blocks are built later than the rest.
#
# check.py compares this against the option registry and block-type table parsed
# out of the specification, so a capability cannot ship unexercised. It is the
# same declared-not-computed principle as `violations`: nothing here parses a
# block body, which would make the checker the conformant reader it must not be.
_BLOCK_ANN = re.compile(r"^type   = 0x([0-9A-F]{4})")
_OPT_ANN = re.compile(r"^option 0x([0-9A-F]{4}) ")


def exercised(pieces: list[Piece]) -> tuple[list[str], list[str]]:
    blocks, options = set(), set()
    for _data, ann in pieces:
        m = _BLOCK_ANN.match(ann)
        if m:
            blocks.add(f"0x{int(m.group(1), 16):02X}")
            continue
        m = _OPT_ANN.match(ann)
        if m:
            options.add(f"0x{m.group(1)}")
    return sorted(blocks), sorted(options)


def to_bytes(pieces: list[Piece]) -> bytes:
    return b"".join(b for b, _ in pieces)


def to_hexdump(pieces: list[Piece], title: str) -> str:
    lines = [
        f"# {title}",
        "#",
        "# Generated from the same description as the .zpf -- never edited",
        "# by hand, so the annotation cannot drift from the bytes.",
        "",
    ]
    off = 0
    for data, ann in pieces:
        if not data:
            lines.append("")
            continue
        # Split long values across lines of 8 bytes, annotating the first.
        for i in range(0, len(data), 8):
            chunk = data[i : i + 8]
            hexs = " ".join(f"{c:02X}" for c in chunk)
            note = ann if i == 0 else ""
            lines.append(f"{off:04X}  {hexs:<24} {note}".rstrip())
            off += len(chunk)
    lines.append(f"{off:04X}                           (end of file, {off} bytes)")
    return "\n".join(lines) + "\n"


def jsonl_bytes(objs: list[dict]) -> bytes:
    """Render a vector's expected projection, one compact object per line."""
    return ("\n".join(json.dumps(o, separators=(",", ":")) for o in objs) + "\n").encode()


def emit(d: str, files: dict[str, bytes], label: str, check: bool) -> list[str]:
    """Write a fixture's files, or verify the committed ones match.

    One function for both directions so the two cannot drift -- a --check that
    tested something other than what a plain run writes would be worse than none.
    """
    if not check:
        os.makedirs(d, exist_ok=True)
        for fn, data in files.items():
            with open(os.path.join(d, fn), "wb") as f:
                f.write(data)
        return []
    problems = []
    for fn, want in files.items():
        path = os.path.join(d, fn)
        if not os.path.exists(path):
            problems.append(f"missing {label}/{fn}")
        elif read_bytes(path) != want:
            problems.append(f"stale {label}/{fn}")
    return problems


def main() -> int:
    check = "--check" in sys.argv
    build_chain()
    build_splice()
    build_tunnel()
    manifest = []
    problems = []

    # The chain lives in one directory: its three files are a single fixture,
    # and only together do the digests and offsets mean anything.
    fixture_entries = []
    for fx in FIXTURES.values():
        fdir = os.path.join(HERE, fx["name"])
        files, f_blocks, f_options = {}, set(), set()
        for c in fx["members"]:
            pieces = assemble(c["blocks"])
            b_types, o_ids = exercised(pieces)
            f_blocks.update(b_types)
            f_options.update(o_ids)
            files[f"{c['name']}.zpf"] = to_bytes(pieces)
            files[f"{c['name']}.hex"] = to_hexdump(pieces, f"{fx['name']}/{c['name']}").encode()
            files[f"{c['name']}.jsonl"] = jsonl_bytes(c["jsonl"])
        problems += emit(fdir, files, fx["name"], check)
        fixture_entries.append(
            {
                "name": fx["name"],
                "tier": fx["tier"],
                "violations": fx["violations"],
                "blocks": sorted(f_blocks),
                "options": sorted(f_options),
                "bytes": sum(len(v) for k, v in files.items() if k.endswith(".zpf")),
                "summary": fx["summary"],
                "spec_section": fx["spec"],
                "expect": fx["expect"],
                "has_jsonl": True,
                "files": sorted(files),
            }
        )
    for v in VECTORS:
        pieces = assemble(v["blocks"])
        raw = to_bytes(pieces)
        d = os.path.join(HERE, v["name"])
        files = {
            f"{v['name']}.zpf": raw,
            f"{v['name']}.hex": to_hexdump(pieces, v["name"]).encode(),
        }
        if v["jsonl"] is not None:
            files[f"{v['name']}.jsonl"] = jsonl_bytes(v["jsonl"])
        problems += emit(d, files, v["name"], check)
        b_types, o_ids = exercised(pieces)
        manifest.append(
            {
                "name": v["name"],
                "tier": v["tier"],
                "violations": v["violations"],
                **({"advisory": True} if v["advisory"] else {}),
                "bytes": len(raw),
                "blocks": b_types,
                "options": o_ids,
                "summary": v["summary"],
                "spec_section": v["spec"],
                "expect": v["expect"] or ("Accept. The .jsonl file is the expected projection."),
                "has_jsonl": v["jsonl"] is not None,
            }
        )

    manifest += fixture_entries

    mtext = json.dumps({"format": FORMAT, "vectors": manifest}, indent=2) + "\n"
    mpath = os.path.join(HERE, "manifest.json")
    if check:
        if not os.path.exists(mpath) or read_text(mpath) != mtext:
            problems.append("stale manifest.json")
        if problems:
            print("\n".join(problems))
            return 1
        print(f"{len(VECTORS)} vectors + {len(FIXTURES)} fixtures up to date")
        return 0
    with open(mpath, "w") as f:
        f.write(mtext)
    n = sum(len(f["members"]) for f in FIXTURES.values())
    print(f"wrote {len(VECTORS)} vectors + {len(FIXTURES)} fixtures ({n} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
