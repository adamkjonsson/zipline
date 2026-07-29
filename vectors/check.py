#!/usr/bin/env python3
"""Check the vectors are internally consistent and behave as the manifest says.

This is deliberately NOT a conformant reader. It knows only the frame -- type,
reserved, length -- plus the File Header body, because that is all it takes to
tell a structurally-corrupt file from a well-framed one. Semantic expectations
(the isolate tier) are stated in the manifest for a human and for an
implementation's test harness; nothing here adjudicates them, because a checker
that ruled on semantics would become a second normative authority, which is
exactly what the README says a vector must never be.

What it does verify:
  * every committed file matches what build.py produces (no drift)
  * accept/isolate vectors are well-framed: block walk lands exactly on EOF,
    every length is a multiple of 4, magic and version are what this version
    defines
  * reject vectors actually contain the structural defect they claim
  * each accept vector's .jsonl parses and has one line per block

Usage:  python3 check.py
"""

import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAGIC = 0x5A495046
MAJOR, MINOR = 0, 10


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

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(manifest['vectors'])} vectors consistent")
    return 0


if __name__ == '__main__':
    sys.exit(main())
