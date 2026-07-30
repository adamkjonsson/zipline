# Changelog

All notable changes to the **Zipline Payload Format** specification are
documented in this file. It records changes to the *standard*, not to any
implementation of it.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
with two adaptations noted under [Conventions](#conventions).

## Conventions

**Versions are `major.minor`**, matching the `version_major` / `version_minor`
fields in the [File Header](docs/zipline-payload-format.md#file-header-0x01) — there is
no patch component, because a version that is not on the wire cannot be
communicated to a reader. Both components are independent integers compared
componentwise: **`0.10` follows `0.9`** and is greater than it.

The compatibility rules have two regimes, and the format is currently in the
first:

- **`0.x` — a design in progress.** Any minor release may change anything,
  including in ways that break existing readers. A reader MUST reject a
  `version_minor` it does not implement. Nothing is guaranteed to survive a
  `0.x` bump, and no file written against one `0.x` version should be expected
  to read under another.
- **`1.0` and later.** A **minor** bump only adds blocks and options that old
  readers safely skip, and pins down behaviour an earlier version left
  undefined; every file valid under `1.n` stays valid under `1.n+1`, and readers
  do not consult the minor at all. A **major** bump may change the frame, a
  block body, or the meaning of an existing field, and a reader MUST reject a
  `version_major` it does not implement.

**Change categories.** Keep a Changelog's six types, plus one:

- **Clarified** — behaviour the previous version left undefined or stated
  ambiguously, now pinned down. Distinguished from *Changed* because no
  conformant file and no correct reader becomes wrong: only under-specified
  cases are affected. Implementers should read these first — they are where two
  independent implementations most easily disagree.

Entries state the delta only; the specification itself remains the normative
text.

**Reading across versions.** While in `0.x`, don't: a reader rejects a minor it
does not implement, and that is the intended behaviour. The entries below still
distinguish *Clarified* from *Changed*, because the distinction tells an
implementer whether their existing code was wrong or merely incomplete — but
neither is safe to skip within `0.x`.

---

## [0.10] — 2026-07-30

### A note on the numbering

A release was designated `1.0` on 2026-07-09, before any implementation of the
format existed. That was premature. The first implementation surfaced enough
genuine problems — and their resolutions broke enough existing behaviour — that
calling the result a minor bump would have been false: a conformant reader of the
July release silently isolates every record in some files this version permits.

So the July release is retroactively designated **`0.9`**, and this one is
**`0.10`**. The format stays in `0.x` until it has survived implementation, and
`1.0` is reserved for a version that has. More `0.x` rounds are expected.

This is not a compatibility-preserving release, and does not pretend to be:
`0.10` changes existing behaviour, removes a key, and renames a value. The
reasoning is in
[docs/implementation-review-response.md](docs/implementation-review-response.md);
the round of work that preceded it is in
[docs/implementation-feedback-analysis.md](docs/implementation-feedback-analysis.md).

### Clarified

- **Timestamps are not an ordering invariant**. A reader MUST NOT
  reject a file or discard a session because stored timestamps run backwards,
  and MUST NOT re-sort a `SEQUENCED` session by timestamp — its stored order is
  authoritative. Timestamps order records in exactly one place: as the tie-break
  between causally concurrent records during a merge. 0.9 demonstrated a
  legitimate inversion in a worked example but never stated the reader's side of
  it. *A reader that validates monotonic timestamps must drop that check.*
- **The single-trustworthy-clock precondition for `SEQUENCED` binds hint-less
  sessions only**. A session carrying TCP `seq`/`ack` may be sequenced
  however badly its capture clocks disagree; sequencing means "stored in a valid
  causal order", never "sorted by timestamp". 0.9 said this, but rested the
  scope on a single adjective and was misread.
- **Reserved bits of the Record `flags` field are ignored on read**, now
  stated as it already was for the File Header and Session `flags` fields. The
  global reserved-fields rule always required this; only the wording differed.
  A bit nonetheless set is *preserved* through a round-trip without being
  interpreted — the same split between retaining and interpreting that 0.9
  already applied to unknown option ids.
- **Unknown Source `kind` values are an isolatable semantic condition**. A
  reader that cannot classify a Source cannot interpret any record or span
  referencing it — `kind` selects whether span offsets are capture-file byte
  offsets or logical stream offsets — so it MAY reject or discard that Source
  and its dependents, and MUST NOT guess. An unrecognised `tcp_role`, being
  advisory, just means "unknown". *`kind` is therefore not a free extension
  point: unlike a new option id, a new `kind` value will be isolated by existing
  readers.*
- **The `Undecoded` `reason` vocabulary has two recoverability classes**:
  *bytes exist* (`undecodable`, `skipped`) and *hole* (`gap`, `truncated`). 0.9
  described the split in prose without naming it as the part a consumer must get
  right.
- **Each layer has its own offset space, and a decoded stream's is now defined**:
  the concatenation of a participant's decoded record payloads in stored order,
  byte 0 being the first byte of the first such record. Undecoded regions
  contribute nothing, so unlike a transport stream's space it is *not*
  hole-inclusive. 0.9 defined offsets only for reassembled transport streams,
  which left `raw → tls-records → http` — a pipeline 0.9 explicitly invites —
  with no defined offset space for its second stage to reference.
  *Implementers doing multi-stage decode: this is the rule you were missing.*
- **`spans` versus `origin`, not `decoder_id`, discriminates what a file's own
  stage produced**. A record carrying `spans` was built by this stage; a
  record without them, whose participant carries `origin`, was re-emitted from
  the input. `decoder_id` says which decoder's layer a record belongs to, and a
  pass-through carries inherited ones forward, so it no longer implies the
  decoder ran in this stage.
- **`version_minor` describes the file, not the rendering.** A converter
  projects any file into whichever version of the JSONL face it implements, so
  the `format` string reports what the file says rather than what the tool is.
  *The field answers "what does this file contain", never "which tool wrote this
  line".*
- **A one-participant or single-sender session is trivially sequenceable**.
  It has no cross-participant order to get wrong, so it needs no basis at all.
  Vacuous under 0.9's rule, but worth stating, since the clock precondition
  appeared to bite exactly the one-way UDP case it cannot apply to.
- **A decoded-layer filter or reordering stage is a decode stage, not a
  pass-through.** Dropping or reordering a decoded record shifts offsets in that
  participant's space, which stored order defines, so the output cannot claim to
  preserve it. Such a transform cites its input in `spans` — which for a
  reordering stage will *not* ascend with stored order — and marks dropped
  regions `skipped`, bringing the coverage guarantee to bear.
- **`decoder_id` names a layer, not a stage.** A transform that rearranges
  records without decoding them **inherits** its input's `decoder_id`s and
  re-declares the Decoder Descriptors they reference, exactly as a pass-through
  does; a filtered or reordered HTTP message is still an HTTP message. It
  identifies itself through `produced_by`, as every derived file does. *A
  consequence, recorded under future extensions rather than fixed: such a
  transform's own configuration has no `params_digest` to live in, so a filtered
  file records what it came from but not how. A merge already had this gap.*
- **A decoded record's offset range is positional.** A Record block carries no
  offset field, so record *k* of a participant occupies `[Σ payload_len of the
  preceding records, + its own payload_len)` in stored order. The offset-space
  rule implied it; nothing stated it, and a consumer cannot resolve a record
  without it.
- **The class of an `Undecoded` `reason` governs recovery; the word carries
  intent.** Both are usable, for different purposes — a consumer counting
  genuinely unparsed bytes separates `undecodable` from `skipped`. `0.9`'s
  "the class, not the word, is what a consumer acts on" contradicted `skipped`'s
  own justification.
- **A failed recovery walk has two outcomes and they MUST be reported
  distinctly**: *no bytes exist* (the chain resolved; the region is genuinely
  empty) versus *bytes unavailable* (the chain broke — an intermediate file is
  missing, unreadable, or fails its `digest`). Collapsing the second into the
  first asserts something the consumer never established, and is the exact
  silent-data-loss the coverage guarantee exists to prevent.
- **The recovery walk is explicitly conditional.** Nothing obliges a consumer
  that is merely reading a file to walk any provenance chain; the walk is for a
  consumer that actually wants the bytes.

### Added

- **[Conformance vectors](vectors/)** — 21 small `.zpf` files with their
  expected projections or expected failures, covering the baseline container,
  all four unrecognised-data escapes, every `0.10` construct, and both error
  tiers. Hand-built from the normative text rather than generated by any
  implementation, which is what lets them catch an implementation diverging from
  it. `raw-minimal` is byte-for-byte identical to the specification's worked
  example. *Start here when implementing: the `escape-*` and `reject-unknown-minor`
  vectors are the ones a plausible-looking reader most often fails.*
- **Session option `sequenced_basis`** (`0x0053`, string) — what a `SEQUENCED`
  hint-less session's order rests on. A producer **MUST** set it on such a
  session; omitting it is a semantic violation. Open vocabulary, defined values
  `clock`, `protocol`, `external`; a reader MUST NOT reject a session for a value
  it does not recognise.

  It is mostly *not* something a consumer branches on — it is an explanation kept
  for when an order turns out to be wrong, in the family of `creator` and
  `params_digest`: a nonsensical order is a different investigation under `clock`
  (capture skew) than under `protocol` (the producer's assumptions). Requiring it
  also puts the obligation where the knowledge is, since a producer that must name
  a basis has to decide what it is at the moment it sets the bit. One mechanical
  check does fall out: `basis = clock` on a file with several `capture` Sources
  and no `SINGLE_CLOCK` is self-contradictory.
- **Undecoded option `reason_class`** (`0x00A1`, string, `hole` or `bytes`) —
  **required** with any `reason` outside the canonical four. The `reason`
  vocabulary is open so producers can be specific; this keeps that freedom from
  costing consumers the one fact they must act on. *Previously an unrecognised
  reason had no discoverable class at all.*
- **Canonical `Undecoded` reason `skipped`** — a region the decoder
  declined *on purpose*: data it does not care about, or data carrying no
  information, such as a byte-order mark, a padding or a reserved field. It sits
  in the bytes-exist class alongside `undecodable`, from which it differs in
  intent, not recoverability. It earns canonical status because the coverage
  guarantee leaves a decoder no honest third option — without it, a decoder
  ignoring a BOM must either stretch a record's `spans` over bytes it never
  interpreted or call them `undecodable`, asserting a failure that did not
  happen. It also keeps `undecodable` usable as a decoder-quality signal.
  *The vocabulary was already open, so this canonicalises an existing
  possibility rather than adding a capability; 0.9 readers treat `skipped` as
  any unrecognised reason.*
- **The JSONL projection's four escapes for unrecognised data**. The
  binary face has always had one universal rule for what a reader does not
  recognise — skip by length, retain, never error. The projection now mirrors
  it: every unrecognised element has a defined syntactic escape, a converter
  never invents meaning for one, and never silently drops one.

  | Unrecognised | JSONL form |
  |---|---|
  | option id | `options` array entry *(already in 0.9)* |
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

- **Version numbering, and what a reader does with it.** Three parts:
  - **`major` and `minor` are independent integers, compared componentwise** —
    never one decimal number. `0.10` is the tenth minor and is **greater** than
    `0.9`. *A parser that reads the `format` string's tail as a float sorts
    `0.10` below `0.9` and silently accepts a file it must reject.*
  - **While `version_major` is `0`, a reader MUST reject a `version_minor` it
    does not implement** — joining the structural-corruption tier alongside an
    unimplemented `version_major`. This is what makes a breaking `0.x` release
    detectable instead of silently destructive.
  - **A writer stamps the version it implements.** The rule that it should
    compute the *lowest* version whose features a file happens to use is
    **withdrawn**: a streaming writer cannot satisfy it, since the File Header
    precedes the content, and it would oblige a writer at, say, `1.67` to carry
    a feature-to-minor mapping forever — to buy a precision readers derive
    locally for free.
- **The `Undecoded` reason `tcp-gap` is renamed `gap`.** It was the only
  transport-specific token in the vocabulary, in a format that is
  transport-neutral everywhere else — and loss detection is not a TCP privilege:
  RTP has sequence numbers, SCTP has TSNs, an application protocol may carry its
  own. Nothing is lost by dropping `tcp`, since the session's `proto` already
  says what the transport was. *A canonical value should be the generic case;
  saying precisely how a hole was found is what the open vocabulary and
  `reason_class` are for.*
- **A pass-through transform preserves its input's *layer*, not just its bytes**.
  0.9 defined pass-through as carrying no
  `decoder_id`, which silently confined it to raw input and left any transform
  over a decoded file — an annotator or a re-merge — unexpressible. A
  pass-through now re-emits its input's records with bytes, logical offsets,
  `decoder_id`s, `content_type`s and Undecoded blocks unchanged, whatever layer
  the input was at, and re-declares the Decoder Descriptors they reference. The
  input's coverage guarantee then holds of the output without the output
  carrying any `spans`. Decoder Descriptors and Undecoded blocks are no longer
  restricted to decode-stage files. *A strict 0.9 reader may refuse a file that
  carries `decoder_id`s alongside `origin`; the [annotator example](docs/zipline-payload-format.md)
  shows the shape.*
- **A transform that only adds metadata is a pass-through**, and its
  output is a *derived* file. Annotating a raw file therefore moves capture-level
  provenance (`link_type`, the capture's `uri`/`digest`) one level away, reached
  through the input Source rather than directly. Nothing is lost, but a consumer
  reading it must take the extra hop.
- **A pass-through carrying inherited Undecoded blocks MUST also declare the
  file those blocks name** and make their `source_id` resolve to it. This
  is the one case where a derived file names something other than its immediate
  input — because the statement being carried forward was always about that
  further-up file. Keeping the inherited ids and numbering the immediate input
  around them lets the blocks be copied verbatim.
- **`SEQUENCED` on a hint-less session requires a sound basis, not specifically
  a clock**. A single trustworthy clock remains the
  common basis; ordering knowledge the format does not model — a server-assigned
  order, an application sequence number, an out-of-band record — now also
  qualifies, with `sequenced_basis` to say which. The producer owns the
  soundness; a reader could never verify the clock claim either. *This permits
  sequenced multi-party UDP and chat sessions that 0.9 forbade.*
- **The specification file is now `docs/zipline-payload-format.md`**,
  renamed from `docs/payload-format.md`: kebab-case, project name included, and
  no version in the filename so the path survives future versions. *A
  documentation-layout change, not a format change — but it breaks existing
  links.*
- **A converter MUST NOT invent an option id** for an unrecognised JSON key on a
  known block. There is no id to write, and guessing manufactures data.
  Such a key cannot arise from a binary source, only from hand-written or
  third-party JSONL; on the JSONL → binary path a converter MUST reject the line
  or drop the key, and MUST report it either way.
- **JSONL: the File Header rate is the key `tick_hz`, carrying a number** —
  previously the alias `time_units`. `tick_hz` is the binary field's own name, so
  the projection's general naming rule now covers it and the alias table has one
  fewer exception. *Writers: emit `tick_hz`.*

### Removed

- **JSONL key `time_units`**, superseded by `tick_hz`. Removed outright rather
  than deprecated: `0.10` claims no compatibility with `0.9`, so there is nothing
  to keep accepting. *A converter that still emits or accepts `time_units` is
  writing `0.9`.*

### Fixed

- **Four JSONL examples wrote `"time_units":"us"`** — a unit label, where
  0.9's normative text defines the value as a rate in ticks per second and
  permits only a number or a decimal string. The examples were non-conformant
  against their own specification, so anything written by copying them was too.
  Corrected to `"tick_hz":1000000`.
- **The example of an *unregistered* option id was `0x0091`**, which is
  registered — it is `content_type`. Changed to `0x0200`, which is outside the
  registry.
- **The decoded-file example's two `record` lines omitted `source_id`**, a
  mandatory body field that the projection's own rule says always projects. Every
  other example in the document includes it. Added.
- **A single-occurrence `endpoint` rendered as a scalar string in every
  example**, while the rule says a repeatable option renders as a JSON array —
  and `spans`, the other repeatable id, is an array even with one entry. Settled
  in favour of the rule: `endpoint` is **always** an array, so a reader never
  branches on a key's JSON type. Eleven example lines corrected. *Found while
  building the conformance vectors, which could not be written until it was
  decided.*
- **Three cross-reference anchors never resolved** — `#session-descriptor-0x10`,
  `#participant-descriptor-0x11` and `#session-end-0x12` pointed at bold labels,
  which generate no anchor. Those five descriptor blocks are now `####`
  headings, matching every other block in the document.

---

## [0.9] — 2026-07-09

The initial specification, published at the time as **`1.0`** and designated
final. It was neither: no implementation existed yet, and the first one found
enough to force a breaking revision. Retroactively renumbered — see the note
under `0.10` above.

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

[Unreleased]: https://github.com/adamkjonsson/zipline/compare/v0.10...HEAD
[0.10]: https://github.com/adamkjonsson/zipline/compare/v0.9...v0.10
[0.9]: https://github.com/adamkjonsson/zipline/releases/tag/v0.9
