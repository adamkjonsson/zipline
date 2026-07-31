# Zipline Payload Format 0.11 — review

Review of the [0.11 specification](https://github.com/adamkjonsson/zipline/blob/v0.11/docs/zipline-payload-format.md)
and [CHANGELOG](https://github.com/adamkjonsson/zipline/blob/v0.11/CHANGELOG.md),
tag `v0.11`. Written from `python-zipline`, a complete implementation of `0.9`
(binary container, JSON-Lines projection, conformance checker, causal merge,
decode-stage and pass-through transforms).

This is the second round: it follows a review of `0.10`, which `0.11` was
released to correct. Findings from that round are tracked in
[Part 1](#part-1--010-findings-confirmed-fixed); new and surviving findings are
in [Part 2](#part-2--what-remains).

---

## Verdict

**`0.11` does what it set out to do.** All six `0.10` findings are fixed in the
normative text — verified by diffing the two specifications, not by reading the
CHANGELOG's claims. The release adds no block, no option and no capability, as
advertised; the one addition (`sequenced_basis` value `trivial`) is load-bearing
for one of the fixes and could not have been omitted.

Two fixes are better than what was proposed. Nothing in `0.11` introduced a new
problem.

**Three things remain**, none of them blocking. One is worth resolving before
independent implementations proliferate, because it is the only place where two
conformant readers can still disagree about a file. The other two are a missing
definition and a one-sentence imprecision.

---

## Part 1 — `0.10` findings, confirmed fixed

| # | `0.10` finding | Resolution in `0.11` | Verified |
|---|----------------|----------------------|----------|
| 1 | `sequenced_basis` required by the registry, exempted by the narrative, SHOULD in a third passage; exemption undecidable for a streaming writer | Recording made unconditional; new `trivial` value; all three passages agree | ✅ |
| 2 | Merge had no defined behaviour on a hint-less session; step 4's skew fallback was not implementable | Merge specified as **stable** w.r.t. stored order; skew fallback removed; reader always uses timestamp | ✅ |
| 3 | No expressible version-transcode path | `0.x` files declared **disposable**; upgrade transform deferred to `0.12` | ✅ (see [note](#looking-ahead-to-012)) |
| 4 | CHANGELOG's "versions match the header fields" invariant false for `0.9` | Stated in *Conventions* and in the `[0.9]` section | ✅ |
| 5 | `zpf-input` conflated "my input" with "a file my inherited references name" | Clarified: immediate inputs are the Sources `origin`/`spans` point at | ✅ |
| 6 | `format` alias table illustrated with the retracted `"zipline-payload/1"` | Now `"zipline-payload/2"` | ✅ |

Two of these were resolved better than proposed, and the difference is worth
recording:

- **#1** — the review suggested dropping the exemption. `0.11` instead separated
  *recording* from *soundness* and added `trivial` to carry the case that the
  exemption used to cover. That keeps the producer honest (it must still name
  what it relies on) while making the rule decidable at the moment `SEQUENCED` is
  written. It also caught a third inconsistent passage the review had missed.
- **#5** — the review suggested a new option to distinguish the two kinds of
  `zpf-input` Source. `0.11` instead made the existing structure load-bearing:
  the immediate inputs are whatever `origin` or `spans` name, and anything else
  is there to resolve a reference. Same discriminating power, no new surface.

---

## Part 2 — What remains

### 1. The exact-timestamp tie is unresolved, and it is the last place readers can disagree

`0.11` states the gap openly, which `0.10` had masked behind its
round-robin fallback:

> Independent per-reader merges come close — they all break ties by timestamp —
> but two concurrent records bearing the *same* timestamp are a genuine tie that
> this document does not resolve, so readers may still differ there.

Surfacing it was right. Leaving it open is worth reconsidering, because it means
**two conformant readers can produce different orders for the same
non-sequenced file** — which is precisely the property the format otherwise
sells, and the reason sequencing is offered as an optimisation rather than a
correctness fix.

The cost of closing it is nil. Within a session, `participant_id` is unique
(it is scoped to its session), so the merge's frontiers are totally ordered by
`(timestamp, participant_id)`. Combined with the stability rule `0.11` already
adds, that yields a single deterministic order for every file, with no new
option, no new field, and no cost to any reader.

**Suggested wording**, replacing step 4 of the merge algorithm:

> 4. Where the topo order is free (concurrent records with no causal edge
>    between them), break ties by timestamp; where timestamps are equal, by
>    ascending `participant_id`.

And in *Sequenced files*, the determinism paragraph becomes a plain statement
that independent reader merges agree, rather than a caveat.

Note this is already the de-facto behaviour in at least one implementation:
`python-zipline` merges on `(timestamp, pid)` today, because a total order was
needed to make the merge testable at all. That is weak evidence that
implementations will converge on `pid` anyway — better to specify it than to
have it become folklore.

### 2. "hint-less" is load-bearing but never defined

The term carries normative weight in thirteen places, including the
`sequenced_basis` **MUST** and the `SEQUENCED` soundness rule. The closest thing
to a definition is a parenthetical in *Conformance*:

> a session with no causal hints (no TCP `seq`/`ack` — e.g. chat or one-way UDP)

Two consequences follow, and an implementer must guess at both:

**The mixed case is undefined.** A session where *some* records carry
`seq_start`/`ack` and some do not is neither clearly hint-less nor clearly
hinted. It is not exotic: a capture that begins mid-stream, or a writer that
folds pure-ACKs into the next data record, can produce one. The natural reading
is that any hint anywhere yields causal edges, so the session is *not* hint-less
and needs no basis — but the text does not say so.

**The property belongs to records, not to the Session Descriptor.** A reader
validating "a hint-less `SEQUENCED` session MUST carry `sequenced_basis`" cannot
evaluate it when it reads the Session Descriptor, because whether the session is
hint-less is not yet known. The check must be deferred to Session End or
end-of-stream. That is cheap — one boolean per open session, and it composes
with the state a reader already keeps — but it is the kind of thing every
implementer rediscovers independently, and the `isolate-sequenced-no-basis`
vector will silently encode whichever answer its author chose.

**Suggested fix:** define the term once, where it is first used, and state the
evaluation point:

> A session is **hint-less** when no record in it carries `seq_start` or `ack`.
> A single such hint anywhere in the session yields causal edges, so the session
> is not hint-less. Because this is a property of the session's records, a
> reader can only conclude it at [Session End](#session-end-0x12) or
> end-of-stream; a checker defers the `sequenced_basis` requirement to that
> point.

### 3. The merge's new producer-tie-break sentence overreaches

`0.11` adds, correctly, that the tie-break choice belongs to the producer:

> A producer computing a sequenced order **MAY** choose a different tie-break —
> round-robin, source order, anything deterministic — if it knows the clocks are
> unreliable, and it says so with `sequenced_basis`.

But `sequenced_basis` is scoped to hint-less sessions — *Conformance* is explicit
that "a session carrying `seq`/`ack` … needs no `sequenced_basis`". So a TCP
session's producer that breaks concurrent-record ties by something other than
timestamp has nowhere to record that fact, and the sentence implies otherwise.

Nothing breaks — a sequenced session's stored order is authoritative regardless
of how it was arrived at, and a reader never re-derives it. It is an imprecision
rather than a defect. Scoping the clause ("…and, on a hint-less session, says so
with `sequenced_basis`") would settle it.

---

## Looking ahead to `0.12`

`0.11` resolves the transcode finding by declaring `0.x` files disposable and
deferring an upgrade transform to `0.12`. Two observations for whoever designs
it.

`0.11` is itself the argument for one: a release that changes no frame, no block
body and no field meaning still orphans every `0.10` file, because the minor is
the only way a reader tells them apart. The churn is real and will recur at every
bump.

The transform is probably **not** a new derived-file kind. A transcoded raw file
is still raw — capture-sourced, same bytes, same ids — and forcing it through the
pass-through shape would require declaring a `zpf-input` Source and putting
`origin` on every participant, recording a derivation that did not happen and
moving capture provenance a hop away. What is actually missing is a way to say
"these bytes were re-stamped from version X", which a single File Header option
would carry without disturbing the two-kind taxonomy. Worth considering before
the taxonomy grows a third branch.

---

## Verified correct

Checked while reviewing, and sound — recorded so the next reviewer need not
re-derive them:

- **Worked example byte arithmetic.** The 196-byte raw file is internally
  consistent: every block's `length` matches its content, every block and every
  block content begins on a 4-byte boundary, and the block-to-block jumps
  (`0x18 = 0x00 + 8 + 16`, `0x34 = 0x18 + 8 + 20`, …) land correctly. Only the
  `version_minor` byte changed from `0.10`, and the total is unaffected.
- **Reserved flag mask.** `0xFF20` is exactly the complement of the seven defined
  record flag bits (`0x00DF`), and the escape example's `"0x0020"` is a genuinely
  reserved bit rather than an accidentally-defined one.
- **Packed layouts.** A `spans` entry is 28 bytes (`2+2+8+8+8`), an `origin`
  12 (`2+2+8`), and the Record body 28 (`8+2+2+8+2+2+4`) — all multiples of 4,
  with the u16s leading so the u64s stay 4-byte aligned. The Undecoded body is
  byte-identical to a `spans` entry, as claimed.
- **Option-value cap.** `⌊65535 / 28⌋ = 2340` spans per occurrence is correct,
  and the chunking rule lifts it off the logical list as described.
- **Componentwise version comparison** is stated consistently everywhere it
  appears, including the warning that a float parse sorts `0.10` below `0.9`.

---

## Implementation impact

Included as evidence rather than as a request — `0.10` and `0.11` exist because
of implementation feedback, so what an existing implementation actually hits may
be useful.

`python-zipline` implements `0.9`. Moving to `0.11` is a substantial but bounded
job; the ranking below is by cost, and only the first item is design-heavy.

1. **The file-kind discriminator.** The checker infers a file's kind from
   `decoder_id`, which `0.10` replaced with `spans`-versus-`origin`. This is the
   single largest change, because it is a re-seating of the inference rather than
   a patch, and it brings the grandparent-Source rule with it. It is also the
   change most clearly worth making: the current code rejects exactly the
   decoded-layer annotator file `0.10` added an example for.
2. **The four JSONL escapes.** Not merely missing — the existing converter
   *drops* unrecognised record flag bits and *rejects* unknown `kind`/`tcp_role`
   values. This was a live data-loss bug that the escapes fix.
3. **Decoded offset spaces.** The positional-range rule is the one place `0.11`
   requires structure the implementation has no equivalent of. `0.11`'s new cost
   note (O(k) random access, prefix sums on a first pass) is accurate and was the
   guidance needed.
4. **Mechanical work** — `time_units` → `tick_hz`, `tcp-gap` → `gap`, the version
   stamp, `endpoint` always an array, `reason_class`, `sequenced_basis` including
   `trivial`.
5. **Ordering.** `0.11` turns this into a *deletion*: the implementation
   currently rejects backwards timestamps in two places, and the stability
   clarification means both checks simply go, with the existing
   `(timestamp, pid)` merge already satisfying the new rule.

One correction worth reporting upstream, unrelated to `0.10` or `0.11`: this
implementation wrote the JSONL File Header rate as a **unit label**
(`"time_units":"us"`) rather than a rate, because it was copied from `0.9`'s
four worked examples — which were themselves non-conformant against `0.9`'s own
normative text. `0.10`'s *Fixed* section corrects the examples. This is a good
illustration of examples being load-bearing in practice whatever their formal
status, and an argument for the conformance vectors carrying the weight instead.

### On the vectors

The `vectors/` directory is the most valuable thing `0.10` and `0.11` added for
an implementer. The new three-file `chain/` fixture in particular is the only
fixture that can exercise two-hop resolution through a decoded-layer
pass-through, the recovery walk, and digest verification together — which is
exactly the area of the discriminator change above, and therefore the highest-risk
part of the port. Hand-building them from the normative text rather than
generating them from an implementation was the right call, and it is what lets
them catch the divergences described here.
