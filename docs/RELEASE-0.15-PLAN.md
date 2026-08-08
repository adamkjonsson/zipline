# Release 0.15 — implementation plan

*Written 2026-08-06 against **v0.14**, the four issues carrying the `0.15`
milestone, and [#78](https://github.com/adamkjonsson/zipline/issues/78) — the one
comment python-zipline returned on its `0.14` implementation. This is a working
roadmap, not normative text: it says what to change, in what order, and what
"done" means.*

---

## What this release is

**A feature release, and the one that changes what existing files mean.** `0.11`,
`0.12` and `0.14` were corrective; `0.13` shipped the corrective third of #41.
`0.15` finishes #41 — the parts that rewrite the conceptual model rather than
patch it — and closes the hole python-zipline found in what `0.13` shipped.

| Issue | Title | Kind |
|---|---|---|
| [#78](https://github.com/adamkjonsson/zipline/issues/78) | Discontinuities that appear when filtering records | spec, **high** |
| [#53](https://github.com/adamkjonsson/zipline/issues/53) | F0 — provenance and layer as independent axes | spec |
| [#54](https://github.com/adamkjonsson/zipline/issues/54) | F1 — sessionization as a reassembly decoder | spec, **new syntax** |
| [#55](https://github.com/adamkjonsson/zipline/issues/55) | F2 — tunnel worked example and fixtures | vectors |
| [#41](https://github.com/adamkjonsson/zipline/issues/41) | Decrypted tunnels: key the offset space on what a stream is | closes with #55 |
| [#42](https://github.com/adamkjonsson/zipline/issues/42) | Candidate: require `sequenced_basis` on every `SEQUENCED` | **closed, not adopted** |

**Expect the largest `Changed` section the format has had.** #78 makes files
conformant under `0.14` non-conformant under `0.15`. F0 and F1 leave every
existing file *byte*-conformant but restate what its records mean. Drafting those
entries is Phase work, not release work — `0.14` learned that the hard way and the
lesson holds double here.

---

## The scope decisions

### 1. #78 is in, and it is not a clarification — it finishes `0.13`

`0.13` shipped the [Discontinuity](zipline-payload-format.md) block to close
Finding 3, the silent splice on `raw → tls-records → http`. It shipped the block
and the duty to *carry one forward*. It did not ship the duty to **originate**
one, and Finding 3 is therefore still conformant.

Every normative statement about emitting the block is conditioned on the input
already carrying one. Sentence-level, there are three:

| Where | Statement | Conditioned on |
|---|---|---|
| §Discontinuity | a consumer MUST NOT treat records either side as contiguous | a block exists |
| §Discontinuity | a decode stage MUST NOT emit a unit whose `spans` cross one without emitting its own | a block exists **in the input** |
| §Discontinuity / §Conformance | a decoded-layer pass-through MUST re-emit every Discontinuity, renumbered | a block exists in the input |

Walk Finding 3 against those. Stage 1 (`tls-records`) loses a TCP segment. Its
input is a transport layer, where a hole is expressed hole-inclusively and a
Discontinuity is **forbidden** — so there is no input block, and none of the three
rules fires. Stage 1 emits an Undecoded `gap` and two records that are *adjacent*
in its concatenation space. Stage 2 reads those two records with nothing to tell
them apart from continuous output, splices them, covers the join completely, and
passes. The block exists, the chain-carrying duty exists, and the head of the
chain is unobliged.

The same hole opens three ways:

- **a decode stage** that declines an input region between two units it emitted —
  Finding 3;
- **a filter**, which drops records and marks the dropped regions Undecoded
  `skipped` (§Layers). Its survivors are adjacent in the output space and do not
  join. This is #78's title;
- **a reordering stage**, which is where `reordered-decoded` demonstrates it: two
  adjacent output records meeting at output byte 50, spanning `[100,150)` and
  `[0,100)` in that order.

**`reordered-decoded` is not a vector defect.** python-zipline is right to file
this against the specification. Per the vectors' ground rule 2 the vector would be
the thing that is wrong — but only if the text said otherwise, and it does not.

### 2. The duty keys on whether two units join, not on unspanned input bytes

#78 leaves this open. It is decidable, and the answer shapes the drafting.

*Settled in Phase 0, together with decision 3, and stated there in its final
form: the key is **do these two units join**, of which withheld content is one
case. The argument below is what led there, and its negative half — why input
coverage cannot be the key — is unaffected.*

**Keying on unspanned input bytes fails in both directions.** It over-triggers on
a TLS decoder that leaves record headers, nonces and tags Undecoded `skipped`:
those bytes carried no stream content, the plaintext either side joins perfectly,
and a rule keyed on input coverage demands a block that would be a lie. It
under-triggers wherever output is continuous but `spans` do not abut, which since
`0.13` is *most* decoders — byte-transforming decode is legal, and overlap is
legal under at-least-once coverage. #78 makes this second point itself: the
`spans` workaround has been unsound since `0.13`.

`reason_class` does not rescue it. Framing bytes are `skipped` and a filter's
dropped records are `skipped`; both are bytes-class, and only one is a break.

**Keying on withheld output content works**, because it asks the producer the one
question the producer can always answer: *did I fail to carry forward content that
belonged between these two units?* Framing bytes withhold nothing. A dropped
record, a declined message, a lost plaintext region withhold something.

**Draft it against offset-space semantics, not against the word "decoded."** The
scope condition is *a stream whose offsets are the concatenation of its record
payloads* — which is what makes a break inexpressible without the block, and is
exactly why a transport layer is exempt. Phrased that way the rule survives F0 and
F1 untouched. Phrased as "a decoded file" it has to be rewritten twice in this
same release, once when F0 separates the axes and again when F1 makes the layer a
declared property.

There is a **checkable core** worth stating separately, because the general duty
rests on producer knowledge and a checker cannot verify it: an Undecoded region of
the **no-data** class (`gap`, `truncated`) lying between the input regions of two
adjacent output units is unambiguously a break — no bytes existed, so no content
can have been carried forward. That is Finding 3 exactly, and it is verifiable
from one file.

### 3. The reordering question — settled in Phase 0: per seam, under one rule

*Answered 2026-08-07, before any wording was drafted, which is what this section
asked for. **A reordering stage emits a Discontinuity at every seam**, and it does
so under the same rule as every other case rather than one of its own. What
follows is why the first answer won and what the other two got wrong; the
candidate table is kept at the end, unedited, as the record of what was weighed.*

**The rule Phase 1 drafts is: a producer MUST emit a Discontinuity between two
adjacent output units that do not join in the content its output represents.**
One sentence, no carve-out. Decision 2's withheld content is the sufficient
condition, not the key — the key is *do these two join*, and it settles all four
shapes without a second concept:

| Shape | Do they join? | Block |
|---|---|---|
| Framing bytes, nonces, tags left Undecoded `skipped` | yes — the plaintext joins perfectly | no |
| Finding 3: a no-data region between two output units | no — content is gone | yes |
| A filter dropping a record | no — content withheld | yes |
| A reordering stage's seam | no — they were never adjacent | yes |

**The specification had already committed to this reading**, in §Discontinuity:
"What the block asserts is not a length. It asserts that the two sides **do not
join**." `reordered-decoded`'s two records assert that they join, and it is false.
Exempting reordering is therefore not a narrowing of #78 but a retreat from a
sentence that shipped in `0.13` — and it costs the withheld-content half too: if an
unmarked seam stops meaning *these join* it can only mean *nothing was withheld*,
which turns the block from an invariant into a hint.

Two arguments in the table below do not survive contact, and are corrected here
rather than deleted, because both were load-bearing:

- **"A compression can be added later — minor-compatible even after `1.0`."**
  False for this option. A reader that does not recognise an option id retains it
  and *ignores it semantically* (§Unrecognised data), so a `1.0` reader meeting a
  participant-level assertion skips it and splices — the exact failure. That is the
  `0x22` block's situation verbatim, and the specification already states it for the
  block: not safe to skip, a **major** bump after `1.0`. The wholesale option is
  free now, in `0.x`, and only now. Deferring it is still right; "we can always add
  it later" is not the reason.
- **"Two adjacent messages never concatenated into anything."** Not for the
  protocols driving this. Pipelined HTTP/1.1 responses and successive TLS
  plaintexts *are* concatenated on the wire, and a decoded stream's offset space is
  defined as that concatenation precisely so a stage 3 can re-frame across a message
  boundary — the case §Discontinuity was written about. The unit-set stream where
  adjacency means nothing is real, but hypothetical, and it is a better argument for
  the participant-level assertion than reordering ever was.

**There is no checkable core for the reordering half**, and looking for one is
what confirmed decision 2's `spans` argument. The obvious candidate — consecutive
records whose spans run *downward* cannot join — is wrong, and F1 is the
counterexample: a reassembly decoder fed out-of-order packets emits descending
spans over output that joins perfectly. So reordering rests on producer knowledge,
the no-data class stays the one mechanically verifiable rule, and checkability does
not separate the two leading answers.

**Cost, measured rather than feared.** `reordered-decoded` has two records and one
seam: one block, and one added line in its `.jsonl`. `N-1` is the fully-reversed
worst case, which nothing in the suite and nothing python-zipline reported
produces.

The participant-level assertion is **deferred, not rejected**, and filed as
[#80](https://github.com/adamkjonsson/zipline/issues/80) with the pre-`1.0`
deadline in its body — the same treatment #42 got, and for the same reason: no
evidence of necessity yet.

The three candidate answers as they were weighed, and what would settle each:

| Answer | Cost | What would make it right |
|---|---|---|
| **Per-seam block.** Every seam between units not adjacent in the input gets one. | `N-1` blocks on a fully reversed stream; `reordered-decoded` gains one and its `.jsonl` changes | Reordering stages are rare and their streams are short, so the noise is theoretical. Needs no new syntax, and a compression can be added later — a new option is minor-compatible even after `1.0`, whereas an unstated duty is the defect being fixed |
| **A participant-level assertion.** One option declaring the stream a unit sequence whose stored order is not stream order, discharging the per-seam duty wholesale. | A second new option, in a release already adding F1's | It is arguably truer: the stream's contiguity claim is void as a whole, not at `N-1` individual points. Also the honest model for a decoded stream of discrete messages, where adjacency never meant concatenation |
| **Exempt reordering entirely.** The duty covers withheld content only. | none | A reordered stream never claimed contiguity, so nothing is being hidden. Leaves `reordered-decoded` shipping as an unmarked splice, which is the thing #78 objected to |

The question underneath all three, and the one answered first: **what does
"contiguous" mean for a decoded stream of discrete units?** The answer is that
adjacency asserts the two units join in the content the output represents — which
§Discontinuity already said, and which the offset-space definition already relies
on. The distinction this section hoped might hold, that two adjacent `http`
messages never concatenated into anything, does not: pipelined responses
concatenate, and re-framing across a message boundary is the downstream case the
block exists for.

### 4. #42 closes, not adopted

It has been filed as *a candidate, not a commitment, pending evidence of
necessity* since `0.12`. Three releases and one full external implementation later,
no evidence has arrived — python-zipline implemented `0.14` and returned exactly
one comment, and it was #78.

#53's rationale for co-scheduling it with F0 was that implementers should absorb
compatibility breaks in a single migration. That argument says *if* it happens,
`0.15` is where — it does not say it should happen. Adding an unmotivated
conformance break to the largest breaking release the format has had inverts the
argument's own logic.

It closes into **§Design decisions not taken**, which is where the specification
already keeps this reasoning, with the gap it identified recorded honestly: a
mostly-unhinted `SEQUENCED` session is not hint-less, so no basis is required, and
a consumer's loss is legibility rather than correctness. If that ever bites, the
issue body is the record of the analysis and reopening costs nothing.

### 5. F2 stays in scope

The relief valve, if one is needed, is F2 — it is fixtures, not normative text.
Take it anyway, for the reason `0.14` built #70's coverage tool first: F1 adds an
option and an enum, and a capability whose first exercise is the *next* release is
how #66 happened. #70's tool will fail the release if F1's layer enum reaches
Phase 5 unexercised, and that failure is the point.

**But F1 ships its own minimal vector, and does not wait for F2.** A single
sessionization-stage vector in Phase 3 keeps the suite honest phase by phase and
makes F2 a worked *example* rather than the first proof that F1 is implementable.

### 6. #54's open coordination with #36 is already settled

#54 asks that F1's reassembly `params_digest` be reconciled with #36 "deliberately,
not by arrival order." #36 shipped in `0.13` as `transform_params_digest`, scoped
in the option registry to *a transform that produced records **without decoding***
— a filter, a reordering stage, a merge — with the explicit note that a decode
stage's config lives on its Decoder.

F1 makes reassembly a **decoder**. So its config goes on `params_digest`, the
boundary is already drawn in normative text, and neither mechanism is redundant.
Record the decision and move on; do not reopen it.

---

## Dependencies

```
Phase 0 decision: what "contiguous" means for a unit stream
        └──▶ #78's wording, and whether reordering is in it

#78 ──▶ independent of F0/F1 by design (drafted against offset-space
        semantics, not file kind), so it lands first and finishes 0.13

#53 (F0) ──▶ #54 (F1) ──▶ #55 (F2) ──▶ closes #41
   axes         layer         tunnel
   separated    declared      chain
```

**F0 before F1 is the ordering #41's analysis argues for and it is not merely
tidy.** F0 states that provenance and layer are independent; F1's new option is
what gives the layer axis somewhere to be written down. Shipping F1 first means
adding the option and then immediately restating what it means.

**#78 before F0 is a choice, not a constraint.** F0 rewrites 101 occurrences of
"raw" and will sweep #78's paragraphs along with everything else, so the cost of
going first is one paragraph re-read — provided decision 2 is honoured and the
rule is keyed on offset-space semantics. The benefit is that the one finding an
external implementation actually reported does not sit behind the largest
restructure in the format's history.

---

## The questions F1 must settle

#41's analysis left these explicitly unchecked. Each blocks F1 and none has an
owner yet; answer them in Phase 3 as they arise, and record the answers.

- ~~**Is `isn` already legal on a derived participant?**~~ *Answered: yes, and the
  scoping was the bug. `isn`, `seq_start` and the `message` flag now bind on the
  **layer**, in a statement of their own, rather than sitting inside the
  capture-sourced bullet where they read as provenance requirements.*
- ~~**F1 against the merge and `SEQUENCED`.**~~ *Answered by walking it: a
  sessionization stage's records carry `seq_start`/`ack`, so its sessions are **not
  hint-less**, need no `sequenced_basis`, and merge exactly as a capture's do. Said
  so in §Sequenced files, because records carrying a `decoder_id` invite the
  opposite guess. **The walk found a real gap:** the pass-through duty to carry
  `decoder_id` forward and re-declare Decoder Descriptors was keyed on "preserving a
  decoded layer", which F1 makes wrong — a transport stream whose reassembler
  declared itself would have lost its Decoder across a merge, silently changing the
  layer its output reads as. Now keyed on the decoder, not the layer.*
- ~~**F0 against `check.py`.** The checker classifies *files*; F0 makes the property
  per *stream*.~~ *Answered in Phase 2, and the premise was wrong: the checker
  classifies nothing. See the Phase 2 note.*
- ~~**Should the head-of-pipeline reassembler declare itself?**~~ *SHOULD, as
  expected, and the asymmetry is written into §Conformance with its consequence
  spelled out: a consumer cannot conclude that an undeclared transport stream had no
  reassembler, only that none was named. Vector `reassembler-declared`.*
- ~~**A reassembly decoder's `content_type`.**~~ *Absent, with the reasoning in
  §Typing a decoded record rather than only in the analysis — plus the contrast that
  makes it legible, a packet-preserving stage, which does type its records and with
  a `dec:` token.*

---

## Phases

### Phase 0 — stamp, tooling, and the two decisions

1. `MAJOR, MINOR = 0, 15` in `vectors/build.py`; `check.py` to match; regenerate;
   the spec's version sites; open `## [0.15] — unreleased`.
2. Confirm `reject-unknown-minor` rolls 15 → 16 on its own. It derives `MINOR + 1`
   so it should — and `0.13` shipped precisely because that vector silently became
   valid, so deriving it is only proved by checking it.
3. Run #70's coverage tool as a **baseline**, before anything moves. *Recorded at
   `0.14`: 37 options, 12 blocks, 9 rules, all exercised; unchanged by the stamp.*
4. **Settle the reordering question** (decision 3). Nothing in Phase 1 can be
   drafted until it is answered. *Answered: per seam, under one "do they join"
   rule; the wholesale option deferred to #80. Decision 3 carries the reasoning.*
5. **Close #42** with its §Design decisions not taken entry.

Stamp first. Every later phase regenerates the tree, and bumping at the end lands
one large mechanical diff on top of the diffs that need reading.

### Phase 1 — #78, the origination duty

The one finding from an external implementation, and the completion of `0.13`'s
C3. Drafted per decisions 2 and 3, against offset-space semantics.

Ships with its vectors, in the same change:

- an **`isolate`** vector for the unmarked break — a decode stage with a no-data
  Undecoded region between two adjacent output units and no Discontinuity. This is
  Finding 3 as a file, and it is the vector that would have caught the gap;
- an **`accept`** vector for the same stage doing it correctly;
- a **Discontinuity at `reordered-decoded`'s one seam**, per Phase 0's decision.
  Its `.jsonl` gains a line and its bytes change; the descending `spans` that vector
  exists for are untouched.

New `RULES` entries in `check.py` for the duty. Note that `discontinuity-no-splice`
already exists and is exercised by `splice`; the new rule is its origination half,
and the two should read as a pair.

*Shipped, with one substitution worth recording. **The accept vector this phase
called for already existed**: `discontinuity-unknown-width` is Finding 3's stage 1
done right — same decoder, same lost segment, block present — so
`isolate-unmarked-break` is that file with the block deleted, and the two ship as a
pair rather than as a vector and its duplicate. The freed budget went to
`filtered-decoded`, the shape #78 is actually titled after and the one nothing in
the suite exercised: a filter, where `skipped` does its second job. Two `RULES`
entries, `discontinuity-origination` and `discontinuity-reordering`. Two `reason`
values added to the open vocabulary, `records-dropped` and `reordered`.*

*One limit found while verifying: `check_capability_coverage` can only confirm that
the vector a rule **names** exists — it cannot tell whether that vector exercises
the rule. Pointing a rule at the wrong vector passes. That is inherent to declaring
rules by name and is not worth fixing, but it means `RULES` is a statement of
intent that a human still has to keep true.*

### Phase 2 — F0 (#53), the axes

Prose only, no wire change, every existing file stays byte-conformant. It rewrites
the conceptual model, the goals, the terminology paragraph and §Conformance, and
retires "raw" as a normative term across 101 occurrences.

Two scoping notes:

- **Rename the prose, not the vectors.** `raw-minimal` and
  `isolate-discontinuity-in-raw` are identifiers that external harnesses reference
  by name. Renaming them buys consistency and costs every implementation a
  breakage that the release notes cannot express. The vectors' README explains the
  vocabulary; the directory names stay.
- **~~`check.py` classifies per stream from here on, not per file.~~** *Wrong, and
  corrected in execution: `check.py` has no classifier and never had one. It walks
  frames, checks declared tiers and violation counts, verifies capability coverage
  and does `chain/` arithmetic — adjudicating semantics is the thing its own
  docstring says would make it a second normative authority. **The per-file
  classification was a sentence in the specification**: §Conformance's "Files come
  in two kinds, told by their Sources." That sentence is the deliverable, and it is
  now per stream. The §F1-questions list repeats the same misreading.*

*What F0 actually cost `check.py`: four `RULES` entries, one per permission it
opens, and the four vectors they name.*

*Two further notes from execution.* **"raw" was three words, not one.** Of the 101
occurrences only about half were the normative term. Ordinary English — "raw TCP
segment stream", the `prim:` vocabulary's "raw byte string", an unlabelled enum's
"raw number" — stays, as do the identifiers `raw.zpf`, `raw-minimal` and
`isolate-discontinuity-in-raw`. Sorting the three classes is most of the sweep, and
what makes it checkable afterwards.

**Lifting "never a mix" turned out to be a simplification.** §Conformance already
stated the discriminator per record — `spans` versus `origin` — so the file-level
"exactly one, never a mix" was strictly stronger than the rule it introduced.
Dropping it removed a redundancy and a real loss: a stage with a decoder for one
protocol and not another had to pass everything through or mark the second stream
entirely Undecoded, dropping those bytes. It also made intra-file derivation
reachable for the first time, which is why that prohibition is now written down.

### Phase 3 — F1 (#54), reassembly as a decoder

The only item in this release carrying new syntax: one Decoder Descriptor option
naming the layer a decoder emits, one enum. The rule becomes *layer = decoder
present ? the decoder's declared layer : transport*, so files with no decoder are
unaffected.

The cost is the discriminator: "a record is *decoded* iff it carries a
`decoder_id`" is stated in five places and each becomes two questions — is there a
decoder (identity), and what layer does it declare (semantics). Treat this the way
`0.14` treated #63: **one normative statement, the rest referring to it.** Fixing
four of five sites is how #63 happened, and the restatement grep is line-sensitive,
so grep for the rule and then read the section.

The new enum joins Source `kind` as load-bearing: a reader that does not recognise
the value cannot compute the stream's offsets and MUST NOT guess.

Ships a minimal sessionization-stage vector (decision 5) and the answers to the
§F1 questions above.

*Shipped as **`output_layer`, a u8 enum in the Decoder Descriptor body** —
`0 = decoded`, `1 = transport`. Three vectors: `sessionization-stage`,
`reassembler-declared` for the SHOULD, and `isolate-unknown-output-layer` for the
load-bearing enum.*

***It shipped first as a TLV option (`0x0044`) and moved into the body on a
question asked afterwards: what would making it mandatory cost?** Measured: the
option cost 8 bytes — 4 of TLV header, 1 of value, 3 of padding — and the body cost
**nothing**, because the descriptor already carried a spare `_reserved` u16. But
the size was never the point. The body form makes the field unconditional, which
removes the "absent means `decoded`" default a load-bearing field should not have
had, and it is free only while the format is in `0.x` — §Design decisions not taken
already records that a body-layout change costs a major bump after `1.0`.*

***The compatibility argument that had chosen the option form turned out not to
distinguish them.** A reserved field MUST be written 0, so numbering `decoded = 0`
means every Decoder Descriptor ever written already holds the value that says what
it always meant. Verified rather than assumed: all 25 in the suite held 0, and
regenerating changed **no `.zpf` byte at all** — only `.hex` annotations and the 19
`.jsonl` projections, which gain the key. The transport-layer decoder blocks got 8
bytes smaller, 64 → 56.*

***This is the one candidate that escapes §Design decisions not taken's objection
to promoting options.** That entry rejects promotion because every mandatory option
in the format is *conditionally* mandatory, so each would need a sentinel for
absent, and absence carries meaning. An unconditionally mandatory field has no
absent state to encode.*

***There were five restatement sites, not four, and the fifth was found by the
grep-then-read step rather than by the grep.*** *§Decoder Descriptor's "Every
decoded record carries an explicit `decoder_id` — its presence is what makes the
record decoded" is nowhere near the other four, contains none of the phrases the
obvious grep uses, and is exactly the claim F1 falsifies. This is #63's shape a
second time, caught this time because the verification step said to read the
sections rather than trust the grep.*

***Two defects F0 shipped, fixed here.*** *Both keyed the layer on provenance —
the defect F0 existed to remove — and both contradicted `proxy-decoded`, the vector
Phase 2 shipped: §Layers' "a **transport** stream — one reassembled from a capture"
and "A **decoded** stream … exists only as a decode stage's output" (the sentence
#53 quotes as the gap), and §Decoder Descriptor's "Files carrying a decoded layer".
Phase 2's sweep keyed on the word "raw" and neither sentence contains it.*

***The merge walk found a real gap rather than confirming a guess.*** *The
pass-through duty to carry `decoder_id` forward and re-declare Decoder Descriptors
was keyed on "preserving a **decoded** layer". Under F1 that is wrong: a transport
stream whose reassembler declared itself would lose its Decoder across a merge,
silently changing the layer its output reads as. It is now keyed on the decoder,
not the layer. Worth noting because the plan listed this walk as a confirmation
step.*

### Phase 4 — F2 (#55), the tunnel

The worked example and the fixture: `raw(tunnel) → packets → inner transport →
http`, with inner streams carrying `isn`, `seq_start` and real gaps. Four files —
the largest fixture the suite has had, against `chain/`'s three and `splice`'s two.

`0.14` generalised the multi-file build shape for exactly this, and predicted F2
as its third user. Use it. Keep the checking side specific, as `check_chain()` is.

Closes #55 and #41.

*Shipped. `0.14`'s prediction held: `fixture()` and `member()` carried a four-file
chain with no builder change at all. `check_tunnel()` is specific as instructed and
reuses only `merge_ranges()`.*

***The fan-out landed at the reassembler, not the decryptor**, which is where it
belongs and was worth getting right: a WireGuard decryptor emits inner IP packets
and knows nothing about flows; the reassembler is what groups them by 4-tuple. So
`packets.zpf` holds one stream and `inner.zpf` fans it into two sessions — one
input participant stream, two output sessions, neither covering `[0,150)` alone.*

***The hop that justifies the whole release is `inner.zpf` reading
`packets.zpf`'s Discontinuity.** It is a transport stream, so it may not emit one.
It takes the other path §Discontinuity spells out — no record crosses the break, the
crossing is left undone — and the loss survives as a TCP sequence gap instead. That
is the only place in the document where a stage that *cannot* carry a break forward
is shown doing the right thing, and it needed a fixture to be legible.*

***Two verification notes.** The three new checks were each made to fail on purpose
— a stale digest, an uncovered range, a drifted `input_extents` — and each produced
a usable message before the tree was restored; a fixture checker that has never
failed is not known to check anything. And the plan predicted "52 vectors": wrong,
because the manifest counts a fixture as **one** entry however many files it holds.
46 + 3 fixtures = 49.*

### Phase 5 — changelog, conformance sweep, release

#70's tool over the finished release. Then the sweep, with the restatement grep as
a required step — and read the sections it points at, because a line-wrapped copy
survives the grep.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| #78's duty is drafted against "a decoded file" and F0/F1 rewrite it twice | **medium** | Decision 2 is explicit: key it on offset-space semantics. Check the wording against F0's draft before Phase 2 closes |
| F1's discriminator is fixed in four of its five sites | **this shape already happened, as #63** | One normative statement, the rest referring to it. Grep, then read the section |
| F2 slips and F1's enum ships unexercised | medium | Decision 5: F1 carries its own vector in Phase 3. #70's tool fails the release otherwise |
| The `Changed` section is drafted at release and understates F0/F1 | **medium-high — this is the largest one yet** | Draft each entry in the phase that earns it, per `0.14`'s Phase 2 |
| The reordering question is deferred out of Phase 0 and settled implicitly by whatever gets written | **discharged in Phase 0** | Answered before any wording was drafted; decision 3 records the answer and the two arguments it had to correct |
| F0's scope grows into renaming vectors and rewriting the changelog | medium | Prose in the specification only. Vector names are identifiers; the changelog is history |
| The suite is red across phase boundaries and "green" stops being a signal | **near-certain** | Say so up front, which `0.14` could not: each phase ships its rule *and* its vector together, so red means a phase is unfinished rather than a release being mid-flight |

---

## Definition of done

- [x] #78, #53, #54, #55 closed, each in the commit that finishes it; #41 closed by
      #55; #42 closed as not adopted with its §Design decisions not taken entry.
- [x] A stage MUST emit a Discontinuity when its **own** output breaks — stated
      once, keyed on offset-space semantics, with the no-data checkable core stated
      separately from the producer-knowledge duty.
- [x] Finding 3 has an `isolate` vector. The defect `0.13` shipped the block for is
      now a file that fails.
- [x] The reordering question is answered in the specification, either way, and
      `reordered-decoded` agrees with the answer.
- [x] Provenance and layer are stated as independent axes; "raw" is gone from the
      normative text. *(The `check.py` half of this line was struck: it never
      classified. The specification did, and no longer does.)*
- [x] A decoder declares the layer it emits; "decoded iff `decoder_id`" is stated
      **once** and the other sites refer to it. *There were five, not four.*
- [x] A sessionization-stage vector exists independently of F2.
- [x] The tunnel chain is a worked example **and** a fixture, and it walks.
- [x] `python3 vectors/check.py` green; every vector stamps `0.15`.
- [x] #70's tool reports no option, block or rule added in `0.15` without a vector
      naming it.
- [x] `CHANGELOG.md` `[0.15]` complete, with a `Changed` section covering #78, F0
      and F1 — and honest about the fact that F0 and F1 change what already-written
      files mean.
- [x] Every vector in `manifest.json` appears in `vectors/README.md`.

## What execution changed

*Written at release, not before. The convention of these plans is that a document
only ever read forwards teaches nothing — so this section records what the plan
and the analysis got wrong, and what execution turned up that neither anticipated.*

### Three premises that were simply false

**`check.py` classifies files.** Phase 2's headline deliverable — "`check.py`
classifies per stream from here on, not per file, and it is the change that proves
F0 is real rather than editorial" — was written about code that has never
classified anything. `check.py` walks frames, checks declared tiers and violation
counts, verifies capability coverage and does fixture arithmetic; adjudicating
semantics is what its own docstring says would make it a second normative
authority. The per-file classification was one sentence in §Conformance. The plan
asserted a fact about the tree without opening it, and the §F1-questions list
repeated the same claim, so it was wrong twice in one document.

**A compression can be added after `1.0`.** Decision 3's table argued for the
per-seam Discontinuity partly because "a new option is minor-compatible even after
`1.0`". It is not, for that option: an unrecognised option id is retained but
*ignored semantically*, so a `1.0` reader meeting a participant-level "stored order
is not stream order" flag skips it and splices — the exact failure it would exist
to prevent. The conclusion survived; the reason did not, and the corrected reason
is a deadline rather than a convenience. Filed as
[#80](https://github.com/adamkjonsson/zipline/issues/80).

**Two adjacent `http` messages never concatenated into anything.** Decision 3
floated this as the ground for exempting reordering. Pipelined HTTP/1.1 responses
and successive TLS plaintexts *do* concatenate, and a decoded stream's offset space
is *defined* as that concatenation precisely so a downstream stage can re-frame
across a message boundary — the case §Discontinuity was written about.

### What the phases found that nothing predicted

**The accept vector Phase 1 asked for already existed.** `discontinuity-unknown-width`
*is* Finding 3's stage 1 done right. Building the vector the plan named would have
shipped a duplicate; the freed budget went to `filtered-decoded`, the shape #78 is
actually titled after and the one nothing in the suite exercised.

**There were five restatement sites, not four.** The plan and Finding 7 both listed
four places stating "decoded iff `decoder_id`". The fifth — §Decoder Descriptor's
"its presence is what *makes* the record decoded" — sits nowhere near the others and
contains none of the phrases the obvious grep uses. It was caught by the step that
says to read the sections rather than trust the grep, which exists because of #63.
That step earned its keep; the grep alone would have shipped #63 a second time.

**F0 shipped two defects that F0 existed to remove.** §Layers' "a transport stream —
one reassembled from a capture" and §Decoder Descriptor's "Files carrying a decoded
layer" both key the layer on provenance, and both contradicted `proxy-decoded` — the
vector Phase 2 shipped in the same commit. Phase 2's sweep keyed on the word "raw"
and neither sentence contains it. **A vocabulary sweep is not a semantic sweep**, and
the release plan's own instruction to re-read §Layers against the axes would have
caught them if it had been followed against the offset-space passage rather than only
the paragraphs that had changed.

**Walking F1 against the merge found a defect rather than confirming a guess.** The
plan listed it as an untested-but-expected-fine interaction. The pass-through duty to
carry `decoder_id` forward was keyed on "preserving a *decoded* layer", so a transport
stream whose reassembler declared itself would have lost its Decoder across a merge —
silently changing the layer its output reads as, which is the one thing a
pass-through exists not to do.

### One decision reversed after it shipped

`output_layer` shipped as TLV option `0x0044` and moved into the Decoder Descriptor
**body** two hours later, on a question asked afterwards: what would making it
mandatory cost? Measured, the option cost 8 bytes and the body cost nothing, because
the descriptor already carried a spare `_reserved` u16. The size was never the point.
The body form makes the field unconditional — no "absent means `decoded`" default on a
load-bearing field — and removes the not-safe-to-skip hazard entirely, since a reader
that parses the block parses the field.

**And the compatibility argument that had chosen the option form did not
distinguish them.** A reserved field MUST be written 0, so numbering `decoded = 0`
means every Decoder Descriptor ever written already holds the value that says what it
always meant. All 25 in the suite held 0; regenerating changed **no `.zpf` byte at
all**. Two lessons: a design question answered with a measurement beats one answered
with an estimate, and *§Design decisions not taken* was right that body-layout changes
are free only in `0.x` — this is the last release where that move was available.

### What the tooling did and did not catch

`check.py`'s capability coverage did its job twice, failing the build the moment
`0x0044` was removed from the registry and again when a rule named a vector that did
not exist. But two limits are worth writing down, because both make it a weaker
guarantee than it reads as:

- **It confirms only that the vector a rule *names* exists**, never that the vector
  exercises the rule. Pointing a rule at the wrong vector passes. `RULES` is a
  statement of intent a human has to keep true.
- **It parses the option registry and the block table, not the enum tables.** So
  `output_layer` as a body field is invisible to it, and enum *values* are covered
  only by `RULES` entries naming vectors. Moving an option into a body silently
  removes it from mechanical coverage — worth remembering the next time that trade
  looks free.

### Where the numbers were wrong

Phase 4's plan predicted 52 vectors; the answer is 49, because `manifest.json` counts
a fixture as one entry however many files it holds. Phase 2's plan said "101
occurrences of raw"; the count was right and the *classification* was the work — only
about half were the normative term, and sorting ordinary English (`raw TCP segment`,
`prim:`'s `raw byte string`) and identifiers (`raw.zpf`, `raw-minimal`) from it is
what made the sweep checkable afterwards.

### Left standing, deliberately

- **The coverage guarantee is stated in three places** — §Coverage honesty, §TLV
  framing's overlap clarification, and §Conformance's normative MUST. All three agree
  and `0.15` changed none of them, so they were left alone rather than consolidated at
  release. It is the pattern that produced #63 and it is the next one to watch.
- **[#80](https://github.com/adamkjonsson/zipline/issues/80)**, the participant-level
  ordering assertion, deferred with a `1.0` deadline in its body.
- **The head-of-pipeline asymmetry.** A reassembler declaring itself is a SHOULD, so
  one logical layer is labelled in derived files and usually unlabelled in
  capture-sourced ones. Recorded in §Conformance as deliberate.
