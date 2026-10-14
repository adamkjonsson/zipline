# Release 0.23 — the pure-ACK release

*Written 2026-10-14 against **`v0.22`** (`2b18b1c`). The source is the one issue
on the `0.23` milestone, #160, filed from `python-zipline` while porting to
`0.22` (python-zipline#75). This is a working roadmap, not normative text.*

*The release is **`0.23`**, not `0.23.0`, per the changelog's Conventions.*

---

## What this release is

**One defect, important enough to ship alone.** Merge step 2 gives every
record an end, including a zero-length record that occupies no sequence
space. A stored pure ACK therefore gets an edge *to* every peer record whose
ack has reached its offset, and that includes peer records sent before it. In
the ordinary trace (handshake, data, pure ACK) this makes a cycle. A correct
stored order then fails the sequenced check, and an unsequenced merge stalls
with no order to give. `python-zipline` hits it in both `0.5.2` (`0.21`) and
its `0.22` port, so it is older than #151's unwrap and not caused by it.

**Nothing has met it because nobody followed the advice.** *Caveats* tells a
writer to store pure ACKs as zero-length records *so their happens-before edges
aren't lost*. `python-zipline-wire` stores none, and every zero-length record in
the suite is a SYN. A SYN's edge is real, because it occupies a sequence number.
The first producer to follow the advice, a sessionizer over a packet stream that
accounts for inner pure-ACK packets as #154's rebuildable tunnel invites, writes
files whose ordinary TCP sessions stall.

**It changes one definition and adds no keyword, option or field.** No byte of
any file changes. What a reader *computes* for a zero-length record changes,
and so does a zero-length FIN's end, which the issue raises and the rule must
settle.

**Keyword counts.** `0.22` left them at `MAY 55, MUST 124, MUST NOT 44,
SHOULD 28`. None is expected to move. If a sentence turns out to need one, it
gets a `NORMATIVE_ADDITIONS` entry with its argument.

---

## Scope decision: a record's end is one past the last sequence number it occupies

*Decided 2026-10-14: the sequence-space rule, with data records' ends
unchanged.*

The issue is right, and its trace is exact. An `ack` acknowledges **sequence
numbers**: the bytes of data, plus the one number each SYN and FIN consumes. A
pure ACK consumes none. An ack that has reached a pure ACK's offset therefore
says nothing about the pure ACK, and step 2 should draw no edge from it. The
rule's own parenthesis, *R's sender had already received those peer bytes*, was
always about something received, and a pure ACK delivers nothing.

**The rule, per record as `Q`:**

| Record | End for step 2 | Why |
|---|---|---|
| carries data (`payload_len > 0`) | offset + `payload_len` | unchanged. Receiving the data proves the segment was sent, FIN or not |
| zero-length, `syn` | its offset | the SYN occupies `isn`, one below the origin it is stored at, so an ack of `isn + 1` (position 0) covers it. This is today's value, now with its reason stated |
| zero-length, `fin` | offset + 1 | the FIN occupies the sequence number at its offset, so only an ack one past it covers it |
| zero-length, neither (a pure ACK, a bare RST) | **none** | it occupies no sequence number, so no edge runs from it |

Every record keeps its role as `R`. A pure ACK's `ack` still orders it after the
peer bytes it covers, and that is the half of *Caveats*' advice that was sound.

**A data record carrying FIN keeps `offset + payload_len` (decided).** Counting
the FIN would make the end `+ 1` and lose the edge where an ack covers the data
but not yet the FIN. That edge is valid, because receiving the data proves the
segment was sent. So only the zero-length FIN needs a rule of its own. This
costs one more row in the table than the uniform *one past the last sequence
number*, and in return no edge that is valid today is lost.

**What a "zero-length FIN" is, for the record.** A FIN with no data on the same
segment. Its `seq_start` is the sequence number the FIN occupies, which is one
past the last data byte. Nothing new is needed to place it: it sits at the
offset where the next byte would go, like any zero-length record.

**Not in scope: any other flag.** `urg` and `psh` consume no sequence space. On
a zero-length record, `rst` consumes none either, so it falls under *neither*.
Non-TCP transports carry no `syn`/`fin` and are covered by the general wording
("occupies a sequence number"). The *Transport neutrality* paragraph's property
(a) is unaffected.

---

## Sites, from a grep against `2b18b1c`

- spec `:355`, *The guarantee*'s bullet *A record's **end** is its offset plus
  its `payload_len`*. Rewritten to point at the definition in *Fields used*,
  rather than restating a definition that is now four rows.
- spec `:391–396`, *Fields used*' end paragraph: *A zero-length pure-ACK
  record's end is simply its own offset*. **Retires.** It is the sentence that
  states the bug. It becomes the table above in prose, or as a small table,
  decided when written. The unplaceable sentence after it stays.
- spec `:412`, merge step 2's `whose end (offset + payload_len) <= a`. This
  becomes `that has an end, and whose end <= a`, with *see Fields used*.
- spec `:461`, the streaming merge's *every peer record it acks (end ≤ `ack`)*.
  It stays: a record with no end is never waited for.
- spec `:492–494`, *Caveats*' pure-ACK bullet, *store them as zero-length
  records … so their happens-before edges aren't lost*. Rewritten: their edges
  *as `R`* are kept, and they are never a source. The advice itself stands.
- spec `:1838`, *Handshake records*, *its computed end equals it and every
  causal edge and ordering rule works unchanged*. It stays true, and gains
  nothing: the SYN row in *Fields used* gives the reason.
- The `0.22` vectors are unaffected. Every zero-length record in the suite
  carries `syn`, and `sequenced-past-2gib-pure-ack`'s server record is a
  SYN-ACK, so the vector's name says more than its bytes do. Phase 2's sweep
  checks each `expect` string for a stated end.

---

## The vector: `sequenced-pure-ack-and-fin`

Accept tier, `SEQUENCED`, capture-sourced, handshake recorded. It is the issue's
trace extended by a close:

| # | Sender | `seq_start` | Payload | flags | `ack` | End | Ack position |
|---|---|---|---|---|---|---|---|
| 1 | client | 1001 | 0 B | `syn` | none | 0 | none |
| 2 | server | 5001 | 0 B | `syn` | 1001 | 0 | 0 |
| 3 | client | 1001 | 8 B | `psh` | 5001 | 8 | 0 |
| 4 | server | 5001 | 0 B | none | 1009 | **none** | 8 |
| 5 | client | 1009 | 0 B | `fin` | 5001 | **9** | 0 |
| 6 | server | 5001 | 0 B | none | 1010 | **none** | 9 |

Edges under the rule are `1→2`, `1→4`, `1→6`, `2→3`, `2→5`, `3→4`, `3→6` and
`5→6`. The stored
order 1–6 respects every one of them. **Each wrong reading fails on its own
record:**

- giving the pure ACK an end (today's rule) draws `4→3` (0 ≤ 0) against the real
  `3→4`, a **cycle**. The sequenced check refuses it, and an unsequenced merge
  stalls. Record 6 does the same against 3 and 5;
- giving the zero-length FIN its offset as its end (8) draws `5→4` (8 ≤ 8). But
  4 is stored before 5, so the sequenced check refuses the order. The server had
  acked the data and not yet seen the FIN.

Extents: client 8, since the FIN occupies a sequence number but no byte. Server
0. `check.py` draws no causal edges, so like `0.22`'s two ack vectors this one
tests implementations only. `RULES`: `pure-ack-has-no-end`.

---

## Phases

### Phase 0 — stamp, and the post

1. `MAJOR, MINOR = 0, 23` in `build.py` and `check.py`; regenerate; update the
   spec's version sites and the File Header row (now guarded); open
   `## [0.23] — unreleased` with `Changed`.
2. Confirm `reject-unknown-minor` reads `0/24` from its own bytes.
3. Post the decision on #160, so `python-zipline` can build to it. Adam tells
   `python-zipline` and the other implementations himself.

### Phase 1 — #160

- *Fields used*: the end paragraph becomes the four-row rule. *The guarantee*'s
  bullet refers to it. Merge step 2's condition gains *has an end*. *Caveats*'
  pure-ACK bullet is rewritten.
- `sequenced-pure-ack-and-fin`, `RULES` `pure-ack-has-no-end`, and
  `RETIRED_CLAIMS` for *A zero-length pure-ACK record's end is simply its own
  offset*, confirmed present in `v0.22`.
- `vectors/README.md`: an *Added in `0.23`* section with the row.

### Phase 2 — sweep, changelog, review, tag

1. Sweep the spec, the companion, the vectors README and every `expect` string
   for a zero-length record given an end. Record what is found here.
2. `CHANGELOG.md` `[0.23]`, `Changed`: zero-length records that occupy no
   sequence number draw no edge as `Q`; a zero-length FIN ends one past its
   offset. No byte of any file changes, and no answer changes for a file
   whose zero-length records are all SYNs, which covers every file written
   by an implementation so far.
3. Add a `RELEASE-0.23-PLAN.md` line to `README.md`, and update the spec's
   status history if the release earns a "first".
4. `python-zipline` reads the branch, as for `0.22`. Then the PR, and Adam
   merges, tags `v0.23`, and closes #160.

---

## What the sweep found (Phase 2, 2026-10-14)

One site, stated twice, that a reader of the new rule would trip on. *Handshake
records* said a SYN record's *computed end equals* its offset, implicitly
because it is zero length, and `handshake-at-origin`'s builder comment said
*Zero length, so its computed end equals its seq_start*. Since `0.23` zero
length gives no end at all. The SYN has one because it occupies `isn`. Both
now give that reason, and the spec sentence points at *Fields used*. Nothing
else gives a zero-length record an end:

- the streaming merge's *(end ≤ `ack`)* stays true, because a record with no
  end is never waited for;
- the Record block's *a pure-ACK record carrying only an `ack` hint* and the
  timestamp rule for a zero-length pure-ACK record are not about ends;
- the companion's framing-cost note on pure-ACK records is not about ends
  either;
- `sequenced-past-2gib-pure-ack`'s summary already says the server's pure ACKs
  are *not records*, so its name does not invite the reading the risk table
  feared.

The release earns no "first" for the status history.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The rule is written as *zero-length records draw no edge* and silently drops the SYN's real one | **high**, since it is the shortest sentence | The SYN row states its reason (the SYN occupies `isn`). `handshake-at-origin` and `sequenced-past-2gib-pure-ack` still need the SYN-ACK's edge, and the new vector needs both SYNs' edges |
| A data+FIN record gets `+ 1` by analogy with the zero-length FIN | medium | The decision says why not, in the table's first row |
| The *Caveats* advice is withdrawn rather than corrected | low–medium | Storing pure ACKs is still right, for their edges as `R` and for the 2 GiB bound. Only the claim about which edges they keep changes |
| `sequenced-past-2gib-pure-ack`'s name is read as covering this case | low | It has no pure-ACK record, only a SYN-ACK. The sweep says so in its summary if the summary invites the reading |

---

## Definition of done

- [x] *Fields used* defines a record's end per sequence space: data
      unchanged, SYN at its offset, a zero-length FIN at offset + 1, and no end
      otherwise. Step 2 and *Caveats* agree, and the retired spelling is gone.
- [x] `sequenced-pure-ack-and-fin` exists, and each wrong reading fails on its
      own record.
- [x] `python3 vectors/check.py` green at 0.23: **67 vectors, 35 options,
      39 rules**; `reject-unknown-minor` at `0/24`.
- [x] Counts unchanged: `MAY 55, MUST 124, MUST NOT 44, SHOULD 28`.
- [x] `ruff check` and `ruff format` clean.
- [ ] `CHANGELOG.md` `[0.23]` dated; `python-zipline` reviewed the branch;
      `v0.23` tagged; #160 closed.
