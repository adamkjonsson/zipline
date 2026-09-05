# Release 0.19 — the simplification menu

*Written 2026-09-04, revised 2026-09-05 against **`v0.18-r2`** — the re-issue that
extracted the rationale, which is this release's baseline. Sources are
[SIMPLIFICATION-ANALYSIS.md](SIMPLIFICATION-ANALYSIS.md) and `python-zipline`'s
[SIMPLIFICATION-IMPACT.md](https://github.com/adamkjonsson/python-zipline/blob/main/plans/SIMPLIFICATION-IMPACT.md),
which assesses the same five proposals from inside the only complete
implementation. This is a working roadmap, not normative text.*

*The release is **`0.19`**, not `0.19.0`, per the changelog's Conventions.*

---

## What this release is

**Clarification and simplification, in that order.** The plan opened as a purely
subtractive release. It is not, and the reason is worth stating before the
packages: the document's terms are not pinned, so a reader spends effort
reconciling the vocabulary before ever reaching a rule. Deleting text without
fixing that would remove volume and leave the cost.

So the release does two things, and the first gates the second. It **pins the
terms** and rewrites the text to use them consistently (§Terminology, Phase 0 and
Phase 0b). Then it takes **one** reduction package.

**A subtractive release, and the first one.** Every release since `0.9` has added
or corrected. The package half deletes: an option, a rule, a section, the vectors
that pinned them. Nothing in the repository has been built for that, and
§Mechanics of a deletion release is the part of this plan with no precedent to
copy.

**It takes exactly one of the five proposals.** The analysis recommends 3.1–3.3
as a package and `python-zipline` agrees, but a package is not what this document
is for: taking them one at a time is what makes each one's cost visible, and the
five are independent enough that any single one is a complete release. §If you
take more than one says what changes if you disagree.

**The choice is made in Phase 0 and everything after it follows.** Sections A
through E are five self-contained work packages. Read §The choice, pick one, and
the rest of that package is the release. The other four sections stay in this file
for the release that takes them.

---

## The choice

| | Package | Spec lines out | Vectors | Options | Suite code | What is lost | `python-zipline` |
|---|---|---:|---:|---:|---:|---|---|
| **A** | 3.1 pass-through as a kind | ~150 | −4, 2 rewritten | −1 | small | nothing of substance | support |
| **B** | 3.2 justify the sequencing claim | ~170 | −4 | −2 | small | a forensic hint | support |
| **C** | 3.3 agree on non-conformant input | ~150 | −4 | 0 | small | cross-reader agreement on malformed files | support |
| **D** | 3.4 coverage as a verifiable MUST | ~300 | −6 | −2 | medium | single-file self-verifiability; a decryptor's failure class | support **the middle path** |
| **E** | 3.5 provenance and layer as axes | ~330 | −8 | 0 | **~630 lines** | every multi-hop transform chain's per-hop account, a reassembler's `params_digest` | **oppose** |

Vector counts are exact and the suite is at **59**. The spec-lines column is an
estimate kept for scale only, and it is **not** the basis for choosing: see scope
decision 4 for what extraction did and did not take out of each package, and the
ranking below for what replaces it.

**The last column is not a full assessment for D and E.** `python-zipline` has no
transforming decoder, so its document cannot price what those two do to
decompression and decryption. Scope decision 5 says what the suite shows instead,
and both packages carry the finding. A, B and C are unaffected and its verdicts on
them are complete.

**Rank by whether the rules a package deletes serve a goal the document states**,
not by lines. That is what simplification means here, and the Goals list can now
carry the test: `0.18`'s re-issue added *make a decoding failure findable in the
input's own bytes*, so the principle the analysis said was **not in the Goals
list** partly is.

| | Package | Serves a stated goal? |
|---|---|---|
| **B** 3.2 | sequencing basis | **no** — a forensic hint about a claim |
| **C** 3.3 | advisory tier | **no** — it governs non-conformant input |
| **A** 3.1 | pass-through as a kind | mixed — provenance thinly, the `origin` half is vocabulary |
| **E** 3.5 | provenance and layer as axes | **yes** — reassembled bytes as the source of truth, and findability across hops |
| **D** 3.4 | coverage apparatus | **yes** — findability, by name |

> ***Taken: B.*** *Chosen after one question the plan had not asked — whether the
> property actually wanted is traceability of **where and when** a session was
> ordered. It is, and `sequenced_basis` never provided it; see §Package B's Done
> notes. A, C, D and E remain unstarted and their sections stand for the release
> that takes them.*

**Take B.** It deletes the one thing on this list that serves no stated goal and
that nothing else in the format keys on: two options, four vectors, **no `RULES`
entry**, no rule elsewhere depending on it. `python-zipline` supports it and gives
up a guard rather than a feature. A subtractive release should establish its
mechanics where a mistake is recoverable, and this is now that item on both tests
— cheapest to build, and clearest that nothing of value goes.

*This revises the earlier recommendation of A, which was made on line count and
recoverability before the goal test existed. A remains a good second: nobody has
argued anything is lost, and it deletes an option rather than a rule. It ranks
below B only because part of what it removes does serve provenance.*

The rest, ranked by what they cost to decide rather than to do:

- **A** is the second choice: it deletes an option rather than a rule, and neither
  the analysis nor the implementation has named anything lost.
- **C** is cheap to build and expensive to decide, because it **reverses four of
  the thirteen items `0.18` shipped two days ago** — #113, #114, #115 and #116 are
  the origin floor's edges, and 3.3 deletes the paragraphs that fixed them. That
  is an argument for doing it *now* rather than later, when more will have been
  built on them, and it is also the reason to be sure.
- **D** is the one that changes what the format promises rather than how it says
  it, and it has a sub-choice of its own (§D.1) that scope decision 3 now settles.
  It argues against a stated goal, which is a higher bar than it faced when the
  analysis ranked it.
- **E** is opposed by the implementation it would affect, costs more suite code
  than the other four combined, and reverses a change `0.15` made because
  `zpfwire` asked for it. The analysis says to take it only if tunnels turn out to
  be rare, which nothing currently measures — and the loss is wider than tunnels
  anyway, since it lands on every chain that decrypts or decompresses hop by hop.

---

## Terminology: what the words mean

**The document defines "decoder" once, in its first forty-five lines, and that
definition has been wrong since `0.15`.** §Terminology says the decoder is the
transform "which derives a decoded stream from a transport one". Three things
elsewhere contradict it:

- **A decoder may produce a transport stream.** A sessionization stage is a decode
  stage whose decoder is the reassembler, declaring `output_layer = transport`.
- **A decoder may consume a decoded stream.** `capture → tls-records → http` has
  the HTTP decoder reading a decoded input.
- **A decoder may consume no stream in a file at all.** The TLS-proxy case has a
  decoder with no predecessor `.zpf`.

The same paragraph carries two more artefacts of the pre-`0.15` model. It places
the **reassembler outside the transform family**, as a separate producer stage,
when reassembly is now a decoder. And it says **"this spec defines two"**
transforms — the decoder and the merge — while the document goes on to define the
pass-through, the annotator, the filter and the sessionization stage. That is a
stale count in an enumeration, the defect `0.18` spent a phase on, and **this site
is not one of the six `ENUMERATIONS` declares**.

**No ratchet could have caught it.** `RETIRED_CLAIMS` already holds the pre-`0.15`
model down: the entry retiring *"a byte run carries none"* exists to stop exactly
this idea returning. §Terminology asserts the same superseded model in words that
share no phrase with the pattern — the paraphrase blindness `0.18`'s Phase 0
measured, on the highest-traffic paragraph in the document.

### The definitions this release pins

Grounded in what the document already says where it says it correctly, not
invented. §Conformance carries the real definitions at line ~2680; §Terminology
will **name** the terms and point there, never restate them, because a rule stated
twice is what #120 is about.

| Term | What it is | Stated at |
|---|---|---|
| **decoder** | a named, versioned, parameterised **identity** that a `decoder_id` resolves to, declaring the layer its output is in. Not a stage and not software: a claim about what a stream's units are and what produced them | Decoder Descriptor |
| **decode stage** | a transform that **creates** a layer: its records carry `spans` and reference a `zpf-input` Source | §Conformance |
| **pass-through** | a transform that **preserves** the layer its input had: participants carry `origin`, records carry no `spans` | §Conformance |
| **decoded** | a **layer**, the counterpart to transport. Never a synonym for *derived* | §Layers |
| **transform** | any file → file stage deriving a new `.zpf` from existing ones, and **only** that. Two kinds: decode stage and pass-through. A merge, annotator, filter or sessionization stage is one or the other | §Terminology |
| **frames** | what a decoder does when it gives bytes structure: cutting them into units with edges and a type | §Terminology |
| **recodes** | what a decoder does when it changes the bytes and adds no structure — decompressing, decrypting. Reassembly recodes | §Terminology |
| **reassembler** | a decoder. At the head of a pipeline it reads a capture; over a `.zpf` input it is a decode stage called a sessionization stage | §Conformance |

**Three decisions inside that table, each of which could have gone otherwise:**

1. **`decoder` is an identity, not an operation.** The document already says so —
   *"`decoder_id` names a layer, not a stage"* — in §Referencing, where nobody
   looks for a definition. Foregrounding it is what makes a filter's inherited
   `decoder_id` stop looking like a contradiction.
2. **"Decode stage" is kept despite being a misnomer.** A filter or a reorderer is
   a decode stage that decodes nothing; what unites the family is *creating a
   layer*, not running a decoder. **Rename declined**: the term is in
   `python-zipline`'s public API (`DecodeStage`), 25 sites use it, and a rename
   buys a better word at the cost of vocabulary alignment with the only complete
   implementation. Instead the definition says out loud that **a decode stage need
   not run a decoder**, which is the one sentence that dissolves the confusion.
3. **The two vocabularies are collapsed to one.** The document says
   *decode stage / pass-through* in some places and *created / preserved* in
   others for the same distinction. Keep both words but bind them once: a decode
   stage **creates**, a pass-through **preserves**. They stop being two ideas.
4. **"Transform" is narrowed to the file → file stage, and `recode` is coined for
   what it used to also mean.** The word was doing two jobs at two levels of the
   model — a stage that derives a `.zpf` (§Terminology) and the byte-changing act
   inside one (*"a decoder MAY transform"*, §Typing and §Conformance). That
   collision is why the second act had no usable name. **`recode`** takes it:
   changing the bytes while adding no structure.
5. **`decoder` stays broad; the narrow sense becomes a verb.** Decoding is
   properly the act of giving unstructured data meaning and structure, which
   would exclude decompression and decryption — and, applied consistently,
   **excludes TCP reassembly too**, since it orders and dedupes bytes and produces
   no units. `0.15` deliberately made reassembly a decoder so its overlap policy,
   buffer depth and timeout had somewhere to live, and `python-zipline` and
   `zpfwire` both rely on that; narrowing the noun would undo it, and would fight
   the idiom that calls gzip a decoder. So the noun keeps its scope and the
   distinction moves to what a decoder **does**: it frames, recodes, or both.

| Decoder | Frames | Recodes |
|---|---|---|
| HTTP/1.1 | yes | no |
| a gzip body | no | yes |
| TCP reassembly | no | yes |
| `wireguard-decrypt`, in `tunnel/packets.zpf` | yes | yes |

The last row is the case the question came from, and the suite answers it: the
only decryptor in the vectors emits records typed `dec:ip-packet`, one per inner
packet. It recodes *and* frames, so it is a decoder on any reading. **A
recode-only decoder has no vector** — a pure decryptor emitting plaintext bytes
with no unit boundaries — and that gap is worth knowing before Package E is ever
argued, since E's fallback turns exactly this shape into a transport stream.

*Not written as a rule: framing is what gives a stream units to have a decoded
layer over, which is why reassembly declares transport and HTTP declares decoded.
It is a tendency rather than a rule — a gzip output has payload-concatenation
offsets, not sequence-anchored ones — so it belongs in the rationale companion if
anywhere.*

**This is corrective, not normative.** §Terminology carries no `MUST`, `SHOULD` or
`MAY`, so repairing it moves neither guard count — the same property that let the
extraction ship without a version bump.

---

## Scope decisions

### 1. The three issues inherited from `0.18` are handled by the package, not beside it

`0.19` opened with #106, #80 and #125 on it.

- **#125** is #117's option 2 — a third `reason_class` value so any producer word
  can carry "content removed". **Package D closes it by deletion**, and closes
  #117 with it. Under any other package it stays open and this release does not
  do it: a subtractive release adding syntax is the same category error `0.18`
  declined in its scope decision 4.
- **#80** keeps its pre-`1.0` deadline and is **deferred again, deliberately**.
  Third deferral, and the milestone carries the argument. Note the interaction
  nobody has stated: a `0.x` release that deletes an option makes room in the
  registry and in the reader, which is an argument for doing the deletions
  *before* #80 rather than after.
- **#106** stays open. It is a design question, and this release is not one.

### 2. Nothing in this release gets a transition mechanism

A reader rejects a `version_minor` it does not implement, and `0.x` files are
disposable by the format's own rule. Every package therefore lands as a straight
deletion with a `Removed` changelog section, and `reject-unknown-minor` rolls
19 → 20 on its own. The changelog has carried a `Removed` section twice; this is
the first release where it is the largest one.

### 3. The Goals list gains a seventh goal, and it changes what Package D is arguing against

The analysis rests part of its case on the observation that the principle
carrying the weight — *a derived file is a complete, self-verifiable, loss-proof
account of its input* — **is not in the Goals list**. That was true of `0.18` and
is no longer true: `0.19` states the property the format actually offers, which is
narrower than that principle and is the half worth keeping.

> Make a **decoding failure findable in the input's own bytes**. Every decoded
> unit cites the range it was built from, and every region a decoder declined or
> could not parse is declared with a reason rather than dropped — so a tool that
> knows nothing about the protocol can locate each place the decoder's model of it
> broke, follow the reference back to the captured bytes, and re-derive just those
> ranges.

**It is a goal about what the file states, not about what a checker proves**, and
that distinction is the point. `input_extents`, `reason_class` and the seam
predicate are apparatus for proving it from one file; the goal survives their
deletion. What the goal does not survive is the guarantee becoming a SHOULD,
because a failure a producer *may* declare is not one a tool can be sent to find.

**So this settles D.1.** D-pair — coverage stays a MUST, verified across a pair of
files — is what the goal requires. **D-clean contradicts a stated goal** and would
have to change the Goals list in the same release that added it. The other four
packages are unaffected: A, B, C and E touch neither the citation nor the
declaration.

The remaining six goals are untouched by every package. If one appears to need a
Goals edit, that is a signal it has grown beyond its proposal.

### 4. Rationale extraction is done, and it changed less than it promised

Shipped as the `0.18` re-issue, tagged `v0.18-r2`, format unchanged. See
[RATIONALE-EXTRACTION-PLAN.md](RATIONALE-EXTRACTION-PLAN.md). Three things it
leaves this release:

- **Two guards now police every edit here.** Normative-sentence invariance holds
  the specification to `v0.18` less an accounted table of removals, and anchor
  integrity resolves every link across the whole tree. **A reduction package
  removes rules on purpose**, so each deletion needs a `NORMATIVE_REMOVALS` entry
  naming the statement and why — which is exactly the record a subtractive release
  should be keeping anyway, and it is now enforced rather than remembered.
- **`v0.18-r2` is this release's baseline**, not `v0.18`. Every
  `RETIRED_CLAIMS` entry added here reproduces against the extracted tree.
- **The rationale companion is where a deleted rule's argument goes.** That was
  the strongest reason to extract first and it survived contact: the reasoning
  behind a rule this release removes is already in a file, rather than being
  deleted along with it.

**And it did not shrink the packages.** Measured against `v0.18`, extraction took
this much out of each package's principal sections:

| Package | Principal sections | `v0.18` | After extraction |
|---|---|---:|---:|
| **A** 3.1 | Annotating a decoded file | 68 | **68** |
| **B** 3.2 | Sequenced files | 198 | 185 |
| **C** 3.3 | Referencing the source by stream offset | 209 | 203 |
| **D** 3.4 | Undecoded, Discontinuity, Coverage honesty | 483 | 423 |
| **E** 3.5 | Tunnel example, Conceptual model, Decoder Descriptor | 243 | 238 |

**So the claim this plan made — that extraction removes most of what each package
would remove, leaving them to be argued on capability alone — is struck.**
Extraction moved the rationale; a package removes the rationale *and* the
instructional text with it, because deleting a rule deletes its examples,
definitions and consequences too. The packages are as large as they were.

---

### 5. Transforming decoders are the implementation's blind spot, and the suite is what closes it

`python-zipline` has not implemented decoders that **change** data — a
decompressor, a decryptor, an HPACK expander — so its impact document cannot price
what any package does to them. That is worth knowing precisely, because the gap is
narrow and it is not this repository's gap.

**The suite exercises transformation in 8 of the 59 vectors**, counted as records
whose payload length differs from the width of the input range they cite:

| Vector | What it transforms |
|---|---|
| `decoded-basic`, `broken-chain`, `chain` | contraction; the tutorial cases and the provenance walk |
| `session-fan-out`, `mixed-derivation` | contraction under fan-out, and beside a preserved stream |
| `discontinuity-unknown-width`, `splice` | transformation across a declared break |
| `tunnel` | a four-hop decrypt-and-reassemble chain, eight transforming records |

So the assessment instrument is here, not downstream. **The gap is also
asymmetric**: transformation has no bearing on A, B or C, whose rules are about
provenance vocabulary, a session flag, and transport-layer sequence arithmetic.
`python-zipline`'s support verdicts on those three are complete as written. It
bears on **D and E**, in opposite directions, and each package records it under its
own findings.

**Every package runs against those eight vectors before it lands**, which is a
Phase 0 step rather than a reviewer's habit.

---

## Mechanics of a deletion release

Four things behave differently when text is removed rather than changed, and each
has bitten a previous release in its additive form.

**1. `RETIRED_CLAIMS` is the right instrument and this is its release.** Every
deleted rule is a retired claim by definition, and the whole tree asserts them —
`build.py` summaries reach `manifest.json` and therefore an implementation's
harness, and `vectors/README.md` has a row per vector. `0.18` learned that the
suite *paraphrases*, so an entry carries a **tuple of spellings** found by
grepping. A deletion release will add more entries than any before it: budget one
per deleted MUST, and grep the tree for each before writing the pattern.

**Validate each the way `0.18` established**: run the finished entry against the
`v0.18` tag, where it must report the sites this release deleted, and against the
current tree, where it must report nothing. An entry that reports nothing in both
directions is testing nothing.

**2. The capability-coverage check inverts, and it hard-fails.** It requires every
option and block in the registry to have a vector, and every `RULES` entry to name
a vector that exists. Deleting a vector while its option is still in the registry
fails the build; deleting a `RULES` entry's vector fails it too. So **the registry
row, the `RULES` entry and the vector go in one commit**, per package, and the
failure list between them is not a signal of anything.

**3. Two packages break `ENUMERATIONS` locators, and the check will report the
sites as moved rather than passing.** That is the behaviour `0.18` built it to
have, and it is correct, but it must be expected rather than debugged:

- **Package A** deletes *Annotating a decoded file*, killing the locator
  `provenance is the participants' `origin`` ([:1194](zipline-payload-format.md)),
  and rewrites the pass-through carry-forward bullet, killing `re-emit every
  Undecoded block` ([:2932](zipline-payload-format.md)).
- **Package E** deletes the transport-withholding rule, killing `having no way to
  express the break` ([:2852](zipline-payload-format.md)), and the
  sessionization-stage bullet, killing `since a hole is expressible without one`
  ([:2878](zipline-payload-format.md)).

Both packages must re-anchor or remove those entries in the same commit that
deletes the text. Under A and E the `transport-layer labels` set drops to four
sites and two sites respectively; under E, ask whether a set with two members left
is still worth declaring.

**4. The vector-name ratchet resets, and downstream is entitled to know.**
`python-zipline` keeps a `KNOWN_PASSING` list of vector names and a rule that a
name is never removed; when upstream deletes the file, the name has nothing to
guard. The `0.16` port already hit this once. **Name the removed vectors
explicitly in the changelog's `Removed` section**, as a list rather than a
sentence, so the reset is mechanical downstream rather than archaeological.

---

## Phase 0 — terminology, stamp, and the package choice

0. **Pin the terms** per §Terminology, and rewrite §Terminology to name them and
   point at where each is stated. Nothing else in the document changes in this
   step, so the diff is one paragraph and the guards stay green.
1. Choose the package. Everything below depends on it and nothing before it does.
2. `MAJOR, MINOR = 0, 19` in `vectors/build.py`; `check.py` to match; regenerate;
   the spec's version sites; open `## [0.19] — unreleased` with a `Removed`
   heading already in it, and an `Added` entry for the seventh goal (scope
   decision 3), which is already in the specification and has no changelog line
   yet.
3. Confirm `reject-unknown-minor` rolls 19 → 20, read out of the stamped bytes.
4. **Grep the tree for every claim the package retires, before deleting any of
   it.** The `RETIRED_CLAIMS` patterns are written from what that grep finds, and
   `0.18` proved they cannot be written from the sentence alone. This is the one
   step that is cheaper before the deletion than after.
5. **Name the eight transforming vectors as a standing check** (scope decision 5)
   and read the package's deletions against them before the first one lands. They
   are the only place the format's support for decoders that *change* data is
   exercised, and the one implementation reviewing these proposals cannot see it.
6. File the package's items as issues on the `0.19` milestone, as every previous
   round has.

**Expect a red window.** `check.py` will exit 1 from the first deletion until the
package's last commit, because the capability check hard-fails on an option whose
vector is gone and vice versa. Third release running where that is the right
state; `0.18` stopped treating it as an exception and this one should not
reintroduce the treatment.

---

## Phase 0b — rewrite the text in the pinned terms

Every site using the vocabulary loosely, brought onto the definitions. This is
the clarification half, and it is larger than Phase 0 by an order of magnitude:
**176** uses of `decoder`, **225** of `decoded`, **25** of `decode stage`, **52**
of `pass-through`.

Not a find-and-replace. Each site is one of three cases and only the third is
work:

- **Already correct.** Most of them. Leave alone.
- **Loose but unambiguous** — `decoder` where `decode stage` is meant, or
  `decoded` where `derived` is meant. Correct in place.
- **Ambiguous, because the sentence was written under the old model.** These are
  the finds. §Terminology is the first; expect others, and expect each to be a
  small piece of genuine reasoning rather than an edit.

**Three constraints, learned from the extraction:**

- **Nothing normative is reworded.** The invariance guard holds the counts but
  would not notice a `MUST` surviving in weaker words. If a rule needs its wording
  changed to use a pinned term, that is a `Changed` entry with an argument, not a
  terminology fix.
- **`ENUMERATIONS` gains the site this phase found.** "This spec defines two"
  transforms is an undeclared enumeration that went stale exactly as `0.17`'s
  four did. Declare it — with the members it owes — in the commit that fixes it,
  so the next transform added fails the build here.
- **`RETIRED_CLAIMS` gains an entry for the stale definition**, with the
  paraphrase actually found rather than one written against the sentence being
  deleted. It reproduces against `v0.18-r2` and is absent after.

**Order: Phase 0b runs before the package.** The package edits the derivation
vocabulary, and editing it on top of a definition three releases stale is how a
correction gets built on a misreading.

***Done, and it was small — which is the finding.*** The vocabulary was **already
consistent almost everywhere**. Of 176 uses of `decoder`, 225 of `decoded`, 25 of
`decode stage` and 52 of `pass-through`, **six sites** needed correcting:

- **Three** used `transform` for the byte-changing act now called **recode**: the
  weaker promise when following a record's `spans`, the provenance walk crossing a
  stage that recoded, and a recoding decoder's spans not needing to abut.
- **One** had the *decoder* accounting for undecoded regions where the **stage**
  does it — §Conformance's decode-stage bullet, one line below a sentence that
  already said the stage emits those markers.
- **One** listed the Decoder Descriptor's parts without `output_layer`, which the
  pinned definition makes constitutive rather than incidental.
- **One** was §Terminology itself, fixed in Phase 0.

***`decoded` needed no work at all.*** It is used as a layer adjective throughout
— *decoded record*, *decoded stream*, *decoded layer*, *decoded file* — with no
site standing in for *derived*. The 14 apparent hits for "decoded block" are the
tail of **Un**decoded block.

***So the defect was concentrated, not diffuse.*** The document's vocabulary was
sound; one paragraph defining it was three releases stale, and one word was doing
two jobs. That is worth recording because the opposite conclusion — a document
riddled with loose usage needing a sweep — is what a 176-and-225 count suggests
before you look, and it would have justified a far larger and more dangerous edit.

---

## Package A — 3.1 pass-through as a distinct derivation kind

**Loosen to:** every derived record carries `spans`. A merge or an annotator
writes an identity span per record.

### What goes

- Option `origin` (`0x0064`) from the registry and from §Participant Descriptor.
- §Layers *Transforms that change no data* ([:749](zipline-payload-format.md), 17
  lines) and §*Annotating a decoded file* ([:1189](zipline-payload-format.md), 68
  lines) entire.
- In §Conformance: the two-way taxonomy, the discriminator sentences, "a
  `zpf`-sourced participant MUST be one or the other", "not every `zpf-input`
  Source is an input", and the pass-through carry-forward bullet.
- In §Discontinuity: the verbatim-versus-renumbered contrast.
- §Design decisions not taken: the machine-checkable annotation kind entry.
- `RULES`: `zpf-stream-created-or-preserved`, `discontinuity-passthrough-renumber`,
  `per-stream-transform`.
- Vectors: `passthrough-transport`, `passthrough-discontinuity`,
  `annotator-decoded`; `mixed-derivation` and `merge-timestamp-tie` re-vendored
  with identity spans.

### Three findings this plan adds, and two of them change the vector list

***`isolate-unbound-zpf-stream` should be rewritten, not removed.*** The analysis
lists it among the deletions while noting in the same breath that "its rule
collapses to *a `zpf`-sourced record without `spans`*". A rule that collapses
still binds — it binds *harder*, since it now has no exception — and it is exactly
the rule a writer breaks by forgetting the identity span. Keep the vector, keep a
`RULES` entry under a new key, and rewrite the summary. Removing it would delete
the test for the one new obligation this package creates.

***`mixed-derivation` survives as bytes and loses its reason to exist.*** Its
whole point is that the created/preserved bar binds per participant rather than
per file — session 10 carries `spans`, session 11's participant carries `origin`.
Under A there is no bar and no discriminator, so both sessions look alike and the
file demonstrates nothing. It is not a deletion the analysis lists, and it is not
a vector to keep on autopilot either. **Decide it in the package**: either retire
it with the rule, or keep it re-vendored as a fan-in vector and say so in the
summary. Do not re-vendor it silently with identity spans and leave a summary
asserting a rule the release deleted — that is a `RETIRED_CLAIMS` hit against your
own commit, and it will be caught.

***The renumbering rule needs restating, not deleting.*** The analysis removes "a
pass-through preserving a decoded layer carries these forward, renumbered" along
with the asymmetry it belongs to. The asymmetry does go — under A there is no
verbatim copy to contrast with. But a derived file re-emitting an input's
Discontinuity still has to renumber the participant ids into its own namespace,
and that duty is stated nowhere else. One sentence, moved into §Discontinuity's
main body.

### Phases

1. **Registry and descriptor.** Delete `origin`; state that every `zpf`-sourced
   record carries `spans`; write the identity-span sentence where the option's
   paragraph was.
2. **The two Layers sections**, and the §Conformance taxonomy with them. This is
   the phase the `ENUMERATIONS` locators break in; re-anchor in the same commit.
3. **§Discontinuity**: delete the contrast, restate the renumbering duty.
4. **Vectors, one commit**: three removed, `isolate-unbound-zpf-stream` rewritten,
   `merge-timestamp-tie` re-vendored, `mixed-derivation` per the decision above.
   `RULES` and the registry in the same commit or the build stays red.
5. **Changelog, `RETIRED_CLAIMS` sweep, release.**

### Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `mixed-derivation` is re-vendored with a stale summary | **high — it is the default action** | The finding above; check its summary against `RETIRED_CLAIMS` explicitly |
| The identity-span obligation ships with no vector | medium | Keep `isolate-unbound-zpf-stream` and re-point its `RULES` entry |
| The renumbering duty is deleted with the asymmetry | medium | Named in the phase list; it is one sentence and it has no other home |
| `merge_files`'s "byte-identical re-emission" is asserted somewhere in the tree | low | `python-zipline` flags that this stops being literally true; grep both repos |

### Done

- [ ] `origin` is out of the registry, the descriptor, and the JSONL mapping.
- [ ] Every `zpf`-sourced record carries `spans`, stated once, with the identity
      span named as the pass-through case.
- [ ] A vector fails a reader that omits the identity span.
- [ ] `mixed-derivation`'s fate is a recorded decision, not a re-vendor.
- [ ] The renumbering duty survives the deletion of the asymmetry.
- [ ] `ENUMERATIONS` re-anchored; `check.py` green; **56** vectors — 55 if
      `mixed-derivation` is retired with its rule. The analysis budgets 55 because
      it deletes `isolate-unbound-zpf-stream`, which this package keeps.

---

## Package B — 3.2 a producer must justify its sequencing claim

**Loosen to:** `SEQUENCED` is a bare assertion that stored order is a valid causal
order.

### What goes

- Options `sequenced_basis` (`0x0053`) and File Header `flags` (`0x0014`), whose
  only defined bit is `SINGLE_CLOCK`.
- §Sequenced files ([:492](zipline-payload-format.md)): "What a sequenced session
  rests on" through "The two flags are independent", about 110 of its 198 lines.
- §Merge algorithm: the **hint-less** definition
  ([:380](zipline-payload-format.md)) and the paragraph on why a reader can only
  decide it at Session End; the producer tie-break shrinks to one sentence.
- §Conformance: the basis clauses and the missing-`sequenced_basis` violation.
- §Design decisions not taken: "Requiring `sequenced_basis` on every `SEQUENCED`
  session".
- Vectors: `sequenced-basis`, `isolate-sequenced-no-basis`,
  `partially-hinted-sequenced`, `file-clock-metadata`.

### Two findings

***No `RULES` entry moves, and that is what makes this the cleanest package.***
The basis is enforced through the option registry, which the capability check
covers mechanically. Delete the two registry rows and the four vectors in one
commit and the check goes green on its own. Nothing else in the format keys on
either option.

***`file-clock-metadata` is the one vector that cannot simply be deleted.*** It
carries `time_epoch` as well as `flags`, and `time_epoch` moves the clock origin —
a live capability with, as far as this plan can tell, no other vector. The
analysis says its `time_epoch` half "moves into `descriptive-metadata`". **Do that
move before deleting the vector**, and let the capability check confirm it: if
`time_epoch` has no home, the build fails, which is the check working. Confirm the
same for any other option `file-clock-metadata` uniquely exercises.

***`partially-hinted-sequenced` is deleted here and load-bearing in `0.18`.*** It
is the vector that carries #114's `seq_start`-less unplaceable record, given an
`expect` two days ago. Under B it goes for its sequencing half, taking that
placement evidence with it. **Move the placement case to another accept vector
first.** Under Package C this does not arise, because C deletes the placement rule
itself — which is the one real interaction between B and C.

### Phases

1. Move `time_epoch` into `descriptive-metadata`; move
   `partially-hinted-sequenced`'s placement case to a surviving vector. Nothing is
   deleted in this phase and the build stays green.
2. §Sequenced files, §Merge algorithm's hint-less definition, §Conformance, the
   design-decisions entry.
3. Registry rows and the four vectors, one commit.
4. Changelog, `RETIRED_CLAIMS` sweep, release.

***Done. Both findings held, and the guard built for the extraction is what made
the deletion safe.***

***`NORMATIVE_REMOVALS` earned its design on its first real use.*** Eleven
entries, each naming the sentence that went, with the expected counts derived from
the table rather than typed — so the drop from **143/53/54** to **132/48/53**
could not be waved through, and each step of it had to be justified in writing at
the moment it happened. A subtractive release wants exactly this and had nothing
like it before `0.18` built it for a different purpose.

***And it caught a real mistake, of the kind this repository keeps making.*** The
removal entry for the File Header `flags` field's reserved-bits rule matched the
**Session Descriptor's** identical sentence, which survives — so the table claimed
a loss that had not happened, and the check said so. Re-anchored on
`SINGLE_CLOCK`. The lesson is in the code beside the entry: **anchor a removal on
what is unique to the site, not on the rule being removed**, which is the same
shape as `ENUMERATIONS`' lesson that a locator inside the clause being corrected
is not a locator.

***The two rehousings both mattered, and Phase 1 was right to do them first.***
`time_epoch` survives the package and `file-clock-metadata` was its only vector,
so the capability check would have hard-failed on the deletion commit. The
placement shape was subtler: `partially-hinted-sequenced` carried **two** lessons
and only one was about sequencing, so the deletion would have taken `0.18`'s
`seq_start`-less placement evidence with it silently — no check covers "a rule
kept a vector but lost a *shape*". Rehoused as `unplaceable-no-seq-start`, and
dropping the `SEQUENCED` flag from it makes the point the old vector obscured:
**placement keys on whether a stream is sequence-anchored, not on the flag.**

***Two `RETIRED_CLAIMS` entries that differ in kind from every earlier one.***
Every previous entry retires a claim that had become *false*. These two retire
claims that were **true until this release**. The ratchet's job here is not to
stop a stale copy returning but to stop a rule the model deliberately dropped
being reintroduced from an older draft or from an implementation that still
carries it. Worth naming, because it is a second use for the mechanism and the
comment now says so.

***The forensic question reshaped the section rather than just emptying it.***
Asked where a strange order could be traced to, the answer turned out not to be
the basis word at all: it names a *category* of reasoning, while what a reader
needs is which run of which tool. §Sequenced files now points at the build
provenance of the file that set the flag — `produced_by`, `produced_at`,
`transform_params_digest` where a merge's ordering key lives — reached by walking
`zpf-input` Sources back. **That is a better answer than the deleted option gave**,
and it costs no syntax.

### Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `time_epoch` loses its only vector | **high if phase 1 is skipped** | Phase 1 exists for it; the capability check is the backstop |
| #114's placement evidence leaves with the vector | high | Move it first; or take C, which deletes the rule |
| "Hint-less" survives in a sentence that no longer defines it | medium | It appears in §Merge algorithm and §Conformance; grep before deleting |
| `derive_from`'s refusal loses its rule and downstream keeps the guard | low | `python-zipline` names this; it is their call, not the spec's |

### Done

- [x] Both options out of the registry and the JSONL mapping. *36 options, from
      38.*
- [x] `SEQUENCED` is stated once, as a bare assertion, with the trust it rests on
      named in the same sentence — *"the same trust it already extends to the
      order itself, which it cannot check either."*
- [x] "Hint-less" appears nowhere, or is defined where it appears. *Defined, and
      the paragraph now says no rule turns on it: it is a description, not a
      test.*
- [x] `time_epoch` and the `seq_start`-less placement case both still have a
      vector. *`descriptive-metadata` and `unplaceable-no-seq-start`.*
- [x] Every normative statement removed is named in `NORMATIVE_REMOVALS` with the
      keywords it took and why. **Eleven**, and the count is derived from the
      table rather than typed.
- [x] `RETIRED_CLAIMS` carries the basis rule and the `SINGLE_CLOCK` bit, both
      reproducing against `v0.18-r2`.
- [x] The companion keeps the deleted rule's argument, headed as removed, with
      why it was written *and* why it was dropped.
- [x] `check.py` green. ~~*55 vectors.*~~ **56** — the estimate did not allow for
      `unplaceable-no-seq-start`, which the plan's own Phase 1 called for.

---

## Package C — 3.3 two readers must agree on non-conformant input

**Loosen to:** readers agree on conformant files. Every semantic violation gets
one treatment — isolate the smallest sound unit, or ignore the offending option,
with a diagnostic either way.

### What goes

- §Referencing the source by stream offset: "The origin is a floor"
  ([:809](zipline-payload-format.md)) through "The floor is decidable only within
  the serial-arithmetic half-space" ([:874](zipline-payload-format.md)), about 70
  lines, replaced by one sentence — a record whose `seq_start` precedes the origin
  covers no byte of the stream; a reader ignores its placement and SHOULD report
  it.
- §Typing a decoded record: "Violating this is advisory, not isolating" and the
  paragraph after it.
- §Record: the two handshake advisory paragraphs.
- §Conformance: the "displaces this licence" clause and its examples.
- `RULES`: `content-type-transport-advisory`, `role-transport-advisory`,
  `seq-start-origin-floor`, `unplaceable-record-placement`.
- Vectors: `advisory-below-origin-payload`, `advisory-seq-start-below-origin`,
  `advisory-transport-content-type`, `advisory-transport-role`.

### Three findings, and the first is the reason to decide this one carefully

***C deletes four of the thirteen items `0.18` shipped.*** #113 reworded the
§Conformance clause to displacement; #114 wrote the placement rule; #115 costed
the floor's non-vacuous case and added `advisory-below-origin-payload`; #116
extended the treatment to a handshake above the origin. All four are inside the
text C removes. That is not an argument against C — the analysis's point is that
this tier has cost a review round in three consecutive releases, which is evidence
*for* it — but it should be taken with the ledger open. `0.18`'s Phase 2 is the
most recent worked example of what the tier costs to keep correct.

***The advisory *tier* survives; only the pinned repairs go.*** `python-zipline`
is right that the mechanism stays, because the loosened rule still says "ignore
the offending option, with a diagnostic". So the four `advisory-*` vectors are not
all the same shape: the two transport-label ones test *the tier* (accept, report,
ignore the label, round-trip) and nothing about a pinned repair. **Keep at least
one of them.** Deleting all four leaves the advisory tier — still a live concept
in §Conformance — with no vector at all, which is precisely the gap the capability
check exists to prevent and which it will not catch, because a tier is not an
option.

***`partially-hinted-sequenced`'s `expect` goes non-normative.*** `0.18` wrote
into it: unplaceable, zero width at offset 6, extent stays 6. Under C the
placement is unspecified, so a conformant reader may answer differently and the
vector's stated expectation becomes a convention rather than a rule. Either soften
the `expect` and say why in the summary, or state a placement rule after all —
`python-zipline` observes that a reader still has to put the record *somewhere*,
because one range per record is a promise its API makes. If the spec declines to
say where, every implementation will pick, and they will not pick alike. That is
the loss C is buying; make sure it is bought on purpose rather than inherited from
a vector nobody re-read.

### Phases

1. §Referencing's floor block, replaced by the one-sentence rule.
2. §Typing, §Record's handshake paragraphs, §Conformance's displacement clause.
3. Vectors and `RULES`, one commit, keeping the advisory-tier vector chosen above.
4. `partially-hinted-sequenced`'s `expect`, per the decision above.
5. Changelog, `RETIRED_CLAIMS` sweep, release.

### Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The advisory tier is left with no vector | **high — all four are on the deletion list** | Keep one transport-label vector; it tests the tier, not a repair |
| A vector's `expect` quietly outlives its rule | high | `partially-hinted-sequenced` is the named case; check every `expect` naming a placement |
| The `isn + 1` MUST is deleted with its advisory sentences | medium, high cost | It is in §Record and survives every package; `python-zipline` builds a write-side guard on it |
| `0.18`'s four fixes are re-litigated during the deletion | medium | The ledger above; the decision is to delete the tier's repairs, not to revisit whether they were right |

### Done

- [ ] The floor is one sentence, and it says what a reader does.
- [ ] No MUST NOT in the document pins a repair.
- [ ] The advisory tier still has a vector.
- [ ] No `expect` asserts a placement the specification no longer states.
- [ ] `RETIRED_CLAIMS` carries the floor's placement rule, reproducing against
      `v0.18`.
- [ ] `check.py` green; **55** or 56 vectors, depending on the tier vector kept.

---

## Package D — 3.4 coverage as a verifiable MUST

**Loosen to:** see D.1 first. This package has a sub-choice, and it is the whole
decision.

### D.1 The sub-choice: the clean SHOULD, or the pair-verifiable MUST

**D-clean, as the analysis proposes.** A decode stage SHOULD account for
undecoded input and SHOULD mark a break in its own output. No checker proves
either. `check_coverage` against a second file becomes a lint.

**D-pair, `python-zipline`'s counter-suggestion.** Keep the coverage MUST and
delete only the single-file *verification* apparatus: `input_extents`,
`reason_class`, `dropped`, the seam predicate. The property "nothing vanishes
silently" then holds for a **pair** of files rather than for one.

**Scope decision 3 settles this: D-pair.** The seventh goal requires a declaration
a tool can be sent to find, which a SHOULD does not provide. The rest of this
sub-section is the argument that held before the goal was stated, and it reaches
the same place.

**D-pair is the better of the two, and the spec's own text is the argument.** The
`input_extents` section already concedes that an absent entry asserts nothing,
that a consumer cannot distinguish a writer that did not know from one that did
not bother, and that "the self-verifiability it gives is obtainable only from
writers that opt in, which are not the writers whose output most needs checking"
([:1830](zipline-payload-format.md)). Single-file verification was an opt-in aid,
never a guarantee. Deleting it costs less than the analysis's "Lost" line implies,
and reducing the guarantee to a SHOULD costs more than it needs to.

Two things to add to `python-zipline`'s case, and one to correct in it:

- **The precedent is better than the one they reach for.** They cite the
  transport-withholding rule as an existing MUST no single file can verify, which
  is true but unvectorable by construction. The suite already has a MUST verified
  across a *pair*: `check.py`'s `tunnel_covers` confirms that each hop accounts
  for every offset of the input it reads, and the `chain` fixture does the same.
  A pair-verifiable MUST is not a new kind of rule here — it is a shape the
  vector suite has shipped since `0.15`.
- **"Never both" stays single-file checkable.** A span and an Undecoded region
  overlapping on one input stream is visible from the output alone. D-pair should
  say so: the contradiction half of the guarantee keeps its single-file check,
  and only the completeness half moves to the pair. Fewer vectors leave than
  either document counts.
- **The Discontinuity origination duty is a separate MUST and D-pair does not
  say what happens to it.** Coverage is about input offsets; the duty is about
  whether two output units join, and the specification is explicit that it does
  **not** key on input coverage ([:2258](zipline-payload-format.md)) and that most
  of it is not mechanically decidable at all. Having the input in hand does not
  help. So deleting the seam predicate leaves the duty as either an uncheckable
  MUST or a SHOULD, and D-pair must pick. **Keep the MUST and the join table,
  drop the predicate**: the predicate's only stated purpose was making two
  checkers agree, and with no checker proving it there is nothing left for it to
  buy.

*The rest of this package is written for D-pair. Under D-clean, add the coverage
guarantee itself, the "at least once, never both" refinement and the per-input-
stream scoping to the deletions, and move `check_coverage` and `check_chain`'s
coverage half from conformance to lint.*

### What goes

- Options `input_extents` (`0x00C1`) and `reason_class` (`0x00A1`); the `dropped`
  reason value and the `0.18` MUST that a stage removing content writes it.
- §Session End: the `input_extents` text ([:1777](zipline-payload-format.md), 66
  lines) including the fan-out agreement rule.
- §Undecoded: the `reason_class` paragraphs, the `dropped` paragraphs, and "an
  unrecognised `reason` with no `reason_class`" — replaced by: an unrecognised
  value has unknown recoverability, **and a producer whose failure is recoverable
  writes a canonical reason with the specificity in `comment`**. The second half is
  not optional; see the decryptor finding.
- §Discontinuity: "What a producer owes the block" through "Satisfying this
  predicate is not satisfying the duty", **keeping the join table and the duty**,
  deleting the predicate and the two-decidable-cases argument, about 130 lines
  down to about 40.
- `RULES`: `extents-self-verifiable`, `dropped-is-a-break`,
  `discontinuity-origination` (the vector proving it goes), and the `#117`
  comment recording a MUST with no vector.
- Vectors: `isolate-extent-exceeds-coverage`, `isolate-extents-disagree`,
  `isolate-unmarked-break`, `isolate-unmarked-drop`, `undecoded-reason-class`.
  **`isolate-coverage-gap` stays under D-pair** — it is an interior gap, visible
  against the input, and the MUST it tests survives.
- Re-vendored rather than deleted, all three carrying a non-canonical reason:
  `tunnel` (`decrypt-failed`), `undecoded-in-capture` (`overlap-discarded`) and
  whatever replaces `undecoded-reason-class`. Each moves to a canonical reason with
  a `comment`, and `tunnel`'s is the one to write first, since it is the case that
  proves the pattern works.

### Findings

***D closes #117 and #125 by deletion, one release after #117 shipped.*** `0.18`
made "a stage that removed content MUST write `reason = dropped`" a MUST, recorded
that no vector can carry it, and filed #125 to generalise it. D deletes the MUST,
the word, and the option that motivated the issue. Worth stating in the changelog
as one entry rather than three, because it is one decision. **The transforming-
decoder finding below cuts the other way on #125**: if a decryptor needs its
failure's class, the generalisation that issue asks for is what D should take
rather than delete.

***The class distinction is consumer-facing, not checker-facing.*** `reason_class`
can go, but the two recoverability classes — bytes exist, or no bytes anywhere —
decide whether a consumer can fetch the region at all. That is the part of
§Undecoded that must survive the deletion intact, and the phrasing to be careful
with is the replacement sentence for an unrecognised word. The next finding is
why that sentence is the package's most delicate edit.

***A failing decryptor is the case the replacement sentence breaks, and it is the
case `python-zipline` cannot see*** (scope decision 5). In `tunnel/packets.zpf`
the wireguard stage turns 80 ciphertext bytes into 60 plaintext ones, and the
datagram it could not decrypt is an Undecoded block reading `reason:
decrypt-failed` with `reason_class: bytes`. `decrypt-failed` is not one of the
canonical five, so **the option is the only thing carrying its recoverability**.
Under the drafted replacement — an unrecognised value has unknown recoverability —
a consumer can no longer tell that those bytes still exist one hop up and could be
re-decrypted with a better key. That is the seventh goal failing in the case it
was written for.

The producer has a workaround and the package **MUST state it** rather than leave
it to be discovered: a transforming decoder writes a **canonical** reason and puts
the specific failure in `comment`. That is the discipline `0.18` already imposed on
`dropped`, so it is a pattern the document knows how to state, and this is where
the `undecoded-reason-class` vector's replacement belongs — retire it as a
`reason_class` test and keep a vector showing a decryptor's recoverable failure
written the new way. The alternative is #125's generalisation, which is the same
observation reached from the other side.

Two other vectors carry a non-canonical reason with a class: `undecoded-in-capture`
(`overlap-discarded`, a reassembler's discarded overlap) and
`undecoded-reason-class` (`rtp-seq-gap`). Both need the same rewrite, and the
reassembler one is what `zpfwire` writes today.

***The seam predicate is careful because of transforming decoders, which raises
both sides of this package.*** Its clauses exist to avoid false positives on
exactly these stages: it does **not** key on span adjacency, because a transforming
decoder's spans need not abut where its output is continuous
([:2261](zipline-payload-format.md)), and it declines to test pairs whose input
regions run backwards — which is what `tunnel/inner.zpf` produces, its three
records citing `[0,60)`, `[100,150)` and `[60,100)` in that stored order. So
transformation is a reason the apparatus cost three review rounds, *and* a reason
its deletion costs more than the impact document could price. Deleting the
predicate while keeping the duty and the join table is still right; deleting the
reasoning with it is what rationale extraction is for.

***`filtered-decoded` and `reordered-decoded` stay as accept vectors and lose
their obligations.*** Both currently demonstrate a duty; under D they demonstrate
a producer honouring a duty no checker proves. Rewrite both summaries. Neither is
a deletion, and leaving the old summaries in place is a `RETIRED_CLAIMS` hit.

### Phases

1. **Settle D.1 and write it down.** Nothing else starts until it is chosen, and
   the choice changes the deletion list.
2. §Session End's `input_extents`; the registry row; `isolate-extent-exceeds-
   coverage` and `isolate-extents-disagree`.
3. §Undecoded's `reason_class` and `dropped`; the registry row;
   `undecoded-reason-class` and `isolate-unmarked-drop`. **Write the canonical-
   reason-plus-`comment` pattern before deleting the option**, and re-vendor
   `tunnel` and `undecoded-in-capture` onto it in the same commit, or the suite
   ships a decryptor whose failure the format can no longer classify.
4. §Discontinuity's predicate, keeping the duty and the table;
   `isolate-unmarked-break`.
5. §Coverage honesty and §Conformance restated for the pair, or for the SHOULD.
6. Summaries of `filtered-decoded` and `reordered-decoded`; changelog;
   `RETIRED_CLAIMS` sweep; release.

### Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| D.1 is left implicit and the release drifts between the two | **high — this is the package's dominant risk** | Phase 1 exists only to settle it, and the deletion list differs |
| The origination duty is deleted along with its predicate | high | Named in D.1; the duty and the join table are explicitly kept |
| "Never both" is deleted as part of the verification apparatus | medium | It is single-file checkable and stays; `isolate-coverage-gap` is its vector |
| The recoverability classes are lost with `reason_class` | medium | The classes are prose in §Undecoded and survive the option |
| **A decryptor's recoverable failure becomes unclassifiable**, and no reviewer notices because the one implementation reviewing this has no transforming decoder | **high — three vectors carry a non-canonical reason today** | The canonical-reason-plus-`comment` pattern is written before the option is deleted, and `tunnel` is re-vendored onto it in the same commit |
| The predicate's transform-specific reasoning is deleted rather than moved | medium | It is the argument, not the rule; rationale extraction is its home and scope decision 4 defers that |
| A `0.18` MUST is deleted one release after shipping with no changelog trail | medium | One `Removed` entry naming #117 and #125 together |

### Done

- [ ] D.1 is recorded in this file with the argument, before any deletion.
- [ ] Both options out of the registry and the JSONL mapping.
- [ ] The coverage guarantee is stated once, at the strength D.1 chose, and every
      other statement of it agrees.
- [ ] The origination duty and the join table survive; the predicate does not.
- [ ] `filtered-decoded` and `reordered-decoded` carry summaries describing what
      they now demonstrate.
- [ ] `RETIRED_CLAIMS` carries the `dropped` MUST and the fan-out extents rule.
- [ ] #117 and #125 closed by deletion, in one changelog entry — or #125 taken
      instead, if the decryptor finding decides it.
- [ ] A recoverable failure a canonical word does not name has a stated way to
      say so, and a vector writes it that way.
- [ ] The eight transforming vectors pass, `tunnel` read record by record rather
      than by exit code.
- [ ] `check.py` green; **54** vectors under D-pair, 53 under D-clean.

---

## Package E — 3.5 provenance and layer as independent axes

**Loosen to:** the `0.14` model. Capture-sourced means transport, `zpf`-sourced
means decoded, and a record is decoded exactly when it carries `decoder_id`.

*Recorded for completeness and ranked last by both documents. `python-zipline`
opposes it outright.*

### What goes

- The `output_layer` body field and its enum; the Decoder body reverts to a
  reserved u16.
- §Conceptual model: "Provenance and layer are independent axes"
  ([:93](zipline-payload-format.md)) through the four-cell table, about 60 lines.
- §Decoder Descriptor: the `output_layer` text and the boxed note.
- §*Worked example: a decrypted tunnel* ([:1257](zipline-payload-format.md)), 118
  lines, entire.
- §Undecoded's "Against a `capture` source"; §Discontinuity's transport-
  withholding rule; §Conformance's mixed-layer rule, the head-of-pipeline SHOULD,
  the sessionization-stage bullet and the decoded-with-no-predecessor bullet;
  §Enums' "two enums are load-bearing".
- `RULES`: seven of the twenty-eight — `axes-independent`,
  `undecoded-capture-sourced`, `decoder-declares-layer`, `reassembler-may-declare`,
  `unknown-output-layer-isolates`, `layer-consistency`,
  `undecoded-capture-bytes-only`.
- Vectors: `tunnel` (a four-file fixture), `sessionization-stage`,
  `reassembler-declared`, `proxy-decoded`, `undecoded-in-capture`,
  `isolate-mixed-layer-participant`, `isolate-unknown-output-layer`,
  `isolate-hole-against-capture`.

### Findings

***E is the only package with a large suite-code cost, and it is larger than the
other four combined.*** `build_tunnel` is 524 lines of `build.py`
([:4578](../vectors/build.py)); `check_tunnel`, `tunnel_covers`,
`tunnel_digests` and `tunnel_inner_extent` are about 106 lines of `check.py`
([:864](../vectors/check.py)). That is roughly 630 lines of bespoke fixture
machinery deleted, against a "small" for A, B and C. It is deletion rather than
rewriting, which is cheap to do and expensive to undo.

***Seven `RULES` entries is a quarter of the table, and five of them are `0.15`
and `0.16` capabilities added because implementations asked.*** `python-zipline`'s
position — that `0.15` exists because the producer this library is built beside
requested it — is the strongest single argument in either document, and it is
about provenance of the requirement rather than about tunnels being rare.

***E takes a reassembler's `params_digest` with it, and nothing replaces it.***
A capture-sourced file MUST NOT carry `transform_params_digest`, so a reassembler
that declares itself has no way to record its overlap policy, buffer depth or
timeout. The analysis names this under "Lost"; it is worth pricing separately,
because it is the one capability here with no workaround in the `0.14` model.
`tunnel/inner.zpf` is the instance: a `tcp-reassembly` decoder declaring
`output_layer = transport` **and** a `params_digest`.

***The loss is every multi-hop transform chain, not only tunnels, and both
documents price it as tunnels*** (scope decision 5). `tunnel` is the suite's only
four-hop chain and its only worked decrypt: `outer` → `packets` decrypts 80
ciphertext bytes into 60 plaintext ones, `packets` → `inner` reassembles, `inner` →
`http` decodes. The analysis's fallback handling folds the first two hops into one
head-of-pipeline stage that decrypts *and* reassembles, emitting capture-sourced
transport streams. That is a working answer for reading the traffic and it deletes
the per-hop account: which stage lost the datagram, with what configuration, and
which bytes are still recoverable one hop up. `python-zipline` ranks E last on the
strength of `zpfwire`'s declared shape and says the tunnel account "matters if
kober ever decodes through TLS". It is broader than that, and they could not have
seen it — a decompressing or decrypting stage is exactly the functionality they
have not implemented. **Read their opposition as understated rather than as one
implementation's preference.**

### If it is taken anyway

Phase it as: the two enums and the Decoder body first, since every other deletion
depends on the field being gone; then §Conceptual model and §Decoder Descriptor;
then the tunnel example and `build_tunnel`/`check_tunnel` in one commit; then
§Conformance's five sites and the remaining vectors; then the `ENUMERATIONS`
re-anchor, which under E leaves the set with two members and a question about
whether to keep it. Budget the `RETIRED_CLAIMS` sweep as the largest of any
package: seven rules retired, each asserted in a vector summary and a README row.

### Done

- [ ] `output_layer` is gone from the body, the enum table, and every rule keyed
      on it.
- [ ] A decrypted tunnel has a stated handling in the `0.14` model, in prose, in
      the section the worked example vacated.
- [ ] **A transforming decoder still has somewhere to record how it was
      configured**, or the changelog says it does not. This is the finding to
      settle before the package starts, not after.
- [ ] Correspondence-not-identity keeps a vector. `tunnel` is its largest
      demonstration and `chain`'s 16-into-8 record is the surviving one; confirm
      `spans-correspondence` still names a fixture that exists.
- [ ] The reassembler `params_digest` loss is recorded in the changelog as a
      capability removed, not as a section deleted.
- [ ] `RETIRED_CLAIMS` carries all seven retired rules, each reproducing against
      `v0.18`.
- [ ] `check.py` green; **51** vectors.

---

## If you take more than one

Three interactions matter, and two of them are named in neither document.

1. **A without D makes a merge owe coverage.** A merge output carrying `spans`
   *cites* an input stream, and under the current coverage MUST that makes the
   file answerable for it — every offset spanned or marked. A transport input's
   holes are real ranges no payload covers, so a merge would owe an Undecoded
   `gap` block per hole. `python-zipline` found this and it is correct. Under
   D-clean it is a SHOULD; under **D-pair it remains a MUST**, so the work is
   real under the combination this plan recommends.
2. **B and C both bear on `partially-hinted-sequenced`, in opposite directions.**
   B deletes the vector and needs its placement case rehoused first; C deletes the
   placement rule and makes the rehousing unnecessary. Taking both, do C's
   deletion first and B's vector removal after, or the work is done twice.
3. **A and E both break `ENUMERATIONS` locators**, and between them they kill four
   of the six declared sites. Taken together, the `transport-layer labels` set has
   two sites left and should be reconsidered rather than re-anchored.

The order for any combination is **A, B, C, D, E** — cheapest deletion to most
argued, and it happens to be dependency order too, since D's join table survives A
and C's floor rewrite touches nothing D deletes.

---

## Rationale extraction

Out of scope per scope decision 4, and the largest reduction available: about a
third of the document explains why a rule exists or what an earlier version got
wrong, and moving it to a companion file brings the specification near 2 000
lines with no change in meaning. Two things to settle before it starts, both
learned from this repository rather than from the analysis:

- **`RETIRED_CLAIMS` patterns match against the specification and the suite, not
  against a rationale companion.** Moving text out of `SCANNED`'s reach silently
  weakens every existing entry whose sentence lands in the companion. Decide
  whether the companion is scanned before the first paragraph moves.
- **The same habit is in the suite.** `check.py`'s comments and `build.py`'s
  vector summaries carry the argument that produced each rule, which is right for
  a suite that has to be maintained and wrong nowhere. `python-zipline` observes
  the same of its own docstrings. Extraction is a specification decision, not a
  house style to propagate.

---

## Risks common to every package

| Risk | Likelihood | Mitigation |
|---|---|---|
| A deleted rule survives in a vector summary and reaches `manifest.json` | **high — it is this release's characteristic failure** | `RETIRED_CLAIMS` per deleted rule, patterns written from a grep done *before* the deletion |
| The capability check's hard failure is treated as breakage rather than sequencing | high | §Mechanics item 2; registry, `RULES` and vector in one commit |
| The release grows a second package mid-flight | medium | The menu is the scope decision; a second package is a second release |
| Downstream's `KNOWN_PASSING` resets are discovered rather than announced | medium | Removed vectors listed by name in the changelog |
| A vector's `expect` outlives the rule it asserts | medium | Named under C, and it applies wherever an `expect` states a treatment |
| A package is reviewed only against `python-zipline`'s reading, and the transforming-decoder cost goes unpriced | **medium, and it is invisible by construction** | Scope decision 5; the eight transforming vectors are a Phase 0 step, and D and E each carry the finding |
| The `0.19` milestone's inherited issues are silently dropped | low | Scope decision 1 |

---

## Definition of done

Clarification half:

- [x] **§Terminology names each term and points at where it is stated**, restating
      no rule, and no longer says a decoder derives a decoded stream from a
      transport one. *It is a `## Terminology` section now, so its anchor no
      longer moves when the version does — the link guard found that at the
      stamp.*
- [x] **A decode stage is defined as creating a layer**, and it says out loud that
      such a stage need not run a decoder.
- [x] The *created/preserved* and *decode stage/pass-through* vocabularies are
      bound to each other once, not maintained as two.
- [x] The transform enumeration is in `ENUMERATIONS` with its members, failing the
      build if a transform is added without updating it. *Its matcher now accepts
      **bold** as well as `code`, this being the first set whose members are prose
      terms rather than identifiers.*
- [x] `RETIRED_CLAIMS` carries the stale definition, reproducing against
      `v0.18-r2`.
- [x] Normative counts unchanged by the clarification. *All eleven differences
      belong to Package B and each has a `NORMATIVE_REMOVALS` entry.*

Package-independent:

- [x] Exactly one of A–E is complete; the others are untouched in this file. *B.*
- [x] `CHANGELOG.md` `[0.19]` has a `Removed` section naming every deleted option,
      rule and vector, the vectors as a list.
- [x] Every `RETIRED_CLAIMS` entry added by the release reproduces against
      **`v0.18-r2`** and is absent now. *Four entries: two for the clarification,
      two for Package B.*
- [x] `ENUMERATIONS` passes, with any dead locator re-anchored rather than
      deleted quietly. *2 sets, 8 sites.*
- [x] `python3 vectors/check.py` green; every vector stamps `0.19`, and
      `reject-unknown-minor` rolled to `0/20` out of its own bytes.
- [x] `ruff check` and `ruff format` clean.
- [x] The package's own Done list above, complete.
- [ ] `python-zipline` is told which package landed **before** the tag, not after —
      its `v0.3.0` plan sequences work that three of the five packages delete.
- [ ] Tag `v0.19`.

---

## What execution changed

Recorded because a plan only ever read forwards teaches nothing. Five things this
document got wrong.

- **The release was scoped as purely subtractive and is not.** The terms were
  never pinned, and one paragraph had defined `decoder` wrongly since `0.15` —
  found by a question this plan did not think to ask. Clarification became the
  first half and gated the second, which was the right order: Package B edits the
  sequencing vocabulary, and editing it on a stale foundation is how a correction
  gets built on a misreading.
- **The clarification sweep was budgeted as the large half and was the small
  one.** Counts of 176 `decoder` and 225 `decoded` suggested a document riddled
  with loose usage; six sites needed correcting and `decoded` needed none. The
  defect was concentrated — one stale paragraph, one word doing two jobs — and
  believing the counts would have justified a far larger and more dangerous edit.
- **The guard the extraction built for one purpose is what made the deletion
  safe.** `NORMATIVE_REMOVALS` was designed to catch a rule leaving *by accident*
  during extraction. Its first real use was a release removing rules *on purpose*,
  where it forced eleven written justifications and caught one entry that claimed
  a loss which had not happened.
- **The vector estimate was low again**, for the fourth release running. Budgeted
  55, shipped 56: the plan's own Phase 1 called for rehousing the placement shape
  and the estimate did not count the vector that rehousing needs.
- **Two guards reported things no human would have found**, both in this release:
  a link into a section that had moved, and a link into the document's own title
  after the version stamp changed it. Neither is visible in a rendered page. The
  second produced a real improvement — Terminology is a section with a stable
  anchor now, rather than a bold lead-in reachable only through the title.
