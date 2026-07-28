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
  A bit nonetheless set is *preserved* through a round-trip without being
  interpreted (#9) — the same split between retaining and interpreting that 1.0
  already applied to unknown option ids.
- **Unknown Source `kind` values are an isolatable semantic condition** (#9). A
  reader that cannot classify a Source cannot interpret any record or span
  referencing it — `kind` selects whether span offsets are capture-file byte
  offsets or logical stream offsets — so it MAY reject or discard that Source
  and its dependents, and MUST NOT guess. An unrecognised `tcp_role`, being
  advisory, just means "unknown". *`kind` is therefore not a free extension
  point: unlike a new option id, a new `kind` value will be isolated by existing
  readers.*
- **The `Undecoded` `reason` vocabulary has two recoverability classes** (#12):
  *bytes exist* (`undecodable`, `skipped`) and *hole* (`tcp-gap`, `truncated`).
  The class, not the word, is what a consumer acts on. 1.0 described the split
  in prose without naming it as the actionable part.
- **Each layer has its own offset space, and a decoded stream's is now defined**
  (#13): the concatenation of a participant's decoded record payloads in stored
  order, byte 0 being the first byte of the first such record. Undecoded regions
  contribute nothing, so unlike a transport stream's space it is *not*
  hole-inclusive. 1.0 defined offsets only for reassembled transport streams,
  which left `raw → tls-records → http` — a pipeline 1.0 explicitly invites —
  with no defined offset space for its second stage to reference.
  *Implementers doing multi-stage decode: this is the rule you were missing.*
- **`spans` versus `origin`, not `decoder_id`, discriminates what a file's own
  stage produced** (#13). A record carrying `spans` was built by this stage; a
  record without them, whose participant carries `origin`, was re-emitted from
  the input. `decoder_id` says which decoder's layer a record belongs to, and a
  pass-through carries inherited ones forward, so it no longer implies the
  decoder ran in this stage.
- **`version_minor` describes the file, not the rendering.** A converter
  projects any file into whichever version of the JSONL face it implements, so a
  1.0 file rendered by a 1.1 converter still reports `"zipline-payload/1"` while
  using 1.1 key spellings such as `tick_hz`. A writer stamps the *lowest* minor
  whose features the file actually uses. *Do not raise a file's version because
  your tool is newer — the field answers "what does this file contain".*
- **A one-participant or single-sender session is trivially sequenceable** (#14).
  It has no cross-participant order to get wrong, so it needs no basis at all.
  Vacuous under 1.0's rule, but worth stating, since the clock precondition
  appeared to bite exactly the one-way UDP case it cannot apply to.
- **An unrecognised `reason` has unknown recoverability** (#12). A consumer MUST
  NOT assume a class, and in particular MUST NOT treat the range as a hole —
  that would discard bytes that may exist. It follows the reference as for the
  bytes-exist class and reports the region empty only if nothing is found. 1.0
  made the vocabulary open but left this undefined.

### Added

- **Session option `sequenced_basis`** (`0x0053`, string) (#14) — what a
  `SEQUENCED` hint-less session's order rests on. Open vocabulary; suggested
  `clock`, `transport`, `protocol`, `external`. A producer SHOULD set it when
  sequencing a hint-less session. It is advisory: it does not make the order
  checkable, it tells a consumer how far to trust it. A reader MUST NOT reject a
  session for an unrecognised value, or for its absence. *Additive — a new
  option id, skippable by 1.0 readers.*
- **Canonical `Undecoded` reason `skipped`** (#12) — a region the decoder
  declined *on purpose*: data it does not care about, or data carrying no
  information, such as a byte-order mark, a padding or a reserved field. It sits
  in the bytes-exist class alongside `undecodable`, from which it differs in
  intent, not recoverability. It earns canonical status because the coverage
  guarantee leaves a decoder no honest third option — without it, a decoder
  ignoring a BOM must either stretch a record's `spans` over bytes it never
  interpreted or call them `undecodable`, asserting a failure that did not
  happen. It also keeps `undecodable` usable as a decoder-quality signal.
  *The vocabulary was already open, so this canonicalises an existing
  possibility rather than adding a capability; 1.0 readers treat `skipped` as
  any unrecognised reason.*
- **The JSONL projection's four escapes for unrecognised data** (#8, #9). The
  binary face has always had one universal rule for what a reader does not
  recognise — skip by length, retain, never error. The projection now mirrors
  it: every unrecognised element has a defined syntactic escape, a converter
  never invents meaning for one, and never silently drops one.

  | Unrecognised | JSONL form |
  |---|---|
  | option id | `options` array entry *(already in 1.0)* |
  | block type | `"type":"0x0042"` + base64 `"content"` |
  | enum value | the raw number |
  | flag bit | a hex token, e.g. `["psh","0x0020"]` |

  *Without this, the first block type or flag bit added by any future minor
  version would be silently lost by a JSONL round-trip, breaking the format's
  forward-compatibility promise on the JSONL side.* An unrecognised block's
  content is base64'd whole — body, options and padding together, since a
  converter cannot take apart a layout it does not know — which makes that one
  case byte-exact rather than merely semantically lossless.

### Changed

- **A pass-through transform preserves its input's *layer*, not just its bytes**
  (#13) **[strict-reader]**. 1.0 defined pass-through as carrying no
  `decoder_id`, which silently confined it to raw input and left any transform
  over a decoded file — an annotator, a filter, a re-merge — unexpressible. A
  pass-through now re-emits its input's records with bytes, logical offsets,
  `decoder_id`s, `content_type`s and Undecoded blocks unchanged, whatever layer
  the input was at, and re-declares the Decoder Descriptors they reference. The
  input's coverage guarantee then holds of the output without the output
  carrying any `spans`. Decoder Descriptors and Undecoded blocks are no longer
  restricted to decode-stage files. *A strict 1.0 reader may refuse a file that
  carries `decoder_id`s alongside `origin`; the [annotator example](docs/payload-format.md)
  shows the shape.*
- **A transform that only adds metadata is a pass-through** (#13), and its
  output is a *derived* file. Annotating a raw file therefore moves capture-level
  provenance (`link_type`, the capture's `uri`/`digest`) one level away, reached
  through the input Source rather than directly. Nothing is lost, but a consumer
  reading it must take the extra hop.
- **A pass-through carrying inherited Undecoded blocks MUST also declare the
  file those blocks name** (#13) and make their `source_id` resolve to it. This
  is the one case where a derived file names something other than its immediate
  input — because the statement being carried forward was always about that
  further-up file. Keeping the inherited ids and numbering the immediate input
  around them lets the blocks be copied verbatim.
- **`SEQUENCED` on a hint-less session requires a sound basis, not specifically
  a clock** (#14) **[strict-reader]**. A single trustworthy clock remains the
  common basis; ordering knowledge the format does not model — a server-assigned
  order, an application sequence number, an out-of-band record — now also
  qualifies, with `sequenced_basis` to say which. The producer owns the
  soundness; a reader could never verify the clock claim either. *This permits
  sequenced multi-party UDP and chat sessions that 1.0 forbade.*
- **A converter MUST NOT invent an option id** for an unrecognised JSON key on a
  known block (#9). There is no id to write, and guessing manufactures data.
  Such a key cannot arise from a binary source, only from hand-written or
  third-party JSONL; on the JSONL → binary path a converter MUST reject the line
  or drop the key, and MUST report it either way.
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
- **The example of an *unregistered* option id was `0x0091`** (#8), which is
  registered — it is `content_type`. Changed to `0x0200`, which is outside the
  registry.
- **The decoded-file example's two `record` lines omitted `source_id`** (#13), a
  mandatory body field that the projection's own rule says always projects. Every
  other example in the document includes it. Added.
- **Three cross-reference anchors never resolved** — `#session-descriptor-0x10`,
  `#participant-descriptor-0x11` and `#session-end-0x12` pointed at bold labels,
  which generate no anchor. Those five descriptor blocks are now `####`
  headings, matching every other block in the document.

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
