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

- **The merge algorithm is presented but its cost is not.** Step 2 ("for each
  record R… add an edge from every peer record with `seq_end ≤ ack`") is
  naively O(N·M) per session and the topo sort adds more. For long-lived
  high-volume sessions an implementer needs a hint that this is meant to run on
  a sliding window (acks only advance), or they'll either write the quadratic
  version or wonder whether the format is meant for bulk replay at all. A
  sentence on intended scale / windowing would help.
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

### 7. Features that add more complexity than value

- **`boundary` as a `u8` is overbuilt.** Given that meaning comes entirely from
  `decoder_id`, the field is effectively one bit (raw vs decoder-imposed). A
  single `flags` bit would carry the same information and remove the awkward
  "reserved 2–255" range and the I3 ambiguity. This is the clearest slimming
  opportunity. (If a future need for distinct numeric boundary classes is real,
  keep the byte but *define* at least a second value so the range isn't purely
  speculative.)

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

1. **Resolve the raw-in-decoded-file contradiction (I1).** Decide whether
   fallback bytes in a decoded file are `boundary = 0` records referencing a
   zpf-input (and relax the "raw ⇒ capture source" rule accordingly), or whether
   they must be Gaps / passthrough-decoded records. The central model depends on
   this being unambiguous. *Why:* today two readers can legitimately disagree on
   whether such a file is even conformant.

2. **Give the Gap block a defined offset space (G1).** Add a `source_id` to the
   Gap body, or switch Gap to `spans` and drop the inline offsets. *Why:* gaps
   in multi-input decoded files are currently unresolvable from the block alone.

3. **Make the JSONL key mapping authoritative and complete (G2).** Either list
   every field/option's JSON key, or state the rule "registered option name =
   JSON key; only unregistered options use the `options` array." *Why:* the
   "easily consumed face" currently has no implementable contract and contradicts
   its own examples.

**Should-fix (prevents likely-wrong implementations):**

4. **Publish the closed set of repeatable option ids (G3)** and state how `spans`
   (single value, many entries) differs from a repeatable option. *Why:* a
   generic TLV reader otherwise silently drops inner tunnel endpoints.

5. **Add one sentence on span id-namespaces (G4):** a span's `session_id`/`pid`
   are in the referenced source's namespace, not the current file's.

6. **Decide what `boundary` is (I3 / §7).** Recommend collapsing it to a single
   `flags` bit and deleting the "2–255 reserved" range, *or* defining at least
   one more numeric value so the range isn't speculative. *Why:* removes a field
   ambiguity and a small amount of dead complexity.

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