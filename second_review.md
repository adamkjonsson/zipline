# Review of Zipline Payload Format

**Git commit version**: `cb33d12fc415d1ca0158511e84ebf361bfe8268f`

**Date**: 2026-06-29

The specification feels function complete for version 1.0.

Read the specification with a critical mindset, as an implementer for
a language would.

Answer the following questions:

1. Is the spec clearly written? 
2. Is the intent and purpose of the format clear?
3. Is it easy to understand what use cases it has?
4. Do you think the spec will provide a good solution for these use cases?
5. Does the spec have any gaps? Is anything missing in it that makes it difficult to implement language support for it?
6. Are there any inconsistencies in the format?
7. Are there features that in your oppinion adds mote complexity than usefulness? Can the format be slimmed down?
8. What is your assesment of how large a task it is to implement support
for this standard in let's say Python and C++?

Write a list of suggested improvements with motivations in the subsection "Claude´s review" below.

## Claude's review

*Reviewed as an engineer who would have to write a from-scratch reader/writer in
Python and C++, against the binary normative section — the part a conformant
implementation actually has to honour.*

### Summary

This is a strong, unusually well-thought-out spec. The conceptual model
(file → session → participant → record), the N-participant generalisation, the
declare-on-first-use streaming contract, the absolute-seq/ack causal ordering,
and the raw→decoded file-to-file transform are all coherent and motivated. The
binary layout is mostly nailed down to the byte, and the worked hex example is
excellent — it removes most of the ambiguity that usually sinks a format spec.

The issues below are real but mostly *local*: a handful of genuine
under-specifications and two or three internal contradictions that an
implementer would hit on day one. None of them threaten the design; they are
fixable with clarifying text or small field additions.

### 1. Is the spec clearly written?

Yes, with one caveat. The normative binary section is precise and the hex
walkthrough is the best part of the document. The narrative sections are
articulate but *dense* — long, multi-clause sentences carrying several
normative-feeling claims at once (e.g. the timestamp-rule and seq/ack-guarantee
paragraphs). For an implementer this is fine because the normative section is
the contract and explicitly wins on conflict; for a first read it's heavier than
it needs to be. The prose occasionally states the same idea three times in
slightly different words.

### 2. Is the intent and purpose of the format clear?

Yes — unambiguously. The status banner, the Goals list, and the "Prior art"
section make the purpose and the *non-goals* (it is not a capture format, not a
replacement for pcap) clear. The framing of "payload after reassembly, not raw
packets" is stated early and held consistently.

### 3. Is it easy to understand the use cases?

Yes. The three-row table (TCP both directions / chat room N>2 / one-way UDP
N=1) anchors the abstraction immediately, and the two worked examples (skewed
two-file TCP capture, decoded HTTP file) show the format doing real work. A
reader knows within a page what this is for.

### 4. Will the spec be a good solution for those use cases?

Largely yes. The standout is the **separately-captured two-direction** case:
using absolute wire seq/ack for a clock-independent happens-before, with
timestamps demoted to a tie-breaker, is the right call and is well argued. The
file→file decode transform with offset-based provenance genuinely solves the
"2.5 records" boundary-mismatch problem that an in-record layering scheme would
botch.

Two reservations:

- **The merge algorithm's cost is unbounded — and it's *optional, consumer-side*
  work that should be framed as such.** First, scope: TCP reassembly (resolving
  out-of-order/retransmit/overlap *within* one direction) is firmly the
  **producer's** job — a `.zpf` already holds clean, in-order, per-participant
  byte streams, and a reader never reassembles. The merge algorithm is a
  *different* operation: the cross-participant **interleaving** of
  already-reassembled records into one causally-consistent timeline from seq/ack.
  The spec deliberately places this on the **consumer** (on-disk order is
  unconstrained — "a participant's records need not be stored in `seq_start`
  order — the merge algorithm sorts them"), and it is **optional**: a reader that
  only wants one participant's records in stream order never runs it (within a
  participant `seq_start` is already a total order); only a reader that wants the
  merged cross-participant view does. *When* a consumer opts in, though, the cost
  is unstated: Step 2 ("for each record R… add an edge from every peer record
  with `seq_end ≤ ack`") is naively O(N·M) per session, plus the topo sort. For
  long-lived high-volume sessions an implementer needs a hint that this is meant
  to run on a sliding window (acks only advance), or they'll write the quadratic
  version. A sentence stating that the merge is optional consumer-side ordering
  (reassembly is never the reader's job) and noting the intended scale / windowing
  would help.
- **Genuinely concurrent + known-skewed clocks** falls back to "round-robin /
  source order," which is explicitly non-deterministic across writers. That's an
  honest limitation, but it means two conformant consumers can produce different
  orderings of the same file. Worth stating that this is permitted divergence.

### 5. Gaps that make implementation hard

These are the items I'd file as blocking questions before writing code:

- **G1 — The Gap block has no `source_id` and an ambiguous offset space.** Gap
  (`0x21`) carries `session_id`, `participant_id`, `off_start`, `off_end` as
  *logical stream offsets*, but a decoded file may declare **several**
  `zpf-input` sources. There is no field saying *which input stream* the gap's
  offsets index into. Meanwhile the TLV registry lists `spans` as usable in Gap
  — so there are two competing mechanisms (inline offsets vs. a `spans` option)
  and the inline one is under-determined whenever more than one input exists. An
  implementer cannot resolve a gap to a concrete stream from the block alone.
  **Fix:** either add a `source_id` field to the Gap body, or make Gap use
  `spans` exclusively and drop the inline `off_start/off_end`.
  **→ RESOLVED.** Gap was generalised into the **Undecoded** block (`0x21`), which
  carries an explicit `source_id` naming the `zpf-input` whose stream its offsets
  index. (See the [I1 resolution](#resolution-undecoded-block-i1-and-g1).)

- **G2 — JSONL key set is not actually specified.** The "JSONL ↔ binary field
  mapping" table is the only normative statement about JSON key names, yet the
  worked examples use many keys that aren't in it: `boundary`, `decoder_id`,
  `seq_start`, `seq_end`, `ack`, `content_type`, `isn`, `reason`, `uri`,
  `digest`, `proto`, `params_digest`, `produced_by`, etc. The table says
  "options not in this table round-trip through a generic `options` array," which
  directly contradicts the examples (where those appear as first-class keys). So
  a JSONL writer has no authoritative list of key names and a JSONL reader can't
  know whether to look for `seq_start` or `options[…]`. **Fix:** make the mapping
  table exhaustive for every defined field/option, or state a deterministic rule
  (e.g. "every registered option uses its registry name as its JSON key; only
  unregistered/custom options go in `options`").
  **→ RESOLVED** — see [G2 resolution](#resolution-jsonl-key-mapping-g2).

- **G3 — `endpoint` repeatability vs. the "first occurrence wins" default.** The
  TLV rules say a repeatable option's order is significant and MUST be preserved,
  while a non-repeatable option MAY be collapsed to its first occurrence. Good —
  but the *only* signal that `endpoint` is repeatable is prose ("**repeatable**"
  in the registry row). There is no machine-readable repeatable bit in the TLV
  framing, so a generic reader that hasn't special-cased option `0x0060` will
  apply the first-occurrence default and silently drop inner tunnel layers. An
  implementer building a generic option map needs the repeatable set spelled out
  as a closed list (today: `comment`? `endpoint`. is `spans` "repeatable" or a
  single packed value? — it's a single value containing many entries, which is a
  third case worth stating explicitly).

- **G4 — Cross-file id spaces in `spans` are subtle and only stated in passing.**
  A span's `session_id`/`pid` live in the *referenced source's* id space, not the
  current file's. In the decoded example both happen to be `7`, which hides the
  distinction. This is correct as designed but is exactly the kind of thing that
  produces a wrong implementation. One explicit sentence ("the `session_id`/`pid`
  inside a span are interpreted in the referenced source's namespace, never the
  current file's") would prevent it.

- **G5 — `prim:` byte length not tied to payload length.** A `prim:u64-be`
  record's payload "is" an 8-byte integer, but nothing says the payload MUST be
  exactly the width implied by the token (8 bytes), nor what a consumer does if
  it isn't. Minor, but an implementer will ask.

### 6. Inconsistencies

- **I1 — Raw-fallback records in a decoded file contradict the source-kind
  rule.** Conformance says a file MAY mix raw and decoded records ("a decoder…
  falling back to raw on what it cannot parse"), *and* that a raw record's
  `source_id`/`spans` MUST reference a **capture** source, while a decoded file's
  inputs are **zpf-input** sources and "reading `decoded.zpf` never requires
  `raw.zpf`." These can't all hold: a raw fallback record inside a decoded file
  would have to reference a capture source the decoded file doesn't (and
  shouldn't) declare. Either the "raw ⇒ capture source" rule is too strict for
  mixed files, or fallback content should be expressed as a Gap / a passthrough
  decoder rather than a `boundary = 0` record. This needs resolving — it's the
  one contradiction that affects the central raw/decoded model.
  **→ RESOLVED** — see [I1/G1 resolution](#resolution-undecoded-block-i1-and-g1) below.

- **I2 — Span field order differs between the narrative, JSONL, and binary.**
  Narrative provenance (`{source_id, session_id, pid, …}`) and the JSONL mapping
  both list `session_id` before `pid`; the binary packed entry is
  `source_id, pid, session_id, …`. It's harmless because binary is positional and
  JSON is by-name, but presenting three orders for the same record invites a
  transcription bug. Pick one presentation order and note the binary reordering
  is purely for alignment.

- **I3 — `boundary` is described two incompatible ways.** It's simultaneously "a
  boolean-ish raw/decoded discriminator (0 vs ≥1), the number carries no meaning"
  *and* "values 2–255 reserved for future distinctions." If the number is
  meaningless and resolved via `decoder_id`, reserving a numeric range implies it
  *will* carry meaning later — pick one story. (See also #7.)
  **→ RESOLVED** — see [I3 resolution](#resolution-boundary-removed-i3-7).

### 7. Features that add more complexity than value

- **`boundary` as a `u8` is overbuilt.** Given that meaning comes entirely from
  `decoder_id`, the field is effectively one bit (raw vs decoder-imposed). A
  single `flags` bit would carry the same information and remove the awkward
  "reserved 2–255" range and the I3 ambiguity. This is the clearest slimming
  opportunity. (If a future need for distinct numeric boundary classes is real,
  keep the byte but *define* at least a second value so the range isn't purely
  speculative.)
  **→ RESOLVED** — went further than a flag bit: `boundary` was removed entirely.
  See [I3 resolution](#resolution-boundary-removed-i3-7).

- **`isn` is explicitly informational and explicitly unused by ordering.** It's
  harmless, but it's a field whose own description says it does nothing. Keeping
  it is defensible (debugging, sanity checks); just flag that an implementer can
  ignore it entirely with no behavioural consequence.

- **Two encodings double the implementation surface.** This is justified (binary
  for production, JSONL for debugging) and I would not cut it — but it should be
  acknowledged as the single biggest cost multiplier, and G2 makes the cheap face
  more expensive than it looks because its contract is currently incomplete.

- **`ts_first` and Name/Identity Resolution** are both arguably redundant with
  other mechanisms (provenance spans; inline `endpoint`/`identity`). Each has a
  real justification in the text, so I'd keep them, but they're the next things
  to drop if a v1.0 "minimum viable" subset is wanted.

Nothing in the *core* (header, sources, sessions, participants, records, TLV
options, seq/ack ordering) looks like dead weight.

### 8. Effort to implement in Python and C++

The format is mid-sized: a few block types, a TLV codec, one non-trivial
algorithm (causal merge), and a second (JSONL) encoding. Rough estimates for a
**complete, tested, conformant** library (not a weekend prototype):

| Component | Python | C++ |
|---|---|---|
| Block frame + endianness bootstrap + TLV codec | 1–2 days | 2–4 days |
| All block types (read+write) + alignment/padding | 2–3 days | 4–6 days |
| Serial-number (RFC 1982) seq arithmetic | <1 day | <1 day |
| Causal merge (DAG build + topo sort + tie-break) | 2–3 days | 3–4 days |
| JSONL projection + lossless round-trip | 1–2 days | 2–3 days |
| Conformance, truncation handling, test corpus | 2–4 days | 3–5 days |

**Python: ~2 weeks** for a solid library — `struct`, `base64`, and `json` cover
most of it; the merge algorithm and the conformance edge cases dominate the time.

**C++: ~3–4 weeks** — no extra conceptual difficulty, but manual buffer
management, alignment-safe `u64`/`i64` loads (the spec correctly warns these are
only 4-byte aligned), endianness handling, and the lack of built-in base64/JSON
all add steady overhead. RFC-1982 arithmetic and the topo sort are the only
correctness-sensitive parts and are equally easy in both.

The *spec* is not the bottleneck for either language — the byte-level detail is
good enough to code against. The risk to a clean-room implementation is the
handful of ambiguities above (especially G1, G2, I1), each of which would
otherwise be resolved differently by different implementers and break
interoperability.

### Suggested improvements (prioritised)

**Must-fix before calling it 1.0 (interoperability hazards):**

1. ~~**Resolve the raw-in-decoded-file contradiction (I1).**~~ **DONE** —
   resolved by the [Undecoded block](#resolution-undecoded-block-i1-and-g1):
   derived files carry no `boundary = 0` records, and undecoded regions are
   references, not raw bytes.

2. ~~**Give the Gap block a defined offset space (G1).**~~ **DONE** — the
   Undecoded block carries an explicit `source_id`; `spans` is now Record-only.

3. ~~**Make the JSONL key mapping authoritative and complete (G2).**~~ **DONE** —
   adopted the deterministic rule (registered name = JSON key; only unrecognised
   data uses `options`) plus value-encoding rules; see
   [G2 resolution](#resolution-jsonl-key-mapping-g2).

**Should-fix (prevents likely-wrong implementations):**

4. **Publish the closed set of repeatable option ids (G3)** and state how `spans`
   (single value, many entries) differs from a repeatable option. *Why:* a
   generic TLV reader otherwise silently drops inner tunnel endpoints.

5. **Add one sentence on span id-namespaces (G4):** a span's `session_id`/`pid`
   are in the referenced source's namespace, not the current file's.

6. ~~**Decide what `boundary` is (I3 / §7).**~~ **DONE** — removed `boundary`
   outright; a record is decoded iff it carries a `decoder_id` (single source of
   truth, zero redundancy). See
   [I3 resolution](#resolution-boundary-removed-i3-7).

**Nice-to-have (clarity / robustness):**

7. **State the merge algorithm's intended scale / windowing** and acknowledge
   that the known-skew tie-break is permitted-divergent across conformant
   readers.

8. **Specify `prim:` width-vs-payload-length** behaviour (G5): MUST the payload
   equal the token's implied width, and what does a reader do otherwise?

9. **Tighten the prose** in the narrative sections — fewer restatements of the
   same idea — and unify the span field-order presentation (I2). The normative
   section needs no trimming; the explanatory sections do.

10. **Note that `isn` is purely informational** at its definition site so
    implementers know it carries no behaviour, and decide whether it earns its
    place in a minimal v1.0.

## Follow up questions

**Q**: I've been thinking about how to handle the (naive) complexity of O(M*N) for the merge algorithm for readers. Given that I suspect that the typical use-case will be to read zpf-files alot more often then writing them, it would be a good idea to try to move that complexity to the writer, making reading fast and simple. How could that ne done? Please analyse this.

**A**: Good instinct — and the asymmetry is even more favorable than "read more often than write" suggests. The writer isn't just a place to move the cost to; it's a place where the cost is fundamentally cheaper. Let me lay out why, then give you a spectrum of mechanisms from "almost free" to "reader does zero ordering work."

### Why the writer is in a strictly better position

The reader faces O(N·M) **only because of one rule**: `payload-format.md:844-848` says on-disk block order is unconstrained, so a reader handed an arbitrary pile of records can't assume anything and may compare records all-pairs to discover edges.

The writer never has that problem:

- It processes packets in **capture order**, and TCP acks/seqs advance monotonically. So a record becomes "settled" (nothing future can precede it) once both directions have advanced past it — which happens within roughly one **in-flight window / RTT**, not the whole session.
- That means the writer can produce causal order with a **bounded reorder buffer** (≈ bandwidth-delay product), in near-linear time, without breaking the flush-and-forget / bounded-memory goal.

So this isn't shifting an O(N·M) cost onto the writer — it's replacing it with an O(N)-with-small-window cost, paid once, by the party that's already streaming in the right order.

### A spectrum of three mechanisms

Think of it as three levels; you can stop at whichever cost/benefit point you like.

**Level 1 — Constrain on-disk order (almost free, no new fields)**.
Add one SHOULD/MAY: within a participant, records are stored in seq_start order (the writer already has them that way — it's the participant's own monotonic byte stream). That single guarantee collapses the reader's job from all-pairs into a streaming k-way merge: keep one frontier watermark per participant, release a record when every peer record with seq_end ≤ ack has already been emitted — an O(1) amortized check per record, so ~O(N) total with a bounded window. The reader still implements the merge, but it's the cheap, simple version, and memory stays bounded. This alone kills the quadratic blow-up.

**Level 2 — Stamp a total-order ordinal (additive, backward-compatible)**.
Add an optional per-record order TLV: a u64 (scoped per session) giving a total order consistent with the causal partial order, with the writer's tie-break already applied. A reader that sees it ignores seq/ack entirely and orders by a single scalar — one linear pass (or one sort key). A reader that wants to verify, or a file that lacks the field, falls back to Level 1. This is purely additive ("new TLVs, old readers ignore"), keeps physical storage order free for other purposes, and the merge algorithm becomes optional in readers.

**Level 3 — Physical order is causal order + a "sequenced" flag (zero reader ordering logic)**.
A File Header flag (or a distinct conformance profile) asserting: *records are stored in a causally-valid total order*. A conformant reader then reads **sequentially, no ordering code at all** — the tricky algorithm exists only in writers and merge tools, never in the read path. This is the strongest version of your goal: a minimal reader never implements the merge.

These compose: Level 3 is Level 1 + "and I committed to a global interleaving"; Level 2 is the "keep storage order separate" variant of the same commitment.

### The two capture cases map cleanly onto this

- **Single tap sees both directions (the common case)**: the writer does Level 1/2/3 inline with a bounded reorder buffer, as described. No architectural change.
- **Two separate files, skewed clocks (the showcase case)**: no single per-direction writer can merge — it doesn't see the peer. But that's already a transform in this format's worldview. Make it sideA.zpf + sideB.zpf → merged.zpf, exactly analogous to the existing raw.zpf → decoded.zpf decode transform (reuse Source(kind=zpf-input), digest, provenance). The merge tool reads two per-participant-ordered inputs, does the cheap streaming 2-way merge once, and emits a Level-3 sequenced file. Every downstream reader of merged.zpf then pays nothing. The O(N·M)-prone logic lives in one tool, not in every reader.

### Keep seq/ack anyway — this is additive, not a replacement

Don't drop the seq/ack fields when you add ordering:

- Verification / trust: a paranoid or re-deriving reader can confirm the writer's order is actually causal.
- Concurrency fidelity: a baked total order discards the "these two were genuinely concurrent" information. seq/ack lets a reader that cares recover the true partial order; the ordinal/flag is just a convenience linearization on top.
- Re-merge: if the raw inputs change, you re-run the transform from seq/ack.

### Two side benefits worth noting

1. **It fixes my "permitted divergence" reservation for free**. Today, concurrent-records-under-known-skew fall back to a writer-chosen "round-robin / source order," so two conformant readers can disagree. If the writer commits to the tie-break (Levels 2/3), all readers agree by construction — ordering becomes deterministic.
2. **It lets you define a lightweight conformance class**. A "sequenced .zpf" profile guarantees the order is present and correct, so a minimal reader can refuse to implement the merge at all and reject non-sequenced files — useful for constrained consumers.

### The one real cost to weigh

The writer must hold a reorder window before emitting (bounded by in-flight data — small, preserves flush-and-forget), and Levels 2/3 mean the reader trusts the writer (mitigated by keeping seq/ack for verification). And note Level 1 doesn't remove the merge from readers — it only makes it cheap; only Levels 2/3 let readers skip implementing it.

### My recommendation

Adopt **Level 1 as a SHOULD unconditionally** (almost free, removes the quadratic for everyone, no format change beyond one ordering rule) and **Level 3 as an optional "sequenced" profile / File Header flag** for the read-often workflow you're optimizing — with the separate-file merge defined as a transform that produces such a file. That gives you: cheap reads always, zero-ordering-logic reads when you want them, the algorithm confined to writers/merge-tools, deterministic tie-breaks, and full backward compatibility with seq/ack retained for verification.

Want me to draft concrete spec text for this — the Level-1 ordering rule, the order TLV + "sequenced" flag, and a short "Merge transform" subsection mirroring the decode transform — and fold a condensed note into the review's improvements list?

### Resolution — adopted into the spec

This was acted on. `docs/payload-format.md` now implements **Level 1 + Level 3**
(Level 2's per-record ordinal was deliberately *not* added — Level 3's "physical
order = causal order + flag" reaches the read-cheap goal without a new per-record
field):

- **Level 1 (unconditional SHOULD).** "Identifiers & ordering" now says a writer
  SHOULD store each participant's records in `seq_start` (logical stream) order;
  the "Merge algorithm" section gained a *cost* note explaining this collapses a
  reader's merge into a streaming k-way merge (~O(N), in-flight-window memory) and
  that the merge is optional, consumer-side work.
- **Level 3 (optional sequencing).** A new "Sequenced files (precomputed order)"
  subsection, plus two **distinct, orthogonal** flags:
  - **`SEQUENCED` — per *session*** (Session Descriptor `flags` option, bit
    `0x0001`; TLV `0x0052`): this session's records are stored in valid causal
    order, so a reader skips the merge for it. Marked per session because whether
    a session *can* be soundly sequenced is itself per-session (TCP always; a
    hint-less session only under a common clock), so a file may mix sequenced and
    unsequenced sessions.
  - **`SINGLE_CLOCK` — per *file*** (File Header `flags` option, bit `0x0001`; TLV
    `0x0014`): all records share one trustworthy clock (timestamps globally
    comparable, no inter-source skew). A *clock* assertion, not an ordering one.
    Its use case: a raw writer that can't tell several one-way UDP streams form one
    `N`-party session emits them unsequenced, but can assert `SINGLE_CLOCK` so a
    later decoder that regroups them may sequence the regrouped session by
    timestamp soundly.

  The separate-direction case is handled by a **merge transform**
  (`sideA.zpf + sideB.zpf → merged.zpf`) reusing the existing
  `zpf-input`/digest/provenance machinery. Conformance paragraph and JSONL
  mappings (`"single_clock"` on `file`, `"sequenced"` on `session`) updated to
  match.

Two decisions settled during review:

- **Per-session guarantee, confirmed.** SEQUENCED is a *per-session* property:
  TCP sessions are ordered clock-independently from `seq`/`ack`; hint-less
  sessions (chat, one-way UDP) reduce to non-decreasing-timestamp order with a
  fixed tie-break. The spec states a producer **MUST NOT** set SEQUENCED on a
  hint-less session unless all its records share a single trustworthy clock; the
  separate file-level `SINGLE_CLOCK` bit is the file-wide way to assert exactly
  that precondition (and is what a regrouping decoder relies on).
- **`seq`/`ack` kept mandatory in sequenced sessions.** They are retained (not
  dropped to save space) so a reader can still verify the committed order and
  recover the true partial order / genuine concurrency; sequencing is a
  convenience linearization layered on top, never a replacement.

Effect on the items above: this **fully addresses** Nice-to-have #7 (merge scale/
windowing is now documented) and the **first reservation** in §4 (merge cost), and
**resolves** the **second reservation / permitted divergence** for sequenced files
(the producer's fixed tie-break makes all readers agree). Non-sequenced files
retain the original, honestly-stated divergence.

### Resolution: Undecoded block (I1 and G1)

I1 (raw-fallback records contradict the source-kind rule) and G1 (the Gap block
has no `source_id`) were resolved together by **replacing the Gap block with an
`Undecoded` block (`0x21`)** and **disallowing raw passthrough in derived files**.

- **I1.** A derived file now contains **no** `boundary = 0` records, so "raw ⇒
  capture source" never has to bend — raw records live only in raw files. A region
  a decoder could not parse is recorded as an `Undecoded` *reference* (it carries
  no bytes), not copied back as a raw record. The conceptual-model and conformance
  prose were rewritten accordingly ("decoded records + Undecoded markers; no raw
  records in derived files"), and a **coverage guarantee** added: within each input
  participant stream, every offset is covered by some decoded record's `spans` or
  by an Undecoded block.
- **G1.** `Undecoded` carries an explicit `source_id` naming the `zpf-input` whose
  logical offsets `off_start`/`off_end` index — resolving the multi-input
  ambiguity. `spans` is now Record-only (no competing mechanism).
- **Gap = the no-data case.** `reason` distinguishes `undecodable` (bytes exist
  upstream, recoverable by walking the provenance chain to the raw file) from
  `tcp-gap`/`truncated` (the offset range is a hole, no bytes anywhere). A plain
  gap is just an Undecoded block with a no-data `reason`.

Trade-off accepted in the process: a derived file no longer stands alone for the
*bytes* of undecoded regions — recovering them is a one-level-at-a-time walk back
toward the raw file (a missing intermediate stops it). The "stands alone" claim was
softened to cover decoded content only. Two supporting clarifications also landed:
the **offset space is hole-inclusive** (a gap occupies an offset range — now stated
normatively, which the unification relies on), and **raw-file gaps stay implicit**
(a sequence-number discontinuity; a decoder writer reconstructs them via software
support and emits explicit Undecoded blocks in the derived file).

This closes the two most serious findings (I1, G1). Remaining open from the
original review after this, the G2 work, and the I3 work below: G3/I2 (option
repeatability & span field order), G4 (span id-namespaces), G5/#8 (`prim:` width),
and the prose-tightening item.

### Resolution: JSONL key mapping (G2)

G2 (the JSONL face had no implementable key contract and contradicted its own
examples) was resolved by replacing the incomplete mapping table with a
**deterministic rule plus a short exceptions list** in
`### JSONL ↔ binary field mapping`:

- **The rule.** A block's JSON keys are the **canonical names** of its binary body
  fields and registered TLV options (verbatim), except for the brevity aliases.
  Anything registered MUST use its canonical key and MUST NOT go in `options`;
  only *unrecognised* data (future option ids, `Custom` contents) uses a generic
  `options` array. This makes the mapping complete-by-reference to the option
  registry, so it can't drift as options are added.
- **Closed alias list** (the only name-differs cases): `format`, `time_units`,
  `ts`, `pid`, `key`. Corrected the old table's mislabelling of `proto` as an
  alias (it's identity).
- **`type` ↔ block-id table** added (was previously implicit).
- **Value-encoding rules** added — the other half of the gap: 64-bit ints MAY be
  number or decimal string (string SHOULD be used above 2⁵³, reader accepts both);
  enums as string labels (`kind`, `tcp_role`), with `boundary` kept numeric as a
  deliberate, acknowledged asymmetry (likely revised later); flag bitfields by
  name (file/session single bits as booleans, Record `flags` as an array of
  set-bit tokens — tokens added to the flags enum); repeatable options as ordered
  arrays; absent option ⇒ omitted key.
- **Forward-compat clause** added: converters MUST round-trip unknown `type`
  strings, unknown keys, and unregistered options (via the `options` array),
  mirroring the binary skip-by-length rule.

Deferred at the time: the `boundary` string-vs-number asymmetry — since resolved
by removing `boundary` entirely (see below), so the JSONL projection no longer has
a `boundary` key at all.

### Resolution: `boundary` removed (I3, #7)

I3 (the `boundary` field was described two incompatible ways — a meaningless
discriminator *and* a reserved 2–255 range) and slimming item #6/§7 were resolved
by **removing the `boundary` field outright** rather than the recommended
flag-bit: since `boundary ≥ 1` was already a strict biconditional with "carries a
`decoder_id`," the field was pure redundancy.

- **New rule:** a record is *decoded* iff it carries a `decoder_id` — one source
  of truth, zero redundancy, no consistency invariant to violate (a flag bit would
  have re-introduced a milder version of the same smell).
- **Binary:** the Record body's `boundary:u8` + `_reserved:u8` become a single
  `_reserved:u16`; every offset and the 28-byte body size are unchanged, so the
  worked hex example and its 204-byte total still hold (only the annotation
  changed).
- **Removed** the `boundary` enum and the speculative 2–255 range; rewrote the
  conceptual model, Decoder/typing sections, and conformance to key on
  `decoder_id` presence.
- **JSONL:** the `boundary` key is gone from the mapping and every example; the
  G2 "boundary stays numeric" exception was deleted. Raw records simply omit
  `decoder_id`; decoded records carry it.

This also retires the one asymmetry the G2 work had to defer.