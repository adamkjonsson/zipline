# Zipline Payload Format 0.10 — review and impact on `python-zipline`

Reviewed against the [0.10 specification](https://github.com/adamkjonsson/zipline/blob/v0.10/docs/zipline-payload-format.md)
and [CHANGELOG](https://github.com/adamkjonsson/zipline/blob/v0.10/CHANGELOG.md),
tag `v0.10` (2026-07-30). This library implements 0.9.

## Verdict

0.10 is a clear improvement on 0.9 and most of it is the *right* set of changes:
the JSONL escapes close a real forward-compatibility hole, the `spans`-versus-
`origin` discriminator fixes a genuine expressiveness bug, and dropping the
lowest-version-stamp rule removes an obligation a streaming writer could not
meet. Nothing in it looks gratuitous.

Three things are worth pushing back on before we implement, and they are
detailed in [Defects](#defects-in-010-worth-fixing): a **contradiction** about
when `sequenced_basis` is required (which is also undecidable for a streaming
writer), a **gap** where the merge algorithm is left with no legal behaviour on
a hint-less session, and the absence of any expressible **version-transcode**
path, which the reject-unknown-minor rule makes newly urgent.

The single biggest cost to us is not any individual rule — it is that
`conformance.py`'s file-kind inference is built on the discriminator 0.10
replaces.

---

## Impact on this project

### What is already right

Worth stating first, because it is more than expected:

- **`_parse_format` already parses componentwise.** [jsonl.py:155](src/zpf/jsonl.py#L155)
  splits on `.` and calls `int()` on each half, so it reads `0.10` as
  `(0, 10)`. We do not have the float-parsing bug 0.10 warns about, and
  `_format_string` already emits `"zipline-payload/0.10"` correctly for
  `(0, 10)`.
- **`spans` chunking, the 28-byte packed entry, the 2340-per-option cap, and
  `origin`'s 12-byte layout** are unchanged in 0.10 and already correct.
- **No timestamp monotonicity check exists in `conformance.py`** — the checker
  never had one to remove. The checks that *do* exist are in `order.py`, and
  only two of them (see below).
- **`skipped` is already used** as an Undecoded reason by
  [decode.py:311](src/zpf/decode.py#L311); 0.10 canonicalises it, so our
  existing usage becomes conformant rather than merely permitted.
- **No filter or reordering transform exists yet** (`transform.py` has only
  `merge_files`), so 0.10's filter/reorder rules add capability rather than
  breaking anything.

### Pre-existing bug, independent of 0.10

**`time_units` is written as a unit label.**
[jsonl.py:170](src/zpf/jsonl.py#L170) renders `tick_hz = 1_000_000` as
`"time_units":"us"` via `_HZ_TO_TIME_UNIT`. 0.9's normative text already
defined that value as a *rate*, permitting only a number or a decimal string —
so this is non-conformant against **0.9 as well**, not just 0.10. We inherited
it by copying 0.9's four worked examples, which were themselves wrong; 0.10's
*Fixed* section corrects them. Fix this regardless of whether we adopt 0.10.

### Work inventory

Ordered by cost. "Break" = existing behaviour becomes wrong; "Add" = new
surface.

| # | Area | Change | Kind | Where |
|---|------|--------|------|-------|
| 1 | Conformance | `decoder_id` no longer implies decode-stage; discriminator becomes `spans` vs `origin` | **Break** | [conformance.py:270-291](src/zpf/conformance.py#L270-L291) |
| 2 | JSONL escapes | Unknown block type / enum value / flag bit need defined escapes | **Break** (data loss today) | [jsonl.py:388](src/zpf/jsonl.py#L388), [462](src/zpf/jsonl.py#L462), [517](src/zpf/jsonl.py#L517), [573](src/zpf/jsonl.py#L573) |
| 3 | Ordering | Timestamps are not an ordering invariant; must not reject | **Break** | [order.py:117-125](src/zpf/order.py#L117-L125), [order.py:258-266](src/zpf/order.py#L258-L266) |
| 4 | JSONL | `time_units` → `tick_hz`, number-valued | **Break** | [jsonl.py:146-176](src/zpf/jsonl.py#L146-L176), 311, 492 |
| 5 | Version | Stamp `0`/`10`; reject unimplemented **minor** | **Break** | [blocks.py:456](src/zpf/blocks.py#L456), 480, 510; [jsonl.py:904](src/zpf/jsonl.py#L904) |
| 6 | Decoded offsets | Positional offset space for decoded streams, newly normative | **Add** | `decode.py`, `transform.py`, `reassembly.py` |
| 7 | Undecoded | `tcp-gap` → `gap`; `reason_class` option `0x00A1` | **Break** + **Add** | [decode.py:562](src/zpf/decode.py#L562), `blocks.py`, `writer.py` |
| 8 | Session | `sequenced_basis` option `0x0053` | **Add** | `blocks.py`, `writer.py`, `conformance.py` |
| 9 | JSONL | `endpoint` always an array | **Break** | [jsonl.py:361-364](src/zpf/jsonl.py#L361-L364) |
| 10 | Source kind | Unrecognised `kind` is isolatable, not fatal | **Break** | [jsonl.py:517](src/zpf/jsonl.py#L517) |

Notes on the four that carry real design weight:

**#1 — the conformance rewrite.** [conformance.py:280](src/zpf/conformance.py#L280)
does `self._lock_kind(_DECODE, ...)` the moment a record carries a
`decoder_id`. Under 0.10 a pass-through preserving a decoded layer carries
`decoder_id` *and* `origin`, so we would reject exactly the annotator file 0.10
adds an example for. The fix is not a patch: file-kind inference has to be
re-seated on `spans`-vs-`origin`, and `Decoder`/`Undecoded` blocks must become
legal in pass-through files. This also brings the grandparent-Source rule (a
pass-through declaring the file its inherited Undecoded blocks name), which our
`_require_source` model currently has no concept of.

**#2 — the escapes are a live data-loss bug.** We do not merely lack the
escapes; [jsonl.py:388-390](src/zpf/jsonl.py#L388-L390) *silently drops*
unrecognised record flag bits after emitting a diagnostic, and
[jsonl.py:517](src/zpf/jsonl.py#L517)/[573](src/zpf/jsonl.py#L573) *raise* on an
unknown `kind`/`tcp_role` rather than carrying the number across. Our unknown-block
form (`{"type":"unknown","block_type":119,…}`) also differs from 0.10's
(`{"type":"0x0077",…}`). Of everything here this is the most worth doing on its
own merits.

**#3 — ordering.** Two call sites reject on backwards timestamps:
`_Frontier.advance` in the merge and `verify_sequenced`. 0.10 forbids both. But
see [Defect 2](#2-the-merge-has-no-defined-behaviour-on-a-hint-less-session) —
what the merge should do *instead* is not actually specified.

**#5 — no `version_minor` writer knob needed.** 0.10 withdraws the
lowest-version rule ("a writer stamps the version it implements"), so `create()`
needs no new parameter. This is simpler than the approach the old 1.1 impact
notes assumed.

### Rough size

Items 4, 5, 7, 9 are mechanical (a day). Items 2, 3, 8, 10 are contained
(a few days). Item 1 is the real work, and item 6 needs a design pass before
it can be estimated — it is the one place 0.10 adds a normative rule we have no
existing structure for.

---

## Defects in 0.10 worth fixing

### 1. `sequenced_basis` is required and exempted by the same document

The option registry says `sequenced_basis` **"MUST be present"** on a hint-less
`SEQUENCED` session, with no qualification. But *Sequenced files* says two cases
are "sound trivially, **with no basis needed at all**" — a one-participant
session and a single-sender session — and the CHANGELOG restates it ("it needs
no basis at all"). *Conformance* then says "A session with one participant, or
with only one sender, meets this trivially", which does not say whether "this"
is the soundness requirement or the recording requirement.

A checker author cannot implement both readings. Worse:

**The exemption is undecidable for a streaming writer.** `SEQUENCED` lives on
the Session Descriptor, which declare-on-first-use puts *before* the session's
records. Whether "only one participant ever sends" is not known until the
session ends. So a streaming writer deciding whether it may omit
`sequenced_basis` must predict the future — the same class of problem 0.10
correctly withdrew the lowest-version-stamp rule for.

The reader side has the mirror problem: a conformance check for "missing
`sequenced_basis`" cannot fire when the Session Descriptor is read, only at
Session End or EOF, which means holding per-session state specifically for it.

*Suggested fix:* drop the exemption from the recording requirement and keep it
only for the soundness requirement — a producer always writes
`sequenced_basis` on a hint-less `SEQUENCED` session, and the trivial cases
simply make the claim easy to justify (`protocol` or a new `trivial` value).
That is decidable at Session Descriptor time and needs no deferred state.

### 2. The merge has no defined behaviour on a hint-less session

0.10 adds, correctly, that a reader **MUST NOT** reject a file or discard a
session because timestamps run backwards. But for a *non-sequenced, hint-less*
session, timestamps are the merge's only input: with no `seq`/`ack` there are no
causal edges, so every record is concurrent and the entire order is step 4's
tie-break. If those timestamps are non-monotonic, the merge must either emit
timestamp order (contradicting stored order) or stored order (ignoring the only
signal it has) — and 0.10 forbids the third option of refusing.

Step 4's "if clocks are known-skewed, fall back to round-robin / source order"
gestures at this but is not actionable: *known-skewed* is not a property a
reader can determine (absence of `SINGLE_CLOCK` is not an assertion of skew).

This is the one place where 0.10's otherwise-welcome "timestamps are not an
ordering invariant" clarification removed a reader's error path without
supplying the behaviour that replaces it.

*Suggested fix:* state that a merge over a hint-less session is **stable** with
respect to stored order — timestamps break ties between *different*
participants' frontiers only, and never reorder one participant's records
against each other. That is implementable, deterministic, and consistent with
the per-participant stored-order MUST.

### 3. A version transcode is not expressible

While `version_major` is `0`, a reader MUST reject a `version_minor` it does not
implement. 0.10 also removes `time_units` outright rather than deprecating it,
"because 0.10 claims no compatibility with 0.9". Both are defensible. Together
they mean every existing 0.9 file becomes permanently unreadable by conformant
0.10 tooling, and the format defines no way to fix that.

A transcode is not one of the two derived-file kinds. It creates no layer, so it
is not a decode stage. It could masquerade as a pass-through — but a
pass-through MUST declare its input as a `zpf-input` Source and put `origin` on
every participant, which *changes the file's structure and provenance* to record
what was really just a re-stamp. There is no way to say "these are the same
bytes at a newer version".

This will recur at every `0.x` bump, and 0.10 says more are expected.

*Suggested fix:* either bless a transcode as a third, structurally-transparent
derivation, or state plainly in the CHANGELOG that `0.x` files are disposable
and no upgrade path will be offered. Either is fine; the silence is not.

### 4. The CHANGELOG's versioning invariant is false for 0.9

*Conventions* asserts: "Versions are `major.minor`, **matching** the
`version_major` / `version_minor` fields in the File Header." For 0.9 this is
untrue — a 0.9 file stamps `1`/`0`, because the renumbering re-tagged the July
text without rewriting it. 0.9 is the one version in the file where the stated
invariant does not hold, and nothing in the CHANGELOG or either companion
document says so.

An implementer reading only the CHANGELOG will build a 0.9 reader that looks for
`0`/`9` and rejects every real 0.9 file. One sentence fixes it.

### 5. `zpf-input` now conflates two different relationships

In the annotator example, `raw.zpf` and `decoded.zpf` are both declared
`kind: zpf-input`, but only `decoded.zpf` is an input. `raw.zpf` is declared
solely so the inherited Undecoded block's `source_id` still resolves — 0.10 says
as much ("not as a second input").

Yet *Conformance* says "Every derived file MUST declare each of its input
`.zpf`s as a `zpf-input` Source", so a consumer asking "what are this file's
inputs?" gets a wrong answer of two. The only mechanical way to tell them apart
is to check which `source_id` the participants' `origin` options point at — an
inference, not a declaration. Since `kind` is explicitly *not* a free extension
point, an option (say `referenced_ancestor`) would be the clean fix.

Minor, but it undercuts the otherwise-crisp "one `source_id` space, one
referencing mechanism" story.

### 6. Editorial: the `format` alias table illustrates with a retired version

The brevity-alias row explains the omitted-minor rule with
`"zipline-payload/1"` ⇒ major 1, minor 0 — i.e. a **1.0** file, the exact
version that was retracted, in the table a reader consults while working out
what the renumbering did. Using `"zipline-payload/0"` or a hypothetical `2`
would avoid re-raising the confusion the renumbering created.

---

## Usability and performance effects

### Improvements

- **Dropping the lowest-version-stamp rule** removes an obligation a streaming
  writer provably could not satisfy. Straight win.
- **`endpoint` always an array** removes a type branch from every reader. Costs
  us a small break ([jsonl.py:361](src/zpf/jsonl.py#L361)) and pays for itself.
- **The four escapes** cost a converter almost nothing at runtime and remove a
  whole class of silent loss. Note the unknown-block escape is *byte-exact*,
  which is stronger than the rest of the JSONL face.
- **`reason_class`** gives a consumer its one actionable fact about a
  non-canonical reason at the cost of one short string.
- **`gap` over `tcp-gap`** is right for a transport-neutral format, and costs
  only a rename.

### Costs

**Positional decoded offsets are O(k) for random access.** 0.10 newly requires
that decoded record *k* occupies `[Σ payload_len of preceding records, …)` in
stored order. For a forward streaming reader this is free — one running counter
per participant. But to resolve *one* decoded record's range without reading
from the start, a consumer must sum every preceding record's `payload_len` for
that participant. With no index block (still only a future extension) and
records interleaved across participants, answering "where did this record come
from" for an arbitrary record means scanning the file. 0.9 left this undefined;
0.10 makes it normative, so the cost is now mandatory rather than
implementation-chosen. Worth an explicit note in the spec that readers wanting
random access should build the prefix sums on a first pass.

**Reject-unknown-minor makes every `0.x` bump a hard fork.** This is deliberate
and I think correct — silent misinterpretation is worse — but it should be
understood as: every file written today becomes unreadable on the next bump,
with no migration path (see [Defect 3](#3-a-version-transcode-is-not-expressible)).
For anyone storing `.zpf` at rest rather than streaming it, that is a serious
operational property, and "do not build production on it" in the status block is
carrying a lot of weight.

**The decoded pass-through raises reader complexity meaningfully.** Supporting
it means a reader can no longer answer "which raw bytes is this record?" from
one file — the annotator example needs two hops, and 0.10 says plainly "this
file alone cannot say which raw bytes a record came from". That is a real
ergonomic loss, correctly traded for the `spans`/`origin` test staying
mechanical. Our `check_coverage` will not be able to verify a decoded
pass-through at all, since the output carries no `spans`; coverage becomes
inherited-by-assertion.

**No performance regressions** otherwise. Nothing in 0.10 touches the frame,
alignment, the merge's streaming property, or the per-participant ordering MUST
that makes it work. The worked example's byte arithmetic checks out (196 bytes,
every block 4-byte aligned, `0xFF20` is exactly the complement of the seven
defined flag bits).

---

## Recommended sequencing

1. **`time_units` → `tick_hz`** (work item 4). It is a bug against 0.9 too; do
   it first, independent of everything else.
2. **The four escapes** (item 2). Fixes live data loss, and is defensible on its
   own merits.
3. **Version stamp and minor rejection** (item 5). Small, and makes the file
   kind honest before anything else changes behaviour.
4. **Ordering rules** (item 3) — but resolve
   [Defect 2](#2-the-merge-has-no-defined-behaviour-on-a-hint-less-session)
   first, or we will implement a behaviour the spec may later contradict.
5. **Mechanical renames and additions** (items 7, 8, 9, 10) — but resolve
   [Defect 1](#1-sequenced_basis-is-required-and-exempted-by-the-same-document)
   before implementing `sequenced_basis`.
6. **The conformance rewrite** (item 1), then **decoded offset spaces**
   (item 6). These are the design-heavy ones and benefit from the rest landing
   first.

Items 1–3 leave the library reading and writing 0.10's container correctly.
Items 4–6 are what make it *conformant*.
