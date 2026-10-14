# Release 0.22 — the downstream release

*Written 2026-10-13 against **`v0.21`** (`d8e6963`). Sources are the three issues
on the `0.22` milestone — #151, #152, #153 — all filed from
`python-zipline-wire`: the first while implementing its `0.4.0`, which deleted
the #146 shim, the other two while planning python-zipline-wire#35, the
`packets.zpf → inner.zpf` hop of the decrypted-tunnel example. This is a working
roadmap, not normative text.*

*Extended 2026-10-14 with four more, #154–#157, which `python-zipline` filed while
reviewing the candidate (`plan_0_22` at `08bc9d7`). See
[Review round](#review-round-154157). They correct the candidate before the tag
and do not change the three rulings.*

*The release is **`0.22`**, not `0.22.0`, per the changelog's Conventions.*

---

## What this release is

**Every item comes from a downstream stage that `0.21` made possible and that the
text then failed.** #146 placed a transport stream past 2 GiB, and #151 is the
same premise on the other axis: the causal edge rule still compares an `ack`
against record ends by serial arithmetic, and the two are not within 2³¹ of each
other. #152 and #153 are the first real sessionizer over a real packet stream
(`kober`'s WireGuard output) reading the worked example literally. The first finds
a MUST that leaves the stage no conformant way to coalesce two packets. The second
finds that the one type a generic sessionizer needs is routed into a private
namespace.

**It adds one rule, one carve-out, and one content-type scheme. It adds no body
field and no option.** #151 extends `0.21`'s unwrap rule to acks. #152 lets a
sequence-anchored transport output cross an input seam, because its offsets
already carry the break. #153 adds `net:`, a fourth `content_type` scheme with
two closed values. Only #153 changes bytes in an existing vector (`tunnel`'s
`packets.zpf`, retyped).

**Keyword counts.** `0.21` left them at `MAY 54, MUST 124, MUST NOT 44,
SHOULD 28`. This release expects **one** addition, #152's MAY, and no
removals. Any sentence that turns out to need a keyword gets a
`NORMATIVE_ADDITIONS` entry with its argument. No sentence is worded to avoid
one.

**The `adjacency` name is settled.** `0.21` kept the port's reading of the
field's name open on python-zipline#58, and said a better pair would be this
release's first item. #58 is closed and nobody proposed a different name, so
there is no such item.

---

## The three, ranked

| | Issue | What it is | Where it lands | Blocks downstream? |
|---|---|---|---|---|
| **1** | #151 | an `ack` is compared serially against record ends arbitrarily far ahead, so a sequenced stream past 2 GiB with a pure-ACK peer fails the causal check | §Causal ordering: *The guarantee*, *Fields used*, merge steps 1–2; one vector | **yes**. `python-zipline-wire` `0.4.0` ships a strict `xfail` and a known-limit paragraph |
| **2** | #152 | the no-splice duty forbids a transport-layer output from ever coalescing across an input unit or Discontinuity | §Discontinuity, one sentence (a MAY); the worked example's third bullet; one vector | **yes**, but softly. `0.5.0` closes a run at every seam, giving one record per TCP segment on `kober`'s input |
| **3** | #153 | no format-level type for "one network packet" | §Typing a decoded record; §Enums gains a `net:` table; `tunnel` retyped; one vector | no. `--content-type` defaults to `dec:ip-packet` meanwhile |

The ranking is by who is waiting. 1 is a defect a conformant file trips over, and
it can be tagged alone. 2 costs nothing in correctness today, only record count,
and the one downstream that pays for it has said what it does in the meantime. 3
is an enhancement with a working configuration flag in the meantime.

---

## Scope decisions

*Decided 2026-10-13. Each one took the recommended option, except #153's
vocabulary, where both values were taken.*

### 1. #151: acks unwrap along the acker's stored order; no writer duty

The issue's candidate rule is the right one, and the text needs only the
sentences `0.21` wrote for `seq_start`, applied to a second field.

> A record's `ack` is a **position in the peer's offset space**. Walking the
> acker's records in stored order, each ack's position is the previous ack's
> position plus the signed serial delta of the two values. The first ack's
> position is its signed serial delta from the **peer's origin**: `isn + 1`, or
> the peer's first captured byte. Step 2 then compares two positions in one
> space, the peer record's end (its unwrapped offset plus `payload_len`) and the
> ack's position, with plain `≤`.

**The text has to settle three points the issue leaves open:**

- **Acks are not monotonic in stored order, and the rule must not assume they
  are.** The issue says an ack never retreats. That is true on the wire in send
  order, but stored order is `seq_start` order. Suppose a segment was lost and
  retransmitted after newer data was acked. Its record then carries a later ack
  than the record stored after it. A *signed* delta from the predecessor handles
  this exactly. A running maximum would not: it would credit a record's sender
  with bytes it had not yet received when it built the record, which is a
  **false edge**. The rule therefore says *signed delta from the previous ack*
  and never *maximum*. *(Wrong about the maximum, as #155 showed. Any edge a
  maximum adds is implied through the participant's own earlier record, so
  ordering is unchanged. The rule stands; the reason was replaced in Phase 5.)*
- **The walk skips records with no `ack`,** just as the offset walk skips an
  unplaceable record. The predecessor is the last record that carries one. A peer
  record that is **unplaceable** has no end, so it is never a `Q` and draws no
  edge. Its own `ack`, if it has one, still unwraps and still places it as an `R`.
  Placement and acknowledgement are independent.
- **The bound, and why it needs no keyword.** Consecutive acks 2³¹ or more apart
  can arise when a peer is silent for 2 GiB and the writer stored none of its
  pure ACKs, or when the first ack lies 2³¹ past the peer's origin. Such a jump is
  read as a *retreat*. The ack's position is then **under**estimated, which only
  removes edges. *Caveats* already makes the soundness argument: an ack is a
  lower bound, and an underestimate yields a sound partial order with fewer
  edges, so the timestamp tie-break decides more. A sequenced check cannot fail
  because of it, since fewer edges means fewer constraints. One sentence states
  this and points at *Caveats*' existing advice to store pure ACKs as zero-length
  records, which is how a writer that cares keeps the edges. **No new
  MUST/SHOULD (decided).** *(Corrected in Phase 1: the claim holds for
  **forward** steps only. A **backward** step of 2³¹ or more would read as a
  jump and invent edges. That needs a segment retransmitted after 2 GiB of its
  peer's data and stored ahead of an original, as in acks `o`, `o+1.5`, `o+3`,
  `o+0.5` GiB. The text states both directions. The writer's exit for the
  backward case is to omit that retransmission's `ack`, which only removes
  edges, so it still adds no keyword. The comment on #151 claimed the forward
  half as the whole, and is corrected when #151 is closed.)* The issue's own shape needs none of this: the
  server's SYN-ACK record anchors its ack at position 0, every later client
  record ends above it, and no edge is drawn.

**Two sites carry the claim #151 refutes, and both are retired:**
*The guarantee*'s *well-defined for any two values within 2³¹ of each other —
vastly more than any in-flight window — so it never misorders real traffic*
([:346–349](zipline-payload-format.md)), and *Fields used*' *an `ack` … compares
directly against the peer record's computed end*
([:340–342](zipline-payload-format.md)). Merge step 1's sentence *all seq
comparisons below are serial-number comparisons* becomes *positions are
unwrapped (see Referencing), and every comparison below is plain*. Step 2's
`(seq_start + payload_len, mod 2^32) <= a` becomes `end_offset <= ack_position`.
The *Transport neutrality* paragraph's property (a) stays true and needs no edit.

**It changes no byte of any file.** For every session where consecutive acks and
the first ack's distance from the peer's origin are under 2³¹, which covers every
existing vector, the unwrapped comparison gives the same answer as the serial
one.

**One vector:** `sequenced-past-2gib-pure-ack`, on the accept tier. It is
`stream-past-2gib`'s client: four eight-byte records at 1 GiB spacing, with a
server participant whose only record is a zero-length SYN-ACK carrying
`ack = isn + 1`, and the session has `SEQUENCED` set. The summary names the
wrong reading: a reader comparing serially draws `client@2GiB → SYN-ACK` and
reports the stored order as a causal violation. **`check.py` gains no ack
arithmetic.** Ground rule 2 keeps the suite out of semantics except for the pair
checks, and no pair check orders records, so this vector tests implementations
only. Its `RULES` entry is `acks-unwrap`.

### 2. #152: a sequence-anchored transport output carries a break as a hole, so it MAY cross

The no-splice duty exists so that a break visible at one stage is not lost at the
next. At a transport output whose records carry `seq_start`, the break cannot be
lost, because a missing range is a range no record covers. That is the reason
the specification already gives for barring a Discontinuity there. The duty's
purpose is met and only its wording forbids the crossing. **So the consumer duty
gets one carve-out, in the paragraph that states it**
([:2142–2154](zipline-payload-format.md)):

> A decode stage whose output is at the **transport layer** and whose records
> carry `seq_start` discharges this duty through its sequence numbers: it **MAY**
> emit a record whose `spans` cross input units, or an input Discontinuity. Its
> sequence numbers then assert that those bytes join, and it answers for that
> assertion as any reassembler does.

**Three things the issue does not say, and this plan settles:**

- **The carve-out covers crossing an input Discontinuity in a `contiguous`
  participant, not only a `units` seam, and fan-out is why.** In the tunnel, the
  datagram that failed to decrypt may have belonged to a *different* inner flow.
  Flow A's two segments are then contiguous in A's sequence space while
  `packets.zpf` correctly declares a break between them. Forbidding the
  coalesce would make A's reassembler respect a break in a stream it never
  carried.
- **The issue's proviso is dropped.** *Provided the record's bytes are contiguous
  in its own sequence space* is always true: a transport record *is* the range
  from `seq_start` to `seq_start + payload_len`. Writing the proviso would suggest
  a check that cannot fail.
- **The scope is `seq_start`, not the transport layer as a whole.** A transport
  output without sequence numbers, such as a UDP sessionizer, has no holes to
  carry a break in. It keeps the duty as written, which costs nothing because it
  emits one datagram per record anyway.

**The closing sentence that refused a third case is rewritten, not deleted.**
*No third case is defined … none but the declaration* (2152–2154) stays true for
decoded outputs and gains *at the decoded layer*. The *leave the crossing
undone* paragraph (2156–2162) stays as is. It describes a stage that *cannot*
express the break, and a sequence-anchored transport stage now can.

**The worked example's third bullet** ([:1176](zipline-payload-format.md), *The
crossing is left undone*) is wrong after this change. It is rewritten to say
that flow A's second record starts at 100 because a real 40-byte hole is there,
and that if the two segments had been contiguous, the reassembler could have
emitted one record whose spans cite both. The fixture stays the same: its
records are already correct under the new rule.

**Considered and not taken: telling a packet-preserving stage which `adjacency`
to declare.** `kober` writes `units`, while `tunnel`'s `packets.zpf` writes
`contiguous` plus one Discontinuity. Both are conformant. Under this carve-out a
sequence-anchored consumer behaves the same on either, which is part of the
argument for the carve-out, so the question does not need an answer in this
release.

**One vector:** `sessionized-across-units`, accept tier, single-file. It is a
sessionizer's output whose Decoder declares `output_layer = transport`, citing an
input whose participant is `units`. One record carries **two** spans, two inner
packets that are not adjacent in the input (another flow's packet sits between
them), and its `seq_start` and length make them one contiguous run. The summary
says the shape is accepted, that the seam predicate does not apply because it
tests decoded layers only, and that nothing could catch a *wrong* coalesce here,
since the sequence numbers are the producer's assertion. `RULES`:
`transport-crosses-by-seq`. The `NORMATIVE_ADDITIONS` entry is the MAY.

### 3. #153: a `net:` scheme, closed, with `net:ip` and `net:ethernet`

Option 2 from the issue, with both values (decided). The issue is right that a
packet is a format fact the way a pcap link type is, and that neither public
scheme fits it.

| Token | Payload is exactly one… | Defined as |
|---|---|---|
| `net:ip` | IP packet, header first; the version nibble says 4 or 6 | pcap `LINKTYPE_RAW` (101) |
| `net:ethernet` | Ethernet frame from the destination address, no preamble or SFD | pcap `LINKTYPE_ETHERNET` (1) |

**For approval: one `net:ip` value, not `ipv4`/`ipv6` as well.** The version
nibble already says which, so two more tokens would only state it twice. Defining
each value by its pcap link type means the format writes no packet grammar of
its own, and it settles cases the table leaves open (an Ethernet FCS, for
example) the way every pcap reader already settles them.

**Properties, each copied from an existing mechanism:**

- **Closed and spec-defined, like `prim:`.** The tokens live in a §Enums table
  beside `prim:`'s. A `net:` token the reader does not know is treated as an
  unknown scheme is (opaque, fall back to the decoder `name`). That makes
  later values *safe to skip*, so new link types can be added in a `1.x` minor
  when a producer asks for one.
- **No binding rule, unlike `prim:`'s width.** `prim:` is checkable because width
  and `payload_len` are both in the frame. Whether a payload *is* an IP packet is
  protocol parsing, which the format does not do. The label is trusted the way a
  `mime:` label is.
- **The decoded layer only.** Already covered by the transport-layer MUST NOT on
  `content_type`. Nothing new.

**Text sites.** §Typing's *three schemes* list ([:946](zipline-payload-format.md))
becomes four. The *packet-preserving* paragraph
([:1025–1029](zipline-payload-format.md)), which today prescribes a `dec:` token,
now names `net:`. That paragraph currently argues why a `dec:` token is right,
and the argument is retired with a `RETIRED_CLAIMS` spelling. §Enums gains the
table and one sentence saying `net:` is closed. **No keyword:** typing a record
is optional, so a SHOULD to use `net:` would be the first SHOULD attached to
choosing a label.

**`tunnel` is retyped.** Three records and their `.jsonl` faces change from
`dec:ip-packet` to `net:ip`, and so does the worked example's `packets.zpf`
bullet ([:1121](zipline-payload-format.md)). `packets.zpf`'s bytes change, so
`inner.zpf`'s `digest` of it changes, and `check_tunnel` re-derives it. **One new
vector** covers the other value: `decap-ethernet`, accept tier, a VXLAN
decapsulation stage whose records are inner Ethernet frames typed
`net:ethernet`. That is the real case for the second value. `RULES`:
`net-types-packets`.

---

## Mechanics

**1. Expected numbers:** 65 vectors (62 + 3), 37 rules (34 + 3), options
unchanged at 35. One keyword is added (the MAY) and none retired. The
`net:` scheme adds no option, because `content_type` already exists.

**2. `RETIRED_CLAIMS`, from a grep done before the edit.** Expected spellings,
to be confirmed in Phase 0 and validated against `v0.21`: *vastly more than any
in-flight window* (spec :348); *compares directly against the peer record's
computed end* (:341); step 2's `mod 2^32) <= a`; *with three schemes* (:946);
*and with a `dec:` token* (:1027); *The crossing is left undone* (:1176). The
`CHANGELOG` line at :1520 is history and stays.

**3. `ENUMERATIONS`.** Phase 0 checks whether any site lists the `content_type`
schemes as a set. Today only §Typing does, so the guard needs no new set unless
the grep finds a second site. *(It found two more: the registry row and the
`prim:` paragraph. Phase 3 adds the set. See Phase 0's findings.)* The `prim:` table has no guard of its own, so the
`net:` table gets none either.

**4. No external gate.** `0.21`'s gate on Phase 2 was waived the day it was set.
This release's three decisions are posted to the filing issues in Phase 0, as
notice rather than a gate, so `python-zipline-wire` can build to them before the
tag.

---

## Phase 0 — stamp, the grep, and the posts

1. `MAJOR, MINOR = 0, 22` in `vectors/build.py` and `check.py`; regenerate; update
   the spec's version sites (title, every `zipline-payload/0.21` format string,
   the worked example's `version_minor` and its `.hex` check); open
   `## [0.22] — unreleased` with `Changed`, `Clarified` and `Added`.
2. Confirm `reject-unknown-minor` rolls 22 → 23, reading it from the stamped
   bytes.
3. Grep for every spelling §Mechanics item 2 names, plus *serial*, *mod 2³²* and
   *ack* across §Causal ordering, and every `content_type` scheme list across the
   five scanned files. Record the results here before any edit.
4. Post scope decisions 1–3 to #151, #152, #153 and python-zipline-wire#35.

**What the stamp found (step 1, 2026-10-13).** Two places the stamp touched by
hand that the guards do not reach. The File Header table's `version_minor` row
([:1275](zipline-payload-format.md)) still said *`18` for this document*, through
`0.19`, `0.20` and `0.21`. That is the same drift `0.21`'s sweep found in the
worked example's bytes, one table away, and `check_worked_example` cannot see a
table row. It now says `22`. Phase 4 decides whether `check.py` should compare
that row to `MINOR`. It is one regex, and this is the second time a hand-kept
copy of the version has drifted. `reject-unknown-minor` reads `0/23` from its own
bytes, against `raw-minimal`'s `0/22`.

**What the grep found (step 3, 2026-10-13, against `aacfcdf`).** Sites are in
the six files `RETIRED_CLAIMS` scans or the README links from. Line numbers are
from before any edit.

*For Phase 1 (#151):*

- spec `:340–342`: *An `ack` is natively an absolute number in the peer's
  sequence space, so it compares directly against the peer record's computed end
  (`seq_start + payload_len`)*. **Retires.** The first half stays true; the
  *compares directly* half is the claim.
- spec `:344–349`: *all comparisons of `seq_start`/`ack` — and of the derived
  record end — use serial-number arithmetic … well-defined for any two values
  within 2³¹ of each other — vastly more than any in-flight window — so it never
  misorders real traffic*. **Retires** from *vastly more*. Serial arithmetic
  stays the comparison between *consecutive* values. Positions are compared
  plainly.
- spec `:367–369` (*A record's end … is always `seq_start + payload_len` (mod
  2³²)*) is rewritten: the end is the unwrapped offset plus `payload_len`.
- spec `:378–386`, merge steps 1–2: *All seq comparisons below are serial-number
  (RFC 1982) comparisons* and `(seq_start + payload_len, mod 2^32) <= a`. Both are
  rewritten. The pseudocode spelling gets a `RETIRED_CLAIMS` pattern.
- spec `:434`: *every peer record it acks (end ≤ `ack`)*. This stays: it reads
  correctly once *end* and *ack* name positions.
- spec `:436` (*bounded by the in-flight window*), `:451` and `:454` (*Transport
  neutrality*, *serial-number rule/space*), and `:2543` (*serial-number order*,
  the ordering rule): all stay. Each is about consecutive values or memory, not
  about comparing an ack with an end.
- spec `:461–467`, *Caveats*' lower-bound bullet and pure-ACK bullet: stay, and
  are the two bullets the bound sentence cites.
- `build.py:4155` and `manifest.json:1652` (`stream-wraps-seq`'s *under
  serial-number order*): stay. They are about `seq_start`.
- **No suite site says anything about acks**, and none says *compares
  directly*. The new vector is the suite's first statement on the ack axis.

*For Phase 2 (#152):*

- spec `:1176–1180`, the worked example's *The crossing is left undone … it
  declines the crossing, which is what this is*. **Retires.** The fixture stays.
- spec `:2147–2154`, *No third case is defined … none but the declaration*. This
  is rewritten to apply *at the decoded layer*. The spelling is not retired,
  because the sentence survives with a qualifier.
- spec `:2156–2162`, *it has to leave the crossing undone*. This stays. It
  describes a stage that cannot express the break, and that sentence is still
  true.
- `CHANGELOG.md:1520` (`0.17`'s *It declines the crossing instead*) is history
  and stays. The changelog is not scanned.

*For Phase 3 (#153):*

- spec `:946`, *with three schemes*. **Retires** and becomes *four*.
- spec `:1025–1029`, the packet-preserving paragraph: *and with a `dec:` token,
  because "one inner packet" is precisely what distinguishes …*. **Retires.**
- spec `:1121`, the worked example's `packets.zpf` bullet, *typed
  `dec:ip-packet`*. This is rewritten.
- spec `:2336`, the `content_type` registry row, *`mime:`/`prim:`/`dec:`*. **A
  second list of the schemes**, which §Mechanics item 3 asked about. It becomes
  `mime:`/`prim:`/`net:`/`dec:`. Two sites list the set, so the scheme set
  qualifies for an `ENUMERATIONS` entry (*content_type schemes*, anchored at
  `:946` and `:2336`), and Phase 3 adds one.
- spec `:2476`, *No other `prim:` token is legal — `mime:` and `dec:` carry
  everything else*. A third list, and an implicit one: it becomes *`mime:`,
  `net:` and `dec:`*.
- `build.py:5625–5757`: `tunnel`'s three `packets` records, its summary, and
  three `.jsonl` faces, all `dec:ip-packet`. `vectors/README.md` and the
  rationale companion do not mention the token. The companion's `:268` (*a
  `content_type` scheme is the cheaper place*) is about a different, declined
  marker, and stays.

## Phase 1 — #151, the ack axis (taggable alone)

- §Causal ordering per scope decision 1: *The guarantee* (the retired claim
  becomes a pointer to the unwrap rule); *Fields used* (`ack` is a position in
  the peer's offset space); merge steps 1–2; one sentence on the bound beside
  *Caveats*' lower-bound bullet. §Referencing's unwrap paragraph gains one
  sentence: acks unwrap the same way, along the acker's records.
- `sequenced-past-2gib-pure-ack`, `RULES` `acks-unwrap`, `RETIRED_CLAIMS` for
  the two §Causal spellings.
- `vectors/README.md` row.

## Phase 2 — #152, the carve-out

- §Discontinuity consumer paragraph: the MAY, and *at the decoded layer* on the
  *no third case* sentence. §Conformance's sessionization-stage bullet
  ([:2700](zipline-payload-format.md)) gains a clause pointing to it.
- The worked example's third bullet rewritten.
- `sessionized-across-units`, `RULES` `transport-crosses-by-seq`,
  `NORMATIVE_ADDITIONS` for the MAY, `RETIRED_CLAIMS` for *The crossing is left
  undone*.

## Phase 3 — #153, `net:`

- §Typing: four schemes, `net:` described; the packet-preserving paragraph names
  `net:ip`. §Enums: the table and the closed-vocabulary sentence.
- `tunnel` retyped (`build.py` bytes and `.jsonl` faces, written by hand rather
  than substituted, per `0.21`'s single-sourcing lesson); the worked example's
  bullet.
- `decap-ethernet`, `RULES` `net-types-packets`, `RETIRED_CLAIMS` for the
  three-schemes and `dec:`-token spellings.

## Phase 4 — sweep, changelog, downstream, tag

1. Sweep the four example JSONL blocks, the vectors README and the rationale
   companion for `dec:ip-packet`, `three schemes` and serial ack comparisons
   that the guards cannot see. `0.21`'s sweep found three releases of drift in
   prose like this.
2. `CHANGELOG.md` `[0.22]`: `Changed` (acks unwrap, with the sentence that no
   existing file reads differently; `tunnel` retyped); `Clarified` (the
   carve-out: no conformant file becomes wrong, and a file that only declined
   crossings stays conformant); `Added` (`net:` with its two values; the three
   vectors).
3. Add a `RELEASE-0.22-PLAN.md` line to `README.md`.
4. Tell `python-zipline-wire` on #151–#153 (the xfail can become a pass, the
   per-seam cut can go, and `--content-type` can default to `net:ip`), and tell
   `python-zipline` about the ack arithmetic in `_check_not_already_acked` and
   the new scheme. Tell `kober` through its WireGuard example that `net:ip`
   replaces `dec:ip-packet`.
5. Tag `v0.22` on the merge commit.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The ack rule is written with a running maximum, because the issue says acks never retreat | **high**, since it is the issue's own wording | Scope decision 1's first bullet goes into the text as a sentence: signed delta from the previous ack, and why *(the "why" was wrong; see #155)* |
| The bound sentence grows into a SHOULD during writing | medium | The decision is recorded above; the soundness argument is *Caveats*' and is cited, not re-made |
| The carve-out is read as *transport outputs owe nothing*, and a UDP sessionizer coalesces datagrams | medium | It is scoped by `seq_start` in its own sentence, and the third bullet of scope decision 2 explains why |
| Retyping `tunnel` is done with a blind substitution that also rewrites the HTTP hop's `dec:request` | low–medium | The faces are edited by hand, and the face check refuses any mismatch with the bytes |
| A third `net:` value (`ipv4`, `ipv6`, `ieee802_11`) is added "while we're here" | medium | Closed list of two; later values are safe to skip, so adding them can wait for a producer |
| `check.py` grows an ack check to give `sequenced-past-2gib-pure-ack` something to fail | low | Ground rule 2. The vector is for implementations, and its summary says so |

---

## Definition of done

- [ ] §Causal ordering compares unwrapped positions; the two serial claims are
      retired; `sequenced-past-2gib-pure-ack` exists; #151 closed with the text.
      *(All but the closing. Four spellings are retired, not two.)*
- [ ] §Discontinuity has the `seq_start` carve-out (one MAY, with its entry); the
      worked example no longer says the crossing must be left undone;
      `sessionized-across-units` exists; #152 closed. *(All but the closing.)*
- [ ] `net:` is a fourth scheme with `net:ip` and `net:ethernet` in §Enums;
      `tunnel` carries `net:ip`; `decap-ethernet` exists; #153 closed.
      *(All but the closing.)*
- [x] `python3 vectors/check.py` green at 0.22: **65 vectors, 35 options,
      37 rules**; `reject-unknown-minor` at `0/23`.
- [x] Counts `MAY 55, MUST 124, MUST NOT 44, SHOULD 28`, or the difference
      accounted for by entries. *(Exactly these. One addition and no removals.)*
- [x] `ruff check` and `ruff format` clean.
- [ ] `CHANGELOG.md` `[0.22]` dated; three implementations told; `v0.22` tagged.
      *(The entry is written; the date waits for the merge.)*

---

## What execution changed

*Written 2026-10-13, at the end of Phase 4's pre-merge half.*

**The plan stated #151's bound in one direction only, and the issue comment
repeated it.** Scope decision 1 said a misread ack step "only removes edges".
That holds for a **forward** step of 2³¹ or more, which reads as a retreat and
underestimates. A **backward** step that wide reads as a jump and invents edges.
It needs acks stored in the order `o`, `o+1.5`, `o+3`, `o+0.5` GiB, which means
retransmissions delayed past gigabytes of peer data and stored ahead of
originals. The case is contrived, but the plan's sentence was false and a port
would have quoted it. The text states both directions, and the backward case has
an exit (omit that retransmission's `ack`) that again only removes edges, so the
release still adds no keyword. Working through the issue's wording, *an ack never
retreats*, showed it to be false in stored order, and a running maximum, the
natural first draft, would have invented edges in the ordinary retransmission
case. Phase 1 found this before writing the rule, not after. *(The last claim was
itself wrong. #155 showed that a maximum's extra edges are all implied by the
participant's chain, so it changes no order. Phase 5 replaced the reason in the
text.)*

**`tunnel`'s packets were not packets.** The plan said to retype three records,
but their payloads were filler whose first nibble was 5, so `net:ip` would have
been a false label in the vector that defines it. They are now real IPv4 headers
on their TCP payloads, with the sizes kept, so no quoted offset moved and the
retype rippled through two digests. A label that a reader may trust has to be
true in the fixture that teaches it.

**The grep found two more scheme lists than the plan expected**, the registry row
and the `prim:` paragraph's *`mime:` and `dec:` carry everything else*. The second
is an enumeration nobody would have recognised as one. They became the release's
`ENUMERATIONS` set. Anchoring the registry row exposed a limit in the guard: a
locator inside a table row matches both the row and its table, so no row could be
a site. `check_enumerations` now takes the row when one match contains the other.

**A second hand-kept copy of the version had drifted.** The File Header table
said *`18` for this document* through three releases, one table away from the
worked-example bytes that `0.21`'s sweep caught. The stamp fixed it, and
`check.py` now compares the row with `MINOR`. It was seen to fail on a stale
value before it was trusted.

**The sweep found one more stale paragraph the guards could not see:** the
tunnel fixture's README said `inner.zpf` *cannot* express the break and leaves
the crossing undone. It now says the break is carried as a hole and points to
`sessionized-across-units`. The rationale companion needed nothing.

**The numbers landed where the plan put them**: 65 vectors, 35 options, 37
rules, and one keyword added. Closing #151–#153 with their final text (#151's
including the corrected bound), telling the three implementations, the date and
the tag all wait for the merge.

---

## Review round: #154–#157

*Written 2026-10-14. `python-zipline` read the branch at `08bc9d7` and filed four
issues against it, all on the `0.22` milestone. Two correct things this release
claimed (#154, #155), and two make its text precise (#156, #157). None reopens a
scope decision. All four are fixed on the branch before the merge, as Phase 5.*

| | Issue | What it is | Where it lands |
|---|---|---|---|
| **4** | #154 | `tunnel`'s and `decap-ethernet`'s packets declare TCP but carry no TCP header, so `net:ip` is false and `inner.zpf` cannot be rebuilt from `packets.zpf` | `tunnel` (bytes, offsets, faces), the worked example, the vectors README, `check_tunnel`; `decap-ethernet`; `sessionized-across-units` |
| **5** | #155 | the reason given for *previous ack, not a running maximum* is wrong | §*The guarantee*, one paragraph; the changelog bullet; this plan |
| **6** | #156 | `net:ethernet` does not say whether the frame carries an FCS | the `net:` table row and its sentence |
| **7** | #157 | ack positions are signed, and an unplaceable record still gets edges as `R` | §*The guarantee*, one sentence; §*Fields used*, one sentence |

### 4. #154: real TCP headers, and the worked example becomes executable

*Decided 2026-10-14: real headers, carrying PSH|ACK.*

The issue is right, and it catches the release breaking its own rule. Phase 3
replaced filler with "real IPv4 packets" and the execution notes said *a label
that a reader may trust has to be true in the fixture that teaches it*. But the
header says protocol 6 and no TCP header follows, so any packet parser reads the
first 20 payload bytes as a malformed segment. The stronger point is the second
one: the flows `inner.zpf` builds (ports 44300→80 and 44301→53, `seq_start` 1001,
1081 and 5001) cannot be derived from `packets.zpf`. A generic sessionizer, which
#153's `net:ip` exists to serve, cannot rebuild the next hop from this one.

**`tunnel`: each inner packet gets a 20-byte TCP header** carrying `inner.zpf`'s
ports and sequence numbers, with flags **PSH|ACK** and a plausible ack number.
The TCP payloads are unchanged (40, 20 and 30 bytes), so the packets grow by 20
each:

| | Packet | Before | After |
|---|---|---|---|
| flow A, seq 1001 | `IP_A1` | `[0,60)` | `[0,80)` |
| flow B, seq 5001 | `IP_B1` | `[60,100)` | `[80,140)` |
| flow A, seq 1081 | `IP_A2` | `[100,150)` | `[140,210)` |

`packets.zpf`'s extent goes from 150 to 210, so `inner.zpf`'s spans and
`input_extents` move with it. **What does not move:** `outer.zpf`, `inner.zpf`'s
own offsets (they count TCP payload) and `http.zpf`'s spans. The digests ripple
as before.

**`inner.zpf` gains what a faithful sessionizer would carry**: each record gets
`ack` and `flags: ["psh"]`, because the segments now say both (decided). This
adds two keys to each record line of the worked example's `inner.zpf` JSONL. The
ack numbers are chosen once and named in the vector (flow A's peer and flow B's
peer each get an ISN).

**Not in scope: making `outer.zpf` consistent with WireGuard framing.** Its
80-byte datagrams are smaller than an 80-byte plaintext plus WireGuard's 32 bytes
of overhead. They are ciphertext and carry no label, so nothing claims they are
real, and growing them would move `outer.zpf`'s offsets and every span citing
them for no reader's benefit. The vectors README says the outer sizes are
nominal.

**`decap-ethernet`: real UDP headers, with frame sizes kept (approved).**
Each inner IPv4 packet becomes protocol 17 with an 8-byte UDP header (ports,
length and checksum true), and the payload filler shrinks from 26 and 16 to 18
and 8 bytes. Frames stay 60 and 50 bytes, so the vector's offsets, extent and
README numbers do not move. UDP rather than TCP also gives the suite one packet
that is not TCP.

**`sessionized-across-units` (approved): realigned to the new `tunnel`
offsets.** Its summary calls it *`tunnel`'s inner hop with nothing lost* and cites
`[0,60)`, `[60,100)`, `[100,150)`. Those become `[0,80)`, `[80,140)`,
`[140,210)` with extent 210, so the two vectors can still be read together. Its
70-byte record and session 11's 20-byte record do not change.

**Sites, from a grep against `08bc9d7`:**

- the spec's worked example: the packet bullet's `[0,60) [60,100) [100,150)`
  ([:1170](zipline-payload-format.md)), three `spans` and two `input_extents` in
  the `inner.zpf` JSONL (:1185–1204), and the fan-out bullet's `[0,150)` and
  **150** (:1226–1228);
- `build.py`: `ipv4()` gains a real TCP header (a `tcp()` helper beside it), and
  the `tunnel` packets, inner and summary sites (around :6014–6420);
- `check.py`: `check_tunnel`'s `covers(…, 150)` and its message (:1860, :1884);
- `vectors/README.md`: the tunnel section's `[0,150)` and *extent 150*
  (:478–479), the decap row, and the `sessionized-across-units` row.

### 5. #155: a running maximum is equivalent for ordering; the reason is replaced

The issue is right, and Phase 1's reasoning was wrong. Suppose a running maximum
gives record `R_k` the position of an earlier record `R_j`. Every edge `Q → R_k`
this adds is implied by `Q → R_j` together with `R_j → R_k`, the participant's
own chain, which the merge never reorders. So no order changes, and the
stored-order check gives the same verdict. What a maximum gets wrong is a
per-record fact, *this sender had not received those bytes*, and nothing in the
format observes it.

**The rule stays the same: step from the previous ack**, because that is the
natural unwrap and it stays well-defined when acks retreat. **The justification
is replaced** with the issue's own sentence: where only ordering matters, a
running maximum of ack *positions* gives the same result. That is a sentence of
equivalence, not a permission, so it carries no keyword. Without it, the text
reads as if `python-zipline`'s `_StoredOrder`, which keeps a maximum, were
non-conformant.

**The backward-step case in *Caveats* is not affected.** That case is an
*overestimated* position, read past every earlier record's true position, so its
edges are not implied by anything. Phase 1's *What execution changed* paragraph
was right about the bound and wrong about the maximum.

**Corrections elsewhere:** the changelog bullet *Previous ack, never a running
maximum*; scope decision 1's first bullet and *What execution changed* in this
plan, each annotated rather than rewritten; and the #151 closing comment, which
already has to correct the bound and now corrects this as well.

### 6. #156: `net:ethernet` carries no FCS

Taken as proposed. The row becomes *Ethernet frame, from the destination address
to the end of the payload; no preamble, SFD or FCS*. `LINKTYPE_ETHERNET` admits
both forms, so deferring to it settled nothing. The table's lead sentence says
each token *has that link type's meaning*, and gains *except where the row says
more*, so that the row overriding the link type is visible rather than a
contradiction. `decap-ethernet` already has no FCS, so the vector does not change.

### 7. #157: ack positions are signed, and an unplaceable record is still an `R`

Both points are taken as proposed. Each one is the text losing a qualifier the
decision had.

- **§*The guarantee*:** an ack position is a **signed** integer. One below 0
  acknowledges no captured peer byte, so no edge reaches it. This happens when a
  mid-stream capture's first ack lies below the peer's first captured byte.
- **§*Fields used*:** *An unplaceable record has no end and draws no edge*
  becomes *An unplaceable record has no end, so no edge runs from it; an `ack` it
  carries still places it after the peer bytes that ack covers.* That is scope
  decision 1's second bullet, which the Phase 1 text shortened.

**One vector (approved): `sequenced-ack-below-origin`.** A mid-stream
`SEQUENCED` session with no `isn` on either side. The acker's first record stores
an ack 8 below the peer's first captured byte, and is stored **before** every
peer record. Read as signed, its position is −8 and no edge reaches it, so the
order is causal. Read as unsigned, the position wraps to near 2⁶⁴ and draws an
edge from every peer record, so the stored order is refused. That is the bug the
issue names, and like `sequenced-past-2gib-pure-ack` it tests implementations
only. `RULES`: `ack-position-signed`. Without this vector the release would add
a sentence whose wrong reading nothing catches, and this release has already
corrected two of its own sentences.

### Phase 5 — the review fixes

One commit per issue, in this order. #157 and #155 are text-only and the
smallest. #156 is one row. #154 is last because it moves offsets and regenerates
the most.

1. **#157**: two sentences, and `sequenced-ack-below-origin`.
2. **#155**: the replaced paragraph and the changelog bullet; annotate this plan.
3. **#156**: the row and the table's lead sentence.
4. **#154**: `tcp()` and `udp()` helpers; `tunnel` rebuilt (packets, then inner's
   faces by hand, then `check_tunnel`); the worked example's sites;
   `decap-ethernet`; `sessionized-across-units`; README rows. Every `net:ip`
   and `net:ethernet` payload is then written to a pcap of the matching link
   type (101 or 1) and parsed with **packeteer** (`../packeteer`), which checks
   version, protocol, ports, sequence and ack numbers, flags and both
   checksums. packeteer is the check, not a dependency. `build.py` keeps its
   own stdlib `tcp()`/`udp()` helpers, because `CLAUDE.md` forbids
   regeneration depending on anything installed. Using an independent parser
   is the point: the claim was made once without a check, and checking it with
   a parser written by the same hand that made the mistake would not count. The
   parse output is recorded in this plan.
5. Changelog: #154 rewrites the *real IPv4 packets* bullet; #156 and #157 are a
   line each under the bullets they refine; and #155 changes the bullet on the
   running maximum.
6. Post on #154–#157 that the fixes are on the branch, and tell `python-zipline`
   on python-zipline#76 that `tunnel` is now rebuildable.

**What packeteer found (Phase 5, 2026-10-14).** I wrote every `net:` payload in the
suite to a pcap of its link type: three `net:ip` records from `tunnel/packets` at
type 101, and two `net:ethernet` records from `decap-ethernet` at type 1. A scan
of every `.jsonl` confirmed those five are all of them. `packeteer parse` read
them back as intended:

| Record | Read as |
|---|---|
| `tunnel` 1 | IPv4 10.8.0.2 → 10.8.0.9, TCP 44300 → 80, seq 1001, ack 7001, flags 24 (PSH\|ACK), 40 bytes |
| `tunnel` 2 | TCP 44301 → 53, seq 5001, ack 9001, flags 24, 20 bytes |
| `tunnel` 3 | TCP 44300 → 80, seq 1081, ack 7001, flags 24, 30 bytes |
| `decap-ethernet` 1–2 | Ethernet II aa:bb:cc:00:00:01 → :02, IPv4, UDP 40000 → 5000, 18 and 8 bytes |

`packeteer build` from the parsed specs reproduced both pcaps **byte for byte**.
packeteer writes out a checksum only when it differs from the one it computes,
which a control with one corrupted TCP checksum confirmed, so the byte-for-byte
round trip is the checksum check. packeteer also noted that the second frame
(50 bytes) is unpadded. That is shorter than the 60-byte minimum on a wire, but
it is normal for a frame a VM hands to a VXLAN endpoint before any NIC pads it,
and it is what `net:ethernet` describes.

**Two more stale sites the plan's grep missed.** The `tunnel` fixture summary's
*(4) ORIGINATION, AND THE CROSSING LEFT UNDONE … packets offset 100*, which is in
capitals, so Phase 2's retired spelling did not match it. And the guard that
should have caught #154 itself: `check_tunnel` hard-coded `packets.zpf`'s extent
as 150 and kept passing when the packets grew to 210. It now derives the extent
from the records and compares both Session Ends' `input_extents` with it, and was
seen to fail on the stale fixture first.

### Definition of done, review round

- [x] #154: every `net:ip` and `net:ethernet` payload in the suite parses as the
      packet its header says, checked by packeteer rather than by eye; `inner.zpf`
      can be rebuilt from `packets.zpf`; the worked example's offsets agree with
      the fixture; `check_tunnel` green.
- [x] #155: the reason is replaced, with no keyword; the changelog and this
      plan are corrected.
- [x] #156: the row says no FCS.
- [x] #157: both sentences, plus `sequenced-ack-below-origin`
      (**66 vectors, 38 rules**).
- [x] Keyword counts unchanged from Phase 4 (MAY 55, MUST 124, MUST NOT 44,
      SHOULD 28). None of the four needs one.
- [ ] #154–#157 closed with their text after the merge, alongside #151–#153.

