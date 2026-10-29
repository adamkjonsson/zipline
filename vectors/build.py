#!/usr/bin/env python3
"""Build the Zipline Payload Format conformance vectors.

Hand-written from docs/zipline-payload-format.md. This is NOT a reader or a
writer for the format, and no vector here is produced by round-tripping through
an implementation -- see README.md for why that distinction is the whole point.

Every block is spelled out field by field, with an annotation per field. The
binary and the annotated hex dump come from that one description, so the dump
can never drift from the bytes. The expected JSONL is written separately, by
hand, so that the two faces of each vector are independent statements about the
same file rather than derivations of one another -- and since 0.20 the two are
compared at registration, so a vector whose bytes do not project to its JSONL
fails here rather than in a downstream port (#141).

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
MAJOR, MINOR = 0, 24
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


class Opt(list):
    """A TLV option: its pieces, plus the logical value the projection renders.

    The pieces are what the bytes and the hex dump are built from. `value` is
    what the .jsonl face is expected to say for this option -- the string, the
    integer, the raw bytes, or for a packed option its entries as dicts -- and is
    what `project()` reads. Until 0.20 a helper returned bare pieces, so the
    builder knew every byte it wrote and nothing of what it meant, and the two
    faces of a vector could disagree with nothing to notice (#141).
    """

    def __init__(self, pieces: list[Piece], oid: int, name: str, value: object) -> None:
        super().__init__(pieces)
        self.oid = oid
        self.name = name
        self.value = value


class Blk(list):
    """A block: its pieces, plus the body fields and options the projection renders.

    `fields` maps each body field's CANONICAL binary name to its logical value;
    `project()` applies the brevity aliases and the value encodings. `None` marks
    a block of a type this version does not define, which projects through the
    unknown-block escape and has no fields to name.
    """

    def __init__(
        self, pieces: list[Piece], btype: int, fields: dict | None, options: list[Opt]
    ) -> None:
        super().__init__(pieces)
        self.btype = btype
        self.fields = fields
        self.options = options


def P(b: bytes, ann: str = "") -> Piece:
    return (b, ann)


def option(oid: int, value: bytes, name: str, note: str = "", *, logical: object = None) -> Opt:
    """TLV option: id u16, len u16, value, padded to a 4-byte boundary.

    len counts the value only, never the 4-byte option header or the padding.
    `logical` is the value the projection renders; it defaults to the raw bytes,
    which is right for a `bytes`-typed option and for an unregistered one.
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
    return Opt(out, oid, name, value if logical is None else logical)


def _describe(value: bytes) -> str:
    try:
        s = value.decode("ascii")
        if s.isprintable():
            return f'"{s}"'
    except UnicodeDecodeError:
        pass
    return ""


def block(
    btype: int,
    name: str,
    body: list[Piece],
    options: tuple[Opt, ...] | list[Opt] = (),
    *,
    fields: dict | None,
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
    return Blk(head + content, btype, fields, list(options))


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
    # `format` is the alias for the version pair; magic is framing and does not
    # project.
    fields = {"format": f"zipline-payload/{major}.{minor}", "tick_hz": tick_hz}
    return block(0x01, "File Header", body, options, fields=fields)


def source(source_id: int, kind: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    kind_name = ENUMS["kind"].get(kind, "UNDEFINED")
    body = [
        P(u16(source_id), f"source_id = {source_id}"),
        P(u8(kind), f"kind = {kind}  ({kind_name})"),
        P(u8(0), "_reserved"),
    ]
    fields = {"source_id": source_id, "kind": kind}
    return block(0x02, "Source Descriptor", body, options, fields=fields)


def decoder(
    decoder_id: int, options: tuple[Opt, ...] | list[Opt] = (), output_layer: int = 0
) -> Blk:
    """Build a Decoder Descriptor (0x03).

    output_layer is a BODY field, not an option: 0 = decoded, 1 = transport.
    Numbering decoded 0 is what makes it fit the old _reserved u16 without
    changing a byte of any file written before it existed -- every one of those
    holds 0 there, and every one of them meant decoded.
    """
    layer_name = ENUMS["output_layer"].get(output_layer, "?")
    body = [
        P(u16(decoder_id), f"decoder_id = {decoder_id}"),
        P(u8(output_layer), f"output_layer = {output_layer}  ({layer_name})"),
        P(u8(0), "_reserved"),
    ]
    fields = {"decoder_id": decoder_id, "output_layer": output_layer}
    return block(0x03, "Decoder Descriptor", body, options, fields=fields)


def session(session_id: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    body = [P(u64(session_id), f"session_id = {session_id}  (u64)")]
    return block(0x10, "Session Descriptor", body, options, fields={"session_id": session_id})


def session_end(session_id: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    body = [P(u64(session_id), f"session_id = {session_id}  (u64)")]
    return block(0x12, "Session End", body, options, fields={"session_id": session_id})


def participant(
    session_id: int, pid: int, options: tuple[Opt, ...] | list[Opt] = (), adjacency: int = 0
) -> Blk:
    """Build a Participant Descriptor (0x11).

    adjacency is a BODY field, not an option: 0 = contiguous, 1 = units. It took
    the reserved u16's first byte in 0.21 the way output_layer took the
    Decoder's, and numbering contiguous 0 is what made that free -- every file
    written before it holds 0 there, and every one of them meant that stored
    neighbours join.
    """
    adj_name = ENUMS["adjacency"].get(adjacency, "?")
    body = [
        P(u64(session_id), f"session_id = {session_id}  (u64)"),
        P(u16(pid), f"participant_id = {pid}"),
        P(u8(adjacency), f"adjacency = {adjacency}  ({adj_name})"),
        P(u8(0), "_reserved"),
    ]
    fields = {"session_id": session_id, "participant_id": pid, "adjacency": adjacency}
    return block(0x11, "Participant Descriptor", body, options, fields=fields)


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
    # payload_len is framing and does not project; the base64 payload's own
    # length stands in for it.
    fields = {
        "session_id": session_id,
        "sender_pid": sender_pid,
        "source_id": source_id,
        "timestamp": timestamp,
        "flags": flags,
        "payload": payload,
    }
    return block(0x20, "Record", body, options, fields=fields)


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
    fields = {
        "source_id": source_id,
        "participant_id": pid,
        "session_id": session_id,
        "off_start": off_start,
        "off_end": off_end,
    }
    return block(0x21, "Undecoded", body, options, fields=fields)


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
    fields = {"session_id": session_id, "participant_id": pid}
    return block(0x22, "Discontinuity", body, options, fields=fields)


def name_block(session_id: int, pid: int, options: tuple[Opt, ...] | list[Opt] = ()) -> Blk:
    body = [
        P(u64(session_id), f"session_id = {session_id}"),
        P(u16(pid), f"participant_id = {pid}"),
        P(u16(0), "_reserved"),
    ]
    fields = {"session_id": session_id, "participant_id": pid}
    return block(0x30, "Name/Identity Resolution", body, options, fields=fields)


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
    fields = {"pen": pen, "subtype": subtype, "payload": payload}
    return block(0xFF, "Custom", body, fields=fields)


def end_block() -> Blk:
    body = [P(u32(0x5A454E44), 'end_magic = 0x5A454E44  ("ZEND")')]
    return block(0x41, "End of file", body, fields={})


def unknown_block(btype: int, content_bytes: bytes) -> Blk:
    """Build a block of a type this document does not define.

    The forward-compatibility case a reader must skip by length.
    """
    return block(
        btype, "UNKNOWN to this version", [P(content_bytes, "opaque content")], fields=None
    )


# ------------------------------------------------------------ option helpers


def s(x: str) -> bytes:
    return x.encode("utf-8")


def o_comment(v: str) -> Opt:
    return option(0x0001, s(v), "comment", logical=v)


def o_creator(v: str) -> Opt:
    return option(0x0011, s(v), "creator", logical=v)


def o_produced_by(v: str) -> Opt:
    return option(0x0012, s(v), "produced_by", logical=v)


def o_produced_at(v: int) -> Opt:
    return option(0x0013, i64(v), "produced_at", str(v), logical=v)


def o_transform_params_digest(v: str) -> Opt:
    return option(0x0015, s(v), "transform_params_digest", logical=v)


def o_uri(v: str) -> Opt:
    return option(0x0020, s(v), "uri", logical=v)


def o_digest(v: str) -> Opt:
    return option(0x0021, s(v), "digest", logical=v)


def o_dec_name(v: str) -> Opt:
    return option(0x0041, s(v), "name", logical=v)


def o_dec_version(v: str) -> Opt:
    return option(0x0042, s(v), "version", logical=v)


def o_params_digest(v: str) -> Opt:
    return option(0x0043, s(v), "params_digest", logical=v)


def o_proto(v: str) -> Opt:
    return option(0x0050, s(v), "proto", logical=v)


def o_flow_key(v: str) -> Opt:
    return option(0x0051, s(v), "flow_key", logical=v)


def o_sess_flags(v: int) -> Opt:
    return option(0x0052, u16(v), "flags", f"0x{v:04X}", logical=v)


def o_external_sid(v: bytes) -> Opt:
    return option(0x0054, v, "external_session_id", f"{len(v)} opaque bytes")


def o_endpoint(v: str) -> Opt:
    return option(0x0060, s(v), "endpoint", logical=v)


def o_time_epoch(v: int) -> Opt:
    return option(0x0010, i64(v), "time_epoch", str(v), logical=v)


def o_link_type(v: int) -> Opt:
    return option(0x0022, u16(v), "link_type", str(v), logical=v)


def o_identity(v: str) -> Opt:
    return option(0x0062, s(v), "identity", logical=v)


def o_ts_first(v: int) -> Opt:
    return option(0x0073, i64(v), "ts_first", str(v), logical=v)


def o_isn(v: int) -> Opt:
    return option(0x0061, u32(v), "isn", str(v), logical=v)


def o_tcp_role(v: int) -> Opt:
    return option(0x0063, u8(v), "tcp_role", str(v), logical=v)


def o_seq_start(v: int) -> Opt:
    return option(0x0070, u32(v), "seq_start", str(v), logical=v)


def o_ack(v: int) -> Opt:
    return option(0x0072, u32(v), "ack", str(v), logical=v)


def o_spans(entries: list[tuple[int, int, int, int, int]]) -> Opt:
    """Build a spans option from `(source_id, session_id, pid, off_start, off_end)` tuples.

    The tuple is in LOGICAL order -- the order every prose statement of the
    triple uses, and the order the JSONL spells it. The bytes put the two u16s
    first, for alignment only, and until 0.20 so did this helper's argument
    list: `(source, pid, session, ...)`, an order a reader had to know NOT to
    assume. mixed-derivation was written in logical order against it and
    shipped a span citing pid 8 of session 0 (#141, defect 6).
    """
    packed = b"".join(
        u16(src) + u16(pid) + u64(sess) + u64(a) + u64(b) for src, sess, pid, a, b in entries
    )
    logical = [
        {"source_id": src, "session_id": sess, "pid": pid, "off_start": a, "off_end": b}
        for src, sess, pid, a, b in entries
    ]
    return option(0x0080, packed, "spans", f"{len(entries)} entry/entries", logical=logical)


def o_decoder_id(v: int) -> Opt:
    return option(0x0090, u16(v), "decoder_id", str(v), logical=v)


def o_content_type(v: str) -> Opt:
    return option(0x0091, s(v), "content_type", logical=v)


def o_role(v: str) -> Opt:
    return option(0x0092, s(v), "role", logical=v)


def o_reason(v: str) -> Opt:
    return option(0x00A0, s(v), "reason", logical=v)


def o_reason_class(v: str) -> Opt:
    return option(0x00A1, s(v), "reason_class", logical=v)


def o_end_reason(v: str) -> Opt:
    return option(0x00C0, s(v), "reason", logical=v)


def o_input_extents(entries: list[tuple[int, int, int, int]]) -> Opt:
    """Build an input_extents option from `(source_id, session_id, pid, extent)` tuples.

    Logical order, as o_spans: the u16s lead in the bytes only for alignment.
    """
    packed = b"".join(u16(src) + u16(pid) + u64(sess) + u64(ext) for src, sess, pid, ext in entries)
    logical = [
        {"source_id": src, "session_id": sess, "pid": pid, "extent": ext}
        for src, sess, pid, ext in entries
    ]
    return option(0x00C1, packed, "input_extents", f"{len(entries)} entry/entries", logical=logical)


def o_width(v: int) -> Opt:
    return option(0x00D0, u64(v), "width", str(v), logical=v)


def o_disc_reason(v: str) -> Opt:
    return option(0x00D1, s(v), "reason", logical=v)


def o_label(v: str) -> Opt:
    return option(0x00B0, s(v), "label", logical=v)


def o_name_kind(v: str) -> Opt:
    return option(0x00B1, s(v), "kind", logical=v)


def o_unregistered(oid: int, v: bytes) -> Opt:
    return option(oid, v, "UNREGISTERED")


# ----------------------------------------------------------------- projection

# The JSONL <-> binary mapping, as build.py knows it: the `type` strings, the
# brevity aliases, the enum labels and the flag tokens the specification's
# mapping section and enum tables define. This is the ONE place the builder
# says what its bytes mean, and it exists so that the hand-authored .jsonl can
# be checked against the description that emitted the bytes rather than trusted
# beside it. Three vectors shipped with the two faces disagreeing (#141, defects
# 5 and 6); nothing could see it, because the .hex is generated from the same
# description as the .zpf and check.py parses no block body by design.
#
# The .jsonl files stay hand-written. Generating them from this projector would
# remove the disagreement by removing the second opinion -- a wrong value would
# produce two matching wrong faces. Comparing keeps the second opinion, and the
# 40 hand-authored projections are this projector's test suite as much as it is
# theirs.

TYPE_NAMES = {
    0x01: "file",
    0x02: "source",
    0x03: "decoder",
    0x10: "session",
    0x11: "participant",
    0x12: "session_end",
    0x20: "record",
    0x21: "undecoded",
    0x22: "discontinuity",
    0x30: "name",
    0x41: "end",
    0xFF: "custom",
}

ALIASES = {"timestamp": "ts", "participant_id": "pid", "flow_key": "key"}

ENUMS = {
    "kind": {0: "capture", 1: "zpf-input"},
    "output_layer": {0: "decoded", 1: "transport"},
    "adjacency": {0: "contiguous", 1: "units"},
    "tcp_role": {1: "initiator", 2: "responder"},  # 0 = unknown, and is omitted
}

FLAG_TOKENS = {
    0x0001: "psh",
    0x0002: "fin",
    0x0004: "rst",
    0x0008: "syn",
    0x0010: "urg",
    0x0040: "retransmit",
    0x0080: "message",
    0x0100: "copy",
}

# Options whose repetition is a list (endpoint) or chunking (spans,
# input_extents): each projects as one array, always, over every occurrence.
REPEATABLE = {"endpoint"}
CHUNKED = {"spans", "input_extents"}


def flag_tokens(flags: int) -> list[str]:
    """Render a Record's flags as set-bit tokens, ascending; a bit with no token as hex."""
    return [FLAG_TOKENS.get(1 << i, f"0x{1 << i:04X}") for i in range(16) if flags & (1 << i)]


def project(blk: Blk) -> dict:
    """Project one block to its JSONL object, by the mapping.

    Body fields always project; an absent option is an omitted key; a zero
    bitfield is omitted; and each of the four escapes has its form -- an unknown
    block type, an unregistered option, an enum value with no label, a flag bit
    with no token.
    """
    if blk.fields is None:
        # Unknown block type: the whole content field, opaque, and no other key.
        content = b"".join(b for b, _ in blk)[8:]
        return {"type": f"0x{blk.btype:04X}", "content": b64(content)}
    out: dict = {"type": TYPE_NAMES[blk.btype]}
    for name, v in blk.fields.items():
        if name == "flags":
            if v:
                out["flags"] = flag_tokens(v)
            continue
        out[ALIASES.get(name, name)] = _render(name, v)
    for opt in blk.options:
        _project_option(out, opt)
    return out


def _project_option(out: dict, opt: Opt) -> None:
    """Add one option to a block's projection: its key, its encoding, its escape."""
    if opt.name == "UNREGISTERED":
        out.setdefault("options", []).append({"id": f"0x{opt.oid:04X}", "value": b64(opt.value)})
        return
    if opt.name == "flags":  # the Session flags bitfield
        if opt.value & ~0x0001:
            raise ValueError(f"session flags 0x{opt.value:04X}: only SEQUENCED is defined")
        if opt.value:
            out["sequenced"] = True
        return
    if opt.name == "tcp_role" and opt.value == 0:
        return  # unknown: omitted
    key = ALIASES.get(opt.name, opt.name)
    v = _render(opt.name, opt.value)
    if opt.name in CHUNKED:
        out.setdefault(key, []).extend(v)
    elif opt.name in REPEATABLE:
        out.setdefault(key, []).append(v)
    elif key in out:
        raise ValueError(f"option {opt.name} repeats, and is not repeatable")
    else:
        out[key] = v


def _render(name: str, v: object) -> object:
    """Encode one logical value: enum label (or raw number), base64 bytes, or as is."""
    if name in ENUMS:
        return ENUMS[name].get(v, v)
    if isinstance(v, bytes):
        return b64(v)
    return v


def check_faces(label: str, blocks: list[Blk], jsonl: list[dict]) -> None:
    """Refuse a vector whose bytes and hand-written projection disagree.

    Compared per block, as objects: key order is free (ground rule 3), values
    are not. The message names the block and every key that differs, with both
    faces' values, because which face is wrong is a question for the author --
    the .jsonl was right in all three of #141's defects.
    """
    if len(blocks) != len(jsonl):
        raise ValueError(
            f"{label}: {len(blocks)} blocks but {len(jsonl)} .jsonl lines -- "
            "the two faces describe different files"
        )
    for i, (blk, want) in enumerate(zip(blocks, jsonl, strict=True)):
        got = project(blk)
        if got == want:
            continue

        def side(d: dict, k: str) -> str:
            return repr(d[k]) if k in d else "<absent>"

        diffs = [
            f"  {k}: .jsonl says {side(want, k)}, the bytes project {side(got, k)}"
            for k in sorted(set(got) | set(want))
            if got.get(k) != want.get(k) or (k in got) != (k in want)
        ]
        raise ValueError(
            f"{label}: block {i} ({got['type']}) -- the .zpf and the .jsonl disagree:\n"
            + "\n".join(diffs)
        )


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
    extents: list[tuple[int, int, int]] | None = None,
    merged: list[tuple[int, list[int]]] | None = None,
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

    A vector with a `jsonl` face is refused unless the bytes project to it, block
    for block (`check_faces`). The two faces stay independently authored -- that
    is what makes their agreement mean something -- and since 0.20 they are
    compared here rather than by the first downstream port to diff them (#141).

    `extents` is required on the accept tier, for the reason `violations` is
    required everywhere: a number an author must confront is one that gets
    checked, and a default is a number nobody looked at. It declares each
    participant stream's extent in its own offset space, as `(session_id, pid,
    extent)`, and is the accept tier's assertion about what a reader COMPUTES --
    `violations` catches only the wrong reading that produces a finding, and a
    reader that skips a Discontinuity's width, or trusts a wrapped offset, is
    wrong silently (#140). Every declared participant is named, and nothing else
    is: each number is the author's reading of the specification, and a wrong
    one is caught by the first implementation that disagrees, which is the loop
    the suite lacked. Nothing here computes it.

    `merged` is the same assertion for the merge (#162): on the accept tier,
    every UNSEQUENCED session in which two or more participants send records has
    a merged order a reader computes, and the vector states it as `(session_id,
    order)`, the order being the session's records by 1-based stored position.
    Required wherever that shape occurs, for the reason `extents` is. Checked
    here for shape only -- a permutation of the session's records that keeps
    each participant's own order -- and never computed: the merge is semantics.
    A multi-file fixture declares it through fixture(), naming each file (#163).
    """
    if advisory and tier != "accept":
        raise ValueError(f"{name}: advisory is meaningless off the accept tier")
    if jsonl is not None:
        check_faces(name, blocks, jsonl)
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
            "extents": check_extents(name, tier, blocks, extents),
            "merged": check_merged(name, tier, blocks, merged),
        }
    )


def check_extents(
    name: str, tier: str, blocks: list[Blk], extents: list[tuple[int, int, int]] | None
) -> list[dict] | None:
    """Require `extents` on the accept tier, naming exactly the declared participants."""
    if tier != "accept":
        if extents is not None:
            raise ValueError(f"{name}: extents is declared on the accept tier only")
        return None
    if extents is None:
        raise TypeError(f"{name}: an accept vector declares extents, one per participant stream")
    declared = [
        (b.fields["session_id"], b.fields["participant_id"]) for b in blocks if b.btype == 0x11
    ]
    named = [(sess, pid) for sess, pid, _ext in extents]
    if sorted(named) != sorted(declared):
        raise ValueError(
            f"{name}: extents name {sorted(named)} but the file declares "
            f"participants {sorted(declared)}"
        )
    return [{"session_id": sess, "pid": pid, "extent": ext} for sess, pid, ext in extents]


def merge_sessions(blocks: list[Blk]) -> dict[int, list[int]]:
    """Map each unsequenced session with two or more senders to its records' senders."""
    sequenced = {
        b.fields["session_id"]
        for b in blocks
        if b.btype == 0x10 and any(o.name == "flags" and o.value & 0x0001 for o in b.options)
    }
    senders: dict[int, list[int]] = {}
    for b in blocks:
        if b.btype == 0x20 and b.fields["session_id"] not in sequenced:
            senders.setdefault(b.fields["session_id"], []).append(b.fields["sender_pid"])
    return {sid: pids for sid, pids in senders.items() if len(set(pids)) > 1}


def check_merged(
    name: str, tier: str, blocks: list[Blk], merged: list[tuple[int, list[int]]] | None
) -> list[dict] | None:
    """Require `merged` wherever an accept vector has a session a reader must merge."""
    need = merge_sessions(blocks) if tier == "accept" else {}
    if not need:
        if merged is not None:
            raise ValueError(f"{name}: merged is declared, but no session here needs a merge")
        return None
    if merged is None:
        raise TypeError(
            f"{name}: sessions {sorted(need)} are unsequenced with several senders; "
            f"declare their merged order"
        )
    if sorted(sid for sid, _ in merged) != sorted(need):
        raise ValueError(
            f"{name}: merged names {sorted(s for s, _ in merged)}, needs {sorted(need)}"
        )
    for sid, order in merged:
        pids = need[sid]
        if sorted(order) != list(range(1, len(pids) + 1)):
            raise ValueError(
                f"{name}: session {sid} order {order} is not a permutation of its records"
            )
        for pid in set(pids):
            mine = [i for i in order if pids[i - 1] == pid]
            if mine != sorted(mine):
                raise ValueError(
                    f"{name}: session {sid} order reorders participant {pid}'s records"
                )
    return [{"session_id": sid, "order": order} for sid, order in merged]


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
            "adjacency": "contiguous",
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
    extents=[(7, 0, 18)],
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
            options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 18)]), o_content_type("dec:request")],
        ),
        record(
            7,
            1,
            1,
            995,
            b"RESP",
            options=[o_decoder_id(1), o_spans([(1, 7, 1, 0, 100)]), o_content_type("dec:response")],
        ),
        undecoded(1, 1, 7, 100, 139, [o_reason("undecodable"), o_decoder_id(1)]),
        # Extents make the coverage guarantee checkable from this file alone:
        # pid 0 spans [0,18), pid 1 spans [0,100) + undecoded [100,139).
        session_end(7, [o_end_reason("fin"), o_input_extents([(1, 7, 0, 18), (1, 7, 1, 139)])]),
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["93.184.216.34:80"],
        },
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
    extents=[(7, 0, 3), (7, 1, 4)],
    merged=[(7, [2, 1])],
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
                o_spans([(1, 30, 0, 0, 4)]),
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
                o_spans([(1, 30, 0, 4, 8)]),
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
                o_spans([(1, 30, 0, 8, 12)]),
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
                o_spans([(1, 30, 0, 12, 16)]),
                o_content_type("prim:u32"),
                o_role("seq_no"),
            ],
        ),
        session_end(31, [o_input_extents([(1, 30, 0, 16)])]),
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
        {
            "type": "participant",
            "session_id": 31,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:9000"],
        },
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
    extents=[(31, 0, 16)],
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
    extents=[],
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(7, 0, 2)],
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
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "tcp_role": 7,
        },
        {"type": "end"},
    ],
    violations=0,
    extents=[(7, 0, 0)],
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(7, 0, 2)],
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
            options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 18)]), o_content_type("dec:request")],
        ),
        undecoded(1, 0, 7, 18, 60, [o_reason("undecodable"), o_decoder_id(1)]),
        session_end(7, [o_input_extents([(1, 7, 0, 60)])]),
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(7, 0, 3)],
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
        record(7, 0, 1, 1000, b"body", options=[o_decoder_id(1), o_spans([(1, 7, 0, 3, 7)])]),
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(7, 0, 4)],
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(7, 0, 0)],
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
        record(7, 0, 1, 1000, b"A" * 50, options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 100)])]),
        # The input-side loss and the output-side break are two statements.
        undecoded(1, 0, 7, 100, 139, [o_reason("gap"), o_decoder_id(1)]),
        discontinuity(7, 0, [o_disc_reason("tls-record-lost")]),
        record(7, 0, 1, 1100, b"B" * 30, options=[o_decoder_id(1), o_spans([(1, 7, 0, 139, 200)])]),
        session_end(7, [o_input_extents([(1, 7, 0, 200)])]),
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(7, 0, 80)],
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
        record(100, 0, 1, 1000, b"S100-a", options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 80)])]),
        record(101, 0, 1, 1010, b"S101-a", options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 80)])]),
        record(
            100, 0, 1, 1100, b"S100-b", options=[o_decoder_id(1), o_spans([(1, 7, 0, 80, 140)])]
        ),
        record(
            101, 0, 1, 1200, b"S101-b", options=[o_decoder_id(1), o_spans([(1, 7, 0, 140, 200)])]
        ),
        # Each consuming session declares the stream's WHOLE extent, not its share.
        session_end(100, [o_input_extents([(1, 7, 0, 200)])]),
        session_end(101, [o_input_extents([(1, 7, 0, 200)])]),
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
        {
            "type": "participant",
            "session_id": 100,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
        {"type": "session", "session_id": 101, "proto": "http"},
        {
            "type": "participant",
            "session_id": 101,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(100, 0, 12), (101, 0, 12)],
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
        record(100, 0, 1, 1000, b"a", options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 100)])]),
        record(101, 0, 1, 1100, b"b", options=[o_decoder_id(1), o_spans([(1, 7, 0, 100, 200)])]),
        session_end(100, [o_input_extents([(1, 7, 0, 200)])]),
        session_end(101, [o_input_extents([(1, 7, 0, 160)])]),
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
    "silent failure the block exists to prevent, and it produces no violation "
    "and the same projection. The declared extent is what catches it: 105, "
    "not 80.",
    "Discontinuity (0x22)",
    [
        file_header(options=[o_produced_by("zpf-quic 0.1"), o_produced_at(1719590000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("quic-stream"), o_dec_version("0.1")]),
        session(9, [o_proto("quic")]),
        participant(9, 0, [o_endpoint("10.0.0.1:51000")]),
        record(9, 0, 1, 2000, b"C" * 50, options=[o_decoder_id(1), o_spans([(1, 9, 0, 0, 50)])]),
        undecoded(1, 0, 9, 50, 75, [o_reason("gap"), o_decoder_id(1)]),
        discontinuity(9, 0, [o_width(25), o_disc_reason("stream-gap")]),
        record(9, 0, 1, 2100, b"D" * 30, options=[o_decoder_id(1), o_spans([(1, 9, 0, 75, 105)])]),
        session_end(9, [o_input_extents([(1, 9, 0, 105)])]),
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
        {
            "type": "participant",
            "session_id": 9,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(9, 0, 105)],
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(7, 0, 2)],
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
            "adjacency": "contiguous",
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
    extents=[(7, 0, 2)],
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
    extents=[],
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
    "so the output offsets are unchanged at [0,50) and [50,150). Since 0.21 a "
    "reordering stage has a second form -- declare the participant a unit "
    "sequence with adjacency = units and emit no block at all "
    "(unit-sequence-reversed) -- and this vector keeps the first: one seam in "
    "a stream that otherwise joins is what the per-seam block is for.",
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
                o_spans([(1, 7, 1, 100, 150)]),
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
            options=[o_decoder_id(1), o_spans([(1, 7, 1, 0, 100)]), o_content_type("dec:response")],
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["93.184.216.34:80"],
        },
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
    extents=[(7, 1, 150)],
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
    "whether the spans are identity is what decides that and these are not. "
    "The declared extent, 160 and not 120, is what catches a reader that "
    "skipped the width; nothing else in the file does.",
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
                o_spans([(1, 7, 1, 0, 60)]),
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
                o_spans([(1, 7, 1, 100, 160)]),
                o_content_type("dec:response"),
            ],
        ),
        session_end(7, [o_input_extents([(1, 7, 1, 160)])]),
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["93.184.216.34:80"],
        },
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
    extents=[(7, 1, 160)],
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
            options=[o_decoder_id(1), o_spans([(1, 4, 0, 0, 50)]), o_seq_start(1001)],
        ),
        undecoded(1, 0, 4, 50, 75, [o_reason("gap"), o_decoder_id(1)]),
        record(
            7,
            0,
            1,
            1200,
            b"B" * 30,
            options=[o_decoder_id(1), o_spans([(1, 4, 0, 75, 105)]), o_seq_start(1076)],
        ),
        session_end(7, [o_input_extents([(1, 4, 0, 105)])]),
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
            "adjacency": "contiguous",
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
    extents=[(7, 0, 105)],
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
            "adjacency": "contiguous",
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
    extents=[(7, 0, 18)],
)

vector(
    "proxy-decoded",
    "accept",
    "CASE G: a decoded stream with NO predecessor file. A TLS-terminating "
    "proxy logging application messages -- the bytes they were computed from "
    "were never written to a .zpf and never will be. Records carry decoder_id "
    "and reference a CAPTURE Source, which is the cell the axes were "
    "conflated to forbid: capture-sourced provenance, decoded layer. No spans, "
    "because there is no input stream to name. Two consequences "
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
        {
            "type": "participant",
            "session_id": 3,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
    extents=[(3, 0, 35)],
)

vector(
    "undecoded-in-capture",
    "accept",
    "An Undecoded block in a CAPTURE-SOURCED file. The stage is the "
    "reassembler and the input is the capture itself: it discarded an "
    "overlapping segment it could not resolve -- retransmitted or duplicated, "
    "the block does not say and need not -- and says so rather than "
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
            "adjacency": "contiguous",
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
    extents=[(7, 0, 105)],
)

vector(
    "mixed-derivation",
    "accept",
    "ONE derived file holding a decode-stage stream BESIDE a pass-through "
    "stream. Session 10 is created: its records carry spans into input session "
    "7 and the file accounts for the input it decoded. Session 11 is preserved: "
    "its record carries an IDENTITY span into input session 8 -- the same range "
    "in as out, [0,10) -- and its bytes and offsets are the input's unchanged. "
    "Before 0.15 a derived file was exactly one of the two, never a mix, which "
    "left a tool with a decoder for one protocol and not the other two "
    "dishonest options -- pass everything through, or mark the undecodable "
    "session's whole stream Undecoded, which DROPS those bytes from the output. "
    "Since 0.19 every zpf-sourced record carries spans and which kind a stream "
    "is, is read from them: identity spans preserve, any other span creates. "
    "That binds per participant; across streams there is no rule.",
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
        # Created: a span into input session 7 that is not an identity span.
        session(10, [o_proto("http")]),
        participant(10, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            10,
            0,
            1,
            1000,
            b"GET /",
            options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 40)]), o_content_type("dec:request")],
        ),
        session_end(10, [o_input_extents([(1, 7, 0, 40)])]),
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
        {
            "type": "participant",
            "session_id": 10,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
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
            "adjacency": "contiguous",
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
    extents=[(10, 0, 5), (11, 0, 10)],
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
        {
            "type": "participant",
            "session_id": 8,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["alice"],
        },
        {
            "type": "participant",
            "session_id": 8,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["bob"],
        },
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
    extents=[(8, 0, 4), (8, 1, 2)],
    merged=[(8, [2, 1, 3])],
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
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "participant",
            "session_id": 1,
            "pid": 1,
            "adjacency": "contiguous",
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
    extents=[(1, 0, 5), (1, 1, 12)],
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
        {
            "type": "participant",
            "session_id": 8,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["alice"],
        },
        {
            "type": "participant",
            "session_id": 8,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["bob"],
        },
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
    extents=[(8, 0, 10), (8, 1, 8)],
    merged=[(8, [2, 1])],
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
    "Its twin is unplaceable-below-origin, the other shape of one rule.",
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
        {
            "type": "participant",
            "session_id": 9,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:5000"],
        },
        {
            "type": "participant",
            "session_id": 9,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.2:5000"],
        },
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
    expect="Accept. The .jsonl file is the expected projection, and the declared "
    "extents are 6 for pid 0 and 5 for pid 1. pid 0's first record is at "
    "[0,6) and its second carries no seq_start on a stream whose first "
    "record has one, so it is UNPLACEABLE -- it covers no byte of the "
    "stream and contributes nothing, so the extent stays 6 and those six "
    "bytes are in no offset at all. A reader that appended them at [6,12) "
    "is reading an offset the file does not state. Which range a reader "
    "reports for the record is not pinned; two readers may differ there "
    "while both give extent 6. A reader SHOULD report the record, and the "
    "suite does not test that it does -- the file breaks no rule, so "
    "silence is conformant, exactly as for unplaceable-below-origin, the "
    "other shape of the same sentence. pid 1 is NOT this rule's case: no "
    "record of that participant carries a seq_start, so its stream is not "
    "sequence-anchored to begin with, and its extent is the accumulation "
    "of its payloads. Since 0.21 the floor is stated against a record's "
    "PREDECESSOR rather than the origin, and applies whether or not the "
    "participant carries an isn: pid 0 has none, its origin is its first "
    "captured byte, and a reader that applied no floor for want of an isn "
    "would place the second record somewhere and report more than 6.",
    violations=0,
    extents=[(9, 0, 6), (9, 1, 5)],
    merged=[(9, [1, 2, 3])],
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
        record(7, 0, 1, 1000, b"part", options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 10)])]),
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
        record(7, 0, 1, 1000, b"part", options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 20)])]),
        session_end(7, [o_input_extents([(1, 7, 0, 40)])]),
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
        record(7, 0, 1, 1000, b"A" * 50, options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 100)])]),
        # The input-side loss is declared. THE VIOLATION is what follows it:
        # no Discontinuity, so the two records are simply adjacent at 50 and a
        # downstream stage may splice them with every rule still satisfied.
        undecoded(1, 0, 7, 100, 139, [o_reason("gap"), o_decoder_id(1)]),
        record(7, 0, 1, 1100, b"B" * 30, options=[o_decoder_id(1), o_spans([(1, 7, 0, 139, 200)])]),
        session_end(7, [o_input_extents([(1, 7, 0, 200)])]),
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
            options=[o_seq_start(1001), o_spans([(1, 21, 0, 0, 5)])],
        ),
        session(20, [o_proto("http")]),
        participant(20, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            20,
            0,
            1,
            1100,
            b"GET /",
            options=[o_decoder_id(1), o_spans([(1, 21, 0, 0, 5)]), o_content_type("dec:request")],
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
    "that adds something: an overlapping segment the reassembler discarded, "
    "retransmitted or duplicated, exists in the pcap and is expressible "
    "nowhere else.",
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
            options=[o_decoder_id(1), o_spans([(1, 5, 0, 0, 5)]), o_content_type("dec:request")],
        ),
        # THE VIOLATION: same participant, a decoder declaring the other layer.
        record(
            30,
            0,
            1,
            1100,
            b"C" * 20,
            options=[o_decoder_id(2), o_spans([(1, 5, 0, 5, 25)]), o_seq_start(1001)],
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
    "A zpf-SOURCED record carrying NO SPANS: it references a zpf-input Source "
    "and nothing says which stream inside the input its bytes came from, so "
    "nothing resolves one level down and no coverage obligation can be "
    "computed in either direction. Every zpf-sourced record carries spans -- "
    "a pass-through's are identity spans -- so the rule binds per record with "
    "no second shape to check. Before 0.19 the same file broke a different "
    "rule, that a participant be either created or preserved, which 0.15 had "
    "stated as a bar on being BOTH and was silent on being neither; that is how "
    "isolate-self-derived shipped carrying this as a second, unintended "
    "violation. Contrast mixed-derivation, where both participants' records "
    "carry spans and the spans say which kind each stream is.",
    "Conformance -- every zpf-sourced record carries spans",
    [
        file_header(options=[o_produced_by("zpf-tool 0.1"), o_produced_at(1719650000)]),
        source(1, 1, [o_uri("upstream.zpf"), o_digest("sha256:22bb")]),
        session(40, [o_proto("tcp")]),
        # THE VIOLATION: zpf-sourced, and the record below carries no spans.
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
    "NOT whose violation is ADVISORY. 0.17's origin floor was the other such "
    "MUST NOT until 0.19 dropped it, and now the transport-label bar -- this "
    "vector and advisory-transport-role's -- is the advisory tier. The "
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
                o_spans([(1, 6, 0, 0, 40)]),
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
            "adjacency": "contiguous",
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
    extents=[(50, 0, 40)],
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
    "real traffic. Its negative twin, the same record written one below the "
    "origin, was advisory-seq-start-below-origin until 0.19 removed it with "
    "the floor's MUST NOT; unplaceable-below-origin now carries that shape. "
    "It also carries the responder's SYN-ACK as its own zero-length syn record "
    "with an ack, which the specification describes and nothing else exercises.",
    "Record (0x20) -- handshake records",
    [
        file_header(),
        source(1, 0, [o_uri("tcp.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(1)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000), o_tcp_role(2)]),
        # The client's SYN, at the origin. It occupies isn, one below, so its
        # end equals its seq_start -- not because it is zero length: since 0.23
        # a zero-length record with no syn or fin has no end at all.
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
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
            "tcp_role": "initiator",
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
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
    extents=[(7, 0, 18), (7, 1, 19)],
    merged=[(7, [1, 2, 3, 4])],
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
                o_spans([(1, 6, 0, 0, 40)]),
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
            "adjacency": "contiguous",
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
    extents=[(51, 0, 40)],
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
    "every other record, which is the reading this vector exists to fail. "
    "Since 0.21 the floor binds each record to its PREDECESSOR, the origin "
    "being the first record's, and this is the first-record case of that "
    "rule. An unplaceable record anchors nothing: the second record measures "
    "from the origin, not from seq_start 1000, so it sits at 0 and the extent "
    "is 16 -- a reader that let the first record anchor would put it at 1 "
    "and report 17.",
    "Referencing the source by stream offset -- unplaceable records",
    [
        file_header(),
        source(1, 0, [o_uri("offbyone.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(1)]),
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
            "adjacency": "contiguous",
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
    expect="Accept. The .jsonl file is the expected projection, and the declared "
    "extent is 16. The first record is unplaceable: it contributes nothing to "
    "the extent and covers no byte, so the participant's stream is [0,16) -- "
    "the two later records -- and the eight bytes of the first are in no "
    "offset at all. Which range a reader reports for it is not pinned; that "
    "it counts for nothing is. It is NOT deleted: a reader still lists it, "
    "still reports its timestamp and payload, and a consumer indexing by "
    "anything but offset still sees it. A reader SHOULD report the record, "
    "and the suite does not test that it does -- the file breaks no rule, "
    "so silence is conformant and a harness asserting a clean accept is "
    "right to. Two wrong readings diverge visibly here, where the record "
    "carries payload, and would not on a zero-length one: one places the "
    "record at 4294967295 and reports extent 4294967303, the other drops it "
    "and reports two records where the file has three. Rejecting or "
    "isolating is NOT conformant.",
    violations=0,
    extents=[(7, 0, 16)],
)

# 0.21 (#146). Offsets unwrap along stored order. Two vectors, because two
# wrong readings fail on different files: the one below defeats a reader that
# measures every record against the origin under serial arithmetic, and
# stream-wraps-seq defeats one that subtracts without the modulus.
GIB = 2**30

vector(
    "stream-past-2gib",
    "accept",
    "A transport stream that passes 2 GiB in one direction: isn 1000, four "
    "eight-byte records at offsets 0, 1 GiB, 2 GiB and 3 GiB, every neighbour "
    "one serial step of 2**30 from the last. Under 0.20 the third record was "
    "BELOW THE ORIGIN: its seq_start is 2**31 past isn + 1, which serial "
    "arithmetic cannot tell from 2**31 before it, and the document said so and "
    "drew the wrong conclusion. Since 0.21 offsets unwrap along stored order -- "
    "each record is its predecessor's offset plus the signed serial delta of "
    "their seq_starts, the origin being the first record's predecessor -- so "
    "the third record sits at 2**31 and the fourth at 3 * 2**30. The declared "
    "extent is 3221225480. A reader that applies the floor against the origin "
    "for every record reports two unplaceable records and an extent of "
    "1073741832, which is the reading this vector exists to fail; a reader "
    "that trusts the wrapped offset reports 1073741832 as well, for the third "
    "record, and something near 2**32 for the fourth.",
    "Referencing the source by stream offset -- offsets unwrap along stored order",
    [
        file_header(),
        source(1, 0, [o_uri("bulk.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(1)]),
        record(7, 0, 1, 1000, b"AAAABBBB", flags=0x0001, options=[o_seq_start(1001)]),
        record(7, 0, 1, 2000, b"CCCCDDDD", flags=0x0001, options=[o_seq_start(1001 + GIB)]),
        # 2**31 past the origin: serially INDISTINGUISHABLE from 2**31 before it,
        # which is why the origin cannot be what it is measured from.
        record(7, 0, 1, 3000, b"EEEEFFFF", flags=0x0001, options=[o_seq_start(1001 + 2 * GIB)]),
        record(7, 0, 1, 4000, b"GGGGHHHH", flags=0x0001, options=[o_seq_start(1001 + 3 * GIB)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "bulk.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
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
            "payload": b64(b"AAAABBBB"),
            "seq_start": 1001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "flags": ["psh"],
            "payload": b64(b"CCCCDDDD"),
            "seq_start": 1001 + GIB,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 3000,
            "flags": ["psh"],
            "payload": b64(b"EEEEFFFF"),
            "seq_start": 1001 + 2 * GIB,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 4000,
            "flags": ["psh"],
            "payload": b64(b"GGGGHHHH"),
            "seq_start": 1001 + 3 * GIB,
        },
        {"type": "end"},
    ],
    expect="Accept. The .jsonl file is the expected projection, and the declared "
    "extent is 3221225480: four placeable records at 0, 2**30, 2**31 and "
    "3 * 2**30, the last eight bytes long. No record is unplaceable. A reader "
    "that measures each record against the origin under serial arithmetic "
    "finds the third and fourth below it and reports an extent of 1073741832; "
    "that reading was the document's own until 0.21 and is wrong now. "
    "Rejecting or isolating is NOT conformant: every neighbour is within a "
    "window's serial distance of the last, so the ordering rule holds "
    "throughout.",
    violations=0,
    extents=[(7, 0, 3 * GIB + 8)],
)

vector(
    "stream-wraps-seq",
    "accept",
    "A transport stream whose sequence numbers pass through 2**32: isn is "
    "2**32 - 5, so the origin is 2**32 - 4; the first record starts there with "
    "eight bytes and ends, on the wire, at 4; the second starts at 4. The "
    "signed serial delta between the two seq_starts is 8, so the second record "
    "sits at offset 8 and the extent is 16. This is the COMMONER of the two "
    "unwrapping shapes -- any stream wraps with probability length / 2**32 per "
    "random isn, so a 2 GiB stream does so one time in two -- and until 0.21 "
    "no vector had it and the suite's own extent arithmetic got it wrong: "
    "plain seq_start - (isn + 1) gives the second record a range starting at "
    "-4294967288 and an extent of 8. A reader that subtracts without the "
    "modulus fails here; one that takes the delta unsigned places the second "
    "record at 4294967304.",
    "Referencing the source by stream offset -- offsets unwrap along stored order",
    [
        file_header(),
        source(1, 0, [o_uri("wrap.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(2**32 - 5), o_tcp_role(1)]),
        record(7, 0, 1, 1000, b"AAAABBBB", flags=0x0001, options=[o_seq_start(2**32 - 4)]),
        # seq 4 is (2**32 - 4) + 8 mod 2**32: the byte after the first record.
        record(7, 0, 1, 2000, b"CCCCDDDD", flags=0x0001, options=[o_seq_start(4)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "wrap.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 2**32 - 5,
            "tcp_role": "initiator",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "flags": ["psh"],
            "payload": b64(b"AAAABBBB"),
            "seq_start": 2**32 - 4,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "flags": ["psh"],
            "payload": b64(b"CCCCDDDD"),
            "seq_start": 4,
        },
        {"type": "end"},
    ],
    expect="Accept. The .jsonl file is the expected projection, and the declared "
    "extent is 16: the first record at [0,8), the second at [8,16), because "
    "the serial delta from seq_start 4294967292 to seq_start 4 is +8. No "
    "record is unplaceable. A reader that computes seq_start - (isn + 1) as "
    "plain integers places the second record below zero; one that reduces the "
    "difference mod 2**32 without treating it as signed places it at "
    "4294967304 and reports an extent of 4294967312. Rejecting or isolating "
    "is NOT conformant: under serial-number order seq_start 4 follows "
    "4294967292, which is what the ordering rule means by order.",
    violations=0,
    extents=[(7, 0, 16)],
)

# 0.21 (#147). The one shape the walk above cannot place, and its exit.
KEY = "10.0.0.1:51000 <-> 93.184.216.34:80"

vector(
    "session-split-capture-gap",
    "accept",
    "A hole of 2**31 bytes or more between two consecutive records of one "
    "participant, which is the one shape the unwrapping rule cannot place: "
    "the far side is 2**31 + 8 past the near side, which serial arithmetic "
    "reads as 2**31 - 8 BEFORE it, and the ordering rule refuses the pair. "
    "The producer knew the hole was real -- it had a clock the sequence "
    "number is not -- and this is what the format offers: end session 7 at "
    "the hole with reason capture-gap, open session 8 on the same key with "
    "no isn, and carry on from the first captured byte. Two sessions where "
    "the wire had one conversation, and the reason word plus the repeated key "
    "are what say so. Session 7's extent is 8, session 8's is 8; no offset "
    "spans the hole because no stream does. A reader that treats the repeated "
    "flow_key as a duplicate, or the second session's first record as out of "
    "order against the first session's, has misread the split: ids belong to "
    "sessions, and the ordering rule is per (session_id, participant_id).",
    "Referencing the source by stream offset -- the unmeasurable hole",
    [
        file_header(),
        source(1, 0, [o_uri("paused.pcap")]),
        session(7, [o_proto("tcp"), o_flow_key(KEY)]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(1)]),
        record(7, 0, 1, 1000, b"AAAABBBB", flags=0x0001, options=[o_seq_start(1001)]),
        # The next segment of this direction is 2**31 + 8 bytes on: unplaceable
        # in session 7, so session 7 ends here and says why.
        session_end(7, [o_end_reason("capture-gap")]),
        session(8, [o_proto("tcp"), o_flow_key(KEY)]),
        # No isn: the origin of the resumed stream is its first captured byte.
        participant(8, 0, [o_endpoint("10.0.0.1:51000")]),
        record(
            8, 0, 1, 90_000_000, b"CCCCDDDD", flags=0x0001, options=[o_seq_start(1001 + 2**31 + 8)]
        ),
        session_end(8, [o_end_reason("capture-end")]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "paused.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp", "key": KEY},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
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
            "payload": b64(b"AAAABBBB"),
            "seq_start": 1001,
        },
        {"type": "session_end", "session_id": 7, "reason": "capture-gap"},
        {"type": "session", "session_id": 8, "proto": "tcp", "key": KEY},
        {
            "type": "participant",
            "session_id": 8,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
        {
            "type": "record",
            "session_id": 8,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 90_000_000,
            "flags": ["psh"],
            "payload": b64(b"CCCCDDDD"),
            "seq_start": 1001 + 2**31 + 8,
        },
        {"type": "session_end", "session_id": 8, "reason": "capture-end"},
        {"type": "end"},
    ],
    expect="Accept. The .jsonl file is the expected projection, and the declared "
    "extents are 8 for session 7 and 8 for session 8. Session 7's one record "
    "is at [0,8) from its isn; session 8 has no isn, so its one record is at "
    "[0,8) from its own first captured byte, whatever its seq_start says "
    "about the other session's stream. The two sessions are one wire "
    "conversation, which is what reason = capture-gap on session 7 states; a "
    "reader is not required to join them and nothing in the file lets it. "
    "Rejecting or isolating is NOT conformant: a repeated flow_key is not a "
    "duplicate id, and the ordering rule binds within a (session_id, "
    "participant_id), so session 8's seq_start is compared with nothing in "
    "session 7.",
    violations=0,
    extents=[(7, 0, 8), (8, 0, 8)],
)

# 0.22 (#151). #146's twin on the ack axis. The causal edge rule compared an ack
# with peer record ends by serial arithmetic, which is defined only within 2**31
# -- and an ack stored once on a peer that never speaks again stays put while
# the record ends run on past it. check.py computes no edges, so this vector
# tests implementations only.
vector(
    "sequenced-past-2gib-pure-ack",
    "accept",
    "stream-past-2gib's client, after a recorded handshake, in a SEQUENCED "
    "session whose server sends nothing after its SYN-ACK. The server's pure "
    "ACKs are not records, so its one ack in the file is the SYN-ACK's 1001 "
    "for the whole session. That ack is a POSITION in the client's stream -- "
    "0, the origin -- and every client data record ends above it, at 8, "
    "2**30 + 8, 2**31 + 8 and 3 * 2**30 + 8, so no edge runs from any of them "
    "to the SYN-ACK and the stored order is causal. Through 0.21 step 2 "
    "compared the raw values serially, and the record at 2 GiB ends 2**31 + 8 "
    "past 1001, which serial arithmetic reads as BEFORE it: the edge "
    "client@2GiB -> SYN-ACK, a record that must precede the handshake. The "
    "ordinary large upload, with a peer that only acks, failed the sequenced "
    "check from that record on. Since 0.22 ends and acks are unwrapped into "
    "the peer's offset space and compared as plain integers.",
    "Causal ordering from TCP seq/ack -- acks unwrap into the peer's space",
    [
        file_header(),
        source(1, 0, [o_uri("upload.pcap")]),
        session(7, [o_proto("tcp"), o_sess_flags(0x0001)]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(1)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000), o_tcp_role(2)]),
        record(7, 0, 1, 1000, b"", flags=0x0008, options=[o_seq_start(1001)]),
        # The server's only record: its ack stays at position 0 of the client's
        # stream for the rest of the session.
        record(7, 1, 1, 1100, b"", flags=0x0008, options=[o_seq_start(5001), o_ack(1001)]),
        record(7, 0, 1, 2000, b"AAAABBBB", flags=0x0001, options=[o_seq_start(1001), o_ack(5001)]),
        record(
            7,
            0,
            1,
            3000,
            b"CCCCDDDD",
            flags=0x0001,
            options=[o_seq_start(1001 + GIB), o_ack(5001)],
        ),
        # Ends 2**31 + 8 past the SYN-ACK's ack: serially BELOW it.
        record(
            7,
            0,
            1,
            4000,
            b"EEEEFFFF",
            flags=0x0001,
            options=[o_seq_start(1001 + 2 * GIB), o_ack(5001)],
        ),
        record(
            7,
            0,
            1,
            5000,
            b"GGGGHHHH",
            flags=0x0001,
            options=[o_seq_start(1001 + 3 * GIB), o_ack(5001)],
        ),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "upload.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp", "sequenced": True},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
            "tcp_role": "initiator",
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
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
            "ts": 2000,
            "flags": ["psh"],
            "payload": b64(b"AAAABBBB"),
            "seq_start": 1001,
            "ack": 5001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 3000,
            "flags": ["psh"],
            "payload": b64(b"CCCCDDDD"),
            "seq_start": 1001 + GIB,
            "ack": 5001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 4000,
            "flags": ["psh"],
            "payload": b64(b"EEEEFFFF"),
            "seq_start": 1001 + 2 * GIB,
            "ack": 5001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 5000,
            "flags": ["psh"],
            "payload": b64(b"GGGGHHHH"),
            "seq_start": 1001 + 3 * GIB,
            "ack": 5001,
        },
        {"type": "end"},
    ],
    expect="Accept, and consume the records in STORED order: the session is "
    "SEQUENCED and the order is causal. The SYN-ACK's ack 1001 is position 0 "
    "of the client's stream; the client SYN ends at 0 and precedes it, as "
    "stored; the four data records end at 8, 2**30 + 8, 2**31 + 8 and "
    "3 * 2**30 + 8, all above 0, so none precedes it. Each data record's ack "
    "5001 is position 0 of the server's stream, where the SYN-ACK ends, so "
    "the SYN-ACK precedes all four, as stored. A reader or writer that "
    "compares raw values serially draws client@2GiB -> SYN-ACK and "
    "client@3GiB -> SYN-ACK, and reports the stored order as a causal "
    "violation; that reading was the document's own until 0.22 and is wrong "
    "now. Rejecting, isolating, or refusing to write the file is NOT "
    "conformant. Extents are those of stream-past-2gib for the client, and "
    "0 for the server, whose one record is zero-length at its origin.",
    violations=0,
    extents=[(7, 0, 3 * GIB + 8), (7, 1, 0)],
)

# 0.22 (#157). An ack position is signed. A mid-stream capture's first ack can
# lie below the peer's first captured byte; stored in the type of an offset,
# its position wraps to near 2**64 and draws an edge from every peer record.
vector(
    "sequenced-ack-below-origin",
    "accept",
    "A mid-stream capture, SEQUENCED, with no isn on either side, so each "
    "participant's origin is its first captured byte: 1001 for the client, "
    "5001 for the server. The server's response is stored FIRST and carries "
    "ack 993 -- it acknowledges eight client bytes sent before the capture "
    "began. That ack's position in the client's stream is 993 - 1001 = -8: a "
    "signed integer, below 0, acknowledging no captured client byte, so no "
    "edge reaches the response. The client's request, stored after it, acks "
    "5013, the end of the response's twelve bytes, so the response precedes "
    "the request, as stored. A reader that keeps ack positions in an "
    "unsigned type -- the type of an offset -- wraps -8 to just under 2**64 "
    "(or 2**32, taking the serial delta unsigned), finds the request's end "
    "below it, draws request -> response, and refuses a correct order.",
    "Causal ordering from TCP seq/ack -- ack positions are signed",
    [
        file_header(),
        source(1, 0, [o_uri("midstream.pcap")]),
        session(7, [o_proto("tcp"), o_sess_flags(0x0001)]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        # Acks eight client bytes the capture never saw: position -8.
        record(7, 1, 1, 1000, b"HTTP/1.1 200", options=[o_seq_start(5001), o_ack(993)]),
        record(7, 0, 1, 1100, b"GET /two", options=[o_seq_start(1001), o_ack(5013)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "midstream.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp", "sequenced": True},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["93.184.216.34:80"],
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"HTTP/1.1 200"),
            "seq_start": 5001,
            "ack": 993,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1100,
            "payload": b64(b"GET /two"),
            "seq_start": 1001,
            "ack": 5013,
        },
        {"type": "end"},
    ],
    expect="Accept, and consume the records in STORED order: the session is "
    "SEQUENCED and the order is causal. The response's ack 993 is position -8 "
    "of the client's stream, below the request's end at 8, so no edge runs "
    "from the request to it. The request's ack 5013 is position 12 of the "
    "server's stream, where the response ends, so the response precedes the "
    "request, as stored. A reader that stores ack positions unsigned reads "
    "-8 as a huge position, draws request -> response, and reports the "
    "stored order as a causal violation. Rejecting, isolating, or refusing to "
    "write the file is NOT conformant. Extents are 8 and 12: with no isn, "
    "each stream starts at its first captured byte.",
    violations=0,
    extents=[(7, 0, 8), (7, 1, 12)],
)

# 0.23 (#160). A record's end is one past the last sequence number it
# occupies. A pure ACK occupies none, so no edge runs from it; through 0.22 it
# had an end at its offset, and the ordinary handshake, data, pure-ACK trace
# made a cycle. The close is added for the zero-length FIN, which occupies the
# number at its offset and so ends one past it.
vector(
    "sequenced-pure-ack-and-fin",
    "accept",
    "A SEQUENCED session with a recorded handshake, eight bytes of data, the "
    "server's pure ACK of them, the client's zero-length FIN, and the server's "
    "pure ACK of the FIN -- pure ACKs stored as zero-length records, as "
    "Caveats advises. Ends: the SYN 0 (it occupies isn, below the origin), "
    "the SYN-ACK 0, the data 8, the FIN 9 (it occupies the number at its "
    "offset 8), and the two pure ACKs NONE, since they occupy no sequence "
    "number. The edges are SYN -> SYN-ACK and both pure ACKs, SYN-ACK -> data "
    "and FIN, data -> both pure ACKs, and FIN -> the last pure ACK; the stored "
    "order respects all of them. Through 0.22 a pure ACK's end was its own "
    "offset, 0, which the data's ack of 5001 (position 0) covers: the false "
    "edge pure-ACK -> data against the real data -> pure-ACK, a cycle. The "
    "sequenced check refused the true order and an unsequenced merge "
    "stalled. Not caught before because no producer stored pure ACKs and "
    "every zero-length record in the suite was a SYN, whose edge is real. "
    "Being SEQUENCED, this file can only catch a reading that ADDS an edge; "
    "merge-pure-ack-and-fin is its unsequenced twin, for the readings that "
    "drop one and for a merge that stalls.",
    "Causal ordering from TCP seq/ack -- a record's end is one past the last sequence "
    "number it occupies",
    [
        file_header(),
        source(1, 0, [o_uri("close.pcap")]),
        session(7, [o_proto("tcp"), o_sess_flags(0x0001)]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(1)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000), o_tcp_role(2)]),
        record(7, 0, 1, 1000, b"", flags=0x0008, options=[o_seq_start(1001)]),
        record(7, 1, 1, 1100, b"", flags=0x0008, options=[o_seq_start(5001), o_ack(1001)]),
        record(
            7, 0, 1, 1200, b"HELO 1\r\n", flags=0x0001, options=[o_seq_start(1001), o_ack(5001)]
        ),
        # A pure ACK: no end. Through 0.22 its end was 0, and the data's ack
        # covering 0 made the edge pure-ACK -> data, a cycle with data -> here.
        record(7, 1, 1, 1300, b"", options=[o_seq_start(5001), o_ack(1009)]),
        # A zero-length FIN at offset 8: it occupies 1009, so its end is 9 and the
        # ack of 1009 just before it (position 8) does NOT cover it.
        record(7, 0, 1, 1400, b"", flags=0x0002, options=[o_seq_start(1009), o_ack(5001)]),
        record(7, 1, 1, 1500, b"", options=[o_seq_start(5001), o_ack(1010)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "close.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp", "sequenced": True},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
            "tcp_role": "initiator",
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
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
            "payload": b64(b"HELO 1\r\n"),
            "seq_start": 1001,
            "ack": 5001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1300,
            "payload": "",
            "seq_start": 5001,
            "ack": 1009,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1400,
            "flags": ["fin"],
            "payload": "",
            "seq_start": 1009,
            "ack": 5001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1500,
            "payload": "",
            "seq_start": 5001,
            "ack": 1010,
        },
        {"type": "end"},
    ],
    expect="Accept, and consume the records in STORED order: the session is "
    "SEQUENCED and the order is causal. Client ends: SYN 0, data 8, FIN 9. "
    "Server ends: SYN-ACK 0, and none for the two pure ACKs. Server ack "
    "positions 0, 8 and 9; client ack positions 0 (data and FIN). Every edge "
    "runs forward in stored order. A reader that gives a pure ACK an end at "
    "its offset draws pure-ACK -> data (0 <= 0) against data -> pure-ACK "
    "(8 <= 8), a cycle: it refuses the order, or, merging, stalls. A reader "
    "that ends the zero-length FIN at its offset (8) draws FIN -> the first "
    "pure ACK (8 <= 8), which is stored before the FIN, and refuses the order: "
    "that pure ACK acknowledged the data, not the FIN. Rejecting, isolating, "
    "or refusing to write the file is NOT conformant. Extents are 8 for the "
    "client -- the FIN occupies a sequence number but no byte -- and 0 for "
    "the server.",
    violations=0,
    extents=[(7, 0, 8), (7, 1, 0)],
)

# 0.23 (#161). The sequenced vector above is consumed in stored order, so only
# the stored-order check reaches the end rule, and that check fails only on an
# EXTRA edge. A reading that drops one passes it, and so does a merge that
# stalls only when it merges. This twin is unsequenced, with the server's clock
# 50 ticks behind, so the timestamp tie-break pulls a server record too early
# wherever an edge is missing: each wrong reading gives a different order.
vector(
    "merge-pure-ack-and-fin",
    "accept",
    "sequenced-pure-ack-and-fin's six records, NOT sequenced, with the "
    "server's capture clock 50 ticks behind the client's, and stored server "
    "first (each participant's own order kept), so stored order is not the "
    "answer. A reader merges: edges from acks, each participant's records in "
    "stored order, ties broken by (timestamp, participant_id). Under the 0.23 "
    "end rule the edges are SYN -> SYN-ACK and both pure ACKs, SYN-ACK -> data "
    "and FIN, data -> both pure ACKs, FIN -> the last pure ACK, and the merged "
    "order is client SYN, SYN-ACK, data, pure ACK, FIN, pure ACK -- the causal "
    "order, though the skew would put every server record first. Each wrong "
    "reading gives its own answer: a SYN given no end loses SYN -> SYN-ACK and "
    "the SYN-ACK (ts 950) overtakes the SYN it acknowledges; a pure ACK ended "
    "at its offset makes the cycle and the merge stalls after the SYN-ACK; a "
    "FIN ended at its offset puts the FIN before the pure ACK that "
    "acknowledged only the data.",
    "Causal ordering from TCP seq/ack -- the merge, over records with and without an end",
    [
        file_header(),
        source(1, 0, [o_uri("skewed.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000), o_tcp_role(1)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000), o_tcp_role(2)]),
        # Server first, its clock 50 behind. Stored order is not the merged one.
        record(7, 1, 1, 950, b"", flags=0x0008, options=[o_seq_start(5001), o_ack(1001)]),
        record(7, 1, 1, 1150, b"", options=[o_seq_start(5001), o_ack(1009)]),
        record(7, 1, 1, 1350, b"", options=[o_seq_start(5001), o_ack(1010)]),
        record(7, 0, 1, 1000, b"", flags=0x0008, options=[o_seq_start(1001)]),
        record(
            7, 0, 1, 1200, b"HELO 1\r\n", flags=0x0001, options=[o_seq_start(1001), o_ack(5001)]
        ),
        record(7, 0, 1, 1400, b"", flags=0x0002, options=[o_seq_start(1009), o_ack(5001)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "skewed.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
            "tcp_role": "initiator",
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["93.184.216.34:80"],
            "isn": 5000,
            "tcp_role": "responder",
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 950,
            "flags": ["syn"],
            "payload": "",
            "seq_start": 5001,
            "ack": 1001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1150,
            "payload": "",
            "seq_start": 5001,
            "ack": 1009,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 1350,
            "payload": "",
            "seq_start": 5001,
            "ack": 1010,
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
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1200,
            "flags": ["psh"],
            "payload": b64(b"HELO 1\r\n"),
            "seq_start": 1001,
            "ack": 5001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1400,
            "flags": ["fin"],
            "payload": "",
            "seq_start": 1009,
            "ack": 5001,
        },
        {"type": "end"},
    ],
    expect="Accept. Merged, the order is: client SYN (ts 1000), server SYN-ACK "
    "(950), client data (1200), server pure ACK (1150), client FIN (1400), "
    "server pure ACK (1350) -- in stored terms, records 4, 1, 5, 2, 6, 3. "
    "Every adjacent inversion of timestamp is an edge doing its work. A "
    "reader that gives a SYN no end puts the SYN-ACK first; one that gives a "
    "pure ACK an end at its offset stalls after the SYN-ACK, the data and the "
    "first pure ACK each waiting on the other; one that ends the zero-length "
    "FIN at its offset puts the FIN before the first pure ACK. A reader that "
    "returns stored order has not merged. Rejecting or isolating is NOT "
    "conformant. Extents are 8 for the client and 0 for the server.",
    violations=0,
    extents=[(7, 0, 8), (7, 1, 0)],
    merged=[(7, [4, 1, 5, 2, 6, 3])],
)


# 0.24 (#168). A closing side's final pure ACK is stored at the sequence number
# its segment carries, one past that side's FIN, and the extent counts sequence
# numbers: the stream reaches one past its last byte, and the position between
# is the FIN's. The trace is asymmetric on purpose. The server's FIN rides on
# its data and its final ACK is stored past it; the client's FIN rides on its
# data with nothing after it, so the one stream reaches past its FIN and the
# other does not. Shared with decoded-past-fin's capture.zpf.
def closed_final_ack() -> tuple[list[Blk], list[dict]]:
    """Build the capture-sourced close: both faces, for the vector and the fixture."""
    blocks = [
        file_header(),
        source(1, 0, [o_uri("close.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000)]),
        record(7, 0, 1, 1000, b"PING", flags=0x0001, options=[o_seq_start(1001), o_ack(5001)]),
        # Data and FIN: the data is [0,4), and the FIN occupies 5005, offset 4.
        record(7, 1, 1, 1100, b"PONG", flags=0x0003, options=[o_seq_start(5001), o_ack(1005)]),
        # Data and FIN again, [4,8) with the FIN at offset 8. It acks the
        # server's FIN (5006), and nothing of the client's is stored past it.
        record(7, 0, 1, 1200, b"QUIT", flags=0x0003, options=[o_seq_start(1005), o_ack(5006)]),
        # The server's final pure ACK, at its wire number 5006: offset 5, one
        # past its FIN. It acks the client's FIN (1010). No end, so no edge from it.
        record(7, 1, 1, 1300, b"", options=[o_seq_start(5006), o_ack(1010)]),
        end_block(),
    ]

    def rec(pid: int, ts: int, flags: list[str], payload: bytes, seq: int, ack: int) -> dict:
        return {
            "type": "record",
            "session_id": 7,
            "sender_pid": pid,
            "source_id": 1,
            "ts": ts,
            **({"flags": flags} if flags else {}),
            "payload": b64(payload),
            "seq_start": seq,
            "ack": ack,
        }

    jsonl = [
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "close.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 7,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["93.184.216.34:80"],
            "isn": 5000,
        },
        rec(0, 1000, ["psh"], b"PING", 1001, 5001),
        rec(1, 1100, ["psh", "fin"], b"PONG", 5001, 1005),
        rec(0, 1200, ["psh", "fin"], b"QUIT", 1005, 5006),
        rec(1, 1300, [], b"", 5006, 1010),
        {"type": "end"},
    ]
    return blocks, jsonl


CLOSED_BLOCKS, CLOSED_JSONL = closed_final_ack()
vector(
    "closed-final-ack",
    "accept",
    "A closed connection, as a sessionizer following Caveats writes it: each "
    "side's FIN rides on its data, and the server's final pure ACK is stored "
    "at the sequence number its segment carries, 5006 -- one past its own FIN "
    "at 5005. The server's stream is PONG at [0,4), its FIN at offset 4, and "
    "the pure ACK at offset 5, so the stream reaches 5: one past its last "
    "byte, and the position between is the FIN's. The client's FIN at offset 8 "
    "has nothing stored past it, so its stream ends at its last byte, 8. Since "
    "0.24 the extent is stated as the furthest point a placeable record "
    "reaches, measured in sequence numbers; through 0.23 it was never "
    "defined, and python-zipline's decode stage and its own coverage check "
    "disagreed on every closed connection zpfwire wrote.",
    "Referencing the source by stream offset -- a transport stream's extent",
    CLOSED_BLOCKS,
    jsonl=CLOSED_JSONL,
    expect="Accept. Extents are 8 for the client and 5 for the server: the "
    "server's final pure ACK at offset 5 extends its stream past the FIN's "
    "position, 4, which holds no byte. A reader that counts only bytes "
    "measures the server's stream as 4 and is wrong. Ends for the merge, per "
    "Fields used: PING 4, PONG 4 (a data record keeps its data end with FIN), "
    "QUIT 8, and none for the pure ACK. Ack positions 0, 4, 5 and 9. The merge "
    "is stored order.",
    violations=0,
    extents=[(7, 0, 8), (7, 1, 5)],
    merged=[(7, [1, 2, 3, 4])],
)


# 0.24 (#169). A DNS answer seen twice through a mirror port. On UDP the copy
# cannot be discarded -- the withholding rule makes it content of the stream --
# so it is written, and since 0.24 the `copy` flag says the sender sent once.
# The isolate twin flags a record whose bytes differ from its predecessor's, the
# one constraint a reader can check without knowing how the producer told.
DNS_QUERY = b"Q example.com A"
DNS_ANSWER = b"R example.com A 93.184.216.34"


def udp_capture_copy(copy_payload: bytes) -> tuple[list[Blk], list[dict]]:
    """Build a query, its answer, and the answer's capture-point copy: both faces."""
    sent = [(0, 1000, DNS_QUERY, 0x0080, ["message"]), (1, 1100, DNS_ANSWER, 0x0080, ["message"])]
    recs = [*sent, (1, 1101, copy_payload, 0x0180, ["message", "copy"])]
    blocks = [
        file_header(),
        source(1, 0, [o_uri("mirror.pcap")]),
        session(9, [o_proto("udp")]),
        participant(9, 0, [o_endpoint("10.0.0.1:53000")]),
        participant(9, 1, [o_endpoint("10.0.0.53:53")]),
        *(record(9, pid, 1, ts, p, flags=f) for pid, ts, p, f, _tokens in recs),
        end_block(),
    ]
    jsonl = [
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "mirror.pcap"},
        {"type": "session", "session_id": 9, "proto": "udp"},
        {
            "type": "participant",
            "session_id": 9,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:53000"],
        },
        {
            "type": "participant",
            "session_id": 9,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.53:53"],
        },
        *(
            {
                "type": "record",
                "session_id": 9,
                "sender_pid": pid,
                "source_id": 1,
                "ts": ts,
                "flags": tokens,
                "payload": b64(p),
            }
            for pid, ts, p, _f, tokens in recs
        ),
        {"type": "end"},
    ]
    return blocks, jsonl


COPY_BLOCKS, COPY_JSONL = udp_capture_copy(DNS_ANSWER)
vector(
    "udp-capture-copy",
    "accept",
    "A DNS query and its answer over UDP, captured through a mirror port that "
    "saw the answer twice, a microsecond apart. On a sequence-anchored stream "
    "the reassembler would discard the copy and cite it; a stream without a "
    "sequence anchor has no such exit, since the withholding rule makes the "
    "copy content of the stream. So it is written, as the server's second "
    "record, and since 0.24 the copy flag says the sender sent once. It "
    "repeats its participant's preceding record byte for byte and carries no "
    "seq_start, as the two MUST NOTs require. Through 0.23 the file could only "
    "say the server answered twice.",
    "Enums -- copy names the capture point's act, where the copy cannot be discarded",
    COPY_BLOCKS,
    jsonl=COPY_JSONL,
    expect="Accept. The server's second record carries the token copy (flags "
    "message and copy, 0x0180), and the JSONL projection names it; a reader "
    "without the token renders 0x0100 as a hex token and fails the "
    "projection. Read as messages as sent, the exchange is one query and one "
    "answer: skip the flagged record. Read as what the capture saw, it is "
    "three records. The copy is content of the stream either way, so the "
    "server's extent counts it: 58, twice the answer's 29. The client's is 15. "
    "The session is hint-less, so the merge is by timestamp: stored order.",
    violations=0,
    extents=[(9, 0, 15), (9, 1, 58)],
    merged=[(9, [1, 2, 3])],
)

DIFF_BLOCKS, DIFF_JSONL = udp_capture_copy(DNS_ANSWER[:-1] + b"5")
vector(
    "isolate-copy-differs",
    "isolate",
    "udp-capture-copy with the copy's last byte changed: the record flagged "
    "copy says 93.184.216.35 where the record it claims to repeat says "
    "93.184.216.34. A writer MUST NOT set copy unless the record's payload is "
    "byte-identical to its participant's preceding record's, so the flag "
    "asserts a repeat the bytes contradict. This is the constraint a reader "
    "can check from the file alone, whatever the producer knew.",
    "Enums -- copy names the capture point's act, where the copy cannot be discarded",
    DIFF_BLOCKS,
    jsonl=DIFF_JSONL,
    expect="Isolate session 9 (a reader MAY treat it as a semantic violation), "
    "or reject. A reader that trusts the flag and skips the record drops an "
    "answer that differs from the first, which is the misreading the "
    "constraint prevents. The projection is still the .jsonl: the flag "
    "round-trips as copy whatever the reader concludes about it.",
    violations=1,
)

# 0.22 (#152). The carry duty's two recourses are both barred at the transport
# layer, so a reassembler over a unit sequence could never coalesce two
# packets. Its sequence numbers carry any break as a hole, so now it may.
vector(
    "sessionized-across-units",
    "accept",
    "A sessionization stage over a packet stream -- tunnel's inner hop, with "
    "nothing lost. The input, packets.zpf, is a unit sequence as kober's "
    "WireGuard output is: three inner packets at [0,80), [80,140) and "
    "[140,210), participant declared units, so every seam is a declared break. "
    "The first and third are flow A's and carry 40 and 30 bytes of TCP payload "
    "at seq 1001 and 1041, which join; the second is flow B's. Session 10's one "
    "record coalesces flow A into 70 bytes with TWO spans, one per input "
    "packet, crossing two declared breaks. Through 0.21 that record had no "
    "conformant form: the carry duty asked for a Discontinuity or a units "
    "output, and a transport-layer stream may have neither. Since 0.22 a "
    "transport output whose records carry seq_start MAY cross, because a break "
    "there is a range of sequence numbers no record covers and cannot be lost. "
    "Nothing in this file shows the input's adjacency, and nothing could catch "
    "a wrong coalesce: the sequence numbers are the producer's assertion.",
    "Discontinuity (0x22) -- what a consumer owes the block",
    [
        file_header(options=[o_produced_by("zpf-sessionize 1.0"), o_produced_at(1719700100)]),
        source(1, 1, [o_uri("packets.zpf"), o_digest("sha256:5e1a")]),
        decoder(
            1,
            [
                o_dec_name("tcp-reassembly"),
                o_dec_version("1.1"),
                o_params_digest("sha256:2f60"),
            ],
            output_layer=1,
        ),
        session(10, [o_proto("tcp")]),
        participant(10, 0, [o_endpoint("10.8.0.2:44300"), o_isn(1000)]),
        # One record, two input packets: [0,80) and [140,210), flow B's between.
        record(
            10,
            0,
            1,
            1000,
            b"A" * 40 + b"B" * 30,
            options=[
                o_decoder_id(1),
                o_spans([(1, 5, 0, 0, 80), (1, 5, 0, 140, 210)]),
                o_seq_start(1001),
            ],
        ),
        session_end(10, [o_input_extents([(1, 5, 0, 210)])]),
        session(11, [o_proto("tcp")]),
        participant(11, 0, [o_endpoint("10.8.0.2:44301"), o_isn(5000)]),
        record(
            11,
            0,
            1,
            1100,
            b"C" * 20,
            options=[o_decoder_id(1), o_spans([(1, 5, 0, 80, 140)]), o_seq_start(5001)],
        ),
        session_end(11, [o_input_extents([(1, 5, 0, 210)])]),
        end_block(),
    ],
    jsonl=[
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
            "digest": "sha256:5e1a",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "transport",
            "name": "tcp-reassembly",
            "version": "1.1",
            "params_digest": "sha256:2f60",
        },
        {"type": "session", "session_id": 10, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 10,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.8.0.2:44300"],
            "isn": 1000,
        },
        {
            "type": "record",
            "session_id": 10,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"A" * 40 + b"B" * 30),
            "decoder_id": 1,
            "spans": [
                {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 0, "off_end": 80},
                {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 140, "off_end": 210},
            ],
            "seq_start": 1001,
        },
        {
            "type": "session_end",
            "session_id": 10,
            "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": 210}],
        },
        {"type": "session", "session_id": 11, "proto": "tcp"},
        {
            "type": "participant",
            "session_id": 11,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.8.0.2:44301"],
            "isn": 5000,
        },
        {
            "type": "record",
            "session_id": 11,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1100,
            "payload": b64(b"C" * 20),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 5, "pid": 0, "off_start": 80, "off_end": 140}],
            "seq_start": 5001,
        },
        {
            "type": "session_end",
            "session_id": 11,
            "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": 210}],
        },
        {"type": "end"},
    ],
    expect="Accept. Session 10 has one placeable record at [0,70), extent 70; "
    "session 11 one at [0,20), extent 20. The input stream (source 1, session "
    "5, pid 0) is covered once over [0,210) by the union of the two sessions' "
    "spans, and both Session Ends declare its whole extent, 210, as fan-out "
    "requires. Session 10's record cites two input units and crosses two "
    "declared breaks; that is conformant for a transport-layer output whose "
    "records carry seq_start, and the seam predicate does not apply, since it "
    "tests decoded layers only. A reader that reports a no-splice violation, "
    "or rejects or isolates the session, has applied the decoded layer's "
    "carry duty to a stream whose offsets already carry every break.",
    violations=0,
    extents=[(10, 0, 70), (11, 0, 20)],
)


IPV4_SRC, IPV4_DST = bytes([10, 8, 0, 2]), bytes([10, 8, 0, 9])
TCP, UDP = 6, 17
TCP_PSH_ACK = 0x18


def inet_checksum(data: bytes) -> int:
    """Return the RFC 1071 ones'-complement checksum of `data`."""
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f">{len(data) // 2}H", data))
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def tcp(
    sport: int, dport: int, seq: int, ack: int, payload: bytes, src: bytes, dst: bytes
) -> bytes:
    """Build a 20-byte TCP header, flags PSH|ACK, true checksum, on `payload`."""
    hdr = bytearray(
        struct.pack(">HHIIBBHHH", sport, dport, seq, ack, 5 << 4, TCP_PSH_ACK, 65535, 0, 0)
    )
    pseudo = src + dst + struct.pack(">BBH", 0, TCP, len(hdr) + len(payload))
    struct.pack_into(">H", hdr, 16, inet_checksum(pseudo + bytes(hdr) + payload))
    return bytes(hdr) + payload


def udp(sport: int, dport: int, payload: bytes, src: bytes, dst: bytes) -> bytes:
    """Build an 8-byte UDP header, true length and checksum, on `payload`."""
    hdr = bytearray(struct.pack(">HHHH", sport, dport, 8 + len(payload), 0))
    pseudo = src + dst + struct.pack(">BBH", 0, UDP, len(hdr) + len(payload))
    struct.pack_into(">H", hdr, 6, inet_checksum(pseudo + bytes(hdr) + payload) or 0xFFFF)
    return bytes(hdr) + payload


def ipv4(proto: int, segment: bytes, src: bytes = IPV4_SRC, dst: bytes = IPV4_DST) -> bytes:
    """Prefix `segment` with a 20-byte IPv4 header: true length and checksum.

    Since 0.22 a packet-preserving stage types its records net:ip, which means
    LINKTYPE_RAW: the payload IS an IP packet, and every header in it is real
    -- the IP header, and the TCP or UDP header after it, ports, sequence
    numbers and checksums included -- so the label is true and a sessionizer
    can rebuild the next hop from the packets alone (#154). Checked with an
    independent parser (packeteer) when written; nothing here depends on it.
    """
    hdr = bytearray(
        struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(segment), 0, 0x4000, 64, proto, 0, src, dst)
    )
    struct.pack_into(">H", hdr, 10, inet_checksum(bytes(hdr)))
    return bytes(hdr) + segment


def tcp_packet(sport: int, dport: int, seq: int, ack: int, payload: bytes) -> bytes:
    """Build an IPv4 packet carrying one TCP segment, 10.8.0.2 -> 10.8.0.9."""
    return ipv4(TCP, tcp(sport, dport, seq, ack, payload, IPV4_SRC, IPV4_DST))


def udp_packet(sport: int, dport: int, payload: bytes) -> bytes:
    """Build an IPv4 packet carrying one UDP datagram, 10.8.0.2 -> 10.8.0.9."""
    return ipv4(UDP, udp(sport, dport, payload, IPV4_SRC, IPV4_DST))


def udp_fragments(sport: int, dport: int, payload: bytes, ident: int, cut: int) -> list[bytes]:
    """Split one UDP datagram into two IPv4 fragments at byte `cut` of its IP payload.

    Real headers, as ipv4() writes them, but with DF clear: both carry the
    identification `ident`, the first sets More Fragments at offset 0, and the
    second gives its offset in 8-byte units (#166). `cut` must be a multiple of 8.
    """
    datagram = udp(sport, dport, payload, IPV4_SRC, IPV4_DST)
    out = []
    for start, end, flags in ((0, cut, 0x2000), (cut, len(datagram), 0)):
        chunk = datagram[start:end]
        hdr = bytearray(
            struct.pack(
                ">BBHHHBBH4s4s",
                0x45,
                0,
                20 + len(chunk),
                ident,
                flags | start // 8,
                64,
                UDP,
                0,
                IPV4_SRC,
                IPV4_DST,
            )
        )
        struct.pack_into(">H", hdr, 10, inet_checksum(bytes(hdr)))
        out.append(bytes(hdr) + chunk)
    return out


ETH_DST, ETH_SRC = bytes.fromhex("aabbcc000002"), bytes.fromhex("aabbcc000001")


def ethernet(packet: bytes) -> bytes:
    """Wrap `packet` as IPv4 in an Ethernet II frame: LINKTYPE_ETHERNET's unit."""
    return ETH_DST + ETH_SRC + b"\x08\x00" + packet


# 14 + 20 + 8 + 18 = 60 and 14 + 20 + 8 + 8 = 50: the sizes the vector had when its
# packets were filler, so no offset of it moved when they became real (#154).
FRAME_1 = ethernet(udp_packet(40000, 5000, b"d" * 18))
FRAME_2 = ethernet(udp_packet(40000, 5000, b"e" * 8))

# 0.22 (#153). net:'s second value. tunnel carries net:ip; this is the stage
# whose output is link-layer frames, which is why the scheme has more than one
# value at all. The input it cites -- an 8-byte VXLAN header (I flag, VNI 5001)
# before each frame -- is described, not shipped.
vector(
    "decap-ethernet",
    "accept",
    "A VXLAN decapsulation stage: its input is two 8-byte VXLAN headers each "
    "followed by an inner Ethernet frame, and its output is one record per "
    "frame typed net:ethernet -- LINKTYPE_ETHERNET's unit, from the destination "
    "address, no preamble, no FCS. Every header in each frame is real -- "
    "Ethernet II, IPv4, UDP, lengths and checksums true -- so a reader that "
    "knows the token can hand each record to "
    "anything that reads a pcap of link type 1. Each record spans its whole "
    "datagram, VXLAN header included, because the header (its VNI) fed the "
    "decapsulation -- the correspondence rule tunnel's decrypt stage follows. "
    "The participant is declared units, since two frames side by side are two "
    "packets and never one byte run; contiguous with no Discontinuity is also "
    "conformant, as tunnel shows. The endpoint list runs outer to inner: the "
    "VNI, then the inner sender's MAC.",
    "Enums -- the content_type net: vocabulary",
    [
        file_header(options=[o_produced_by("zpf-vxlan 0.1"), o_produced_at(1719800000)]),
        source(1, 1, [o_uri("vxlan.zpf"), o_digest("sha256:91c3")]),
        decoder(
            1,
            [o_dec_name("vxlan-decap"), o_dec_version("0.1"), o_params_digest("sha256:0b7d")],
        ),
        session(4, [o_proto("ethernet")]),
        participant(4, 0, [o_endpoint("vni:5001"), o_endpoint("aa:bb:cc:00:00:01")], adjacency=1),
        record(
            4,
            0,
            1,
            1000,
            FRAME_1,
            options=[o_decoder_id(1), o_spans([(1, 3, 0, 0, 68)]), o_content_type("net:ethernet")],
        ),
        record(
            4,
            0,
            1,
            1100,
            FRAME_2,
            options=[
                o_decoder_id(1),
                o_spans([(1, 3, 0, 68, 126)]),
                o_content_type("net:ethernet"),
            ],
        ),
        session_end(4, [o_input_extents([(1, 3, 0, 126)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-vxlan 0.1",
            "produced_at": 1719800000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "vxlan.zpf",
            "digest": "sha256:91c3",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "vxlan-decap",
            "version": "0.1",
            "params_digest": "sha256:0b7d",
        },
        {"type": "session", "session_id": 4, "proto": "ethernet"},
        {
            "type": "participant",
            "session_id": 4,
            "pid": 0,
            "adjacency": "units",
            "endpoint": ["vni:5001", "aa:bb:cc:00:00:01"],
        },
        {
            "type": "record",
            "session_id": 4,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(FRAME_1),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 3, "pid": 0, "off_start": 0, "off_end": 68}],
            "content_type": "net:ethernet",
        },
        {
            "type": "record",
            "session_id": 4,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1100,
            "payload": b64(FRAME_2),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 3, "pid": 0, "off_start": 68, "off_end": 126}],
            "content_type": "net:ethernet",
        },
        {
            "type": "session_end",
            "session_id": 4,
            "input_extents": [{"source_id": 1, "session_id": 3, "pid": 0, "extent": 126}],
        },
        {"type": "end"},
    ],
    expect="Accept. Two records at [0,60) and [60,110) of a unit sequence, extent "
    "110; the input stream (source 1, session 3, pid 0) is covered once over "
    "[0,126). Both records' content_type is net:ethernet, a token this version "
    "defines: the payload is one Ethernet frame as a LINKTYPE_ETHERNET capture "
    "stores it. A reader that does not know the net: scheme treats the label "
    "as opaque and falls back to the decoder name, which is conformant -- an "
    "unknown scheme is opaque -- but a reader implementing this version knows "
    "the token. Rejecting or isolating is NOT conformant, and neither is "
    "checking the label against the payload: net: binds no length and the "
    "format parses no packet.",
    violations=0,
    extents=[(4, 0, 110)],
)

# 0.21 (#80, #106). The adjacency body field, in its four shapes: the two the
# milestone comment asked for, and the two every load-bearing enum owes.
DNS_HEADER = b"\x12\x34\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"


vector(
    "unit-sequence-reversed",
    "accept",
    "#80's shape: a stage that REVERSES a participant's four decoded records, "
    "and declares the participant a unit sequence instead of emitting a "
    "Discontinuity at each of its three seams. Input pid 1 held A = [0,40), "
    "B = [40,80), C = [80,120), D = [120,160); the output stores D, C, B, A, "
    "so the spans run downward at every step and no two stored neighbours "
    "were ever neighbours on the wire. Under the per-seam form that is N-1 "
    "blocks saying the same thing; adjacency = units says it once, for the "
    "participant, and is the truer statement -- the stream's contiguity claim "
    "is void as a whole, not at three points. The offset space is UNCHANGED: "
    "D at [0,40), C at [40,80), B at [80,120), A at [120,160), extent 160, "
    "every record addressable and citable. What changed is what adjacency "
    "asserts, which is nothing. A reader that applies the reordering "
    "predicate regardless of the field, or splices any two of these records, "
    "has ignored a body field. Like reordered-decoded it is a decode stage "
    "with an inherited decoder and its own config in transform_params_digest; "
    "unlike it, no block.",
    "Participant Descriptor -- adjacency",
    [
        file_header(
            options=[
                o_produced_by("zpf-reverse 0.1"),
                o_produced_at(1719540000),
                o_transform_params_digest("sha256:9b2f"),
            ]
        ),
        source(1, 1, [o_uri("decoded.zpf"), o_digest("sha256:44dd")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        # THE FIELD: units. Every seam below is a break, and none is marked.
        participant(7, 1, [o_endpoint("93.184.216.34:80")], adjacency=1),
        record(
            7,
            1,
            1,
            995,
            b"D" * 40,
            options=[o_decoder_id(1), o_spans([(1, 7, 1, 120, 160)])],
        ),
        record(
            7,
            1,
            1,
            994,
            b"C" * 40,
            options=[o_decoder_id(1), o_spans([(1, 7, 1, 80, 120)])],
        ),
        record(
            7,
            1,
            1,
            993,
            b"B" * 40,
            options=[o_decoder_id(1), o_spans([(1, 7, 1, 40, 80)])],
        ),
        record(
            7,
            1,
            1,
            992,
            b"A" * 40,
            options=[o_decoder_id(1), o_spans([(1, 7, 1, 0, 40)])],
        ),
        session_end(7, [o_input_extents([(1, 7, 1, 160)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-reverse 0.1",
            "produced_at": 1719540000,
            "transform_params_digest": "sha256:9b2f",
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
        {
            "type": "participant",
            "session_id": 7,
            "pid": 1,
            "adjacency": "units",
            "endpoint": ["93.184.216.34:80"],
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 995,
            "payload": b64(b"D" * 40),
            "decoder_id": 1,
            "spans": [
                {"source_id": 1, "session_id": 7, "pid": 1, "off_start": 120, "off_end": 160}
            ],
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 994,
            "payload": b64(b"C" * 40),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 1, "off_start": 80, "off_end": 120}],
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 993,
            "payload": b64(b"B" * 40),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 1, "off_start": 40, "off_end": 80}],
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 1,
            "source_id": 1,
            "ts": 992,
            "payload": b64(b"A" * 40),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 1, "off_start": 0, "off_end": 40}],
        },
        {
            "type": "session_end",
            "session_id": 7,
            "input_extents": [{"source_id": 1, "session_id": 7, "pid": 1, "extent": 160}],
        },
        {"type": "end"},
    ],
    expect="Accept. The .jsonl file is the expected projection, and the declared "
    "extent is 160: four 40-byte records at [0,40), [40,80), [80,120) and "
    "[120,160) in stored order, the same arithmetic as any decoded stream. "
    "The participant is a unit sequence, so a consumer MUST NOT treat any two "
    "of its records as contiguous, and the file owes no Discontinuity at any "
    "seam. A reader that raises the reordering predicate here has not read "
    "the body field; one that reports the file as missing three blocks has "
    "applied the per-seam form to a participant that took the other. "
    "Coverage is complete -- four spans, [0,160), meeting the declared "
    "extent -- and descending spans are no finding, as reordered-decoded "
    "already shows.",
    violations=0,
    extents=[(7, 1, 160)],
)

vector(
    "unit-sequence-nested",
    "accept",
    "#106's shape: a decoder whose units DECOMPOSE one another. A 12-byte DNS "
    "header is emitted whole, then its flags word, then three sub-fields of "
    "the flags word -- so input bytes [2,4) appear at FIVE different offsets "
    "of the output stream, and the stream is a pre-order flattening of a tree "
    "with the tree removed. The seam duty asks whether two adjacent units "
    "JOIN, and here the question does not apply: `flags.qr` is not "
    "continuous with `flags`, it is INSIDE it, and adjacency was never a claim "
    "about continuity. Before 0.21 such a file was untested rather than "
    "conformant -- the seam predicate declines every A >= B pair, and this "
    "file is built entirely out of them. Now it says what it is: "
    "adjacency = units, no block owed, the offset space still the "
    "concatenation (12 + 2 + 1 + 1 + 1 = 17) so every field is citable by a "
    "downstream stage. kober's DNS output in miniature, and the first vector "
    "in the suite whose spans overlap by containment. Coverage: the header's "
    "span covers [0,12) of the input, which is at-least-once; the sub-field "
    "spans overlap it, which is permitted.",
    "Participant Descriptor -- adjacency",
    [
        file_header(options=[o_produced_by("zpf-dnsfields 0.1"), o_produced_at(1719810000)]),
        source(1, 1, [o_uri("frames.zpf"), o_digest("sha256:6a1c")]),
        decoder(1, [o_dec_name("dns-fields"), o_dec_version("0.1")]),
        session(31, [o_proto("dns")]),
        participant(31, 0, [o_endpoint("10.0.0.1:53000")], adjacency=1),
        record(
            31,
            0,
            1,
            1000,
            DNS_HEADER,
            options=[
                o_decoder_id(1),
                o_spans([(1, 30, 0, 0, 12)]),
                o_content_type("prim:bytes"),
                o_role("header"),
            ],
        ),
        # The flags word, stored little-endian as prim: requires; the wire is
        # big-endian 0x8180 and the decoder byte-swapped it.
        record(
            31,
            0,
            1,
            1000,
            struct.pack("<H", 0x8180),
            options=[
                o_decoder_id(1),
                o_spans([(1, 30, 0, 2, 4)]),
                o_content_type("prim:u16"),
                o_role("flags"),
            ],
        ),
        # Three fields carved out of the two bytes just emitted. Sub-byte
        # fields widen to prim:u8 and cite the byte containing them.
        record(
            31,
            0,
            1,
            1000,
            b"\x01",
            options=[
                o_decoder_id(1),
                o_spans([(1, 30, 0, 2, 3)]),
                o_content_type("prim:u8"),
                o_role("flags.qr"),
            ],
        ),
        record(
            31,
            0,
            1,
            1000,
            b"\x00",
            options=[
                o_decoder_id(1),
                o_spans([(1, 30, 0, 2, 3)]),
                o_content_type("prim:u8"),
                o_role("flags.opcode"),
            ],
        ),
        record(
            31,
            0,
            1,
            1000,
            b"\x00",
            options=[
                o_decoder_id(1),
                o_spans([(1, 30, 0, 3, 4)]),
                o_content_type("prim:u8"),
                o_role("flags.rcode"),
            ],
        ),
        session_end(31, [o_input_extents([(1, 30, 0, 12)])]),
        end_block(),
    ],
    jsonl=[
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-dnsfields 0.1",
            "produced_at": 1719810000,
        },
        {
            "type": "source",
            "source_id": 1,
            "kind": "zpf-input",
            "uri": "frames.zpf",
            "digest": "sha256:6a1c",
        },
        {
            "type": "decoder",
            "decoder_id": 1,
            "output_layer": "decoded",
            "name": "dns-fields",
            "version": "0.1",
        },
        {"type": "session", "session_id": 31, "proto": "dns"},
        {
            "type": "participant",
            "session_id": 31,
            "pid": 0,
            "adjacency": "units",
            "endpoint": ["10.0.0.1:53000"],
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(DNS_HEADER),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 0, "off_end": 12}],
            "content_type": "prim:bytes",
            "role": "header",
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(struct.pack("<H", 0x8180)),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 2, "off_end": 4}],
            "content_type": "prim:u16",
            "role": "flags",
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"\x01"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 2, "off_end": 3}],
            "content_type": "prim:u8",
            "role": "flags.qr",
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"\x00"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 2, "off_end": 3}],
            "content_type": "prim:u8",
            "role": "flags.opcode",
        },
        {
            "type": "record",
            "session_id": 31,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(b"\x00"),
            "decoder_id": 1,
            "spans": [{"source_id": 1, "session_id": 30, "pid": 0, "off_start": 3, "off_end": 4}],
            "content_type": "prim:u8",
            "role": "flags.rcode",
        },
        {
            "type": "session_end",
            "session_id": 31,
            "input_extents": [{"source_id": 1, "session_id": 30, "pid": 0, "extent": 12}],
        },
        {"type": "end"},
    ],
    expect="Accept. The .jsonl file is the expected projection, and the declared "
    "extent is 17: five records at [0,12), [12,14), [14,15), [15,16) and "
    "[16,17), the stored-order concatenation, exactly as for any decoded "
    "stream. The participant is a unit sequence, so no two of these records "
    "may be treated as contiguous -- which is right, since the third is "
    "inside the second -- and the seam predicate does not apply to it. A "
    "reader that owes this file a Discontinuity between any pair has misread "
    "the field; one that rejects the overlapping spans has misread the "
    "coverage rule, which requires at least once and forbids only "
    "spanned-and-Undecoded. Rejecting or isolating is NOT conformant.",
    violations=0,
    extents=[(31, 0, 17)],
)

vector(
    "isolate-unknown-adjacency",
    "isolate",
    "A Participant declaring an adjacency this version does not define. The "
    "third load-bearing enum, and the load-bearing twin of "
    "isolate-unknown-output-layer for the same reason: the value decides "
    "whether any two of this participant's records may be spliced, so a "
    "reader that does not recognise it cannot say what a single pair of them "
    "asserts. Contrast escape-unknown-enum, where an unknown tcp_role is "
    "advisory. The file is otherwise conformant -- a decoded stream with one "
    "record -- and the failure is entirely in what the reader cannot conclude.",
    "Enums -- load-bearing values",
    [
        file_header(options=[o_produced_by("zpf-decode 0.9"), o_produced_at(1719820000)]),
        source(1, 1, [o_uri("transport.zpf"), o_digest("sha256:2e9d")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        # THE VIOLATION: adjacency 2, which nothing defines.
        participant(7, 0, [o_endpoint("10.0.0.1:51000")], adjacency=2),
        record(
            7,
            0,
            1,
            1000,
            b"GET / HTTP/1.1\r\n\r\n",
            options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 18)])],
        ),
        end_block(),
    ],
    expect="MAY reject the file, or discard participant 0 of session 7 together "
    "with everything referencing it. MUST NOT guess a value, and MUST NOT "
    "fall back to contiguous -- 0 and an unrecognised value are different "
    "statements, and treating them alike would splice records the writer "
    "may have declared unjoinable. This is the same condition as an unknown "
    "Source kind or output_layer and is handled the same way.",
    violations=1,
)

vector(
    "advisory-transport-adjacency",
    "accept",
    "adjacency = units on a TRANSPORT-layer participant: a capture-sourced TCP "
    "stream whose offsets come from its sequence numbers, where stored order "
    "defines nothing and the field says nothing. A writer MUST NOT set it "
    "there, and the violation is ADVISORY in the shape of a transport-layer "
    "label: the reader ignores the field, reports it, and accepts the file, "
    "because ignoring it loses nothing -- every offset is still exactly where "
    "seq_start puts it. Not the isolate shape of isolate-discontinuity-in-raw: "
    "that block contradicts the offsets, this field is merely inert. The "
    "extent is 16 by seq_start arithmetic, and a reader that changed it on "
    "account of the field has read a body field the layer told it to ignore.",
    "Participant Descriptor -- adjacency on a transport-layer participant",
    [
        file_header(),
        source(1, 0, [o_uri("c.pcap")]),
        session(7, [o_proto("tcp")]),
        # THE VIOLATION: units on a participant whose records are byte runs.
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)], adjacency=1),
        record(7, 0, 1, 1000, b"AAAABBBB", flags=0x0001, options=[o_seq_start(1001)]),
        record(7, 0, 1, 2000, b"CCCCDDDD", flags=0x0001, options=[o_seq_start(1009)]),
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
            "adjacency": "units",
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
            "payload": b64(b"AAAABBBB"),
            "seq_start": 1001,
        },
        {
            "type": "record",
            "session_id": 7,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 2000,
            "flags": ["psh"],
            "payload": b64(b"CCCCDDDD"),
            "seq_start": 1009,
        },
        {"type": "end"},
    ],
    expect="Accept, having reported the field: adjacency = units on a "
    "transport-layer participant breaks a MUST NOT whose violation is "
    "advisory. The reader ignores the field and reads the stream as any "
    "sequence-anchored transport stream -- two records at [0,8) and [8,16), "
    "extent 16. The .jsonl file is the expected projection and carries the "
    "field as written, since a projection preserves what it does not act "
    "on. Rejecting or isolating this file is NOT conformant: the advisory "
    "strength is stated in Participant Descriptor, by reference to the "
    "treatment a transport-layer label gets.",
    violations=1,
    advisory=True,
    extents=[(7, 0, 16)],
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
                o_spans([(1, 7, 1, 0, 60)]),
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
                o_spans([(1, 7, 1, 100, 160)]),
                o_content_type("dec:response"),
            ],
        ),
        session_end(7, [o_input_extents([(1, 7, 1, 160)])]),
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
    "which that is true (adjacency, since 0.21, is the third -- see "
    "isolate-unknown-adjacency): the value decides whether this stream's offsets are "
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
            options=[o_decoder_id(1), o_spans([(1, 4, 0, 0, 50)]), o_seq_start(1001)],
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
    Refused, as a single-file vector is, if its two faces disagree.
    """
    check_faces(f"{fixture}/{name}", blocks, jsonl)
    FIXTURES[fixture]["members"].append(
        {"name": name, "summary": summary, "blocks": blocks, "jsonl": jsonl}
    )
    return to_bytes(assemble(blocks))


def fixture(
    name: str,
    tier: str,
    summary: str,
    spec: str,
    expect: str,
    *,
    violations: int,
    merged: list[tuple[str, int, list[int]]] | None = None,
) -> None:
    """Declare a multi-file fixture. Its files are added by member().

    `merged` is vector()'s key with the file named (#163): the files of one
    fixture share session ids, so an order is `(file, session_id, order)`, the
    file being the member's name. It is checked once the members exist, by
    check_fixture_merged().
    """
    FIXTURES[name] = {
        "name": name,
        "tier": tier,
        "summary": summary,
        "spec": spec,
        "expect": expect,
        "violations": violations,
        "merged": merged,
        "members": [],
    }


def check_fixture_merged(fx: dict) -> list[dict] | None:
    """Require `merged` per member file, by the single-file rule, and name each item's file."""
    members = [c["name"] for c in fx["members"]]
    given = fx["merged"] or []
    unknown = sorted({f for f, _sid, _order in given} - set(members))
    if unknown:
        raise ValueError(f"{fx['name']}: merged names files {unknown}, not among {members}")
    for c in fx["members"]:
        mine = [(sid, order) for f, sid, order in given if f == c["name"]]
        check_merged(f"{fx['name']}/{c['name']}", fx["tier"], c["blocks"], mine or None)
    if not given:
        return None
    return [{"file": f, "session_id": sid, "order": order} for f, sid, order in given]


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
        # Each file's session 7 has two senders. raw is ordered by its acks
        # (the response acks the request's end), the two decoded files by
        # timestamp alone. Every order equals stored order (#163).
        merged=[("raw", 7, [1, 2, 3]), ("decoded", 7, [1, 2]), ("annotated", 7, [1, 2])],
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
                "adjacency": "contiguous",
                "endpoint": ["10.0.0.1:51000"],
                "isn": 1000,
            },
            {
                "type": "participant",
                "session_id": 7,
                "pid": 1,
                "adjacency": "contiguous",
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
            options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 9)]), o_content_type("dec:request")],
        ),
        record(
            7,
            1,
            1,
            1100,
            DEC_RESP,
            options=[o_decoder_id(1), o_spans([(1, 7, 1, 0, 16)]), o_content_type("dec:response")],
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
            {
                "type": "participant",
                "session_id": 7,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.0.0.1:51000"],
            },
            {
                "type": "participant",
                "session_id": 7,
                "pid": 1,
                "adjacency": "contiguous",
                "endpoint": ["93.184.216.34:80"],
            },
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
                o_spans([(2, 7, 0, 0, len(DEC_REQ))]),
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
                o_spans([(2, 7, 1, 0, len(DEC_RESP))]),
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
                "adjacency": "contiguous",
                "endpoint": ["10.0.0.1:51000"],
            },
            {
                "type": "participant",
                "session_id": 7,
                "pid": 1,
                "adjacency": "contiguous",
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
        record(7, 0, 1, 1000, b"A" * 50, options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 100)])]),
        undecoded(1, 0, 7, 100, 139, [o_reason("gap"), o_decoder_id(1)]),
        # No width: the plaintext length the lost ciphertext would have
        # produced is not recoverable, so it contributes 0 and the two records
        # remain numerically adjacent at 50 -- which is the whole hazard.
        discontinuity(7, 0, [o_disc_reason("tls-record-lost")]),
        record(7, 0, 1, 1100, b"B" * 30, options=[o_decoder_id(1), o_spans([(1, 7, 0, 139, 200)])]),
        session_end(7, [o_input_extents([(1, 7, 0, 200)])]),
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
            {
                "type": "participant",
                "session_id": 7,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.0.0.1:51000"],
            },
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
            options=[o_decoder_id(1), o_spans([(1, 7, 0, 0, 80)]), o_content_type("dec:request")],
        ),
        session_end(7, [o_input_extents([(1, 7, 0, 80)])]),
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
            {
                "type": "participant",
                "session_id": 7,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.0.0.1:51000"],
            },
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
TCP_A1, TCP_A2, TCP_B1 = b"a" * 40, b"b" * 30, b"c" * 20  # inner TCP payloads


# Inner packets, once decrypted: real IPv4 + TCP, PSH|ACK, carrying exactly the
# ports and sequence numbers inner.zpf builds its two flows from, so that hop can
# be rebuilt from these packets alone (#154). Flow A's peer ISN is 7000 and flow
# B's 9000; neither peer sends anything, so each flow's ack stays at its origin.
ACK_A, ACK_B = 7001, 9001
IP_A1 = tcp_packet(44300, 80, 1001, ACK_A, TCP_A1)  # 80 bytes
IP_B1 = tcp_packet(44301, 53, 5001, ACK_B, TCP_B1)  # 60 bytes
# 1041 (40 bytes) is the packet the decrypt stage lost.
IP_A2 = tcp_packet(44300, 80, 1081, ACK_A, TCP_A2)  # 70 bytes


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
        "declare the same 210 for the shared input. (3) A zpf-SOURCED TRANSPORT "
        "STREAM: inner.zpf declares output_layer = transport, carries isn and "
        "seq_start, and expresses its 40-byte hole in the SEQUENCE NUMBERS -- no "
        "Discontinuity, no content_type. (4) ORIGINATION, AND THE BREAK CARRIED "
        "AS A HOLE: packets.zpf withholds an inner packet and declares the "
        "break at its offset 140; the lost packet was flow A's, so inner.zpf "
        "carries the break as a TCP sequence gap, which a transport stream needs "
        "no block for (and since 0.22 its packets are real IPv4 + TCP, so "
        "inner.zpf can be rebuilt from them); http.zpf "
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
            {
                "type": "participant",
                "session_id": 1,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["198.51.100.7:51820"],
            },
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
            options=[o_decoder_id(1), o_spans([(1, 1, 0, 0, 80)]), o_content_type("net:ip")],
        ),
        record(
            5,
            0,
            1,
            1100,
            IP_B1,
            options=[
                o_decoder_id(1),
                o_spans([(1, 1, 0, 80, 160)]),
                o_content_type("net:ip"),
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
                o_spans([(1, 1, 0, 240, 320)]),
                o_content_type("net:ip"),
            ],
        ),
        session_end(5, [o_input_extents([(1, 1, 0, 320)])]),
        end_block(),
    ]
    packets = member(
        "tunnel",
        "packets",
        "The decrypt stage. One record per inner IP packet, typed net:ip "
        "because a packet IS a unit -- unlike a reassembly window, which is a "
        "slice -- and since 0.22 the format names that unit itself, so a generic "
        "sessionizer need not know this decoder's token. Each payload is a real "
        "IPv4 packet carrying a real TCP segment, PSH|ACK, with the ports and "
        "sequence numbers inner.zpf's two flows are built from, and true "
        "checksums. Its own offset space is the payload concatenation: [0,80) "
        "[80,140) [140,210), the Discontinuity contributing 0.",
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
            {
                "type": "participant",
                "session_id": 5,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.8.0.2"],
            },
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
                "content_type": "net:ip",
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
                "content_type": "net:ip",
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
                "content_type": "net:ip",
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
            flags=0x0001,
            options=[o_decoder_id(1), o_spans([(1, 5, 0, 0, 80)]), o_seq_start(1001), o_ack(ACK_A)],
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
            flags=0x0001,
            options=[
                o_decoder_id(1),
                o_spans([(1, 5, 0, 140, 210)]),
                o_seq_start(1081),
                o_ack(ACK_A),
            ],
        ),
        session_end(10, [o_input_extents([(1, 5, 0, 210)])]),
        # Flow B: a second inner connection out of the SAME input stream.
        session(11, [o_proto("tcp"), o_flow_key("10.8.0.2:44301 -> 10.8.0.9:53")]),
        participant(11, 0, [o_endpoint("10.8.0.2:44301"), o_isn(5000)]),
        record(
            11,
            0,
            1,
            1100,
            TCP_B1,
            flags=0x0001,
            options=[
                o_decoder_id(1),
                o_spans([(1, 5, 0, 80, 140)]),
                o_seq_start(5001),
                o_ack(ACK_B),
            ],
        ),
        # The same extent 210 as session 10 declares: under fan-out every
        # consuming session declares the WHOLE input stream, not its share.
        session_end(11, [o_input_extents([(1, 5, 0, 210)])]),
        end_block(),
    ]
    inner = member(
        "tunnel",
        "inner",
        "The sessionization stage, and the file this whole release was for. A "
        "zpf-SOURCED TRANSPORT stream: its Decoder declares output_layer = "
        "transport, so isn-anchored hole-inclusive offsets apply even though a "
        "decode stage produced it. It FANS OUT -- one input stream into sessions "
        "10 and 11, neither covering [0,210) alone. Flow A's lost packet is a "
        "40-byte hole at [40,80), visible as seq 1081 where 1041 would be "
        "contiguous. No Discontinuity: a transport stream may not carry one, and "
        "the break its input declared at packets offset 140 is carried as that "
        "hole. Every field here -- ports, seq_start, ack, psh -- is read from the "
        "TCP headers of packets.zpf, so a sessionizer can rebuild this file from "
        "that one.",
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
                "adjacency": "contiguous",
                "endpoint": ["10.8.0.2:44300"],
                "isn": 1000,
            },
            {
                "type": "record",
                "session_id": 10,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "flags": ["psh"],
                "payload": b64(TCP_A1),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 0, "off_end": 80}
                ],
                "seq_start": 1001,
                "ack": 7001,
            },
            {
                "type": "record",
                "session_id": 10,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1300,
                "flags": ["psh"],
                "payload": b64(TCP_A2),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 140, "off_end": 210}
                ],
                "seq_start": 1081,
                "ack": 7001,
            },
            {
                "type": "session_end",
                "session_id": 10,
                "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": 210}],
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
                "adjacency": "contiguous",
                "endpoint": ["10.8.0.2:44301"],
                "isn": 5000,
            },
            {
                "type": "record",
                "session_id": 11,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1100,
                "flags": ["psh"],
                "payload": b64(TCP_B1),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": 80, "off_end": 140}
                ],
                "seq_start": 5001,
                "ack": 9001,
            },
            {
                "type": "session_end",
                "session_id": 11,
                "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": 210}],
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
            options=[o_decoder_id(1), o_spans([(1, 10, 0, 0, 40)]), o_content_type("dec:request")],
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
                o_spans([(1, 10, 0, 80, 110)]),
                o_content_type("dec:response"),
            ],
        ),
        session_end(20, [o_input_extents([(1, 10, 0, 110)])]),
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
            {
                "type": "participant",
                "session_id": 20,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.8.0.2:44300"],
            },
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


# ------------------------------------------------------------------- the merge
#
# Two single-direction captures merged into one sequenced session, where one
# input's stream has a hole. The obligation this pins (#133): a merge is a
# pass-through, every record it re-emits carries an identity span, an identity
# span cites the input, and the coverage guarantee makes a file answerable for
# every offset of an input stream it cites -- so a hole in a preserved
# transport stream is marked with an Undecoded gap block, like any other
# uncovered range. Before 0.19 a merge cited nothing and owed nothing.
#
# Byte budget, fixed here so every offset below is checkable by hand:
#   sideA (a.zpf, session 7 / pid 0, isn 1000, the client):
#     "GET / HTTP/1.1\r\n"       16 bytes at seq 1001  -> offsets [0,16)
#     "Host: example.com\r\n"    19 bytes LOST         -> the hole [16,35)
#     "Accept: */*\r\n\r\n"      15 bytes at seq 1036  -> offsets [35,50)
#   sideB (b.zpf, session 3 / pid 0, isn 5000, the server):
#     "HTTP/1.1 200 OK\r\n\r\n"  19 bytes at seq 5001  -> offsets [0,19)
# The hole is real in the sequence numbers: 1001 + 16 = 1017, and the next
# captured byte is at 1036. merged.zpf's identity spans cover [0,16) and
# [35,50) of sideA's stream; the gap block covers [16,35); its Session End
# declares the extent 50, so the obligation is checkable from merged.zpf alone.

MERGE_A1 = b"GET / HTTP/1.1\r\n"  # 16
MERGE_A2 = b"Accept: */*\r\n\r\n"  # 15, at seq 1036: 19 bytes lost between
MERGE_B1 = b"HTTP/1.1 200 OK\r\n\r\n"  # 19
MERGE_KEY = "10.0.0.1:51000 <-> 93.184.216.34:80"


def merge_file(name: str, summary: str, blocks: list[Blk], jsonl: list[dict]) -> bytes:
    return member("merge", name, summary, blocks, jsonl)


def merge_output_blocks(a_dg: str, b_dg: str, *, gap: bool) -> list[Blk]:
    """Build the merged file's blocks, with or without the gap block the merge owes.

    One description for both faces of the obligation, so the negative twin
    differs from merged.zpf in exactly the block whose absence it tests.
    """
    hole = [undecoded(1, 0, 7, 16, 35, [o_reason("gap")])] if gap else []
    return [
        file_header(
            options=[
                o_produced_by("zpf-merge 1.2"),
                o_produced_at(1719510000),
                o_transform_params_digest("sha256:77c1"),
            ]
        ),
        source(1, 1, [o_uri("a.zpf"), o_digest(a_dg)]),
        source(2, 1, [o_uri("b.zpf"), o_digest(b_dg)]),
        session(1, [o_proto("tcp"), o_flow_key(MERGE_KEY), o_sess_flags(0x0001)]),
        participant(1, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        participant(1, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000)]),
        # Identity spans: each record cites the range of its input stream it
        # was re-emitted from, the same range it occupies here.
        record(
            1,
            0,
            1,
            1000,
            MERGE_A1,
            options=[o_seq_start(1001), o_ack(5001), o_spans([(1, 7, 0, 0, 16)])],
        ),
        # THE OBLIGATION: sideA's stream has no bytes at [16,35). The output's
        # sequence numbers already say so -- 1017 to 1036 -- but the file cites
        # the input, so it answers for the input's every offset, and this is
        # the block that answers for these. The twin omits it.
        *hole,
        record(
            1,
            0,
            1,
            1020,
            MERGE_A2,
            flags=0x0001,
            options=[o_seq_start(1036), o_ack(5001), o_spans([(1, 7, 0, 35, 50)])],
        ),
        # Stored after both request records: it acks 1051, the end of the
        # request, so it causally follows them despite the earlier timestamp.
        record(
            1,
            1,
            2,
            995,
            MERGE_B1,
            flags=0x0001,
            options=[o_seq_start(5001), o_ack(1051), o_spans([(2, 3, 0, 0, 19)])],
        ),
        # input_extents is what makes the twin decidable from one file: the
        # declared 50 against a coverage of [0,16) + [35,50) is the hole.
        session_end(1, [o_input_extents([(1, 7, 0, 50), (2, 3, 0, 19)])]),
        end_block(),
    ]


def merge_output_jsonl(a_dg: str, b_dg: str, *, gap: bool) -> list[dict]:
    hole = [
        {
            "type": "undecoded",
            "source_id": 1,
            "session_id": 7,
            "pid": 0,
            "off_start": 16,
            "off_end": 35,
            "reason": "gap",
        }
    ]
    return [
        {
            "type": "file",
            "format": FORMAT,
            "tick_hz": 1000000,
            "produced_by": "zpf-merge 1.2",
            "produced_at": 1719510000,
            "transform_params_digest": "sha256:77c1",
        },
        {"type": "source", "source_id": 1, "kind": "zpf-input", "uri": "a.zpf", "digest": a_dg},
        {"type": "source", "source_id": 2, "kind": "zpf-input", "uri": "b.zpf", "digest": b_dg},
        {"type": "session", "session_id": 1, "proto": "tcp", "key": MERGE_KEY, "sequenced": True},
        {
            "type": "participant",
            "session_id": 1,
            "pid": 0,
            "adjacency": "contiguous",
            "endpoint": ["10.0.0.1:51000"],
            "isn": 1000,
        },
        {
            "type": "participant",
            "session_id": 1,
            "pid": 1,
            "adjacency": "contiguous",
            "endpoint": ["93.184.216.34:80"],
            "isn": 5000,
        },
        {
            "type": "record",
            "session_id": 1,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1000,
            "payload": b64(MERGE_A1),
            "seq_start": 1001,
            "ack": 5001,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 0, "off_end": 16}],
        },
        *(hole if gap else []),
        {
            "type": "record",
            "session_id": 1,
            "sender_pid": 0,
            "source_id": 1,
            "ts": 1020,
            "flags": ["psh"],
            "payload": b64(MERGE_A2),
            "seq_start": 1036,
            "ack": 5001,
            "spans": [{"source_id": 1, "session_id": 7, "pid": 0, "off_start": 35, "off_end": 50}],
        },
        {
            "type": "record",
            "session_id": 1,
            "sender_pid": 1,
            "source_id": 2,
            "ts": 995,
            "flags": ["psh"],
            "payload": b64(MERGE_B1),
            "seq_start": 5001,
            "ack": 1051,
            "spans": [{"source_id": 2, "session_id": 3, "pid": 0, "off_start": 0, "off_end": 19}],
        },
        {
            "type": "session_end",
            "session_id": 1,
            "input_extents": [
                {"source_id": 1, "session_id": 7, "pid": 0, "extent": 50},
                {"source_id": 2, "session_id": 3, "pid": 0, "extent": 19},
            ],
        },
        {"type": "end"},
    ]


def build_merge() -> None:
    """Build the two inputs and the merge, hashing each input so the merge can cite it."""
    fixture(
        "merge",
        "accept",
        "A merge of two single-direction captures into one SEQUENCED session, "
        "where one input's stream has a hole: a.zpf's client stream is missing "
        "19 bytes between its two records, visible in its sequence numbers. "
        "merged.zpf is a pass-through, so every record carries an identity span "
        "into its input -- and citing the input makes the file answerable for "
        "it. The coverage guarantee then owes an Undecoded gap block for the "
        "hole, naming a.zpf's range [16,35), exactly as a decode stage would "
        "owe one; the output's own sequence numbers carrying the same gap does "
        "not discharge it, because those speak of this file's stream and the "
        "guarantee is stated against the input's. Before 0.19 a merge cited "
        "nothing and owed nothing here; the identity span is what changed. "
        "Session End declares both input extents, so the obligation is checkable "
        "from merged.zpf alone -- which is what lets the negative twin, "
        "isolate-merge-unmarked-hole, be a single file.",
        "Conformance -- a pass-through marks its input's holes; Coverage honesty",
        "Accept all three. Each .jsonl is the expected projection; each declared "
        "digest is the real SHA-256 of the input it names. A reader that walks "
        "merged.zpf's coverage of a.zpf's stream finds [0,16) and [35,50) "
        "spanned and [16,35) marked, against a declared extent of 50 -- "
        "complete, and never both.",
        violations=0,
    )
    a = merge_file(
        "a",
        "sideA: the client direction, capture-sourced, with a hole. Two records "
        "at seq 1001 and 1036 on a stream whose origin is 1001; the 19 bytes "
        "between them were never captured, so offsets [16,35) belong to no "
        "record.",
        [
            file_header(options=[o_creator("zpf-sessionize 1.0")]),
            source(1, 0, [o_uri("sideA.pcap")]),
            session(7, [o_proto("tcp")]),
            participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
            record(7, 0, 1, 1000, MERGE_A1, options=[o_seq_start(1001), o_ack(5001)]),
            # The hole: 1001 + 16 = 1017, and this record starts at 1036.
            record(7, 0, 1, 1020, MERGE_A2, flags=0x0001, options=[o_seq_start(1036), o_ack(5001)]),
            end_block(),
        ],
        [
            {"type": "file", "format": FORMAT, "tick_hz": 1000000, "creator": "zpf-sessionize 1.0"},
            {"type": "source", "source_id": 1, "kind": "capture", "uri": "sideA.pcap"},
            {"type": "session", "session_id": 7, "proto": "tcp"},
            {
                "type": "participant",
                "session_id": 7,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.0.0.1:51000"],
                "isn": 1000,
            },
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000,
                "payload": b64(MERGE_A1),
                "seq_start": 1001,
                "ack": 5001,
            },
            {
                "type": "record",
                "session_id": 7,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1020,
                "flags": ["psh"],
                "payload": b64(MERGE_A2),
                "seq_start": 1036,
                "ack": 5001,
            },
            {"type": "end"},
        ],
    )
    a_dg = "sha256:" + hashlib.sha256(a).hexdigest()

    b = merge_file(
        "b",
        "sideB: the server direction, capture-sourced, complete. One record at "
        "seq 5001 acking 1051, the end of the request.",
        [
            file_header(options=[o_creator("zpf-sessionize 1.0")]),
            source(1, 0, [o_uri("sideB.pcap")]),
            session(3, [o_proto("tcp")]),
            participant(3, 0, [o_endpoint("93.184.216.34:80"), o_isn(5000)]),
            record(3, 0, 1, 995, MERGE_B1, flags=0x0001, options=[o_seq_start(5001), o_ack(1051)]),
            end_block(),
        ],
        [
            {"type": "file", "format": FORMAT, "tick_hz": 1000000, "creator": "zpf-sessionize 1.0"},
            {"type": "source", "source_id": 1, "kind": "capture", "uri": "sideB.pcap"},
            {"type": "session", "session_id": 3, "proto": "tcp"},
            {
                "type": "participant",
                "session_id": 3,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["93.184.216.34:80"],
                "isn": 5000,
            },
            {
                "type": "record",
                "session_id": 3,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 995,
                "flags": ["psh"],
                "payload": b64(MERGE_B1),
                "seq_start": 5001,
                "ack": 1051,
            },
            {"type": "end"},
        ],
    )
    b_dg = "sha256:" + hashlib.sha256(b).hexdigest()

    merge_file(
        "merged",
        "The merge: one sequenced session, both directions, every record "
        "carrying an identity span into its input, and an Undecoded gap block "
        "for the 19 bytes a.zpf never had. The server's record is stored last "
        "because it acks the whole request, despite its earlier timestamp.",
        merge_output_blocks(a_dg, b_dg, gap=True),
        merge_output_jsonl(a_dg, b_dg, gap=True),
    )

    # The negative twin, registered here so it cites the inputs' real digests.
    vector(
        "isolate-merge-unmarked-hole",
        "isolate",
        "merge/merged.zpf with its gap block omitted: a merge whose input "
        "stream has a hole at [16,35) that nothing in the output accounts for. "
        "The records carry identity spans, so the file cites a.zpf's stream "
        "and is answerable for every offset of it; its Session End declares "
        "that stream 50 long; its spans cover [0,16) and [35,50); and no "
        "Undecoded block names the rest. That the output's own sequence "
        "numbers jump from 1017 to 1036 does not help -- they describe this "
        "file's stream, and the guarantee is stated against the input's. "
        "It is a single file, not a pair, BECAUSE input_extents is on the "
        "Session End: the declared 50 against a coverage of 31 bytes is "
        "the violation, and no input need be opened to see it. That is the "
        "property Package D-pair would trade away, and under it this vector "
        "would need merge/a.zpf beside it.",
        "Conformance -- a pass-through marks its input's holes; Coverage honesty",
        merge_output_blocks(a_dg, b_dg, gap=False),
        expect="MAY reject the file, or isolate session 1. The coverage guarantee "
        "fails for input stream (source 1, session 7, pid 0): declared extent "
        "50, covered [0,16) and [35,50), and [16,35) neither spanned nor "
        "marked. A reader MUST NOT infer the gap block from the sequence "
        "numbers and treat the file as whole; the block is what the producer "
        "owes, and its absence is the producer's omission.",
        violations=1,
    )


# 0.24 (#168). closed-final-ack as the input to a decode stage. The server's
# stream reaches 5 and its FIN occupies offset 4, which holds no byte: the
# decoder spans [0,4), marks nothing at 4, and declares the extent 5. A
# coverage check that counts the FIN's position reports a gap there, which is
# the failure zipline-kober met on every TCP input over zpfwire 0.8.0.
def build_past_fin() -> None:
    """Build the capture and a decode stage over it that leaves the FIN's position bare."""
    fixture(
        "decoded-past-fin",
        "accept",
        "closed-final-ack's capture, and a decode stage over it. The server's "
        "stream reaches 5, one past its FIN at offset 4, because its final pure "
        "ACK is stored at its wire number. The decoder spans the server's data "
        "[0,4), owes the FIN's position nothing and marks nothing there, and "
        "declares the stream's extent as 5. The client's FIN has nothing past "
        "it, so its stream is [0,8) and is covered exactly.",
        "Coverage honesty -- the position a FIN occupies is owed nothing",
        "Accept both files. decoded.zpf's Session End declares extents 8 and 5, "
        "both what capture.zpf's sequence numbers give. A coverage check that "
        "reports [4,5) of the server's stream as a gap, or an extent mismatch "
        "against 4, is wrong: that position is the FIN's and holds no byte. "
        "Marking it Undecoded is not required.",
        violations=0,
        merged=[("capture", 7, [1, 2, 3, 4]), ("decoded", 7, [1, 2, 3])],
    )
    capture = member(
        "decoded-past-fin",
        "capture",
        "closed-final-ack, as this pair's input.",
        CLOSED_BLOCKS,
        CLOSED_JSONL,
    )
    dg = "sha256:" + hashlib.sha256(capture).hexdigest()

    def dec(pid: int, ts: int, payload: bytes, start: int, end: int) -> tuple[Blk, dict]:
        blk = record(
            7, pid, 1, ts, payload, options=[o_decoder_id(1), o_spans([(1, 7, pid, start, end)])]
        )
        line = {
            "type": "record",
            "session_id": 7,
            "sender_pid": pid,
            "source_id": 1,
            "ts": ts,
            "payload": b64(payload),
            "decoder_id": 1,
            "spans": [
                {"source_id": 1, "session_id": 7, "pid": pid, "off_start": start, "off_end": end}
            ],
        }
        return blk, line

    recs = [
        dec(0, 1000, b"PING", 0, 4),
        dec(1, 1100, b"PONG", 0, 4),
        dec(0, 1200, b"QUIT", 4, 8),
    ]
    member(
        "decoded-past-fin",
        "decoded",
        "A decode stage over capture.zpf. Its spans cover the client's [0,8) "
        "and the server's [0,4); the server's offset 4 is its FIN's, and is "
        "owed nothing.",
        [
            file_header(options=[o_produced_by("zpf-decode 0.4"), o_produced_at(1719500000)]),
            source(1, 1, [o_uri("capture.zpf"), o_digest(dg)]),
            decoder(1, [o_dec_name("ping"), o_dec_version("0.4")]),
            session(7, [o_proto("ping")]),
            participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
            participant(7, 1, [o_endpoint("93.184.216.34:80")]),
            *(blk for blk, _ in recs),
            session_end(7, [o_input_extents([(1, 7, 0, 8), (1, 7, 1, 5)])]),
            end_block(),
        ],
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
                "uri": "capture.zpf",
                "digest": dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "ping",
                "version": "0.4",
            },
            {"type": "session", "session_id": 7, "proto": "ping"},
            {
                "type": "participant",
                "session_id": 7,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.0.0.1:51000"],
            },
            {
                "type": "participant",
                "session_id": 7,
                "pid": 1,
                "adjacency": "contiguous",
                "endpoint": ["93.184.216.34:80"],
            },
            *(line for _, line in recs),
            {
                "type": "session_end",
                "session_id": 7,
                "input_extents": [
                    {"source_id": 1, "session_id": 7, "pid": 0, "extent": 8},
                    {"source_id": 1, "session_id": 7, "pid": 1, "extent": 5},
                ],
            },
            {"type": "end"},
        ],
    )


# 0.24 (#166). One UDP datagram, IP-fragmented inside a tunnel, arrives as two
# records of a unit sequence with another flow's packet between them. Its
# reassembly is one message whose spans must cite both fragments, crossing two
# seams, and it carries no seq_start. Through 0.23 the permission to cross was
# keyed on seq_start alone, so the datagram had no conformant record. Since 0.24
# the `message` flag is the evidence of a join a checker can see.
FRAG_DATA, FLOW_B_DATA = b"d" * 40, b"e" * 12


# 0.24 (#170). The same input with the datagram's second fragment lost. The
# first fragment is not a message, so it is not content of the stream: the
# stage writes no record for it, which withholds nothing, and marks its range
# in the INPUT's space undecodable, the word the SHOULD pins. That block is the
# trace. Flow B is written as before. Built by the same function, `lost=True`.
FRAGMENT_LOST_SUMMARY = (
    "sessionized-fragments with the datagram's second fragment lost. packets.zpf "
    "is a unit sequence of two net:ip records with real headers: the first "
    "fragment (id 0x1234, MF) at [0,52) and another flow's datagram at [52,92). "
    "No second fragment ever arrived, so the first is pieces of a message, not a "
    "message. inner.zpf writes no record for it, which withholds nothing of the "
    "stream, and marks [0,52) of packets.zpf undecodable, with a comment naming "
    "the missing fragment. Session 21 is flow B. Through 0.23 the shape had no "
    "conformant form: a partial datagram is not a message, and the transport "
    "layer could not withhold it."
)
FRAGMENT_LOST_EXPECT = (
    "Accept both files. An incomplete reassembly is not content of a "
    "message-oriented stream, so leaving it out is not withholding: a check that "
    "calls the missing datagram withheld content reports a violation that is not "
    "there. The fragment's bytes are accounted for in the input's space by the "
    "Undecoded block, reason undecodable (the SHOULD), and inner.zpf's coverage "
    "of packets.zpf is complete with it. A reader wanting every input unit cited "
    "by some record finds the block in its place. Session 21 declares "
    "packets.zpf's full extent, 92."
)


def build_fragments(name: str, lost: bool) -> None:
    """Build a unit sequence carrying a fragmented datagram, and its reassembly or its loss."""
    fixture(
        name,
        "accept",
        "A sessionization stage reassembling an IP-fragmented UDP datagram. "
        "packets.zpf is a decryptor's output, a unit sequence of three net:ip "
        "records with real headers: the datagram's first fragment (id 0x1234, "
        "MF, 32 bytes of IP payload) at [0,52), another flow's datagram at "
        "[52,92), and the second fragment (offset 4, i.e. 32 bytes) at [92,128). "
        "inner.zpf's session 20 is the datagram reassembled, one record flagged "
        "message citing both fragments across two seams, with no seq_start. "
        "Through 0.23 that record had no conformant form: the permission to "
        "cross input units was keyed on seq_start."
        if not lost
        else FRAGMENT_LOST_SUMMARY,
        "Discontinuity (0x22) -- a transport-layer record meets both duties when "
        "it carries the evidence of its own join"
        if not lost
        else "Discontinuity (0x22) -- an incomplete reassembly is not content of the stream",
        "Accept both files. Session 20's record is exactly one transport message, "
        "so the units it cites are that message's fragments and join as its "
        "reassembly: a splice check that requires seq_start to cross a unit "
        "sequence's seams reports a violation that is not there. Its 40-byte "
        "payload is the datagram's data, the fragments' IP payloads joined at "
        "their offsets with the UDP header removed. Both sessions declare "
        "packets.zpf's full extent, 128."
        if not lost
        else FRAGMENT_LOST_EXPECT,
        violations=0,
    )
    frag1, frag2 = udp_fragments(5000, 5353, FRAG_DATA, 0x1234, 32)
    flow_b = udp_packet(5001, 53, FLOW_B_DATA)
    pkts = [(1000, frag1), (1100, flow_b)] + ([] if lost else [(1200, frag2)])
    extent = sum(len(p) for _ts, p in pkts)
    packets = member(
        name,
        "packets",
        "A decryptor's output: two inner IPv4 packets as a unit sequence, the "
        "first a fragment whose partner never arrived."
        if lost
        else "A decryptor's output: three inner IPv4 packets as a unit sequence, "
        "the second between the two fragments of the first's datagram.",
        [
            file_header(options=[o_produced_by("zpf-wg 0.3"), o_produced_at(1719700000)]),
            source(1, 0, [o_uri("wg.pcap")]),
            decoder(1, [o_dec_name("wireguard-decrypt"), o_dec_version("0.3")]),
            session(5, [o_proto("ip")]),
            participant(5, 0, [o_endpoint("10.8.0.2")], adjacency=1),
            *(
                record(5, 0, 1, ts, p, options=[o_decoder_id(1), o_content_type("net:ip")])
                for ts, p in pkts
            ),
            end_block(),
        ],
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-wg 0.3",
                "produced_at": 1719700000,
            },
            {"type": "source", "source_id": 1, "kind": "capture", "uri": "wg.pcap"},
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "wireguard-decrypt",
                "version": "0.3",
            },
            {"type": "session", "session_id": 5, "proto": "ip"},
            {
                "type": "participant",
                "session_id": 5,
                "pid": 0,
                "adjacency": "units",
                "endpoint": ["10.8.0.2"],
            },
            *(
                {
                    "type": "record",
                    "session_id": 5,
                    "sender_pid": 0,
                    "source_id": 1,
                    "ts": ts,
                    "payload": b64(p),
                    "decoder_id": 1,
                    "content_type": "net:ip",
                }
                for ts, p in pkts
            ),
            {"type": "end"},
        ],
    )
    dg = "sha256:" + hashlib.sha256(packets).hexdigest()

    def flow(sess: int, port: int, ts: int, payload: bytes, spans: list) -> list:
        """Both faces of one UDP flow's session: descriptors, its record, its end."""
        blocks = [
            session(sess, [o_proto("udp")]),
            participant(sess, 0, [o_endpoint(f"10.8.0.2:{port}")]),
            record(
                sess,
                0,
                1,
                ts,
                payload,
                flags=0x0080,
                options=[o_decoder_id(1), o_spans([(1, 5, 0, a, b) for a, b in spans])],
            ),
            session_end(sess, [o_input_extents([(1, 5, 0, extent)])]),
        ]
        lines = [
            {"type": "session", "session_id": sess, "proto": "udp"},
            {
                "type": "participant",
                "session_id": sess,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": [f"10.8.0.2:{port}"],
            },
            {
                "type": "record",
                "session_id": sess,
                "sender_pid": 0,
                "source_id": 1,
                "ts": ts,
                "flags": ["message"],
                "payload": b64(payload),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": a, "off_end": b}
                    for a, b in spans
                ],
            },
            {
                "type": "session_end",
                "session_id": sess,
                "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": extent}],
            },
        ]
        return [blocks, lines]

    b_blocks, b_lines = flow(21, 5001, 1100, FLOW_B_DATA, [(52, 92)])
    if lost:
        # No record for flow A: its one fragment is pieces of a message. The
        # block names the input's range, in the input's ids, and is the trace.
        note = "fragment 1 of 2 of datagram id 0x1234; fragment 2 never arrived"
        a_blocks = [
            undecoded(1, 0, 5, 0, 52, [o_reason("undecodable"), o_decoder_id(1), o_comment(note)])
        ]
        a_lines = [
            {
                "type": "undecoded",
                "source_id": 1,
                "session_id": 5,
                "pid": 0,
                "off_start": 0,
                "off_end": 52,
                "reason": "undecodable",
                "decoder_id": 1,
                "comment": note,
            }
        ]
    else:
        # Flow A: one message, two spans, one per fragment, flow B's packet between.
        a_blocks, a_lines = flow(20, 5000, 1000, FRAG_DATA, [(0, 52), (92, 128)])
    member(
        name,
        "inner",
        "The sessionization stage over packets.zpf: no record for the incomplete "
        "datagram, its fragment marked undecodable, and flow B's datagram as its "
        "own session."
        if lost
        else "The sessionization stage over packets.zpf: flow A's datagram "
        "reassembled from its two fragments as one message record, and flow B's "
        "datagram as its own session.",
        [
            file_header(options=[o_produced_by("zpf-sessionize 1.0"), o_produced_at(1719700100)]),
            source(1, 1, [o_uri("packets.zpf"), o_digest(dg)]),
            decoder(1, [o_dec_name("udp-reassembly"), o_dec_version("1.1")], output_layer=1),
            *a_blocks,
            *b_blocks,
            end_block(),
        ],
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
                "digest": dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "transport",
                "name": "udp-reassembly",
                "version": "1.1",
            },
            *a_lines,
            *b_lines,
            {"type": "end"},
        ],
    )


# 0.24 (#167). The second half of 0.22's permission: a sequence-anchored record
# crossing a DECLARED break, which sessionized-across-units never tested (it
# crosses unit seams, which no splice check examines as declared blocks). The
# input is contiguous, flow A, flow B, flow A, with a Discontinuity before A's
# second packet: the lost packet upstream was another flow's, as #152's own
# example puts it, so A's two packets join in A's sequence space. The mirror
# is the same pair with A's record carrying neither seq_start nor message: no
# evidence of the join, so it owes the carry duty, and a transport stream can
# meet it with neither a Discontinuity nor units. Both pairs come from here.
def build_across_break(name: str, anchored: bool) -> None:
    """Build packets.zpf with a declared break, and a sessionizer crossing it."""
    if anchored:
        fixture(
            name,
            "accept",
            "A sessionization stage crossing a DECLARED break. packets.zpf is a "
            "contiguous packet stream of three net:ip records with real headers "
            "-- flow A at [0,80), flow B at [80,140), flow A at [140,210) -- and "
            "a Discontinuity (decrypt-failed, no width) between flow B's packet "
            "and flow A's second. Flow A's sequence numbers join across it (1001 "
            "+ 40 = 1041), so what was lost belonged to another flow. inner.zpf's "
            "session 10 is flow A as one record with seq_start, its two spans "
            "crossing the break; session 11 is flow B.",
            "Discontinuity (0x22) -- a transport-layer record meets both duties "
            "when it carries the evidence of its own join",
            "Accept both files. Session 10's record carries seq_start, so its "
            "sequence numbers assert the join and a break between its packets is "
            "a range of sequence numbers no record covers: it MAY cross the "
            "declared Discontinuity. A splice check that applies the decoded "
            "layer's carry duty to it reports a violation that is not there. "
            "isolate-transport-splice is this pair with the evidence removed.",
            violations=0,
        )
    else:
        fixture(
            name,
            "isolate",
            "sessionized-across-break with flow A's record stripped of its "
            "evidence: no isn on its participant, no seq_start and no ack on the "
            "record, and no message flag, since it is TCP. The record still "
            "crosses packets.zpf's declared Discontinuity with two spans, so it "
            "asserts a join nothing in it can answer for. A transport output "
            "without the evidence owes both duties, and has neither recourse: a "
            "transport stream carries no Discontinuity and is never units.",
            "Discontinuity (0x22) -- a transport record carrying neither owes both "
            "duties as stated",
            "Accept packets.zpf; it breaks no rule. ISOLATE or reject inner.zpf's "
            "session 10: its record crosses a declared Discontinuity in its input "
            "and carries neither seq_start nor message, so nothing in it says the "
            "two packets join, and the break is gone one hop along. Session 11 "
            "is conformant. A reader handed only inner.zpf cannot judge it: the "
            "violation needs packets.zpf in hand, as splice does. This is the "
            "pairwise twin of isolate-unmarked-break.",
            violations=1,
        )
    pkts = [
        (1000, tcp_packet(44300, 80, 1001, 7001, b"a" * 40)),  # flow A, [0,80)
        (1100, tcp_packet(44301, 53, 5001, 9001, b"c" * 20)),  # flow B, [80,140)
        (1300, tcp_packet(44300, 80, 1041, 7001, b"b" * 30)),  # flow A, [140,210)
    ]

    def pkt(ts: int, p: bytes) -> tuple[Blk, dict]:
        line = {
            "type": "record",
            "session_id": 5,
            "sender_pid": 0,
            "source_id": 1,
            "ts": ts,
            "payload": b64(p),
            "decoder_id": 1,
            "content_type": "net:ip",
        }
        return record(5, 0, 1, ts, p, options=[o_decoder_id(1), o_content_type("net:ip")]), line

    recs = [pkt(ts, p) for ts, p in pkts]
    # The break sits after flow B's packet, before flow A's second.
    brk = (
        discontinuity(5, 0, [o_disc_reason("decrypt-failed")]),
        {"type": "discontinuity", "session_id": 5, "pid": 0, "reason": "decrypt-failed"},
    )
    body = [recs[0], recs[1], brk, recs[2]]
    packets = member(
        name,
        "packets",
        "A decryptor's output: three inner IPv4 packets as a contiguous stream, "
        "with a declared break after the second, where a packet failed to decrypt.",
        [
            file_header(options=[o_produced_by("zpf-wg 0.3"), o_produced_at(1719700000)]),
            source(1, 0, [o_uri("wg.pcap")]),
            decoder(1, [o_dec_name("wireguard-decrypt"), o_dec_version("0.3")]),
            session(5, [o_proto("ip")]),
            participant(5, 0, [o_endpoint("10.8.0.2")]),
            *(b for b, _ in body),
            end_block(),
        ],
        [
            {
                "type": "file",
                "format": FORMAT,
                "tick_hz": 1000000,
                "produced_by": "zpf-wg 0.3",
                "produced_at": 1719700000,
            },
            {"type": "source", "source_id": 1, "kind": "capture", "uri": "wg.pcap"},
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "decoded",
                "name": "wireguard-decrypt",
                "version": "0.3",
            },
            {"type": "session", "session_id": 5, "proto": "ip"},
            {
                "type": "participant",
                "session_id": 5,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": ["10.8.0.2"],
            },
            *(line for _, line in body),
            {"type": "end"},
        ],
    )
    dg = "sha256:" + hashlib.sha256(packets).hexdigest()

    def flow(sess: int, port: int, isn: int, ack: int, payload: bytes, spans: list) -> list:
        """Both faces of one TCP flow's session; flow A loses its evidence in the mirror."""
        evidence = anchored or sess != 10
        blocks = [
            session(sess, [o_proto("tcp")]),
            participant(
                sess, 0, [o_endpoint(f"10.8.0.2:{port}")] + ([o_isn(isn)] if evidence else [])
            ),
            record(
                sess,
                0,
                1,
                1000 if sess == 10 else 1100,
                payload,
                flags=0x0001,
                options=[o_decoder_id(1), o_spans([(1, 5, 0, a, b) for a, b in spans])]
                + ([o_seq_start(isn + 1), o_ack(ack)] if evidence else []),
            ),
            session_end(sess, [o_input_extents([(1, 5, 0, 210)])]),
        ]
        lines = [
            {"type": "session", "session_id": sess, "proto": "tcp"},
            {
                "type": "participant",
                "session_id": sess,
                "pid": 0,
                "adjacency": "contiguous",
                "endpoint": [f"10.8.0.2:{port}"],
                **({"isn": isn} if evidence else {}),
            },
            {
                "type": "record",
                "session_id": sess,
                "sender_pid": 0,
                "source_id": 1,
                "ts": 1000 if sess == 10 else 1100,
                "flags": ["psh"],
                "payload": b64(payload),
                "decoder_id": 1,
                "spans": [
                    {"source_id": 1, "session_id": 5, "pid": 0, "off_start": a, "off_end": b}
                    for a, b in spans
                ],
                **({"seq_start": isn + 1, "ack": ack} if evidence else {}),
            },
            {
                "type": "session_end",
                "session_id": sess,
                "input_extents": [{"source_id": 1, "session_id": 5, "pid": 0, "extent": 210}],
            },
        ]
        return [blocks, lines]

    # Flow A: one record, two spans, crossing the declared break at 140.
    a_blocks, a_lines = flow(10, 44300, 1000, 7001, b"a" * 40 + b"b" * 30, [(0, 80), (140, 210)])
    b_blocks, b_lines = flow(11, 44301, 5000, 9001, b"c" * 20, [(80, 140)])
    member(
        name,
        "inner",
        "The sessionization stage over packets.zpf: flow A as one record whose "
        "spans cross the declared break, and flow B as its own session."
        + ("" if anchored else " Flow A's record carries no seq_start, which is the violation."),
        [
            file_header(options=[o_produced_by("zpf-sessionize 1.0"), o_produced_at(1719700100)]),
            source(1, 1, [o_uri("packets.zpf"), o_digest(dg)]),
            decoder(1, [o_dec_name("tcp-reassembly"), o_dec_version("1.1")], output_layer=1),
            *a_blocks,
            *b_blocks,
            end_block(),
        ],
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
                "digest": dg,
            },
            {
                "type": "decoder",
                "decoder_id": 1,
                "output_layer": "transport",
                "name": "tcp-reassembly",
                "version": "1.1",
            },
            *a_lines,
            *b_lines,
            {"type": "end"},
        ],
    )


def main() -> int:
    check = "--check" in sys.argv
    build_chain()
    build_splice()
    build_tunnel()
    build_merge()
    build_past_fin()
    build_fragments("sessionized-fragments", lost=False)
    build_fragments("sessionized-fragment-lost", lost=True)
    build_across_break("sessionized-across-break", anchored=True)
    build_across_break("isolate-transport-splice", anchored=False)
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
        merged = check_fixture_merged(fx)
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
                **({"merged": merged} if merged is not None else {}),
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
                **({"extents": v["extents"]} if v["extents"] is not None else {}),
                **({"merged": v["merged"]} if v["merged"] is not None else {}),
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
