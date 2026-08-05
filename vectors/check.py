#!/usr/bin/env python3
"""Check the vectors are internally consistent and behave as the manifest says.

This is deliberately NOT a conformant reader. It knows only the frame -- type,
reserved, length -- plus the File Header body, because that is all it takes to
tell a structurally-corrupt file from a well-framed one. Semantic expectations
(the isolate tier) are stated in the manifest for a human and for an
implementation's test harness; nothing here adjudicates them, because a checker
that ruled on semantics would become a second normative authority, which is
exactly what the README says a vector must never be.

The one exception is the `chain` fixture, where a little arithmetic is
unavoidable: its entire value is that the digests and offsets agree, and a
fixture whose numbers have silently drifted is worse than none. Those checks
verify the fixture against itself, not the specification against anything.

What it does verify:
  * every committed file matches what build.py produces (no drift)
  * every vector's declared violation count agrees with its declared tier --
    accept 0, reject 1, isolate 1. The count is declared, never computed from
    the file; see VIOLATIONS_BY_TIER
  * every capability the format defines is exercised by some vector: option ids
    and block types parsed from the specification's own tables, plus the rules
    declared in RULES. What each vector exercises is recorded by build.py, which
    built the bytes -- nothing here parses a block body
  * accept/isolate vectors are well-framed: block walk lands exactly on EOF,
    every length is a multiple of 4, magic and version are what this version
    defines
  * reject vectors actually contain the structural defect they claim
  * each accept vector's .jsonl parses and has one line per block
  * for the chain: every declared digest is the real SHA-256 of the sibling
    file it names, and decoded.zpf's spans plus Undecoded blocks cover exactly
    the streams raw.zpf actually contains

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
MAJOR, MINOR = 0, 14

# How many violations each tier must declare. A negative vector carrying two
# silently tests whichever the reader detects first, and passes implementations
# that never exercised the rule it was built for -- isolate-coverage-gap did
# exactly that through 0.12. This compares the *declared* count against the
# *declared* tier; it never inspects a file to count them, because a checker that
# ruled on semantics would become a second normative authority.
VIOLATIONS_BY_TIER = {"accept": 0, "reject": 1, "isolate": 1}

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
    "spans-correspondence": (
        "a decoder may transform; spans name what a unit corresponds to",
        "chain",
    ),
    "session-fan-out": (
        "a stage's output sessions need not mirror its input's",
        None,
    ),  # tracked by issue #66
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
}


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
    if v["violations"] != VIOLATIONS_BY_TIER[tier]:
        return [
            f"{name}: declares {v['violations']} violation(s) but tier "
            f"'{tier}' requires exactly {VIOLATIONS_BY_TIER[tier]}. A "
            f"negative vector carries exactly one violation -- with two it "
            f"tests whichever a reader detects first. Split it, or fix the "
            f"vector so it carries only the one it was built for."
        ]
    return []


def check_jsonl(v: dict, block_count: int) -> list[str]:
    """Check an accept vector's projection parses and has one line per block."""
    name = v["name"]
    path = os.path.join(HERE, name, f"{name}.jsonl")
    jl = [x for x in read_text(path).splitlines() if x.strip()]
    out = []
    for i, line in enumerate(jl, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            out.append(f"{name}:{i}: invalid JSON -- {e}")
    if len(jl) != block_count:
        out.append(f"{name}: {block_count} blocks but {len(jl)} JSONL lines")
    return out


def check_vector(v: dict) -> list[str]:
    """Check one vector's bytes against the tier and size the manifest declares."""
    name, tier = v["name"], v["tier"]
    out = []
    raw = read_bytes(os.path.join(HERE, name, f"{name}.zpf"))
    if len(raw) != v["bytes"]:
        out.append(f"{name}: manifest says {v['bytes']} bytes, file has {len(raw)}")

    try:
        blocks = list(walk(raw))
        corrupt = None
    except Corrupt as e:
        blocks, corrupt = None, str(e)

    if tier == "reject":
        if corrupt is None:
            out.append(f"{name}: claims the reject tier but walks cleanly")
        else:
            print(f"  {name}: correctly rejected -- {corrupt}")
        return out

    if corrupt is not None:
        out.append(f"{name}: must be well-framed but {corrupt}")
        return out
    if v["has_jsonl"]:
        out += check_jsonl(v, len(blocks))
    print(f"  {name}: {len(blocks)} blocks, well-framed")
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
        if "files" in v:  # the chain fixture; check_chain handles it
            continue
        failures += check_vector(v)

    failures += check_chain()
    failures += check_capability_coverage(manifest)

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(manifest['vectors'])} vectors consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
