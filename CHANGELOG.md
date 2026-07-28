# Changelog

All notable changes to the **Zipline Payload Format** specification are
documented in this file. It records changes to the *standard*, not to any
implementation of it.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
with two adaptations noted under [Conventions](#conventions).

## Conventions

**Versions are `major.minor`**, matching the `version_major` / `version_minor`
fields in the [File Header](docs/payload-format.md#file-header-0x01) — there is
no patch component, because a version that is not on the wire cannot be
communicated to a reader. The meanings are the format's own:

- **major** — may change the block frame, a block body, or the meaning of an
  existing field. A reader MUST reject a `version_major` it does not implement.
- **minor** — adds blocks and options that old readers safely skip, pins down
  behaviour an earlier version left undefined, and may relax writer
  restrictions. Every file valid under `1.n` stays valid under `1.n+1`.

**Change categories.** Keep a Changelog's six types, plus one:

- **Clarified** — behaviour the previous version left undefined or stated
  ambiguously, now pinned down. Distinguished from *Changed* because no
  conformant file and no correct reader becomes wrong: only under-specified
  cases are affected. Implementers should read these first — they are where two
  independent implementations most easily disagree.

Each entry names the issue it resolves. Entries state the delta only; the
specification itself remains the normative text.

**Reading across versions.** A `1.0` reader meeting a `1.1` file skips what it
does not recognise and reads the rest — with one exception class, flagged
per-entry as **[strict-reader]**: a relaxation that permits a file `1.0`
forbade may be refused by a `1.0` reader that enforces the old restriction
(a conformant choice under the format's error-handling tiers). Writers needing
maximum reach should avoid those constructs until readers have caught up.

---

## [Unreleased] — 1.1-beta

**In development.** Version 1.0 remains final and unchanged.

Version 1.1 collects clarifications and additions arising from the first
implementation of the standard (issues #8–#16). The analysis behind it, the
open decisions, and the phased plan are in
[docs/implementation-feedback-analysis.md](docs/implementation-feedback-analysis.md).
Entries appear here as each change lands, so this section is the precise
1.0 → 1.1 delta for implementers.

No change in 1.1 alters the **binary** container: not the block frame, not an
existing block body, not an existing option id, and not the meaning of any field
a 1.0 file already carries. The JSONL projection has one deprecated key, listed
below and still accepted on read.

### Clarified

- **Timestamps are not an ordering invariant** (#11, #14). A reader MUST NOT
  reject a file or discard a session because stored timestamps run backwards,
  and MUST NOT re-sort a `SEQUENCED` session by timestamp — its stored order is
  authoritative. Timestamps order records in exactly one place: as the tie-break
  between causally concurrent records during a merge. 1.0 demonstrated a
  legitimate inversion in a worked example but never stated the reader's side of
  it. *A reader that validates monotonic timestamps must drop that check.*
- **The single-trustworthy-clock precondition for `SEQUENCED` binds hint-less
  sessions only** (#11). A session carrying TCP `seq`/`ack` may be sequenced
  however badly its capture clocks disagree; sequencing means "stored in a valid
  causal order", never "sorted by timestamp". 1.0 said this, but rested the
  scope on a single adjective and was misread.
- **Reserved bits of the Record `flags` field are ignored on read** (#16), now
  stated as it already was for the File Header and Session `flags` fields. The
  global reserved-fields rule always required this; only the wording differed.

### Changed

- **JSONL: the File Header rate is the key `tick_hz`, carrying a number** (#10)
  — previously the alias `time_units`. `tick_hz` is the binary field's own name,
  so the projection's general naming rule now covers it and the alias table has
  one fewer exception. *Writers: emit `tick_hz`.*

### Deprecated

- **JSONL key `time_units`** (#10), superseded by `tick_hz`. A reader MUST still
  accept it carrying a number and treat it as `tick_hz`; a writer MUST NOT emit
  it. Removal lands in a later version. *Readers: keep accepting it for now.*

### Fixed

- **Four JSONL examples wrote `"time_units":"us"`** (#10) — a unit label, where
  1.0's normative text defines the value as a rate in ticks per second and
  permits only a number or a decimal string. The examples were non-conformant
  against their own specification, so anything written by copying them was too.
  Corrected to `"tick_hz":1000000`.

---

## [1.0] — 2026-07-09

The initial specification. Final and stable for implementation and interchange.

### Added

- **Container.** Length-prefixed typed blocks with an 8-byte frame, little-endian
  throughout, 4-byte aligned; TLV options (`id: u16, len: u16, value`) with
  skip-what-you-don't-know rules for both unknown block types and unknown option
  ids.
- **Model.** Sessions holding *N* participants (not two sides), carrying directed
  records that name a sender and no recipient — covering TCP (`N = 2`), chat
  rooms (`N > 2`) and one-way UDP (`N = 1`) in one shape.
- **Blocks.** File Header, Source Descriptor, Decoder Descriptor, Session
  Descriptor, Participant Descriptor, Session End, Record, Undecoded,
  Name/Identity Resolution, End, and a PEN-namespaced Custom block.
- **Declare-on-first-use.** A descriptor need only precede its first reference,
  making the format append-only and streamable; Session End is its mirror,
  bounding reader state.
- **Causal ordering.** Cross-participant order derived from absolute TCP
  `seq_start`/`ack` under RFC 1982 serial-number arithmetic, so separately
  captured directions with skewed clocks order correctly; specified as a
  streaming k-way merge, with timestamps used only to break genuine ties.
- **Precomputed order.** Per-session `SEQUENCED` flag and file-level
  `SINGLE_CLOCK` flag, letting a producer commit a resolved order once so
  readers skip the merge.
- **Layering.** Decoding as a file → file transform (`raw.zpf → decoded.zpf`)
  rather than an in-record layer, with logical 0-based stream offsets, `spans`
  provenance, `digest` dependency edges, and the coverage guarantee enforced by
  Undecoded blocks.
- **JSON-Lines projection.** A semantically lossless one-object-per-line face
  defined by one naming rule plus a short list of exceptions.
- **Conformance.** Two-tier error handling (structural corruption → reject;
  semantic violation → MAY isolate), truncation and completeness rules, and a
  byte-annotated worked example of a complete 196-byte raw file.

[Unreleased]: https://github.com/adamkjonsson/zipline/compare/v1.0...HEAD
[1.0]: https://github.com/adamkjonsson/zipline/releases/tag/v1.0
