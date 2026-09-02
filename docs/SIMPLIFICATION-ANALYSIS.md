# Simplification analysis: which principles carry the weight

> **Decision record, not a plan.** This document analyses the `0.18` specification
> as it stands, asks which of its underlying principles could be loosened, and
> estimates what each loosening would remove. It drafts no spec wording and
> decides nothing. Once a direction is chosen, the work becomes issues on a
> release milestone, as every previous round has.

All references are to [zipline-payload-format.md](zipline-payload-format.md) at
`0.18` and to [vectors/](../vectors/) at the same version.

---

## 1. Verdict

The complexity is not spread evenly across the six stated goals. Five of them are
cheap. Almost all of the weight sits under one principle that is **not in the
Goals list** but has governed every release since `0.13`:

> A derived file must be a complete, self-verifiable, loss-proof account of its
> input, at every hop of a chain.

Loosening that principle, together with two smaller ones that grew beside it,
would roughly halve the normative surface. The six stated goals — many sessions
per file, N participants, reassembled bytes as truth, streamable, packet-time
clock, seq/ack causality — cost little and this document does not propose
touching them.

Separately from any principle, about a third of the document is rationale and
release history rather than specification. Moving it out is the single largest
reduction available and changes nothing the format means.

---

## 2. Where the weight is

The specification grew from 1 647 lines at `0.9` to 3 517 at `0.18`, and its
MUST count doubled over the same period:

| Version | Lines | MUST | SHOULD | MAY |
|---|---:|---:|---:|---:|
| `0.9` | 1 647 | 70 | 14 | 26 |
| `0.13` | 2 590 | 108 | 16 | 37 |
| `0.15` | 3 114 | 121 | 23 | 43 |
| `0.18` | 3 517 | 143 | 27 | 49 |

The growth is concentrated. Grouping the text by the principle that produced it:

| Cluster | Approx. lines | Vectors (of 60) | Driving principle |
|---|---:|---:|---|
| **Derivation** — layers, spans, Undecoded, Discontinuity, coverage, pass-through, `origin`, `input_extents`, the two axes | ~1 500 | ~30 | derived files are self-verifiable and lossless |
| **Sequencing** — `SEQUENCED`, `sequenced_basis`, `SINGLE_CLOCK`, hint-less | ~250 | 4 | a producer must justify every claim it makes |
| **Advisory tier** — origin floor, unplaceable records, transport-layer `content_type`/`role`, handshake placement | ~250 | 4 | two readers must agree even on non-conformant files |
| **Everything else** — frame, blocks, JSONL projection, merge algorithm, examples | ~1 500 | ~22 | the stated goals |

The largest individual sections tell the same story: *Conformance* (349 lines),
*Discontinuity* (259), *Referencing the source by stream offset* (209),
*Sequenced files* (198), *Undecoded* (195), and the *decrypted tunnel* example
(118) are all in the first two clusters.

---

## 3. Principles that could be loosened

Ranked by simplification gained against capability lost. Each entry names what
the loosening deletes, so the size of the win can be checked against the text
rather than taken on trust.

### 3.1 Pass-through as a distinct derivation kind

**Today.** A `zpf`-sourced stream is one of two things: a *decode stage* output,
whose records carry `spans`, or a *pass-through* output, whose participants carry
`origin` and whose records carry nothing. The two are told apart by which option
is present, the rule binds per participant, and a set of asymmetries follow:
inherited Undecoded blocks are copied verbatim while Discontinuities are
renumbered; an annotator's records resolve in two hops while its Undecoded blocks
resolve in one; a file may declare a `zpf-input` Source that is not an input.

**Loosen to.** Every derived record carries `spans`. A merge or an annotator
writes an identity span per record — the same range in, the same range out.

**Why it is safe.** The specification already treats a *filter* exactly this
way: it inherits its input's `decoder_id`s, re-declares their descriptors, and
cites input ranges with `spans`. Pass-through is the special case that got its
own vocabulary. The cost is 28 bytes per record in a merged file.

**Deletes.**

- Option `origin` (`0x0064`) and its paragraph under *Participant Descriptor*.
- In *Conformance*: the two-way taxonomy, "the discriminator is `spans` versus
  `origin`", "the discriminator binds per participant", "a `zpf`-sourced
  participant MUST be one or the other", "not every `zpf-input` Source is an
  input", and the pass-through bullet with its carry-forward rules.
- In *Layers*: "Transforms that change no data" and the whole *Annotating a
  decoded file* section.
- In *Discontinuity*: "a pass-through preserving a decoded layer carries these
  forward, renumbered" and the verbatim-versus-renumbered contrast.
- The *Design decisions not taken* entry on a machine-checkable annotation kind.
- Vectors: `passthrough-transport`, `passthrough-discontinuity`,
  `annotator-decoded`, `isolate-unbound-zpf-stream` (its rule collapses to "a
  `zpf`-sourced record without `spans`"). `mixed-derivation` and
  `merge-timestamp-tie` are rewritten with identity spans.

**Lost.** Nothing of substance.

### 3.2 A producer must justify its sequencing claim

**Today.** A hint-less session marked `SEQUENCED` MUST carry `sequenced_basis`
naming what the order rests on, with a four-word vocabulary and a `trivial`
value for the case where there was nothing to get wrong. A file-level
`SINGLE_CLOCK` flag supplies the basis file-wide. Because a streaming producer
writes the Session Descriptor before it can know whether the session will be
hint-less, the rule is keyed on "what the producer relies on", and a reader can
only check it at Session End.

**Loosen to.** `SEQUENCED` is a bare assertion that stored order is a valid
causal order. The producer is trusted, as it already is for the order itself.

**Why it is safe.** The specification says of the field that it is "mostly *not*
something a consumer branches on — it is an explanation kept for when something
turns out to be wrong". The one mechanical check it enables (a `clock` basis in a
multi-source file without `SINGLE_CLOCK`) is a MAY.

**Deletes.**

- Options `sequenced_basis` (`0x0053`) and File Header `flags` (`0x0014`),
  whose only defined bit is `SINGLE_CLOCK`.
- In *Sequenced files*: everything from "What a sequenced session rests on" to
  "The two flags are independent", about 110 lines.
- In *Merge algorithm*: the hint-less definition and the paragraph on why a
  reader can only decide it at Session End; the producer-tie-break paragraph
  shrinks to one sentence.
- In *Conformance*: the basis clauses of "Ordering and sequencing" and the
  "missing `sequenced_basis`" violation.
- The *Design decisions not taken* entry on requiring the basis unconditionally,
  and the JSONL alias `single_clock`.
- Vectors: `sequenced-basis`, `isolate-sequenced-no-basis`,
  `partially-hinted-sequenced`, `file-clock-metadata` (its `time_epoch` half
  moves into `descriptive-metadata`).

**Lost.** A forensic hint about what a bad order rested on.

### 3.3 Two readers must agree on non-conformant input

**Today.** Several MUST NOTs carry an *advisory* strength: the reader accepts the
file, applies a stated repair, and reports. Each needed its repair pinned so
that two readers agree: a below-origin record occupies a zero-width range at the
running maximum of the participant's earlier records; a transport-layer
`content_type` or `role` is ignored but must not be taken as evidence of layer;
a misplaced handshake record is placed by ordinary arithmetic. The *Conformance*
error tiers then carry a clause saying these specific rules displace the general
isolation licence.

**Loosen to.** Readers need only agree on conformant files. Every semantic
violation gets one treatment: isolate the smallest sound unit, or ignore the
offending option, with a diagnostic either way. Each current advisory rule
becomes one sentence.

**Why it is safe.** These rules govern writer bugs, not features. The
specification's own justification for pinning them is that "two readers taking
different options would disagree about the stream" — which is true, and is the
cost of a writer error rather than something the format must absorb.

**Deletes.**

- In *Referencing the source by stream offset*: "The origin is a floor" through
  "The floor is decidable only within the serial-arithmetic half-space", about
  70 lines, replaced by: a record whose `seq_start` precedes the origin covers no
  byte of the stream; a reader ignores its placement and SHOULD report it.
- In *Typing a decoded record*: "Violating this is advisory, not isolating" and
  the paragraph after it.
- In *Record*, under handshake records: "Violating this is advisory wherever the
  record sits" and "Two neighbouring shapes follow".
- In *Conformance*: the "displaces this licence" clause and its examples.
- Vectors: `advisory-below-origin-payload`, `advisory-seq-start-below-origin`,
  `advisory-transport-content-type`, `advisory-transport-role`.

**Lost.** Guaranteed identical output across readers for a writer's off-by-one.

### 3.4 Coverage as a verifiable MUST

**Today.** In a decode stage's output every offset of every input participant
stream MUST be covered by a `spans` entry or an Undecoded block, and never both.
To make that checkable from one file the specification added `input_extents` on
Session End, an extents-must-agree rule under fan-out, `reason_class` so that an
open `reason` vocabulary still yields a decidable class, the `dropped` value so
that content removal is distinguishable from framing skipped, and a
Discontinuity *origination duty* with a seam predicate stated so that two
checkers agree.

**Loosen to.** A decode stage SHOULD account for input it did not decode with
Undecoded blocks, and SHOULD mark a break in its own output with a
Discontinuity. No checker proves either. Undecoded keeps `reason` as an open
string whose canonical values imply a class; an unrecognised value has unknown
recoverability. Discontinuity keeps `width` and the reader-side rule not to
splice, since both affect the decoded offset space.

**Why it is a real trade.** "Nothing vanishes silently" is the format's strongest
claim, and this loosening reduces it from a property of the file to a property
of the producer. The *broken-chain* and *splice* semantics survive because they
are about reading, not verification.

**Deletes.**

- Options `input_extents` (`0x00C1`) and `reason_class` (`0x00A1`); the
  `dropped` reason value.
- In *Session End*: the `input_extents` text, about 65 lines.
- In *Undecoded*: the `reason_class` paragraphs, the `dropped` paragraphs, and
  "an unrecognised `reason` with no `reason_class`".
- In *Discontinuity*: "What a producer owes the block" through "Satisfying this
  predicate is not satisfying the duty", about 130 lines including the join
  table and the predicate, replaced by one SHOULD.
- In *Coverage honesty* and *Conformance*: the guarantee restated as a SHOULD;
  the "at least once, never both" and per-input-stream refinements go with it.
- Vectors: `isolate-coverage-gap`, `isolate-extent-exceeds-coverage`,
  `isolate-extents-disagree`, `isolate-unmarked-break`, `isolate-unmarked-drop`,
  `undecoded-reason-class`. `filtered-decoded` and `reordered-decoded` lose their
  Discontinuity obligations but stay as accept vectors.

**Lost.** The property that a single derived file proves nothing was dropped.

### 3.5 Provenance and layer as independent axes

**Today.** Since `0.15` a stream's *provenance* (capture or `zpf`-sourced) and
its *layer* (transport or decoded) are independent. The layer comes from the
Decoder's `output_layer` body field; reassembly is a decoder; a `zpf`-sourced
transport stream (a sessionization stage) and a capture-sourced decoded stream
(a TLS proxy) are both first-class. This brought the layer rule, the
mixed-layer rule, the transport-withholding rule, Undecoded blocks against a
capture Source, the head-of-pipeline reassembler SHOULD, and the four-file
tunnel example.

**Loosen to.** The `0.14` model: capture-sourced means transport, `zpf`-sourced
means decoded, and a record is decoded exactly when it carries `decoder_id`.

**How the motivating cases are handled.** A decrypted tunnel is produced by one
head-of-pipeline stage that decrypts and reassembles, emitting capture-sourced
transport streams for the inner flows (optionally with `spans` as capture byte
offsets, which the format already supports). A TLS-terminating proxy emits its
plaintext as a transport byte stream, not as decoded units, and HTTP decoding
then runs as an ordinary decode stage over it.

**Deletes.**

- The `output_layer` body field and enum; the Decoder body reverts to a
  reserved u16.
- In *Conceptual model*: "Provenance and layer are independent axes" through the
  four-cell table and its discussion, about 60 lines.
- In *Decoder Descriptor*: the `output_layer` text and the boxed note, about 45
  lines.
- The whole *Worked example: a decrypted tunnel* section, 118 lines.
- In *Undecoded*: "Against a `capture` source" and the two paragraphs after it.
- In *Discontinuity*: "The exemption assumes the offsets can express it" and the
  transport-withholding rule.
- In *Conformance*: the mixed-layer rule, the head-of-pipeline reassembler
  SHOULD and its recorded asymmetry, the sessionization-stage bullet, the
  decoded-with-no-predecessor bullet, and "the transport layer's requirements
  bind on the layer, not on provenance".
- In *Enums*: "Two enums are load-bearing" becomes one.
- Vectors: `tunnel`, `sessionization-stage`, `reassembler-declared`,
  `proxy-decoded`, `undecoded-in-capture`, `isolate-mixed-layer-participant`,
  `isolate-unknown-output-layer`, `isolate-hole-against-capture`.

**Lost.** The per-hop account of loss inside a tunnel chain, and a
`params_digest` for reassemblers. `0.15` exists because an implementation asked
for both, which is why this item is ranked last.

### 3.6 Not proposed: decoded views in separate files by logical offset

Keeping the decoded view as a separate stream, referenced by hole-inclusive
logical offsets, is what makes the streaming and flush-and-forget goals hold
across a chain. The 2.5-record argument in *Layers* is sound, and folding the
decoded view into the transport file would force every decoder to run in the
writer's own pass. This principle costs text, but the text is buying the format's
shape rather than defending an edge.

Two smaller candidates are noted for completeness and not ranked:

- **Handshake records** (`syn`-flagged zero-length records) are a MAY feature
  with about 60 lines of placement rules. Dropping them loses handshake timing
  only; `isn` and `tcp_role` already carry the handshake's identity.
- **The self-derivation prohibition** and its detection paragraph, about 20
  lines, forbid something a streaming writer cannot produce and a reader often
  cannot detect. One sentence would do.

---

## 4. Recommendation

Take **3.1, 3.2 and 3.3 as a package.** They loosen no stated goal, cost no real
capability, and remove the parts implementers have tripped on: `origin`, the
basis rule, and the advisory tier were each the subject of one or more review
rounds. Then decide **3.4** on its own, because it changes what the format
promises rather than how it says it. Leave **3.5** unless tunnels turn out to be
rare in practice.

Two further observations matter more than any single item:

- **Separate the rationale from the specification.** Around a third of the
  lines explain why a rule exists or what an earlier version got wrong. A
  companion `zipline-payload-format-rationale.md` holding that material, plus
  *Design decisions not taken*, brings the specification near 2 000 lines with
  no change in meaning. This is what [CLAUDE.md](../CLAUDE.md) asks for: text an
  implementer can follow, not the argument that produced it.
- **The estimates compound.** Rationale extraction plus 3.1–3.3 lands around
  1 400 lines; adding 3.4 lands nearer 1 100. These are rough, but the order of
  magnitude is right.

| Package | Approx. lines | Vectors removed | Capability lost |
|---|---:|---:|---|
| Rationale moved out | ~2 000 | 0 | none |
| + 3.1 pass-through, 3.2 basis, 3.3 advisory | ~1 400 | 12 | forensic hints only |
| + 3.4 coverage as SHOULD | ~1 100 | 18 | self-verifiability |
| + 3.5 single axis | ~900 | 26 | per-hop tunnel account |

Every item above is a `0.x` change and needs no transition mechanism: a reader
rejects a `version_minor` it does not implement, and `0.x` files are disposable
by the format's own rule.
