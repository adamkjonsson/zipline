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

**One exception, and it matters if you are writing a `0.9` reader.** A real
`0.9` file stamps `version_major = 1`, `version_minor = 0`. The renumbering
re-designated the July 2026 text; it did not rewrite any bytes, and no file has
ever stamped `0`/`9`. `0.9` is the one version where the name and the header
disagree — every version from `0.10` on stamps what it is called.

`0.x` files are also **disposable**: a reader rejects a `version_minor` it does
not implement, and no upgrade path between `0.x` versions is guaranteed. Where
a `0.9` file still matters, regenerate it from the capture rather than
transcoding it.

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

## [0.13] — unreleased

The first release since `0.9` to add capability rather than only correct.
Scope and reasoning in
[docs/RELEASE-0.13-PLAN.md](docs/RELEASE-0.13-PLAN.md); the work is tracked
against the [`0.13` milestone](https://github.com/adamkjonsson/zipline/milestone/1).

### Clarified

Both of these describe what the format already did. **No file that is conformant
under `0.12` stops being conformant**, and no writer has to change — but a reader
built on the letter of the old text may have been rejecting valid files.

- **`spans` asserts correspondence, not identity.** A decoder **frames, and may
  transform**: it may emit bytes that appear nowhere in its input, in a different
  quantity, and its `spans` name the input region the unit was *computed from*
  rather than a region holding those same bytes. This is what makes gzip, HPACK
  and any decryption stage expressible. *The specification contradicted its own
  shipped conformance vector here:* `vectors/chain/decoded.zpf` has emitted
  `RESP:200` — 8 bytes spanning 16 — since `0.11`, while the text said a decoder
  only frames. `vectors/check.py` never caught it, because it verifies coverage of
  ranges and never payload-to-span correspondence. Consequences now stated: the
  recoverability walk reaches the *corresponding* bytes and not necessarily the
  ones it set out to find (ciphertext, below a TLS stage); the reproducibility
  contract holds for a key-gated stage but only for a key-holder, leaving digest
  verification intact and third-party regeneration impossible; and correspondence
  is **not proximity** — a discarded byte-order mark stays `skipped`, while a
  decryptor's nonce and auth tag are honestly spanned, which closes tunnel-stream
  coverage with no Undecoded blocks rather than one per packet.
- **A decode stage's sessions need not line up with its input's.** The mapping
  from input participant streams to output sessions is **many-to-many** in both
  directions: one input stream may feed several output sessions (HTTP/2
  demultiplexed into a session per stream), one output session may draw on several
  input streams (every two-direction decode already does), and a stage may mint
  sessions with no upstream counterpart. Previously neither permitted nor
  forbidden. What binds an output record to its input is `spans`, never a shared
  `session_id`. The coverage guarantee is unchanged and needed no widening — it
  was already stated per *input participant stream*, which is exactly what makes
  it survive fan-out.

### Added

- **`external_session_id` on the Session Descriptor** (`0x0054`, bytes,
  single-valued) — an identity assigned by something *outside* this format: a
  trace id, a capture orchestrator's UUID, a NetFlow flow key, a case number.
  Nothing here interprets it. It answers a different question from `session_id`,
  which stays **u64** and is still what `spans` and `origin` reference — a
  cross-file reference needs a fixed-width numeric key. Deliberately **opaque and
  variable-length**: one option per session costs nothing per record, so fixing a
  width would foreclose SHA-256s and URNs to save nothing. `bytes` is the option
  registry's first value of that type; it projects as base64, by the same rule
  that already covers `payload`, so a UUID never acquires a second spelling. The
  Session Descriptor prose carries the birthday arithmetic for anyone choosing
  random ids — 2³² is the 50% point in a 64-bit space, and one-in-a-million needs
  only ~6 million ids.
- **`transform_params_digest` on the File Header** (`0x0015`, string,
  single-valued) — the configuration of a transform that produced records
  **without decoding**. Two kinds of stage had nowhere to record it, and the
  specification named the gap without closing it. A **filter or reordering
  stage** is a decode stage, but `decoder_id` names a *layer, not a stage*: it
  inherits its input's decoders and re-declares their descriptors, so every
  `params_digest` in the file describes something that ran further upstream,
  never this stage. A **merge** declares no Decoder at all. Both are
  parameterised, so `produced_by`/`produced_at` did not settle reproducibility
  on their own. A file may carry this *and* an inherited `decoder_id` whose
  descriptor has its own `params_digest` — they describe different stages, one
  here and one upstream — and a raw file, not being a transform's output, MUST
  NOT carry it.
- **Two conformance vectors' worth of coverage.** `external-session-id` carries a
  16-byte binary UUID; `reordered-decoded` gains a `transform_params_digest`, it
  being exactly the transform whose configuration had nowhere to live.

### Fixed

- **Three decode-stage vectors now set `produced_by`/`produced_at`.**
  `undecoded-skipped`, `undecoded-reason-class` and `isolate-coverage-gap` are
  derived files, which *Conformance* requires to declare both, and none did. The
  two tiers failed in opposite directions: the `accept` pair failed a **correct**
  reader, while `isolate-coverage-gap` carried a second violation and so passed
  an **incorrect** one — a reader could trip on the missing provenance and pass
  it with coverage checking entirely unimplemented. Found by `python-zipline`
  porting to `0.12`.
- **`reject-unknown-minor` now stamps the minor after this one.** It stamped
  `13`, which this release makes valid; it is derived from the current version so
  it keeps testing an unimplemented minor at every future bump.

---

## [0.12] — 2026-07-31

A corrective release, like `0.11`: it fixes what the review
of `0.11` found and adds no option, block or capability. Reasoning in
[docs/implementation-review-response-0.11.md](docs/implementation-review-response-0.11.md).

### Clarified

- **`hint-less` is defined**, having carried normative weight in fourteen places
  with only a parenthetical to explain it: **a session in which no record carries
  `seq_start` or `ack`.** One such hint anywhere means the session is not
  hint-less.
- **Deciding it is deferred to Session End.** Hint-lessness is a property of a
  session's *records*, and declare-on-first-use puts the Session Descriptor
  before them — so a reader concludes it only at Session End or end-of-stream,
  and the `sequenced_basis` check defers to that point. *One boolean per open
  session; it composes with state a reader already keeps.* The producer needs no
  such deferral: it decides by what it is relying on, which it knows when it sets
  the flag.

### Added

- **Two conformance vectors.** `merge-timestamp-tie` — two concurrent records
  from different participants with identical timestamps, stored in the *opposite*
  order to the one the merge must produce, so a reader that falls back to stored
  order fails it. And `partially-hinted-sequenced` — a `SEQUENCED` session with
  one hinted record and two unhinted ones, pinning the answer to the question
  that took longest to settle. 26 in total.

### Changed

- **The merge is now fully deterministic.** Step 4 breaks ties by
  `(timestamp, participant_id)` rather than by timestamp alone. `participant_id`
  is unique within its session, so the frontiers are totally ordered and every
  reader of the same file computes the same interleaving — closing the last place
  two conformant readers could legitimately disagree. `0.11` surfaced this gap
  after removing the round-robin fallback that had masked it. *At least one
  implementation already merges on `(timestamp, pid)` because a total order was
  needed to test the merge at all; this ratifies the convention before more
  implementations pick differently.*
- **Sequencing is stated as an optimisation, not a correctness fix**, which
  follows from the above: a producer baking in the order saves each reader the
  work, it does not change the answer.
- **The producer tie-break clause is scoped.** `0.11` said a producer choosing a
  different tie-break "says so with `sequenced_basis`", but that option is scoped
  to hint-less sessions, leaving a TCP producer nowhere to record it. Now: on a
  hint-less session the producer records the basis; on a session with hints there
  is nothing to record, since causal edges account for the order and only
  genuinely concurrent records reach the tie-break.

---

## [0.11] — 2026-07-30

A corrective release: it fixes what the first review of
`0.10` found and adds no option, block or capability. Everything that would add
surface is held for `0.12`. Reasoning in
[docs/implementation-review-response-0.10.md](docs/implementation-review-response-0.10.md).

### Clarified

- **A `0.9` file stamps `1`/`0` in its header**, not `0`/`9` — stated in
  *Conventions* above and in the `[0.9]` section. The renumbering re-designated
  the July 2026 text without rewriting bytes, so `0.9` is the one version whose
  name and header disagree. *Anyone building a `0.9` reader from the CHANGELOG
  alone would otherwise look for `0`/`9` and reject every real `0.9` file.*
- **`0.x` files are disposable**, stated plainly for the first time: no upgrade
  path between `0.x` versions is guaranteed, and a `0.9` file that still matters
  should be regenerated from its capture. *A way to record a version re-stamp is
  planned for `0.13`, as a File Header option rather than a transform; until then
  there is none.*
- **Recording `sequenced_basis` is unconditional; soundness may be trivial.**
  `0.10` required the option in the registry while the narrative exempted the
  trivially-sound cases and a third passage still said SHOULD — three statements,
  no consistent reading. The exemption was also undecidable for a streaming
  writer, since `SEQUENCED` is written before the records that would settle
  whether only one participant sends. A hint-less `SEQUENCED` session now always
  carries the option.
- **The merge never reorders one participant's records against each other.** It
  is a k-way interleaving of already-sorted streams, so the timestamp tie-break
  chooses only *between* participants — including on a hint-less session, where
  every record is concurrent and the whole order is that tie-break. The property
  followed from the algorithm's shape and was stated nowhere.
- **Not every `zpf-input` Source is an input.** A file may declare one so an
  inherited reference resolves — a pass-through carrying Undecoded blocks that
  name a file further up the chain. The immediate inputs are the Sources that
  `origin` or `spans` point at.
- **A decoded record's positional range costs O(k) for random access**, with the
  recommendation to build per-participant prefix sums on a first pass. Free for
  forward reading, which is the design's primary case.

### Changed

- **The specification is version `0.11`**, so a `0.11` file stamps
  `version_major = 0`, `version_minor = 11`, and renders as
  `"zipline-payload/0.11"`. A `0.10` reader MUST reject it — that is the `0.x`
  regime working as intended, not a defect. *Nothing in this release changes the
  frame, a block body, or an option's meaning; the bump is required because the
  version is how a reader tells the two apart.*

### Added

- **`sequenced_basis` value `trivial`** — for a session with one participant, or
  only one that ever sends. Without it, making the recording unconditional would
  force a producer to claim `clock`, `protocol` or `external` when none is true.
  *A defined value in an already-open vocabulary, so this documents an existing
  possibility rather than adding surface — as `skipped` did in `0.10`.*
- **Two conformance vectors**: `hintless-merge-backwards-ts` (accept) and
  `isolate-sequenced-no-basis` (isolate). 23 in total.
- **A three-file provenance chain** in [`vectors/chain/`](vectors/), whose
  digests and offsets genuinely agree: `raw.zpf` → `decoded.zpf` →
  `annotated.zpf`. It is the only fixture that can exercise the recovery walk,
  two-hop resolution through a decoded-layer pass-through, and digest
  verification — and the only place the **coverage guarantee is actually
  checked**, since verifying it requires the input's stream extents, which live
  in the parent. *That is also a concrete demonstration of why recording those
  extents is on the list for a future version.*

### Changed

- **The merge's step 4 no longer asks a reader to detect clock skew.** "If
  clocks are known-skewed, fall back to round-robin / source order" required a
  determination a reader cannot make — skew is not a property a file asserts, and
  the absence of `SINGLE_CLOCK` says nothing either way. A **producer** computing
  a sequenced order may still choose any deterministic tie-break and record it via
  `sequenced_basis`; a reader always uses the timestamp.

### Fixed

- **The brevity-alias table illustrated the omitted-minor rule with
  `"zipline-payload/1"`** — the retracted version, in the table a reader consults
  while working out what the renumbering did. Now `"zipline-payload/2"`.
- **A stale cross-reference to the merge's removed skew fallback.** One passage
  still cited "step 4's clock/round-robin tie-break" as the reason independent
  reader merges may disagree. With the fallback gone, readers agree except on an
  exact timestamp tie — which this version does not resolve, and now says so.

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

**Files of this version stamp `1`/`0` in the File Header**, not `0`/`9`. Only
the designation changed; the bytes never did.

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

[0.13]: https://github.com/adamkjonsson/zipline/compare/v0.12...HEAD
[0.12]: https://github.com/adamkjonsson/zipline/compare/v0.11...v0.12
[0.11]: https://github.com/adamkjonsson/zipline/compare/v0.10...v0.11
[0.10]: https://github.com/adamkjonsson/zipline/compare/v0.9...v0.10
[0.9]: https://github.com/adamkjonsson/zipline/releases/tag/v0.9
