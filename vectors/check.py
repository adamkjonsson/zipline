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
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAGIC = 0x5A495046
MAJOR, MINOR = 0, 14

# How many violations each tier must declare. A negative vector carrying two
# silently tests whichever the reader detects first, and passes implementations
# that never exercised the rule it was built for -- isolate-coverage-gap did
# exactly that through 0.12. This compares the *declared* count against the
# *declared* tier; it never inspects a file to count them, because a checker that
# ruled on semantics would become a second normative authority.
VIOLATIONS_BY_TIER = {'accept': 0, 'reject': 1, 'isolate': 1}


class Corrupt(Exception):
    pass


def walk(raw):
    """Yield (offset, type, length) per block, raising Corrupt on a
    structural defect. Mirrors the reject tier in Conformance."""
    if len(raw) < 8:
        raise Corrupt("shorter than one frame")
    off = 0
    first = True
    while off < len(raw):
        if off + 8 > len(raw):
            raise Corrupt(f"truncated frame at 0x{off:04X}")
        btype, _res, length = struct.unpack_from('<HHI', raw, off)
        if length % 4:
            raise Corrupt(f"length {length} at 0x{off:04X} is not a multiple of 4")
        end = off + 8 + length
        if end > len(raw):
            raise Corrupt(f"block at 0x{off:04X} runs past end of file")
        if first:
            if btype != 0x01:
                raise Corrupt("first block is not a File Header")
            magic, major, minor = struct.unpack_from('<IHH', raw, off + 8)
            if magic != MAGIC:
                raise Corrupt(f"bad magic 0x{magic:08X}")
            if major != MAJOR:
                raise Corrupt(f"version_major {major} not implemented")
            if major == 0 and minor != MINOR:
                raise Corrupt(f"version_minor {minor} not implemented (0.x)")
            first = False
        if btype == 0x20:  # Record -- check payload_len fits its own block
            plen = struct.unpack_from('<I', raw, off + 8 + 24)[0]
            if 28 + plen > length:
                raise Corrupt(f"payload_len {plen} overruns block at 0x{off:04X}")
        yield off, btype, length
        off = end
    if off != len(raw):
        raise Corrupt("trailing bytes")


def check_chain():
    """The chain's numbers must agree, or the fixture is worthless."""
    import base64, hashlib
    d = os.path.join(HERE, 'chain')
    if not os.path.isdir(d):
        return ["chain/ missing"]
    out = []
    real = {f"{n}.zpf": "sha256:" + hashlib.sha256(
        open(os.path.join(d, f"{n}.zpf"), 'rb').read()).hexdigest()
        for n in ('raw', 'decoded', 'annotated')}

    def lines(n):
        return [json.loads(l) for l in open(os.path.join(d, f"{n}.jsonl"))
                if l.strip()]

    for n in ('decoded', 'annotated'):
        for o in lines(n):
            if o.get('type') == 'source' and 'digest' in o:
                want = real.get(o['uri'])
                if want is None:
                    out.append(f"chain/{n}: cites unknown file {o['uri']}")
                elif o['digest'] != want:
                    out.append(f"chain/{n}: digest for {o['uri']} is stale")

    # Reconstruct raw.zpf's stream extents from seq_start - (isn + 1), then
    # confirm decoded.zpf accounts for every byte of them.
    isn, ext = {}, {}
    for o in lines('raw'):
        if o.get('type') == 'participant':
            isn[o['pid']] = o['isn']
        elif o.get('type') == 'record':
            off = o['seq_start'] - (isn[o['sender_pid']] + 1)
            end = off + len(base64.b64decode(o['payload']))
            ext[o['sender_pid']] = max(ext.get(o['sender_pid'], 0), end)

    cov = {}
    for o in lines('decoded'):
        for s in o.get('spans', []):
            cov.setdefault(s['pid'], []).append((s['off_start'], s['off_end']))
        if o.get('type') == 'undecoded':
            cov.setdefault(o['pid'], []).append((o['off_start'], o['off_end']))

    for pid, want_end in sorted(ext.items()):
        rs = sorted(cov.get(pid, []))
        merged = []
        for a, b in rs:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        if merged != [(0, want_end)]:
            out.append(f"chain: pid {pid} covered {merged}, "
                       f"raw stream is [0,{want_end})")
    if not out:
        print(f"  chain: 3 files, digests match, coverage complete "
              f"({', '.join(f'pid {p} [0,{e})' for p, e in sorted(ext.items()))})")
    return out


def main():
    r = subprocess.run([sys.executable, os.path.join(HERE, 'build.py'), '--check'],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode:
        print("FAIL: committed vectors do not match build.py")
        return 1

    manifest = json.load(open(os.path.join(HERE, 'manifest.json')))
    failures = []
    for v in manifest['vectors']:
        name, tier = v['name'], v['tier']

        # Every vector declares a violation count, and it must agree with its
        # tier. Checked before anything else, and for the chain too, so a
        # fixture cannot dodge it by being shaped differently.
        if 'violations' not in v:
            failures.append(f"{name}: no declared violation count")
        elif v['violations'] != VIOLATIONS_BY_TIER[tier]:
            failures.append(
                f"{name}: declares {v['violations']} violation(s) but tier "
                f"'{tier}' requires exactly {VIOLATIONS_BY_TIER[tier]}. A "
                f"negative vector carries exactly one violation -- with two it "
                f"tests whichever a reader detects first. Split it, or fix the "
                f"vector so it carries only the one it was built for.")

        if 'files' in v:          # the chain fixture; check_chain handles it
            continue
        raw = open(os.path.join(HERE, name, f"{name}.zpf"), 'rb').read()
        if len(raw) != v['bytes']:
            failures.append(f"{name}: manifest says {v['bytes']} bytes, file has {len(raw)}")

        try:
            blocks = list(walk(raw))
            corrupt = None
        except Corrupt as e:
            blocks, corrupt = None, str(e)

        if tier == 'reject':
            if corrupt is None:
                failures.append(f"{name}: claims the reject tier but walks cleanly")
            else:
                print(f"  {name}: correctly rejected -- {corrupt}")
        else:
            if corrupt is not None:
                failures.append(f"{name}: must be well-framed but {corrupt}")
                continue
            if v['has_jsonl']:
                path = os.path.join(HERE, name, f"{name}.jsonl")
                lines = [l for l in open(path).read().splitlines() if l.strip()]
                for i, l in enumerate(lines, 1):
                    try:
                        json.loads(l)
                    except json.JSONDecodeError as e:
                        failures.append(f"{name}:{i}: invalid JSON -- {e}")
                if len(lines) != len(blocks):
                    failures.append(
                        f"{name}: {len(blocks)} blocks but {len(lines)} JSONL lines")
            print(f"  {name}: {len(blocks)} blocks, well-framed")

    failures += check_chain()

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(manifest['vectors'])} vectors consistent")
    return 0


if __name__ == '__main__':
    sys.exit(main())
