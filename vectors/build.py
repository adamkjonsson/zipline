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
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The version this tree stamps. Every vector's File Header, every JSONL `format`
# string and the manifest read these, so a version bump is a one-line change and
# no site can be missed.
MAJOR, MINOR = 0, 13
FORMAT = f"zipline-payload/{MAJOR}.{MINOR}"

# ---------------------------------------------------------------- primitives

def u8(v):  return struct.pack('<B', v)
def u16(v): return struct.pack('<H', v)
def u32(v): return struct.pack('<I', v)
def u64(v): return struct.pack('<Q', v)
def i64(v): return struct.pack('<q', v)

def pad4(n):
    """Bytes of padding needed to reach a 4-byte boundary."""
    return (-n) % 4

# A "piece" is (bytes, annotation). Annotation "" means it is padding or a
# continuation line and needs no separate explanation.
def P(b, ann=""):
    return (b, ann)


def option(oid, value, name, note=""):
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
        out.append(P(b'\x00' * pad, "value padding"))
    return out


def _describe(value):
    try:
        s = value.decode('ascii')
        if s.isprintable():
            return f'"{s}"'
    except UnicodeDecodeError:
        pass
    return ""


def block(btype, name, body, options=()):
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
        content.append(P(b'\x00' * pad, "content padding"))
        size += pad
    head = [
        P(u16(btype), f"type   = 0x{btype:04X}  {name}"),
        P(u16(0), "reserved"),
        P(u32(size), f"length = {size}"),
    ]
    return head + content


# --------------------------------------------------------------- block kinds

def file_header(tick_hz=1_000_000, major=MAJOR, minor=MINOR, options=(), magic=0x5A495046):
    body = [
        P(u32(magic), f'magic  = 0x{magic:08X}  ("ZIPF")'),
        P(u16(major), f"version_major = {major}"),
        P(u16(minor), f"version_minor = {minor}"),
        P(u64(tick_hz), f"tick_hz = {tick_hz:_}"),
    ]
    return block(0x01, "File Header", body, options)


def source(source_id, kind, options=()):
    kind_name = {0: "capture", 1: "zpf-input"}.get(kind, "UNDEFINED")
    body = [
        P(u16(source_id), f"source_id = {source_id}"),
        P(u8(kind), f"kind = {kind}  ({kind_name})"),
        P(u8(0), "_reserved"),
    ]
    return block(0x02, "Source Descriptor", body, options)


def decoder(decoder_id, options=()):
    body = [
        P(u16(decoder_id), f"decoder_id = {decoder_id}"),
        P(u16(0), "_reserved"),
    ]
    return block(0x03, "Decoder Descriptor", body, options)


def session(session_id, options=()):
    body = [P(u64(session_id), f"session_id = {session_id}  (u64)")]
    return block(0x10, "Session Descriptor", body, options)


def participant(session_id, pid, options=()):
    body = [
        P(u64(session_id), f"session_id = {session_id}  (u64)"),
        P(u16(pid), f"participant_id = {pid}"),
        P(u16(0), "_reserved"),
    ]
    return block(0x11, "Participant Descriptor", body, options)


def record(session_id, sender_pid, source_id, timestamp, payload,
           flags=0, options=(), payload_len=None):
    """payload_len defaults to len(payload); override it to build a
    deliberately corrupt vector."""
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
            body.append(P(b'\x00' * pad, "payload padding"))
    return block(0x20, "Record", body, options)


def undecoded(source_id, pid, session_id, off_start, off_end, options=()):
    body = [
        P(u16(source_id), f"source_id = {source_id}  (in the input's namespace)"),
        P(u16(pid), f"participant_id = {pid}"),
        P(u64(session_id), f"session_id = {session_id}"),
        P(u64(off_start), f"off_start = {off_start}"),
        P(u64(off_end), f"off_end   = {off_end}"),
    ]
    return block(0x21, "Undecoded", body, options)


def name_block(session_id, pid, options=()):
    body = [
        P(u64(session_id), f"session_id = {session_id}"),
        P(u16(pid), f"participant_id = {pid}"),
        P(u16(0), "_reserved"),
    ]
    return block(0x30, "Name/Identity Resolution", body, options)


def end_block():
    body = [P(u32(0x5A454E44), 'end_magic = 0x5A454E44  ("ZEND")')]
    return block(0x41, "End of file", body)


def unknown_block(btype, content_bytes):
    """A block of a type this document does not define -- the forward
    compatibility case a reader must skip by length."""
    return block(btype, "UNKNOWN to this version", [P(content_bytes, "opaque content")])


# ------------------------------------------------------------ option helpers

def s(x):
    return x.encode('utf-8')

def o_comment(v):        return option(0x0001, s(v), "comment")
def o_creator(v):        return option(0x0011, s(v), "creator")
def o_produced_by(v):    return option(0x0012, s(v), "produced_by")
def o_produced_at(v):    return option(0x0013, i64(v), "produced_at", str(v))
def o_file_flags(v):     return option(0x0014, u16(v), "flags", f"0x{v:04X}")
def o_uri(v):            return option(0x0020, s(v), "uri")
def o_digest(v):         return option(0x0021, s(v), "digest")
def o_dec_name(v):       return option(0x0041, s(v), "name")
def o_dec_version(v):    return option(0x0042, s(v), "version")
def o_params_digest(v):  return option(0x0043, s(v), "params_digest")
def o_proto(v):          return option(0x0050, s(v), "proto")
def o_flow_key(v):       return option(0x0051, s(v), "flow_key")
def o_sess_flags(v):     return option(0x0052, u16(v), "flags", f"0x{v:04X}")
def o_seq_basis(v):      return option(0x0053, s(v), "sequenced_basis")
def o_external_sid(v):
    return option(0x0054, v, "external_session_id", f"{len(v)} opaque bytes")
def o_endpoint(v):       return option(0x0060, s(v), "endpoint")
def o_isn(v):            return option(0x0061, u32(v), "isn", str(v))
def o_tcp_role(v):       return option(0x0063, u8(v), "tcp_role", str(v))
def o_origin(src, pid, sess):
    return option(0x0064, u16(src) + u16(pid) + u64(sess), "origin",
                  f"source {src}, pid {pid}, session {sess}")
def o_seq_start(v):      return option(0x0070, u32(v), "seq_start", str(v))
def o_ack(v):            return option(0x0072, u32(v), "ack", str(v))
def o_spans(entries):
    packed = b''.join(u16(sr) + u16(pid) + u64(se) + u64(a) + u64(b)
                      for sr, pid, se, a, b in entries)
    return option(0x0080, packed, "spans", f"{len(entries)} entry/entries")
def o_decoder_id(v):     return option(0x0090, u16(v), "decoder_id", str(v))
def o_content_type(v):   return option(0x0091, s(v), "content_type")
def o_reason(v):         return option(0x00A0, s(v), "reason")
def o_reason_class(v):   return option(0x00A1, s(v), "reason_class")
def o_label(v):          return option(0x00B0, s(v), "label")
def o_name_kind(v):      return option(0x00B1, s(v), "kind")
def o_unregistered(oid, v):
    return option(oid, v, "UNREGISTERED")


# ------------------------------------------------------------------- vectors

GET = b"GET / HTTP/1.1\r\n\r\n"

def b64(x):
    return base64.b64encode(x).decode('ascii')


VECTORS = []

def vector(name, tier, summary, spec, blocks, jsonl=None, expect=None):
    VECTORS.append(dict(name=name, tier=tier, summary=summary, spec=spec,
                        blocks=blocks, jsonl=jsonl, expect=expect))


# --- baseline -------------------------------------------------------------

vector(
    "raw-minimal", "accept",
    "The minimal conformant raw file: one TCP session, one participant, one "
    "record. Byte-for-byte the worked example in the specification.",
    "Worked example: a minimal raw file",
    [
        file_header(),
        source(1, 0, [o_uri("sideA.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        record(7, 0, 1, 1000, GET, flags=0x0001,
               options=[o_seq_start(1001), o_ack(5001)]),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "sideA.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"], "isn": 1000},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "flags": ["psh"], "payload": b64(GET),
         "seq_start": 1001, "ack": 5001},
    ],
)

vector(
    "decoded-basic", "accept",
    "A decode stage's output: decoded records citing spans in the input, plus "
    "an Undecoded block covering the tail the decoder could not parse.",
    "A decoded file, end to end",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"),
                             o_produced_at(1719500000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        record(7, 0, 1, 1000, b"REQ", options=[
            o_decoder_id(1), o_spans([(1, 0, 7, 0, 18)]),
            o_content_type("dec:request")]),
        record(7, 1, 1, 995, b"RESP", options=[
            o_decoder_id(1), o_spans([(1, 1, 7, 0, 100)]),
            o_content_type("dec:response")]),
        undecoded(1, 1, 7, 100, 139, [o_reason("undecodable"), o_decoder_id(1)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-decode 0.4", "produced_at": 1719500000},
        {"type": "source", "source_id": 1, "kind": "zpf-input", "uri": "raw.zpf",
         "digest": "sha256:9f2c"},
        {"type": "decoder", "decoder_id": 1, "name": "http/1.1", "version": "0.4"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"]},
        {"type": "participant", "session_id": 7, "pid": 1,
         "endpoint": ["93.184.216.34:80"]},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "payload": b64(b"REQ"), "decoder_id": 1,
         "spans": [{"source_id": 1, "session_id": 7, "pid": 0,
                    "off_start": 0, "off_end": 18}],
         "content_type": "dec:request"},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 1,
         "ts": 995, "payload": b64(b"RESP"), "decoder_id": 1,
         "spans": [{"source_id": 1, "session_id": 7, "pid": 1,
                    "off_start": 0, "off_end": 100}],
         "content_type": "dec:response"},
        {"type": "undecoded", "source_id": 1, "session_id": 7, "pid": 1,
         "off_start": 100, "off_end": 139, "reason": "undecodable",
         "decoder_id": 1},
        {"type": "end"},
    ],
)

vector(
    "passthrough-transport", "accept",
    "A pass-through preserving a transport layer: byte-run records with no "
    "decoder_id, provenance carried by origin on each participant.",
    "Conformance -- pass-through transform",
    [
        file_header(options=[o_produced_by("zpf-merge 1.2"),
                             o_produced_at(1719510000)]),
        source(1, 1, [o_uri("sideA.zpf"), o_digest("sha256:11aa")]),
        session(1, [o_proto("tcp"), o_sess_flags(0x0001)]),
        participant(1, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000),
                           o_origin(1, 0, 7)]),
        record(1, 0, 1, 1000, GET, flags=0x0001,
               options=[o_seq_start(1001), o_ack(5001)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-merge 1.2", "produced_at": 1719510000},
        {"type": "source", "source_id": 1, "kind": "zpf-input",
         "uri": "sideA.zpf", "digest": "sha256:11aa"},
        {"type": "session", "session_id": 1, "proto": "tcp", "sequenced": True},
        {"type": "participant", "session_id": 1, "pid": 0,
         "endpoint": ["10.0.0.1:51000"], "isn": 1000,
         "origin": {"source_id": 1, "session_id": 7, "pid": 0}},
        {"type": "record", "session_id": 1, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "flags": ["psh"], "payload": b64(GET),
         "seq_start": 1001, "ack": 5001},
        {"type": "end"},
    ],
)

# --- the four escapes ------------------------------------------------------

vector(
    "escape-unknown-block", "accept",
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
)

vector(
    "escape-unknown-option", "accept",
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
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"]},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "payload": b64(b"hi"),
         "options": [{"id": "0x0200", "value": b64(b"\xaa\xbb")}]},
        {"type": "end"},
    ],
)

vector(
    "escape-unknown-enum", "accept",
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
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"], "tcp_role": 7},
        {"type": "end"},
    ],
)

vector(
    "escape-reserved-flag-bit", "accept",
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
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"]},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "flags": ["psh", "0x0020"], "payload": b64(b"hi")},
        {"type": "end"},
    ],
)

# --- 0.10 constructs -------------------------------------------------------

vector(
    "annotator-decoded", "accept",
    "A pass-through preserving a DECODED layer -- the 0.10 construct 0.9 could "
    "not express. Records keep decoder_id and carry no spans; the Undecoded "
    "block is inherited, so the grandparent source is declared too.",
    "Annotating a decoded file",
    [
        file_header(options=[o_produced_by("zpf-annotate 0.2"),
                             o_produced_at(1719520000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        source(2, 1, [o_uri("decoded.zpf"), o_digest("sha256:44dd")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_origin(2, 0, 7)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_origin(2, 1, 7)]),
        name_block(7, 1, [o_label("example.com"), o_name_kind("tls-sni")]),
        record(7, 0, 2, 1000, b"REQ", options=[
            o_decoder_id(1), o_content_type("dec:request")]),
        record(7, 1, 2, 995, b"RESP", options=[
            o_decoder_id(1), o_content_type("dec:response")]),
        undecoded(1, 1, 7, 100, 139, [o_reason("undecodable"), o_decoder_id(1)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-annotate 0.2", "produced_at": 1719520000},
        {"type": "source", "source_id": 1, "kind": "zpf-input", "uri": "raw.zpf",
         "digest": "sha256:9f2c"},
        {"type": "source", "source_id": 2, "kind": "zpf-input",
         "uri": "decoded.zpf", "digest": "sha256:44dd"},
        {"type": "decoder", "decoder_id": 1, "name": "http/1.1", "version": "0.4"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"],
         "origin": {"source_id": 2, "session_id": 7, "pid": 0}},
        {"type": "participant", "session_id": 7, "pid": 1,
         "endpoint": ["93.184.216.34:80"],
         "origin": {"source_id": 2, "session_id": 7, "pid": 1}},
        {"type": "name", "session_id": 7, "pid": 1, "label": "example.com",
         "kind": "tls-sni"},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 2,
         "ts": 1000, "payload": b64(b"REQ"), "decoder_id": 1,
         "content_type": "dec:request"},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 2,
         "ts": 995, "payload": b64(b"RESP"), "decoder_id": 1,
         "content_type": "dec:response"},
        {"type": "undecoded", "source_id": 1, "session_id": 7, "pid": 1,
         "off_start": 100, "off_end": 139, "reason": "undecodable",
         "decoder_id": 1},
        {"type": "end"},
    ],
)

vector(
    "undecoded-skipped", "accept",
    "A decode stage that deliberately declines a region -- a byte-order mark -- "
    "and says so with reason = skipped rather than claiming a parse failure.",
    "Undecoded (0x21)",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"),
                             o_produced_at(1719540000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("text/utf8"), o_dec_version("1.0")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        undecoded(1, 0, 7, 0, 3, [o_reason("skipped"), o_decoder_id(1),
                                  o_comment("UTF-8 BOM")]),
        record(7, 0, 1, 1000, b"body", options=[
            o_decoder_id(1), o_spans([(1, 0, 7, 3, 7)])]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-decode 0.4", "produced_at": 1719540000},
        {"type": "source", "source_id": 1, "kind": "zpf-input", "uri": "raw.zpf",
         "digest": "sha256:9f2c"},
        {"type": "decoder", "decoder_id": 1, "name": "text/utf8", "version": "1.0"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"]},
        {"type": "undecoded", "source_id": 1, "session_id": 7, "pid": 0,
         "off_start": 0, "off_end": 3, "reason": "skipped", "decoder_id": 1,
         "comment": "UTF-8 BOM"},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "payload": b64(b"body"), "decoder_id": 1,
         "spans": [{"source_id": 1, "session_id": 7, "pid": 0,
                    "off_start": 3, "off_end": 7}]},
        {"type": "end"},
    ],
)

vector(
    "undecoded-reason-class", "accept",
    "A non-canonical reason, which MUST carry reason_class so a consumer can "
    "still tell whether the bytes exist upstream.",
    "Undecoded (0x21)",
    [
        file_header(options=[o_produced_by("zpf-decode 0.4"),
                             o_produced_at(1719550000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
        decoder(1, [o_dec_name("http/1.1")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        undecoded(1, 0, 7, 0, 40, [o_reason("rtp-seq-gap"),
                                   o_reason_class("hole"), o_decoder_id(1)]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-decode 0.4", "produced_at": 1719550000},
        {"type": "source", "source_id": 1, "kind": "zpf-input", "uri": "raw.zpf",
         "digest": "sha256:9f2c"},
        {"type": "decoder", "decoder_id": 1, "name": "http/1.1"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"]},
        {"type": "undecoded", "source_id": 1, "session_id": 7, "pid": 0,
         "off_start": 0, "off_end": 40, "reason": "rtp-seq-gap",
         "reason_class": "hole", "decoder_id": 1},
        {"type": "end"},
    ],
)

UUID = bytes.fromhex("3f2504e04f8911d39a0c0305e82c3301")

vector(
    "external-session-id", "accept",
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
        {"type": "session", "session_id": 7, "proto": "tcp",
         "external_session_id": b64(UUID)},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"]},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "payload": b64(b"hi")},
        {"type": "end"},
    ],
)

vector(
    "sequenced-basis", "accept",
    "A hint-less UDP session marked SEQUENCED. Because it carries no seq/ack, "
    "sequenced_basis is mandatory and states what the order rests on.",
    "Sequenced files (precomputed order)",
    [
        file_header(),
        source(1, 0, [o_uri("chat.pcap")]),
        session(8, [o_proto("irc"), o_sess_flags(0x0001),
                    o_seq_basis("protocol")]),
        participant(8, 0, [o_endpoint("alice")]),
        participant(8, 1, [o_endpoint("bob")]),
        record(8, 0, 1, 2000, b"hi"),
        record(8, 1, 1, 2100, b"yo"),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "chat.pcap"},
        {"type": "session", "session_id": 8, "proto": "irc", "sequenced": True,
         "sequenced_basis": "protocol"},
        {"type": "participant", "session_id": 8, "pid": 0, "endpoint": ["alice"]},
        {"type": "participant", "session_id": 8, "pid": 1, "endpoint": ["bob"]},
        {"type": "record", "session_id": 8, "sender_pid": 0, "source_id": 1,
         "ts": 2000, "payload": b64(b"hi")},
        {"type": "record", "session_id": 8, "sender_pid": 1, "source_id": 1,
         "ts": 2100, "payload": b64(b"yo")},
        {"type": "end"},
    ],
)

vector(
    "reordered-decoded", "accept",
    "A stage that reorders a participant's decoded records without decoding "
    "them. It is a decode stage -- stored order defines the offsets, so "
    "reordering changes them -- and its spans run DOWNWARD against stored "
    "order. A reader that assumes spans ascend fails here.",
    "Layers -- filtering and reordering a decoded stream",
    [
        file_header(options=[o_produced_by("zpf-reorder 0.1"),
                             o_produced_at(1719530000)]),
        source(1, 1, [o_uri("decoded.zpf"), o_digest("sha256:44dd")]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        # Input pid 1 held A = [0,100) then B = [100,150). Emitted B first, so
        # the output stream is B = [0,50), A = [50,150) and the spans descend.
        record(7, 1, 1, 995, b"B" * 50, options=[
            o_decoder_id(1), o_spans([(1, 1, 7, 100, 150)]),
            o_content_type("dec:response")]),
        record(7, 1, 1, 990, b"A" * 100, options=[
            o_decoder_id(1), o_spans([(1, 1, 7, 0, 100)]),
            o_content_type("dec:response")]),
        end_block(),
    ],
    jsonl=[
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-reorder 0.1", "produced_at": 1719530000},
        {"type": "source", "source_id": 1, "kind": "zpf-input",
         "uri": "decoded.zpf", "digest": "sha256:44dd"},
        {"type": "decoder", "decoder_id": 1, "name": "http/1.1", "version": "0.4"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 1,
         "endpoint": ["93.184.216.34:80"]},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 1,
         "ts": 995, "payload": b64(b"B" * 50), "decoder_id": 1,
         "spans": [{"source_id": 1, "session_id": 7, "pid": 1,
                    "off_start": 100, "off_end": 150}],
         "content_type": "dec:response"},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 1,
         "ts": 990, "payload": b64(b"A" * 100), "decoder_id": 1,
         "spans": [{"source_id": 1, "session_id": 7, "pid": 1,
                    "off_start": 0, "off_end": 100}],
         "content_type": "dec:response"},
        {"type": "end"},
    ],
)

vector(
    "hintless-merge-backwards-ts", "accept",
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
        {"type": "record", "session_id": 8, "sender_pid": 0, "source_id": 1,
         "ts": 2000, "payload": b64(b"a1")},
        {"type": "record", "session_id": 8, "sender_pid": 1, "source_id": 1,
         "ts": 1900, "payload": b64(b"b1")},
        {"type": "record", "session_id": 8, "sender_pid": 0, "source_id": 1,
         "ts": 2100, "payload": b64(b"a2")},
        {"type": "end"},
    ],
)

vector(
    "merge-timestamp-tie", "accept",
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
        {"type": "record", "session_id": 8, "sender_pid": 1, "source_id": 1,
         "ts": 2000, "payload": b64(b"from-bob")},
        {"type": "record", "session_id": 8, "sender_pid": 0, "source_id": 1,
         "ts": 2000, "payload": b64(b"from-alice")},
        {"type": "end"},
    ],
)

vector(
    "partially-hinted-sequenced", "accept",
    "A SEQUENCED session where ONE record carries seq_start and the rest carry "
    "no hints at all. Under 0.12's definition a single hint anywhere means the "
    "session is not hint-less, so no sequenced_basis is required -- even though "
    "most of the order rests on timestamps. This vector pins that answer.",
    "Merge algorithm -- hint-less",
    [
        file_header(),
        source(1, 0, [o_uri("mixed.pcap")]),
        session(9, [o_proto("udp"), o_sess_flags(0x0001)]),
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
        {"type": "session", "session_id": 9, "proto": "udp", "sequenced": True},
        {"type": "participant", "session_id": 9, "pid": 0,
         "endpoint": ["10.0.0.1:5000"]},
        {"type": "participant", "session_id": 9, "pid": 1,
         "endpoint": ["10.0.0.2:5000"]},
        {"type": "record", "session_id": 9, "sender_pid": 0, "source_id": 1,
         "ts": 3000, "payload": b64(b"hinted"), "seq_start": 1001},
        {"type": "record", "session_id": 9, "sender_pid": 1, "source_id": 1,
         "ts": 3100, "payload": b64(b"plain")},
        {"type": "record", "session_id": 9, "sender_pid": 0, "source_id": 1,
         "ts": 3200, "payload": b64(b"plain2")},
        {"type": "end"},
    ],
)

# --- negative: the reject tier --------------------------------------------

vector(
    "isolate-sequenced-no-basis", "isolate",
    "A hint-less session marked SEQUENCED with no sequenced_basis. Recording "
    "the basis is unconditional -- the trivially-sound cases write `trivial` "
    "rather than omitting it -- so this file is semantically invalid.",
    "Sequenced files (precomputed order)",
    [
        file_header(),
        source(1, 0, [o_uri("chat.pcap")]),
        session(8, [o_proto("irc"), o_sess_flags(0x0001)]),
        participant(8, 0, [o_endpoint("alice")]),
        record(8, 0, 1, 2000, b"hi"),
        end_block(),
    ],
    expect="MAY reject the file, or isolate the session. Note WHEN: no record "
           "carries seq_start or ack, so the session is hint-less -- but a "
           "reader cannot know that until Session End or end-of-stream, since "
           "hint-lessness is a property of the records and the Session "
           "Descriptor precedes them. A checker that raises this at the "
           "descriptor is guessing; one that never raises it has not deferred "
           "the check.",
)



vector(
    "reject-bad-magic", "reject",
    "The File Header magic is the byte-swapped pattern 5A 49 50 46, which marks "
    "a byte-swapped file. The container is little-endian by definition.",
    "Conformance -- structural corruption",
    [file_header(magic=0x46495A5A), source(1, 0, [o_uri("c.pcap")])],
    expect="Reject the file. A reader SHOULD report that the magic looks "
           "byte-swapped, which is a more useful diagnostic than 'not a zpf'.",
)

vector(
    "reject-unknown-major", "reject",
    "version_major is 1, which this document does not define. A reader MUST "
    "reject a major it does not implement.",
    "File Header -- version numbering",
    [file_header(major=1, minor=0), source(1, 0, [o_uri("c.pcap")])],
    expect="Reject the file.",
)

vector(
    "reject-unknown-minor", "reject",
    f"version_minor is {MINOR + 1} while major is 0. In the 0.x regime the pair "
    f"(0, minor) is the compatibility identity, so a {MAJOR}.{MINOR} reader "
    "MUST reject it.",
    "File Header -- version numbering",
    # The next minor, derived, so this vector keeps testing an unimplemented
    # version instead of becoming a valid file at the next version bump.
    [file_header(minor=MINOR + 1), source(1, 0, [o_uri("c.pcap")])],
    expect="Reject the file. This is the vector that distinguishes a 0.x-aware "
           "reader from one that assumes minors are always skippable.",
)

vector(
    "reject-length-misaligned", "reject",
    "A block length that is not a multiple of 4, which breaks the alignment "
    "invariant the whole container rests on.",
    "Conformance -- structural corruption",
    [file_header(),
     # Hand-framed: a Source block claiming length 6.
     [P(u16(0x02), "type   = 0x0002  Source Descriptor"),
      P(u16(0), "reserved"),
      P(u32(6), "length = 6   (NOT a multiple of 4 -- structural corruption)"),
      P(u16(1), "source_id = 1"),
      P(u8(0), "kind = 0  (capture)"),
      P(u8(0), "_reserved"),
      P(b"\x00\x00", "two bytes to reach the claimed length")]],
    expect="Reject the file.",
)

vector(
    "reject-payload-len-overrun", "reject",
    "A record whose payload_len runs past the end of its own block.",
    "Conformance -- structural corruption",
    [file_header(),
     source(1, 0, [o_uri("c.pcap")]),
     session(7, [o_proto("tcp")]),
     participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
     record(7, 0, 1, 1000, b"hi", payload_len=9999)],
    expect="Reject the file. payload_len exceeds the bytes the block's own "
           "length makes available.",
)

# --- negative: the isolate tier -------------------------------------------

vector(
    "isolate-undeclared-session", "isolate",
    "A record referencing a session_id that was never declared. Well-framed, "
    "so the byte stream is trustworthy: this is a semantic violation.",
    "Conformance -- semantic violations",
    [file_header(),
     source(1, 0, [o_uri("c.pcap")]),
     session(7, [o_proto("tcp")]),
     participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
     record(7, 0, 1, 1000, b"ok"),
     record(99, 0, 1, 1100, b"bad"),
     end_block()],
    expect="MAY reject the file, or isolate the offending record or session. "
           "MUST NOT silently drop it without a diagnostic, and MUST NOT "
           "invent the missing declaration. A reader that discards only the "
           "second record and keeps the first is behaving correctly.",
)

vector(
    "isolate-duplicate-id", "isolate",
    "A source_id declared twice.",
    "Conformance -- semantic violations",
    [file_header(),
     source(1, 0, [o_uri("first.pcap")]),
     source(1, 0, [o_uri("second.pcap")]),
     session(7, [o_proto("tcp")]),
     end_block()],
    expect="MAY reject the file, or isolate. MUST NOT silently pick one.",
)

vector(
    "isolate-coverage-gap", "isolate",
    "A decode stage whose output leaves part of the input stream neither "
    "covered by a decoded record's spans nor marked Undecoded.",
    "Coverage honesty: Undecoded blocks",
    [file_header(options=[o_produced_by("zpf-decode 0.4"),
                          o_produced_at(1719560000)]),
     source(1, 1, [o_uri("raw.zpf"), o_digest("sha256:9f2c")]),
     decoder(1, [o_dec_name("http/1.1")]),
     session(7, [o_proto("http")]),
     participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
     # covers [0,10) only; [10,50) is accounted for nowhere
     record(7, 0, 1, 1000, b"part", options=[
         o_decoder_id(1), o_spans([(1, 0, 7, 0, 10)])]),
     undecoded(1, 0, 7, 20, 50, [o_reason("undecodable"), o_decoder_id(1)]),
     end_block()],
    expect="MAY reject the file, or isolate the session. The range [10,20) of "
           "input stream (session 7, pid 0) is covered by neither a record's "
           "spans nor an Undecoded block, so the coverage guarantee fails.",
)

vector(
    "isolate-unknown-source-kind", "isolate",
    "A Source whose kind is undefined. Unlike tcp_role this is load-bearing: "
    "kind decides how a span's offsets are read, so anything referencing this "
    "Source is uninterpretable.",
    "Unrecognised enum values",
    [file_header(),
     source(1, 7, [o_uri("mystery")]),
     session(7, [o_proto("tcp")]),
     participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
     record(7, 0, 1, 1000, b"hi"),
     end_block()],
    expect="MAY reject the file, or discard the Source together with "
           "everything referencing it. MUST NOT guess a kind. Note this is "
           "the enum case that is NOT a free extension point.",
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

REQ  = b"GET /\r\n\r\n"                 # 9
RESP = b"HTTP/1.1 200\r\n\r\n"          # 16
TAIL = b"\x00\x01\x02\x03"               # 4, undecodable
DEC_REQ  = b"REQ:GET /"                  # 9  -> decoded pid 0 offsets [0,9)
DEC_RESP = b"RESP:200"                   # 8  -> decoded pid 1 offsets [0,8)

CHAIN = []

def chain_file(name, summary, blocks, jsonl):
    CHAIN.append(dict(name=name, summary=summary, blocks=blocks, jsonl=jsonl))
    return to_bytes(assemble(blocks))


def build_chain():
    """Build the three files in order, hashing each so the next can cite it."""
    raw_blocks = [
        file_header(options=[o_creator("zpf-sessionize 1.0")]),
        source(1, 0, [o_uri("cap.pcap")]),
        session(7, [o_proto("tcp")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_isn(1000)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_isn(5000)]),
        record(7, 0, 1, 1000, REQ, flags=0x0001,
               options=[o_seq_start(1001), o_ack(5001)]),
        record(7, 1, 1, 1100, RESP, flags=0x0001,
               options=[o_seq_start(5001), o_ack(1010)]),
        record(7, 1, 1, 1200, TAIL,
               options=[o_seq_start(5017), o_ack(1010)]),
        end_block(),
    ]
    raw = chain_file("raw", "The capture-sourced file the chain starts from.",
                     raw_blocks, [
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "creator": "zpf-sessionize 1.0"},
        {"type": "source", "source_id": 1, "kind": "capture", "uri": "cap.pcap"},
        {"type": "session", "session_id": 7, "proto": "tcp"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"], "isn": 1000},
        {"type": "participant", "session_id": 7, "pid": 1,
         "endpoint": ["93.184.216.34:80"], "isn": 5000},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "flags": ["psh"], "payload": b64(REQ),
         "seq_start": 1001, "ack": 5001},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 1,
         "ts": 1100, "flags": ["psh"], "payload": b64(RESP),
         "seq_start": 5001, "ack": 1010},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 1,
         "ts": 1200, "payload": b64(TAIL), "seq_start": 5017, "ack": 1010},
        {"type": "end"},
    ])
    raw_dg = "sha256:" + hashlib.sha256(raw).hexdigest()

    dec_blocks = [
        file_header(options=[o_produced_by("zpf-decode 0.4"),
                             o_produced_at(1719500000)]),
        source(1, 1, [o_uri("raw.zpf"), o_digest(raw_dg)]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000")]),
        participant(7, 1, [o_endpoint("93.184.216.34:80")]),
        record(7, 0, 1, 1000, DEC_REQ, options=[
            o_decoder_id(1), o_spans([(1, 0, 7, 0, 9)]),
            o_content_type("dec:request")]),
        record(7, 1, 1, 1100, DEC_RESP, options=[
            o_decoder_id(1), o_spans([(1, 1, 7, 0, 16)]),
            o_content_type("dec:response")]),
        undecoded(1, 1, 7, 16, 20, [o_reason("undecodable"), o_decoder_id(1)]),
        end_block(),
    ]
    dec = chain_file("decoded",
                     "A decode stage over raw.zpf. Its spans and Undecoded "
                     "block together cover every byte of both input streams.",
                     dec_blocks, [
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-decode 0.4", "produced_at": 1719500000},
        {"type": "source", "source_id": 1, "kind": "zpf-input", "uri": "raw.zpf",
         "digest": raw_dg},
        {"type": "decoder", "decoder_id": 1, "name": "http/1.1", "version": "0.4"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"]},
        {"type": "participant", "session_id": 7, "pid": 1,
         "endpoint": ["93.184.216.34:80"]},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 1,
         "ts": 1000, "payload": b64(DEC_REQ), "decoder_id": 1,
         "spans": [{"source_id": 1, "session_id": 7, "pid": 0,
                    "off_start": 0, "off_end": 9}],
         "content_type": "dec:request"},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 1,
         "ts": 1100, "payload": b64(DEC_RESP), "decoder_id": 1,
         "spans": [{"source_id": 1, "session_id": 7, "pid": 1,
                    "off_start": 0, "off_end": 16}],
         "content_type": "dec:response"},
        {"type": "undecoded", "source_id": 1, "session_id": 7, "pid": 1,
         "off_start": 16, "off_end": 20, "reason": "undecodable",
         "decoder_id": 1},
        {"type": "end"},
    ])
    dec_dg = "sha256:" + hashlib.sha256(dec).hexdigest()

    ann_blocks = [
        file_header(options=[o_produced_by("zpf-annotate 0.2"),
                             o_produced_at(1719520000)]),
        # Source 1 is the GRANDPARENT, declared only so the inherited Undecoded
        # block still resolves. Source 2 is the immediate input.
        source(1, 1, [o_uri("raw.zpf"), o_digest(raw_dg)]),
        source(2, 1, [o_uri("decoded.zpf"), o_digest(dec_dg)]),
        decoder(1, [o_dec_name("http/1.1"), o_dec_version("0.4")]),
        session(7, [o_proto("http")]),
        participant(7, 0, [o_endpoint("10.0.0.1:51000"), o_origin(2, 0, 7)]),
        participant(7, 1, [o_endpoint("93.184.216.34:80"), o_origin(2, 1, 7)]),
        name_block(7, 1, [o_label("example.com"), o_name_kind("tls-sni")]),
        record(7, 0, 2, 1000, DEC_REQ, options=[
            o_decoder_id(1), o_content_type("dec:request")]),
        record(7, 1, 2, 1100, DEC_RESP, options=[
            o_decoder_id(1), o_content_type("dec:response")]),
        undecoded(1, 1, 7, 16, 20, [o_reason("undecodable"), o_decoder_id(1)]),
        end_block(),
    ]
    chain_file("annotated",
               "A pass-through preserving decoded.zpf's layer, adding only a "
               "label. Records carry no spans; the inherited Undecoded block "
               "still names raw.zpf, so raw.zpf is declared too.",
               ann_blocks, [
        {"type": "file", "format": FORMAT, "tick_hz": 1000000,
         "produced_by": "zpf-annotate 0.2", "produced_at": 1719520000},
        {"type": "source", "source_id": 1, "kind": "zpf-input", "uri": "raw.zpf",
         "digest": raw_dg},
        {"type": "source", "source_id": 2, "kind": "zpf-input",
         "uri": "decoded.zpf", "digest": dec_dg},
        {"type": "decoder", "decoder_id": 1, "name": "http/1.1", "version": "0.4"},
        {"type": "session", "session_id": 7, "proto": "http"},
        {"type": "participant", "session_id": 7, "pid": 0,
         "endpoint": ["10.0.0.1:51000"],
         "origin": {"source_id": 2, "session_id": 7, "pid": 0}},
        {"type": "participant", "session_id": 7, "pid": 1,
         "endpoint": ["93.184.216.34:80"],
         "origin": {"source_id": 2, "session_id": 7, "pid": 1}},
        {"type": "name", "session_id": 7, "pid": 1, "label": "example.com",
         "kind": "tls-sni"},
        {"type": "record", "session_id": 7, "sender_pid": 0, "source_id": 2,
         "ts": 1000, "payload": b64(DEC_REQ), "decoder_id": 1,
         "content_type": "dec:request"},
        {"type": "record", "session_id": 7, "sender_pid": 1, "source_id": 2,
         "ts": 1100, "payload": b64(DEC_RESP), "decoder_id": 1,
         "content_type": "dec:response"},
        {"type": "undecoded", "source_id": 1, "session_id": 7, "pid": 1,
         "off_start": 16, "off_end": 20, "reason": "undecodable",
         "decoder_id": 1},
        {"type": "end"},
    ])


# ------------------------------------------------------------------ emitters

def assemble(blocks):
    pieces = []
    for b in blocks:
        pieces.extend(b)
        pieces.append(P(b"", ""))  # blank line between blocks in the dump
    return pieces


def to_bytes(pieces):
    return b''.join(b for b, _ in pieces)


def to_hexdump(pieces, title):
    lines = [f"# {title}", "#",
             "# Generated from the same description as the .zpf -- never edited",
             "# by hand, so the annotation cannot drift from the bytes.", ""]
    off = 0
    for data, ann in pieces:
        if not data:
            lines.append("")
            continue
        # Split long values across lines of 8 bytes, annotating the first.
        for i in range(0, len(data), 8):
            chunk = data[i:i + 8]
            hexs = ' '.join(f"{c:02X}" for c in chunk)
            note = ann if i == 0 else ""
            lines.append(f"{off:04X}  {hexs:<24} {note}".rstrip())
            off += len(chunk)
    lines.append(f"{off:04X}                           (end of file, {off} bytes)")
    return '\n'.join(lines) + '\n'


def main():
    check = '--check' in sys.argv
    build_chain()
    manifest = []
    problems = []

    # The chain lives in one directory: its three files are a single fixture,
    # and only together do the digests and offsets mean anything.
    cdir = os.path.join(HERE, 'chain')
    chain_files = {}
    for c in CHAIN:
        pieces = assemble(c['blocks'])
        chain_files[f"{c['name']}.zpf"] = to_bytes(pieces)
        chain_files[f"{c['name']}.hex"] = to_hexdump(pieces, f"chain/{c['name']}").encode()
        chain_files[f"{c['name']}.jsonl"] = (
            '\n'.join(json.dumps(o, separators=(',', ':')) for o in c['jsonl'])
            + '\n').encode()
    if check:
        for fn, want in chain_files.items():
            path = os.path.join(cdir, fn)
            if not os.path.exists(path):
                problems.append(f"missing chain/{fn}")
            elif open(path, 'rb').read() != want:
                problems.append(f"stale chain/{fn}")
    else:
        os.makedirs(cdir, exist_ok=True)
        for fn, data in chain_files.items():
            with open(os.path.join(cdir, fn), 'wb') as f:
                f.write(data)
    for v in VECTORS:
        pieces = assemble(v['blocks'])
        raw = to_bytes(pieces)
        d = os.path.join(HERE, v['name'])
        files = {
            f"{v['name']}.zpf": raw,
            f"{v['name']}.hex": to_hexdump(pieces, v['name']).encode(),
        }
        if v['jsonl'] is not None:
            files[f"{v['name']}.jsonl"] = (
                '\n'.join(json.dumps(o, separators=(',', ':')) for o in v['jsonl'])
                + '\n').encode()
        if check:
            for fn, want in files.items():
                path = os.path.join(d, fn)
                if not os.path.exists(path):
                    problems.append(f"missing {v['name']}/{fn}")
                elif open(path, 'rb').read() != want:
                    problems.append(f"stale {v['name']}/{fn}")
        else:
            os.makedirs(d, exist_ok=True)
            for fn, data in files.items():
                with open(os.path.join(d, fn), 'wb') as f:
                    f.write(data)
        manifest.append({
            'name': v['name'], 'tier': v['tier'], 'bytes': len(raw),
            'summary': v['summary'], 'spec_section': v['spec'],
            'expect': v['expect'] or (
                'Accept. The .jsonl file is the expected projection.'),
            'has_jsonl': v['jsonl'] is not None,
        })

    manifest.append({
        'name': 'chain', 'tier': 'accept', 'bytes': sum(
            len(v) for k, v in chain_files.items() if k.endswith('.zpf')),
        'summary': 'A three-file provenance chain whose digests and offsets '
                   'genuinely agree: raw.zpf -> decoded.zpf -> annotated.zpf. '
                   'The only fixture where the recovery walk, two-hop '
                   'resolution and digest verification can be exercised.',
        'spec_section': 'Layers; Coverage honesty; Annotating a decoded file',
        'expect': 'Accept all three. Each .jsonl is the expected projection. '
                  'Each declared digest is the real SHA-256 of the sibling '
                  'file it names, so a reader can verify the chain.',
        'has_jsonl': True,
        'files': sorted(chain_files),
    })

    mtext = json.dumps({'format': FORMAT,
                        'vectors': manifest}, indent=2) + '\n'
    mpath = os.path.join(HERE, 'manifest.json')
    if check:
        if not os.path.exists(mpath) or open(mpath).read() != mtext:
            problems.append('stale manifest.json')
        if problems:
            print('\n'.join(problems))
            return 1
        print(f"{len(VECTORS)} vectors + chain up to date")
        return 0
    with open(mpath, 'w') as f:
        f.write(mtext)
    print(f"wrote {len(VECTORS)} vectors + a {len(CHAIN)}-file chain")
    return 0


if __name__ == '__main__':
    sys.exit(main())
