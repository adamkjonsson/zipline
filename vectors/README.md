# Conformance vectors

Small `.zpf` files, each with its expected JSON-Lines projection or its expected
failure, for testing an implementation of the
[Zipline Payload Format](../docs/zipline-payload-format.md) `0.10`.

Run `python3 check.py` to verify the tree is self-consistent.
Run `python3 build.py` to regenerate it.

## Ground rules

These four decide whether the vectors are worth anything, so they come first.

**1. They are hand-built from the specification, never dumped from an
implementation.** [`build.py`](build.py) spells out every block field by field
from the normative text. It is not a reader or a writer for the format. The
point of a vector is to catch an implementation diverging from the specification
— and a vector generated *by* that implementation cannot, because it encodes
whatever the implementation already gets wrong. The `time_units` defect that
prompted this work would have been captured in a vector and blessed.

*Independent evidence that the builder is right:* `raw-minimal` is byte-for-byte
identical to the 196-byte worked example in the specification, which was written
by hand years apart from this code. That exercises the frame, TLV framing,
padding, and every body layout it touches.

**2. They are subordinate to the specification, not a second source of truth.**
If a vector and the normative text disagree, **the vector is wrong** and gets
fixed. Anything else recreates in a new form the exact failure these exist to
prevent — an implementer copying an artifact instead of reading the text.

That said, a disagreement is *investigated* before it is dismissed. A vector that
contradicts the text usually means the text is ambiguous, which is the second
thing vectors are for. One such ambiguity was found while writing these: the rule
said a repeatable option renders as a JSON array, while every example rendered a
single `endpoint` as a scalar string. That is now settled — always an array.

**3. The JSONL side is compared semantically, not byte-for-byte.** The projection
is *semantically* lossless, so a converter is free to choose key order within a
line, and number-versus-decimal-string encodings for 64-bit fields. But **line
order is significant** — declare-on-first-use and stored record order both carry
meaning.

So the comparison is: same number of lines, in order; each line parsed and
compared as an object; the documented encoding equivalences normalised first. A
harness that diffs the raw text will report false failures on its first run.

**4. Negative vectors matter more than positive ones.** Valid-file/expected-
projection pairs are the easy half. The format has a two-tier error model, and
the tiers are where implementations differ:

| Tier | Meaning |
|------|---------|
| `accept` | A conformant file. The `.jsonl` is the expected projection. |
| `reject` | Structurally corrupt. A reader MUST reject the whole file. |
| `isolate` | Well-framed but semantically invalid. A reader MAY reject the file *or* discard the smallest unit it can soundly isolate — and MUST NOT silently repair, guess, or drop without a diagnostic. |

A reader that *rejects* an `isolate` vector is as wrong as one that accepts it
silently. A reader that treats an unknown block type as corruption fails the
extension contract outright — see the `escape-*` vectors, which are all `accept`.

## Layout

Each vector is a directory:

```
<name>/<name>.zpf     the file under test
<name>/<name>.hex     annotated hex dump, generated from the same description
<name>/<name>.jsonl   expected projection (accept vectors only)
```

The `.hex` dump exists so a change to a vector is reviewable in a diff — a raw
`.zpf` is an opaque blob. It is generated, never edited, so it cannot drift from
the bytes. [`manifest.json`](manifest.json) is the machine-readable index: name,
tier, size, the specification section each comes from, and what a reader must do.

## The vectors

### Baseline

| Vector | What it exercises |
|--------|-------------------|
| `raw-minimal` | The whole container in 196 bytes. Identical to the specification's worked example. |
| `decoded-basic` | A decode stage: `spans` provenance, `content_type`, an Undecoded tail, an End block. |
| `passthrough-transport` | A pass-through preserving a transport layer: `origin`, byte-run records, `SEQUENCED`. |

### The four escapes

All `accept`. These are the forward-compatibility contract, and the place a
naive implementation most often fails by treating extension as corruption.

| Vector | What it exercises |
|--------|-------------------|
| `escape-unknown-block` | An undefined block type — skipped by `length`, projected as a hex type plus base64 `content`. |
| `escape-unknown-option` | An unregistered option id — skipped by `len`, retained in the generic `options` array. |
| `escape-unknown-enum` | An undefined `tcp_role`. Advisory, so it renders as the raw number. |
| `escape-reserved-flag-bit` | A set reserved bit in a record's `flags` — ignored semantically, preserved as a hex token. |

### `0.10` constructs

| Vector | What it exercises |
|--------|-------------------|
| `annotator-decoded` | A pass-through preserving a **decoded** layer — the construct `0.9` could not express. Records keep `decoder_id` and carry no `spans`; the inherited Undecoded block forces the grandparent Source to be declared. |
| `undecoded-skipped` | `reason = skipped` for a deliberately-declined region (a BOM). |
| `undecoded-reason-class` | A non-canonical `reason` carrying the required `reason_class`. |
| `sequenced-basis` | A hint-less `SEQUENCED` session with its mandatory `sequenced_basis`. |
| `reordered-decoded` | A stage that reorders decoded records without decoding them — a decode stage, since stored order defines the offsets. **Its `spans` run downward against stored order**, which a reader assuming they ascend will fail. |

### Reject tier

| Vector | Defect |
|--------|--------|
| `reject-bad-magic` | Byte-swapped magic. |
| `reject-unknown-major` | `version_major` this reader does not implement. |
| `reject-unknown-minor` | `version_minor` 11 while major is 0. **The vector that distinguishes a `0.x`-aware reader from one assuming minors are always skippable.** |
| `reject-length-misaligned` | A block `length` that is not a multiple of 4. |
| `reject-payload-len-overrun` | `payload_len` running past its own block. |

### Isolate tier

| Vector | Violation |
|--------|-----------|
| `isolate-undeclared-session` | A record naming a session that was never declared. |
| `isolate-duplicate-id` | A `source_id` declared twice. |
| `isolate-coverage-gap` | A decode stage leaving an input range neither covered by `spans` nor marked Undecoded. |
| `isolate-unknown-source-kind` | An undefined Source `kind` — load-bearing, unlike `tcp_role`, because it decides how span offsets are read. |

## Coverage this does not have

Stated so nobody mistakes the suite for complete:

- **No multi-file provenance chains** — every vector is a single file, so the
  recovery walk is untested, along with its two distinct failure modes (*no bytes
  exist* versus *bytes unavailable*) and the two-hop resolution a decoded-layer
  pass-through requires. This is the **top candidate for the next round**: it
  needs a consistent set of three files whose offsets and digests actually agree,
  which is more than a vector and closer to a small fixture.
- No causal-merge vectors: no skewed two-file capture, no tie-break case.
- No truncation vectors, which need a file that ends mid-block.
- No tunnelled `endpoint` list, no `spans` chunked across several occurrences,
  no `Custom` block, no Session End.
- Payloads are short and ASCII; nothing exercises the 64-bit fields near 2⁵³
  where the decimal-string encoding becomes mandatory.
