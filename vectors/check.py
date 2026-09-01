#!/usr/bin/env python3
"""Check the vectors are internally consistent and behave as the manifest says.

This is deliberately NOT a conformant reader. It knows only the frame -- type,
reserved, length -- plus the File Header body, because that is all it takes to
tell a structurally-corrupt file from a well-framed one. Semantic expectations
(the isolate tier) are stated in the manifest for a human and for an
implementation's test harness; nothing here adjudicates them, because a checker
that ruled on semantics would become a second normative authority, which is
exactly what the README says a vector must never be.

The one exception is `chain/`, where a little arithmetic is unavoidable: its
entire value is that the digests and offsets agree, and a fixture whose numbers
have silently drifted is worse than none. Those checks verify the fixture against
itself, not the specification against anything, and they are specific to those
three files -- every other check here applies to any fixture.

What it does verify:
  * every committed file matches what build.py produces (no drift)
  * every vector's declared violation count agrees with its declared tier --
    accept 0, reject 1, isolate 1. The count is declared, never computed from
    the file; see VIOLATIONS_BY_TIER
  * every capability the format defines is exercised by some vector: option ids
    and block types parsed from the specification's own tables, plus the rules
    declared in RULES. What each vector exercises is recorded by build.py, which
    built the bytes -- nothing here parses a block body
  * no claim the model has retired is still in the specification, per
    RETIRED_CLAIMS. This is textual, not semantic: it holds a claim retired once
    from quietly returning, and cannot find one nobody has noticed
  * accept/isolate vectors are well-framed: block walk lands exactly on EOF,
    every length is a multiple of 4, magic and version are what this version
    defines. Multi-file fixtures are walked file by file, same as any vector
  * reject vectors actually contain the structural defect they claim
  * each accept vector's .jsonl parses and has one line per block
  * every key in every .jsonl is one the JSONL mapping defines, spelled the way
    it spells it -- a body field's or a registered option's canonical name,
    except where the alias table gives it a shorter one
  * for chain/ specifically: every declared digest is the real SHA-256 of the
    sibling file it names, and decoded.zpf's spans plus Undecoded blocks cover
    exactly the streams raw.zpf actually contains

Usage:  python3 check.py
"""

import json
import os
import re
import struct
import subprocess
import sys
from collections.abc import Iterator

HERE = os.path.dirname(os.path.abspath(__file__))


def read_bytes(path: str) -> bytes:
    """Read a file whole, in binary."""
    with open(path, "rb") as f:
        return f.read()


def read_text(path: str) -> str:
    """Read a file whole, as UTF-8 text."""
    with open(path, encoding="utf-8") as f:
        return f.read()


MAGIC = 0x5A495046
MAJOR, MINOR = 0, 17

# How many violations each tier must declare. A negative vector carrying two
# silently tests whichever the reader detects first, and passes implementations
# that never exercised the rule it was built for -- isolate-coverage-gap did
# exactly that through 0.12. This compares the *declared* count against the
# *declared* tier; it never inspects a file to count them, because a checker that
# ruled on semantics would become a second normative authority.
VIOLATIONS_BY_TIER = {"accept": 0, "reject": 1, "isolate": 1}

# One violation does not isolate: an advisory MUST NOT, where the file stays
# readable and a reader carries on having reported it. 0.16 gained the first
# (content_type on a transport-layer record, #95) and the three tiers could not
# say it -- `accept` means zero violations, `isolate` means the reader may
# discard something, and this is neither.
#
# It is a key on an accept entry rather than a fourth tier because the tier names
# what a READER does, and a reader accepts this file completely. `advisory: true`
# says the acceptance is not because the file is clean. tcp_role escapes the
# question only because an unrecognised enum value is not a violation at all.
ADVISORY_VIOLATIONS = 1

SPEC = os.path.join(HERE, os.pardir, "docs", "zipline-payload-format.md")

# Capabilities that are RULES rather than syntax, and the vector exercising each.
# Session fan-out shipped in 0.13 as a Clarified item with nothing exercising it,
# and nobody noticed until an implementation reviewed the release -- so a purely
# mechanical check over the registry would not have caught the very thing that
# motivated this one. A rule has no id to derive, so it is declared here.
#
# Add a rule when the specification gains one. Adding it with no vector fails,
# which is the point: the failure is what makes the gap impossible to forget.
RULES = {
    # F0's four: the two axes stated independent, and the three cells that
    # follow from it. Each is a permission, and a permission with no vector is
    # how #66 happened.
    "axes-independent": (
        "provenance and layer are independent; a capture-sourced stream may be decoded",
        "proxy-decoded",
    ),
    "undecoded-capture-sourced": (
        "a capture-sourced stream may declare what its reassembler did not carry",
        "undecoded-in-capture",
    ),
    "per-stream-transform": (
        "one file MAY create one stream and preserve another; the bar is per participant",
        "mixed-derivation",
    ),
    "no-intra-file-derivation": (
        "a file MUST NOT derive one of its own streams from another",
        "isolate-self-derived",
    ),
    # F1's three. The option id is covered mechanically by the registry parse;
    # the enum tables are not parsed, so the VALUES are covered only by these
    # entries naming vectors -- the statement-of-intent limit again.
    "decoder-declares-layer": (
        "a decoder declares the layer it emits; reassembly is a decoder",
        "sessionization-stage",
    ),
    "reassembler-may-declare": (
        "a head-of-pipeline reassembler MAY declare itself; the asymmetry is deliberate",
        "reassembler-declared",
    ),
    "unknown-output-layer-isolates": (
        "an unrecognised output_layer leaves offsets uncomputable; MUST NOT guess",
        "isolate-unknown-output-layer",
    ),
    "spans-correspondence": (
        "a decoder may transform; spans name what a unit corresponds to",
        "chain",
    ),
    "session-fan-out": (
        "a stage's output sessions need not mirror its input's",
        "session-fan-out",
    ),
    "coverage-at-least-once": (
        "two records MAY cite one input region; coverage is at least once",
        "session-fan-out",
    ),
    "discontinuity-known-width": (
        "a declared width is a term in the positional arithmetic",
        "discontinuity-known-width",
    ),
    "discontinuity-unknown-width": (
        "an absent width contributes 0; the join is still marked",
        "discontinuity-unknown-width",
    ),
    "extents-self-verifiable": (
        "input_extents makes the coverage guarantee checkable from one file",
        "isolate-extent-exceeds-coverage",
    ),
    "broken-provenance-walk": (
        "bytes unavailable is not the same as no bytes exist",
        "broken-chain",
    ),
    # The two halves of the block's duty, and they read as a pair: originate a
    # break where one first appears, then carry it down the chain. 0.13 shipped
    # only the second, which is what #78 found.
    "discontinuity-origination": (
        "a stage MUST declare a break in its OWN output, not only carry one forward",
        "isolate-unmarked-break",
    ),
    "discontinuity-no-splice": (
        "a stage MUST NOT emit a unit whose spans cross a declared break "
        "without declaring one of its own",
        "splice",
    ),
    "discontinuity-reordering": (
        "stored neighbours that were never adjacent do not join, so each seam is declared",
        "reordered-decoded",
    ),
    "discontinuity-passthrough-renumber": (
        "a pass-through renumbers a Discontinuity but copies Undecoded verbatim",
        "passthrough-discontinuity",
    ),
    # 0.16's four. Each is a MUST the syntax already allowed you to break, which
    # is why each needed a vector before it needed a checker.
    "layer-consistency": (
        "every record of one participant MUST resolve to the same layer",
        "isolate-mixed-layer-participant",
    ),
    "zpf-stream-created-or-preserved": (
        "a zpf-sourced participant MUST carry origin or hold records with spans, never neither",
        "isolate-unbound-zpf-stream",
    ),
    "undecoded-capture-bytes-only": (
        "against a capture source the hole class is unavailable -- "
        "the transport offsets already carry the gap",
        "isolate-hole-against-capture",
    ),
    "content-type-transport-advisory": (
        "a label at the transport layer -- content_type since 0.16, role since 0.17 -- "
        "is a MUST NOT whose violation is ADVISORY: a reader reports it, ignores the "
        "label, and accepts the file",
        "advisory-transport-content-type",
    ),
    # 0.17's option. The id is covered mechanically by the registry parse; what
    # is not is the SCOPING, which is the whole of what makes role more than a
    # comment and is stated in prose no table sees.
    "role-decoder-scoped": (
        "a record MAY carry its type and its name at once; role names the record in a "
        "vocabulary scoped to its decoder's name, as a dec: token is, and asserts no tree",
        "decoded-field-roles",
    ),
    # 0.17's second decidable case. The hole-class one has had a vector since
    # 0.15 (isolate-unmarked-break); this is the bytes-class half, which could
    # not be tested at all while one word did both jobs.
    "dropped-is-a-break": (
        "a bytes-class `dropped` region between two adjacent units requires a "
        "Discontinuity; `skipped` does not, and the word is the producer's statement",
        "isolate-unmarked-drop",
    ),
    # 0.17's floor. Like 0.16's four, a MUST the syntax already let you break --
    # and the second MUST NOT whose violation is advisory rather than isolating.
    "seq-start-origin-floor": (
        "a record's seq_start MUST NOT precede the stream origin; the violation is "
        "ADVISORY and the record is unplaceable, zero-width at the current position",
        "advisory-seq-start-below-origin",
    ),
    # NOT in this table, deliberately: "a stage emitting a transport layer MUST
    # NOT withhold content from a stream whose offsets are not sequence-anchored"
    # (#94). It is a writer obligation with no file-visible signature -- a stream
    # that withheld and one that did not are byte-identical, which is the whole
    # reason the rule is needed. No vector can express it, so listing it here
    # would fail the build forever for a rule that is correctly unverifiable.
    # Recorded here rather than omitted silently, so the gap is a decision.
}


# Claims the model has retired, and MUST NOT reappear in the specification.
#
# #70 added a release checklist step: grep every restatement of a rule before
# changing it. 0.15 changed the layer rule and shipped two paragraphs asserting
# the old one anyway, and the step did not catch either -- because neither
# paragraph RESTATES the rule. The layer rule is stated exactly once, so a check
# that counted its copies would have reported one site, correct, and passed
# clean. What the stale copies do is assert its negation, in words that share no
# phrase with it.
#
# So the mechanism is a ratchet, not a detector. It cannot find a stale claim
# nobody has noticed; what it guarantees is that a claim retired once can never
# quietly return -- which is the failure mode this repository keeps hitting
# (#63 in 0.14, #89 and #91 in 0.15).
#
# Add an entry whenever a release retires a claim, in the release that retires
# it. The pattern matches against whitespace-collapsed text, so a copy that
# happens to wrap differently is still caught -- the 0.14 sweep nearly missed one
# for exactly that reason.
RETIRED_CLAIMS = {
    "transport-carries-no-undecoded": (
        r"neither carries Undecoded blocks, because no decoder ran",
        "0.16",
        89,
        "a transport-layer stream MAY carry Undecoded blocks; the input is the "
        "capture and the stage is the reassembler",
    ),
    "only-advisory-must-not": (
        r"it is the only MUST NOT in this\s+document with that strength",
        "0.17",
        108,
        "the origin floor is a second advisory MUST NOT; the document gives that "
        "strength wherever it can say exactly what a reader does instead",
    ),
    "derived-file-is-not-a-mix": (
        r"exactly one of a \*decode stage\* or a \*pass-through transform\*, never a\s+mix",
        "0.17",
        103,
        "the discriminator binds per participant, not per file; one file MAY hold a "
        "created stream beside a preserved one (mixed-derivation)",
    ),
    "only-holes-are-decidable": (
        r"One case is decidable from a single file",
        "0.17",
        98,
        "two cases are: a hole-class region between two adjacent units, and a "
        "bytes-class region carrying reason = dropped",
    ),
    "byte-run-has-no-decoder-id": (
        r"A byte run carries none",
        "0.16",
        91,
        "a reassembly record is a byte run AND carries a decoder_id; the "
        "distinction is the layer, not the presence of the field",
    ),
}


# Keys the projection defines structurally. Neither the option registry nor a
# block's body table can supply them, because they name no binary field and no
# option: the block discriminator, the two escapes that carry unrecognised data
# (see "Unrecognised data: the four escapes"), and the one member of a structured
# option's entries that is not itself a field or option name.
#
# Declared, for the reason RULES is declared: derived from nothing, so a check
# over the tables alone would report them as unknown keys. Everything else must
# come from the specification.
PROJECTION_KEYS = {
    "type": "the block discriminator",
    "options": "the unrecognised-option escape, an array of {id, value}",
    "id": "an entry in that array",
    "value": "an entry in that array",
    "content": "the unrecognised-block escape, the whole content as base64",
    "extent": "a member of an `input_extents` entry",
}

# Fields the mapping says have no JSON key at all: framing and on-disk-only.
# `type`, `reserved` and `length` are frame fields and appear in no body table;
# the version pair projects only through the `format` alias, so writing either
# half as a key is the same defect as writing a binary name that has an alias.
NOT_PROJECTED = {
    "magic",
    "end_magic",
    "payload_len",
    "_reserved",
    "version_major",
    "version_minor",
}


def spec_body_fields() -> set[str]:
    """Return every block body field the specification names.

    One table per block, found by its header row, in the same way spec_tables()
    finds the registry -- a looser match picks up the value tables that follow
    several of them.
    """
    fields: set[str] = set()
    in_table = False
    for line in read_text(SPEC).splitlines():
        if line.startswith("| Field"):
            in_table = True
            continue
        if in_table:
            m = re.match(r"^\| `([^`]+)`", line)
            if m:
                fields.add(m.group(1))
            elif not line.startswith("|"):
                in_table = False
    return fields


def spec_aliases() -> tuple[set[str], dict[str, str]]:
    """Return the brevity aliases: the JSON keys, and the binary names they replace.

    A row is a *rename* only where its right column is a bare binary name (with
    an optional parenthetical saying where it applies). The other rows describe a
    *rendering* -- the version pair as one `format` string, a flags bit as a
    boolean -- and rename nothing, so `flags` stays a legal key. Reading every
    row as a rename would forbid it.
    """
    keys: set[str] = set()
    renamed: dict[str, str] = {}
    in_table = False
    for line in read_text(SPEC).splitlines():
        if line.startswith("| JSONL key"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            m = re.match(r"^`([^`]+)`$", cells[0])
            if not m:
                continue  # the ---- separator row
            keys.add(m.group(1))
            rename = re.match(r"^`(\w+)`(?:\s*\([^)]*\))?$", cells[1])
            if rename:
                renamed[rename.group(1)] = m.group(1)
    return keys, renamed


def jsonl_keys(path: str) -> Iterator[tuple[int, str]]:
    """Yield (line number, key) for every key in one projection, nested included."""

    def walk_value(value: object) -> Iterator[str]:
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from walk_value(v)
        elif isinstance(value, list):
            for v in value:
                yield from walk_value(v)

    for i, line in enumerate(read_text(path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # check_jsonl reports it; one defect, one message
        for key in walk_value(obj):
            yield i, key


def check_jsonl_keys() -> list[str]:
    """Every JSONL key must be one the mapping defines, spelled the way it says.

    The mapping is one rule plus a short list of exceptions: a key is a body
    field's or a registered option's canonical name, except where the alias table
    gives it a shorter one -- and then the alias is the spelling, not a second
    one. `flow_key` shipped in two fixtures against a table saying `key` (#104),
    which no check could see, because both spellings name something real.

    A key outside all of that is an "unknown key on a known block", which the
    projection deliberately gives no escape: a converter must reject or drop it.
    A fixture is the wrong place to find out.

    Mechanical, and ground rule 2 holds: it compares the tree's key names against
    the specification's own tables. Nothing here parses a block body or rules on
    what a value means.
    """
    opts, _blocks = spec_tables()
    alias_keys, renamed = spec_aliases()
    body = spec_body_fields()
    if not opts or not body or not alias_keys:
        return ["jsonl keys: could not parse the specification's tables"]

    allowed = (body | set(opts.values()) | alias_keys | set(PROJECTION_KEYS)) - NOT_PROJECTED
    allowed -= set(renamed)

    out, seen, files = [], set(), 0
    for root, _dirs, names in sorted(os.walk(HERE)):
        for fn in sorted(names):
            if not fn.endswith(".jsonl"):
                continue
            files += 1
            label = os.path.relpath(os.path.join(root, fn), HERE)
            for i, key in jsonl_keys(os.path.join(root, fn)):
                seen.add(key)
                if key in allowed:
                    continue
                if key in renamed:
                    out.append(
                        f"{label}:{i}: key '{key}' is the binary name of a listed "
                        f"brevity alias -- the projection spells it '{renamed[key]}'"
                    )
                elif key in NOT_PROJECTED:
                    out.append(
                        f"{label}:{i}: key '{key}' is framing or on-disk-only and has no JSON key"
                    )
                else:
                    out.append(
                        f"{label}:{i}: key '{key}' is neither a body field, a "
                        f"registry option name, nor a listed alias"
                    )
    if not out:
        print(
            f"  jsonl keys: {len(seen)} distinct across {files} files -- "
            f"every one a body field, an option or an alias"
        )
    return out


def check_retired_claims() -> list[str]:
    """No claim the model has retired may appear in the specification.

    Whitespace is collapsed before matching so a line-wrapped copy is still
    found; the 0.14 sweep nearly missed a third statement of the coverage
    guarantee because the phrase spanned a line break.
    """
    flat = re.sub(r"\s+", " ", read_text(SPEC))
    out = []
    for name, (pattern, retired_in, issue, instead) in sorted(RETIRED_CLAIMS.items()):
        if re.search(pattern, flat):
            out.append(
                f"retired claim '{name}' is still in the specification "
                f"(retired in {retired_in}, #{issue}) -- {instead}"
            )
    if not out:
        print(f"  retired claims: {len(RETIRED_CLAIMS)} -- none present")
    return out


def spec_tables() -> tuple[dict[str, str], dict[str, str]]:
    """Return every option id and block type the specification defines.

    Parsed from the two tables by their header rows, not by row shape: the flags
    enum table has rows of the same shape (an id, then a name in backticks) and a
    looser match silently swallows them.
    """
    opts, blocks = {}, {}
    table, header = None, None
    with open(SPEC, encoding="utf-8") as fh:
        spec_lines = fh.readlines()
    for line in spec_lines:
        if line.startswith("| Type | Name"):
            table, header = blocks, True
            continue
        if line.startswith("| Id       | Name"):
            table, header = opts, True
            continue
        if table is not None:
            m = re.match(r"^\| `?(0x[0-9A-F]{2,4})`? +\| ([^ |]+)", line)
            if m:
                table[m.group(1)] = m.group(2).strip("`")
                header = False
            elif not line.startswith("|"):
                table, header = None, None
            elif header and set(line.strip()) <= set("|- "):
                continue  # the ---- separator row
    return opts, blocks


class Corrupt(Exception):
    """A structural defect: the file cannot be walked as blocks."""


def check_file_header(raw: bytes, off: int, btype: int) -> None:
    """Check the first block is a File Header this version can read.

    One raise per rule, because each is a distinct entry in the reject tier.
    """
    if btype != 0x01:
        raise Corrupt("first block is not a File Header")
    magic, major, minor = struct.unpack_from("<IHH", raw, off + 8)
    if magic != MAGIC:
        raise Corrupt(f"bad magic 0x{magic:08X}")
    if major != MAJOR:
        raise Corrupt(f"version_major {major} not implemented")
    if major == 0 and minor != MINOR:
        raise Corrupt(f"version_minor {minor} not implemented (0.x)")


def walk(raw: bytes) -> Iterator[tuple[int, int, int]]:
    """Yield (offset, type, length) per block.

    Raises Corrupt on a structural defect, mirroring the reject tier in
    Conformance.
    """
    if len(raw) < 8:
        raise Corrupt("shorter than one frame")
    off = 0
    first = True
    while off < len(raw):
        if off + 8 > len(raw):
            raise Corrupt(f"truncated frame at 0x{off:04X}")
        btype, _res, length = struct.unpack_from("<HHI", raw, off)
        if length % 4:
            raise Corrupt(f"length {length} at 0x{off:04X} is not a multiple of 4")
        end = off + 8 + length
        if end > len(raw):
            raise Corrupt(f"block at 0x{off:04X} runs past end of file")
        if first:
            check_file_header(raw, off, btype)
            first = False
        if btype == 0x20:  # Record -- check payload_len fits its own block
            plen = struct.unpack_from("<I", raw, off + 8 + 24)[0]
            if 28 + plen > length:
                raise Corrupt(f"payload_len {plen} overruns block at 0x{off:04X}")
        yield off, btype, length
        off = end
    if off != len(raw):
        raise Corrupt("trailing bytes")


def chain_lines(d: str, n: str) -> list[dict]:
    """Read one chain file's JSONL projection."""
    text = read_text(os.path.join(d, f"{n}.jsonl"))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def check_chain_digests(d: str) -> list[str]:
    """Check every declared digest is the real SHA-256 of the file it names."""
    import hashlib

    real = {
        f"{n}.zpf": "sha256:" + hashlib.sha256(read_bytes(os.path.join(d, f"{n}.zpf"))).hexdigest()
        for n in ("raw", "decoded", "annotated")
    }
    out = []
    for n in ("decoded", "annotated"):
        for o in chain_lines(d, n):
            if o.get("type") == "source" and "digest" in o:
                want = real.get(o["uri"])
                if want is None:
                    out.append(f"chain/{n}: cites unknown file {o['uri']}")
                elif o["digest"] != want:
                    out.append(f"chain/{n}: digest for {o['uri']} is stale")
    return out


def chain_raw_extents(d: str) -> dict[int, int]:
    """Reconstruct raw.zpf's per-stream extents from seq_start - (isn + 1)."""
    import base64

    isn, ext = {}, {}
    for o in chain_lines(d, "raw"):
        if o.get("type") == "participant":
            isn[o["pid"]] = o["isn"]
        elif o.get("type") == "record":
            off = o["seq_start"] - (isn[o["sender_pid"]] + 1)
            end = off + len(base64.b64decode(o["payload"]))
            ext[o["sender_pid"]] = max(ext.get(o["sender_pid"], 0), end)
    return ext


def merge_ranges(rs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Coalesce sorted, possibly-touching ranges."""
    merged: list[tuple[int, int]] = []
    for a, b in sorted(rs):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def check_chain_coverage(d: str, ext: dict[int, int]) -> list[str]:
    """Confirm decoded.zpf accounts for every byte raw.zpf holds."""
    cov: dict[int, list[tuple[int, int]]] = {}
    for o in chain_lines(d, "decoded"):
        for s in o.get("spans", []):
            cov.setdefault(s["pid"], []).append((s["off_start"], s["off_end"]))
        if o.get("type") == "undecoded":
            cov.setdefault(o["pid"], []).append((o["off_start"], o["off_end"]))

    out = []
    for pid, want_end in sorted(ext.items()):
        merged = merge_ranges(cov.get(pid, []))
        if merged != [(0, want_end)]:
            out.append(f"chain: pid {pid} covered {merged}, raw stream is [0,{want_end})")
    return out


def check_chain() -> list[str]:
    """Verify the chain against itself.

    Its numbers must agree, or the fixture is worthless.
    """
    d = os.path.join(HERE, "chain")
    if not os.path.isdir(d):
        return ["chain/ missing"]
    ext = chain_raw_extents(d)
    out = check_chain_digests(d) + check_chain_coverage(d, ext)
    if not out:
        print(
            f"  chain: 3 files, digests match, coverage complete "
            f"({', '.join(f'pid {p} [0,{e})' for p, e in sorted(ext.items()))})"
        )
    return out


def tunnel_lines(d: str, n: str) -> list[dict]:
    """Read one tunnel file's JSONL projection."""
    text = read_text(os.path.join(d, f"{n}.jsonl"))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def tunnel_digests(d: str) -> list[str]:
    """Check each hop cites the real SHA-256 of the file before it."""
    import hashlib

    real = {
        f"{n}.zpf": "sha256:" + hashlib.sha256(read_bytes(os.path.join(d, f"{n}.zpf"))).hexdigest()
        for n in ("outer", "packets", "inner", "http")
    }
    out = []
    for n in ("packets", "inner", "http"):
        for o in tunnel_lines(d, n):
            if o.get("type") == "source" and "digest" in o:
                want = real.get(o["uri"])
                if want is None:
                    out.append(f"tunnel/{n}: cites unknown file {o['uri']}")
                elif o["digest"] != want:
                    out.append(f"tunnel/{n}: digest for {o['uri']} is stale")
    return out


def tunnel_covers(d: str, stage: str, sess: int, pid: int, want_end: int) -> list[str]:
    """Confirm one hop accounts for every offset of the input stream it reads.

    Accumulated across the WHOLE file rather than per output session: under
    fan-out one input stream feeds several output sessions and no single one
    covers it, which is the property inner.zpf exists to show.
    """
    cov: list[tuple[int, int]] = []
    for o in tunnel_lines(d, stage):
        for s in o.get("spans", []):
            if (s["session_id"], s["pid"]) == (sess, pid):
                cov.append((s["off_start"], s["off_end"]))
        if o.get("type") == "undecoded" and (o["session_id"], o["pid"]) == (sess, pid):
            cov.append((o["off_start"], o["off_end"]))
    merged = merge_ranges(cov)
    if merged != [(0, want_end)]:
        return [f"tunnel/{stage}: covers {merged} of session {sess} pid {pid}, want [0,{want_end})"]
    return []


def tunnel_inner_extent(d: str, sess: int, pid: int) -> int:
    """Reconstruct one inner stream's extent from seq_start - (isn + 1).

    The same arithmetic chain_raw_extents() does, one level further down: it is
    what proves inner.zpf's hole is really in the sequence numbers rather than
    merely asserted in a comment.
    """
    import base64

    isn, end = None, 0
    for o in tunnel_lines(d, "inner"):
        if o.get("type") == "participant" and (o["session_id"], o["pid"]) == (sess, pid):
            isn = o["isn"]
        elif o.get("type") == "record" and (o["session_id"], o["sender_pid"]) == (sess, pid):
            off = o["seq_start"] - (isn + 1)
            end = max(end, off + len(base64.b64decode(o["payload"])))
    return end


def check_tunnel() -> list[str]:
    """Verify the four-file tunnel walks: digests, coverage, and the inner hole.

    Specific to this fixture, as check_chain() is. A generic per-hop walker
    would be most of a conformant reader, which the module docstring rules out.
    """
    d = os.path.join(HERE, "tunnel")
    if not os.path.isdir(d):
        return ["tunnel/ missing"]

    out = tunnel_digests(d)
    # outer -> packets: the whole capture stream, framing included.
    out += tunnel_covers(d, "packets", 1, 0, 320)
    # packets -> inner: the union across BOTH output sessions, not either alone.
    out += tunnel_covers(d, "inner", 5, 0, 150)
    # inner -> http: flow A only; session 11 is not an input to that hop.
    out += tunnel_covers(d, "http", 10, 0, 110)

    # The inner stream's own extent, re-derived from the sequence numbers, must
    # agree with what the next hop declares it to be.
    derived = tunnel_inner_extent(d, 10, 0)
    declared = [
        e["extent"]
        for o in tunnel_lines(d, "http")
        if o.get("type") == "session_end"
        for e in o.get("input_extents", [])
        if (e["session_id"], e["pid"]) == (10, 0)
    ]
    if declared != [derived]:
        out.append(
            f"tunnel: inner flow A is [0,{derived}) by seq_start - (isn + 1), "
            f"but http declares {declared}"
        )

    if not out:
        print(
            f"  tunnel: 4 files, digests match, coverage complete "
            f"(outer [0,320) -> packets [0,150) fan-out -> inner flow A [0,{derived}))"
        )
    return out


def check_capability_coverage(manifest: dict) -> list[str]:
    """Every capability the format defines must be exercised by some vector.

    Fan-out shipped in 0.13 with nothing exercising it, and the gap survived a
    release. This is the check that would have caught it -- and it hard-fails
    rather than warning, because an advisory line is exactly what gets scrolled
    past. A capability with no vector should stop the build until either a vector
    exists or the capability does not.

    Syntax comes from the specification, so a new option or block cannot ship
    uncovered. Rules are declared in RULES, since a permission has no id to
    derive. Neither half inspects a file: what a vector exercises is recorded by
    build.py, which built the bytes.
    """
    opts, blocks = spec_tables()
    if not opts or not blocks:
        return ["capability coverage: could not parse the specification's tables"]

    used_o, used_b = set(), set()
    for v in manifest["vectors"]:
        used_o.update(v.get("options", ()))
        used_b.update(v.get("blocks", ()))

    out = []
    for oid, name in sorted(opts.items()):
        if oid not in used_o:
            out.append(f"option {oid} ({name}) is in the registry but no vector exercises it")
    for btype, name in sorted(blocks.items()):
        if btype not in used_b:
            out.append(f"block {btype} ({name}) is defined but no vector exercises it")
    for rule, (what, vector) in sorted(RULES.items()):
        if vector is None:
            out.append(f"rule '{rule}' has no vector -- {what}")
        elif not any(x["name"] == vector for x in manifest["vectors"]):
            out.append(f"rule '{rule}' names vector '{vector}', which does not exist")

    if not out:
        print(
            f"  capabilities: {len(opts)} options, {len(blocks)} blocks, "
            f"{len(RULES)} rules -- all exercised"
        )
    return out


def check_violations(v: dict) -> list[str]:
    """Check one vector's declared violation count against its declared tier.

    Applies to the chain fixture too, so a fixture cannot dodge it by being
    shaped differently.
    """
    name, tier = v["name"], v["tier"]
    if "violations" not in v:
        return [f"{name}: no declared violation count"]
    advisory = bool(v.get("advisory"))
    if advisory and tier != "accept":
        return [
            f"{name}: declares advisory on tier '{tier}'. An advisory "
            f"violation is one a reader reports and then accepts; on a tier "
            f"where the reader may discard something it says nothing."
        ]
    expected = ADVISORY_VIOLATIONS if advisory else VIOLATIONS_BY_TIER[tier]
    if v["violations"] != expected:
        return [
            f"{name}: declares {v['violations']} violation(s) but tier "
            f"'{tier}'{' (advisory)' if advisory else ''} requires exactly "
            f"{expected}. A "
            f"negative vector carries exactly one violation -- with two it "
            f"tests whichever a reader detects first. Split it, or fix the "
            f"vector so it carries only the one it was built for."
        ]
    return []


def check_jsonl(label: str, path: str, block_count: int) -> list[str]:
    """Check a projection parses and has one line per block."""
    jl = [x for x in read_text(path).splitlines() if x.strip()]
    out = []
    for i, line in enumerate(jl, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            out.append(f"{label}:{i}: invalid JSON -- {e}")
    if len(jl) != block_count:
        out.append(f"{label}: {block_count} blocks but {len(jl)} JSONL lines")
    return out


def fixture_files(v: dict) -> list[tuple[str, str]]:
    """Yield (label, .zpf path) for every file in a fixture.

    A single-file vector lives at <name>/<name>.zpf; a multi-file fixture lists
    its members in the manifest. Both are walked identically -- before 0.14
    anything with a `files` key was skipped entirely, so a second multi-file
    fixture would have been checked by nothing at all.
    """
    name = v["name"]
    if "files" not in v:
        return [(name, os.path.join(HERE, name, f"{name}.zpf"))]
    return [
        (f"{name}/{fn}", os.path.join(HERE, name, fn)) for fn in v["files"] if fn.endswith(".zpf")
    ]


def check_one_file(label: str, path: str, tier: str, has_jsonl: bool) -> list[str]:
    """Walk one .zpf and check it behaves as its tier says."""
    out = []
    try:
        blocks = list(walk(read_bytes(path)))
        corrupt = None
    except Corrupt as e:
        blocks, corrupt = None, str(e)

    if tier == "reject":
        if corrupt is None:
            out.append(f"{label}: claims the reject tier but walks cleanly")
        else:
            print(f"  {label}: correctly rejected -- {corrupt}")
        return out

    if corrupt is not None:
        out.append(f"{label}: must be well-framed but {corrupt}")
        return out
    if has_jsonl:
        out += check_jsonl(label, path[: -len(".zpf")] + ".jsonl", len(blocks))
    print(f"  {label}: {len(blocks)} blocks, well-framed")
    return out


def check_vector(v: dict) -> list[str]:
    """Check a fixture's bytes against the tier and size the manifest declares.

    Handles single-file vectors and multi-file fixtures alike; `bytes` is the
    total across the fixture, so it is checked once rather than per file.
    """
    name, tier = v["name"], v["tier"]
    files = fixture_files(v)
    out = []

    total = sum(len(read_bytes(p)) for _, p in files)
    if total != v["bytes"]:
        out.append(f"{name}: manifest says {v['bytes']} bytes, files total {total}")

    for label, path in files:
        out += check_one_file(label, path, tier, v["has_jsonl"])
    return out


def main() -> int:
    """Verify the vector tree, and return a process exit status."""
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "build.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode:
        print("FAIL: committed vectors do not match build.py")
        return 1

    manifest = json.loads(read_text(os.path.join(HERE, "manifest.json")))
    failures = []
    for v in manifest["vectors"]:
        failures += check_violations(v)
        failures += check_vector(v)

    failures += check_chain()
    failures += check_tunnel()
    failures += check_capability_coverage(manifest)
    failures += check_jsonl_keys()
    failures += check_retired_claims()

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(manifest['vectors'])} vectors consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
