# Review of Zipline Payload Format 1.1-beta

Feedback on the `[Unreleased] — 1.1-beta` section of `CHANGELOG.md` and the
corresponding text in `docs/zipline-payload-format.md`, as of 2026-07-28.

Grounded in `python-zipline`, a complete implementation of 1.0 (binary
container, JSONL projection, causal merge, decode stages, coverage
validation). Each point below is something that either cost implementation
effort, produced a defect, or would produce one if 1.1 were adopted as
written. Ranked by cost to an implementer.

---

## 1. The `[strict-reader]` carve-out has no wire signal

This is the main objection. The changelog is admirably upfront that some
1.1 files may be refused by conformant 1.0 readers — but a 1.0 reader has
no way to *detect* that in advance. It is told minor bumps are safe to skip
past, so it reads the header happily, then meets an annotator file and
silently isolates every record. That is what the Python implementation does
today: diagnostic emitted, all data dropped, exit code fine. Data loss
dressed as leniency.

`version_minor` cannot serve as the signal, because the spec's own rule
says minors are additive and skippable — a reader that refused `minor > 0`
would be over-strict against the 90% of 1.1 files that are pure
clarifications. What is missing is a way to say "this file uses a construct
that changes an existing conformance rule". Either a File Header
feature-flag bit, or a normative sentence of the form:

> A file carrying `decoder_id`s alongside `origin` MUST stamp
> `version_minor ≥ 1`, and a reader enforcing 1.0 file-kind purity SHOULD
> reject `version_minor > 0` rather than isolate.

Without one of those, the relaxation is only safe once every reader has
already upgraded — the situation the version field exists to avoid.

Textually 1.1 is within its own rules (minor "may relax writer
restrictions", and 1.0 files do stay valid). The gap is in **Reading across
versions**, which promises more than the format can deliver.

## 2. The filter example contradicts the offset-space rule

The *Changed* entry motivates layer-preserving pass-throughs with "an
annotator, a filter, a re-merge". But **Each layer has its own offset
space** defines a decoded stream's offsets as the concatenation of that
participant's decoded payloads in stored order, and then draws the
consequence explicitly: a transform that re-chunks or reorders a decoded
participant's records is not a pass-through.

A filter that drops decoded records shifts every subsequent offset in that
participant's space. So decoded-layer filters are still not expressible as
pass-throughs — the one example of the three that the change was meant to
unlock. (Annotators are fine. Re-merges are fine, since per-participant
relative order survives interleaving. Transport-layer filters are also
fine, because that space is seq-derived and hole-inclusive.)

Either drop "a filter" from the motivation, or state explicitly that a
decoded-layer filter must be a decode stage that cites its input and marks
the dropped ranges `skipped` — which does work, and is a good use of the
new reason.

## 3. `sequenced_basis` is unactionable as specified

Open vocabulary, producer SHOULD set it, reader MUST NOT reject on an
unrecognised value *or on its absence*, and it "does not make the order
checkable". So no consumer can branch on it, and no absence means anything:
"no sound basis" is indistinguishable from "producer didn't bother". That
is a comment field with a registered id — and worse than a comment, because
it looks like something a tool should act on.

Make it MUST when SEQUENCED is set on a hint-less session, and its absence
becomes a real signal. Otherwise the honest move is to drop it and say
plainly that SEQUENCED is an unverifiable producer assertion, full stop —
which the relaxation already concedes ("a reader could never verify the
clock claim either").

Separately: `transport` is listed as a suggested value next to a
parenthetical saying it can never legitimately appear. Cut it.

## 4. The unrecognised-`reason` rule buys a MUST with unbounded I/O

> MUST NOT treat the range as a hole… follows the reference as for the
> bytes-exist class and reports the region empty only if nothing is found

This means: for every unknown reason string, walk the provenance chain —
opening and digest-checking each intermediate file — to learn that there
were never any bytes. The cost lands entirely on consumers, and only arises
because the vocabulary is open.

It also cannot distinguish its two failure modes. **Undecoded** says a
missing intermediate file stops recovery there, so "found nothing" covers
both "genuine hole" and "the file I needed is gone". Reporting those
identically is exactly the silent-data-loss shape the coverage guarantee
exists to prevent.

Cheaper fix: make reasons self-classifying — a required companion option,
or a syntactic prefix (`hole:tcp-gap`, `bytes:skipped`). The vocabulary was
already being touched to canonicalise `skipped`; that was the moment.

Smaller related wobble: "the class, not the word, is what a consumer acts
on" sits badly next to the justification for `skipped`, which is precisely
that a consumer counting unparsed bytes should act on the word.

## 5. "Lowest minor whose features the file uses" fights the streaming contract

The File Header is block one, and the format's headline property is
flush-and-forget with bounded memory. A live writer cannot know whether a
session it has not opened yet will need a 1.1 construct, so it must either
stamp pessimistically (contradicting "lowest") or buffer the header
(contradicting streaming).

Worth one sentence permitting a streaming writer to stamp the highest minor
it *may* emit. As written the rule is only satisfiable by batch tools.

---

## What I would not push back on

The timestamp clarification is straightforwardly right, and the Python
implementation was wrong — it rejected files for backwards hint-less
timestamps in two places. Naming the two recoverability classes was
overdue. The four escapes fix a genuine forward-compatibility hole in the
JSONL face; the flag-bit escape in particular, since set reserved bits were
being silently dropped on projection. Canonicalising `skipped` matches what
a real decoder wants to say — the implementation had independently invented
it for exactly the BOM/padding case the spec now describes.

## One ask

The changelog says clarifications are "where two independent
implementations most easily disagree". Given that, 1.1 would be
substantially more valuable with machine-checkable vectors — a handful of
small `.zpf` / `.jsonl` pairs covering the annotator shape, the four
escapes, and an unrecognised `reason`.

Prose worked examples got copied wrong once already: the four
`"time_units":"us"` examples fixed in 1.1 are the direct source of a
conformance defect in the Python implementation, which copied the examples
rather than the normative text. Vectors would have caught it at the first
test run.
