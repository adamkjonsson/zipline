# Release 0.24 — the sessionizer release

*Written 2026-10-28 against `main` at `7332016`, one commit past **`v0.23`**
(`3808439`). The source is the five issues on the `0.24` milestone, #163 and
#166–#169. Four were filed from `python-zipline` and `python-zipline-wire` while
building sessionizers over packet streams, and one (#163) is a follow-up to
#162. This is a working roadmap, not normative text.*

*The release is **`0.24`**, not `0.24.0`, per the changelog's Conventions.*

---

## What this release is

**Every issue comes from one kind of producer.** A sessionizer turns a packet
stream into transport streams: zpfwire over a pcap or a `.zpf`, or a stage over
zipline-kober's decrypted tunnel packets. `0.22` and `0.23` gave it the rules for
TCP. Putting real traffic through it has found what those rules leave out:

| # | Kind | The gap, in one line |
|---|---|---|
| #168 | spec, question | A pure ACK stored past a FIN puts the FIN's sequence number inside the stream's extent, and nothing says that position is not a hole |
| #166 | spec | A UDP datagram reassembled from IP fragments in a `units` input has no conformant record, because the 0.22 permission is keyed on `seq_start` |
| #169 | spec | A capture-point copy of a UDP datagram must be written, and nothing can mark it as a copy |
| #167 | vectors | No vector has a sequence-anchored record crossing a **declared** Discontinuity, and no vector has its mirror that must be reported |
| #163 | vectors | Multi-file vectors are exempt from `merged`, because the key cannot say which file's session an order belongs to |

**Each spec issue has a measured cost.** #168 makes every TCP input over
`zpfwire 0.8.0` fail `check_coverage` in zipline-kober (64 of 64 failures).
#166 loses every fragmented datagram on the packets path (0 of 1,600 written
for 1,000–4,000 B datagrams at MTU 576). #169 leaves 330 of 330 mirror copies
in a 40-seed run unmarked.

**Byte impact.** #169 adds a flag bit, which is new in the Record body's `flags`.
Under the `0.x` rule a `0.23` reader rejects a `0.24` file anyway, so no reserved
bit is reinterpreted. #166 and #168 change no byte of any file. They change what
a stage may write and what a coverage check counts. #163 and #167 are suite
work only.

**Keyword counts.** `0.23` left them at `MAY 55, MUST 124, MUST NOT 44,
SHOULD 28`. #169 is expected to add one or two `MUST NOT`s. #166 should rewrite
an existing `MAY` without adding one. #168 should need none, since it is a
definition. Each new keyword gets a `NORMATIVE_ADDITIONS` entry with its argument.

---

## Scope decisions

*All four decided 2026-10-28, each as proposed. Phase 0 posted the decided form
on each issue before any text was written, so the implementations can build to
it.*

### D1 — #168: an extent is measured in sequence space, and a FIN's position is not a hole

*Decided 2026-10-28: the issue's reading 1, plus one sentence on coverage.*

The offset space **is** sequence-number space already. Every transport offset is
`seq_start` unwrapped from the origin. *Fields used* says a zero-length FIN
occupies the number at its offset. And the 0.23 *Caveats* tell a writer to store
the pure ACK that sits one past that number. Reading 2 (*an extent counts
bytes*) would create a new reader rule to undo something the format already
says, and it costs something real. A pure ACK stored after a lost tail segment
is the only evidence the tail existed:

```
A: data [0, 100)      lost: [100, 150)      A: pure ACK at 150
```

Under reading 1 the extent is 150, and `[100, 150)` is a gap that a decode stage
must mark. Under reading 2 the extent is 100, and the loss disappears.

**The rule, in two sentences:**

1. *Referencing the source by stream offset* states the transport extent
   outright. It is the furthest point any placeable record reaches, where a
   record reaches offset + `payload_len`, so a zero-length record reaches its own
   offset. Today's arithmetic is unchanged: it is what `check.py`'s
   `anchored_ranges`, python-zipline's `stream_extent` and zpfwire already
   compute. It is just never stated as a definition. *Session End*'s `extent`
   points at it, as it already points at *Layers*.
2. *Coverage honesty* gets one sentence: **the position a FIN occupies holds no
   byte, and the coverage guarantee owes it nothing.** It is not a hole, so it
   needs no `gap`. It is not content, so it needs no span. A span reaching over
   it covers it harmlessly, as a span over any hole resolves to no bytes. A
   checker finds the position from the input itself: it is the data end of the
   record carrying `fin`, or the offset of a zero-length `fin` record.

**What this decides for python-zipline.** `check_coverage` is right, and
`_extent_and_gaps` changes: a decode stage declares 2363, not 2362, and leaves
2362 uncovered. It is posted on #168 so the two computations can agree before
the branch does.

**Not in scope.** A FIN whose segment was lost but whose trailing ACK was
captured leaves a one-position gap that nothing explains. That is honest: a
segment *was* lost, and `gap` is the right word for it. The plan says so in the
sentence's rationale and does not make a rule for it.

**The alternative not taken.** Reading 2 is one sentence too (*a
zero-length record extends no extent*). It costs the lost-tail evidence above,
and it changes the measure that `check.py` and python-zipline both compute
today.

### D2 — #166: the permission is keyed on `seq_start` **or `message`**

*Decided 2026-10-28: the issue's option 1, keyed on something a checker can
see.*

Option 1 as written keys the permission on *an output unit reassembled from
fragments of one network-layer datagram*. That is true, and a checker cannot see
it. The evidence (IP identification, fragment offset, the MF bit) is in the
input's `net:ip` bytes, so a splice check would have to parse IPv4 to tell a
conformant reassembly from a violation. The format already has a word for the
claim: **`message`**, *the record is exactly one transport message*. A
transport-layer record that is one whole message and that cites several input
units asserts that those units join as that message's reassembly. That is the
same assertion `seq_start` makes, answered for in the same way.

**The rewrite** of §Discontinuity's *A transport-layer output whose records
carry `seq_start` meets both duties through its offsets* (spec `:2233–2245`):

- the paragraph names two kinds of join evidence. One is sequence numbers, in a
  record carrying `seq_start`. The other is one message's reassembly, in a record
  flagged `message`, as from IP fragments or SCTP DATA chunks;
- the existing `MAY` covers both: such a record may cross input units **or an
  input Discontinuity**. Fragments under fan-out interleave with other flows'
  packets, exactly as #152's segments did;
- the last sentence narrows to *a transport record with neither*. It still owes
  both duties as stated.

**The checker's test becomes decidable:** a transport-layer record whose spans
cross units or a declared break is permitted when it carries `seq_start` or
`message`, and must be reported otherwise. #167's mirror vector (Phase 4) is
then the negative case for both.

**Not in scope: an incomplete reassembly.** When a fragment is lost, the stage
holds pieces that are not a message. Writing them as a `message` would be
false, and the withholding rule (`:2124`) forbids leaving them out of a
non-anchored stream. This is #169's tension again (the comment on #166 quotes
it), and it is not what #166 asks for. **Decided:** open a separate issue for
it, against a later milestone, rather than settle it under this one.

### D3 — #169: a `copy` flag, at bit `0x0100`

*Decided 2026-10-28: the issue's option 1, with two constraints that make it
checkable.*

Option 2 contradicts the withholding rule's own premise, as the issue says.
Option 3 writes the ambiguity down without resolving it. Option 1 mirrors
`retransmit`, so the flag says what the capture point did and the content stays
in the stream.

| Choice | Decided | Why |
|---|---|---|
| bit | **`0x0100`**; the reserved mask becomes `0xFE20` | `0x0020` is the bit `escape-reserved-flag-bit` sets. Taking it would change that vector's bytes and its lesson, and taking `0x0100` changes nothing |
| token | `copy` | the issue's word, and it reads against `retransmit` in the table |
| meaning | this record repeats its participant's **preceding** record as one transmission seen twice. The sender sent once | names the capture point's act, like the paragraph at `:2548` |
| payload | **MUST NOT** be set unless the payload is byte-identical to the preceding record's | checkable from one file. A copy separated by another datagram stays unflagged, which is the conservative reading |
| where | **MUST NOT** be set on a record carrying `seq_start` | a sequence-anchored copy is the reassembler's to discard and cite (`duplicate-discarded`), which the paragraph already says |
| reader | a reader **MAY** treat a flag that breaks either rule as a semantic violation and isolate the session | gives the negative vector something to test |
| producer | sets it only when it can tell. When it cannot, it writes the copy unflagged, which is the existing *SHOULD treat the repeat as a resend*, extended to name this flag | zpfwire's stated plan |

The paragraph at `:2548` gains a second half: *for a stream without a sequence
anchor, where the copy cannot be discarded, the flag says so.* Caveats' bullet
at `:523` gains one clause.

**Not in scope: what a decode stage does with a copy.** It may decode it or
leave it to a consumer. Whether `skipped` fits a copy's range is a real
question, and #169 does not ask it. It goes into the sweep's findings.

### D4 — #163: multi-file `merged` items name their file

*Decided 2026-10-28: as the issue writes it.* `{"file": "raw", "session_id": 7, "order":
[1, 2, 3]}`. `file` is the stem as `files` lists it, required on a multi-file
entry and absent on a single-file one. `check_merged` and `build.py` apply the
ownership rule per file. A grep confirms that **only `chain` owes it today**
(sessions 7 of `raw`, `annotated` and `decoded`; `merge`'s `a`/`b` have one
sender each, and `merged` is sequenced). The new multi-file vectors below may
owe it as well, which is why it lands first.

---

## Sites, from a grep against `7332016`

- spec `:392–410`, *Fields used*. Unchanged. D1 refers to its FIN row and does
  not restate it.
- spec `:772–845`, *Referencing the source by stream offset*. D1's extent
  definition goes beside *The offset space is contiguous* or the unplaceable
  paragraph (*contributes nothing to the extent*), whichever reads better when
  written.
- spec `:1104–1107`, *Coverage honesty*, the coverage guarantee. D1's FIN
  sentence.
- spec `:1726–1728`, *Session End* `extent`. It already points at *Layers*.
  Check that it still lands on the definition.
- spec `:2124–2128`, the withholding rule. Unchanged. D2 and D3 are both built
  so that it holds as written.
- spec `:2223–2245`, the unit-sequence duty and the transport permission. D2's
  rewrite.
- spec `:2534–2559`, the `flags` table, the reserved row and the `retransmit`
  paragraph. D3.
- spec `:523–527`, *Caveats*' reassembler bullet. D3's clause.
- spec *JSONL mapping*: the `flags` token list, if it enumerates them. The
  `enumerations` check (4 sets, 12 sites) will say where.
- `check.py`: the `flags` enumeration, `check_merged` (D4), `covers` (D1's FIN
  exemption), and a pair check for each new multi-file vector.

---

## The vectors

*Names are proposed. The trace of each is fixed when it is built and checked by
script against the generated `.jsonl`, as in `0.23`.*

| Vector | Issue | Tier | Shape | A wrong reading fails because… |
|---|---|---|---|---|
| `closed-final-ack` | #168 | accept, single file | a handshake, data, a data+FIN from each side, and each side's final pure ACK at its wire number | `extents` states one past the data: reading 2 measures one short, on both streams |
| `decoded-past-fin` | #168 | accept, pair | `closed-final-ack` as input. A decode stage's Session End declares the D1 extents and leaves each FIN position uncovered | a coverage check that counts the FIN's position reports a gap, which is the zipline-kober failure |
| `sessionized-fragments` | #166 | accept, pair | `packets.zpf`: a `units` participant of `net:ip` records, two fragments of one UDP datagram with another flow's packet between them. `inner.zpf`: one `message` record citing both fragments' payload | a splice check keyed on `seq_start` alone reports it |
| `sessionized-across-break` | #167 | accept, pair | as #167 proposes: contiguous `packets.zpf`, flow A, B, A, with a declared Discontinuity before A's second packet. `inner.zpf`: flow A as one record with `seq_start`, crossing it | a splice check that applies the decoded layer's duty to a transport record reports it |
| `isolate-transport-splice` | #167, #166 | isolate, pair | `sessionized-across-break`'s `inner.zpf` with flow A's record carrying neither `seq_start` nor `message` | a splice check that waves every transport record through misses it. It is the pairwise twin of `isolate-unmarked-break` |
| `udp-capture-copy` | #169 | accept, single file | a UDP exchange with one datagram seen twice, the second flagged `copy` | a reader without the token fails the JSONL round-trip. The `expect` prose states messages-as-sent |
| `isolate-copy-differs` | #169 | isolate, single file | a `copy` record whose payload differs from its predecessor's | a reader that trusts the flag blindly accepts it |

`sessionized-fragments` and `sessionized-across-break` may share one
`packets.zpf` builder. Whether to ship the input `sessionized-across-units` has
never shipped (#167's first bullet) is **left alone**: `sessionized-across-break`
checks a crossing against a shipped input, which is what that bullet asked for.

Estimated counts: **68 → 75 vectors**, about six new `RULES` entries. The real
numbers go in the Definition of done.

---

## Phases

### Phase 0 — stamp, decisions, the posts

1. Adam decides D1–D4. Record the dates here, as in `0.23`. *(Done: all four
   decided 2026-10-28, as proposed.)*
2. `MAJOR, MINOR = 0, 24` in `build.py` and `check.py`. Regenerate. Update the
   spec's version sites and the File Header row. Open `## [0.24] — unreleased`
   with `Added` and `Changed`.
3. Confirm `reject-unknown-minor` reads `0/25` from its own bytes.
4. Post each decision on its issue (#166, #168 and #169 especially), so
   python-zipline and zpfwire can build to them. Adam tells the implementations
   himself. "Fixed" comments wait for the merge to `main`.

### Phase 1 — #163, `merged` per file

- `check_merged` and `build.py`: the `file` key, required on multi-file entries
  and refused on single-file ones. The ownership rule applies per file.
- `chain` declares its three orders (1 2 3, 1 2, 1 2), each compared with its
  prose.
- See each new check fail (a missing `file`, an unknown stem, a file's session
  left out) before trusting it, as in #162.

### Phase 2 — #168, the FIN's position

- The extent definition and the coverage sentence (D1). *Session End* still
  points at the definition.
- `check.py` `covers`: exempt the FIN position, found from the input. Seen to
  fail on `decoded-past-fin` without the exemption.
- `closed-final-ack` and `decoded-past-fin`, and their `RULES` entries.

### Phase 3 — #166, a reassembled message may cross

- The §Discontinuity rewrite (D2). Confirm the `MAY` count does not move.
- `sessionized-fragments`, with a pair check that the record's spans cross the
  `units` seam and that it carries `message` and no `seq_start`.
- File the incomplete-reassembly issue (D2's *Not in scope*), if Adam agrees.

### Phase 4 — #167, the declared break, both ways

- `sessionized-across-break` and `isolate-transport-splice`, with a pair check
  that confirms the crossing really crosses the declared block.
- These come after Phase 3 because the mirror tests the rule in its final form:
  a record with **neither** kind of evidence.

### Phase 5 — #169, `copy`

- The flag row, the reserved mask, the `retransmit` paragraph's second half,
  and *Caveats*' clause (D3). `NORMATIVE_ADDITIONS` entries for the new
  `MUST NOT`s.
- The JSONL token, wherever the `enumerations` check lists `flags`.
- `udp-capture-copy` and `isolate-copy-differs`.

### Phase 6 — sweep, changelog, review, tag

1. Sweep the spec, the companion, the vectors README and every `expect` string
   for: an extent described as a byte count (D1); a permission or `expect` that
   names only `seq_start` (D2); any text that says a UDP copy cannot be marked
   (D3). Record the findings here.
2. `vectors/README.md`: an *Added in `0.24`* section.
3. `CHANGELOG.md` `[0.24]`. **Added:** the `copy` flag. **Changed:** the
   transport permission accepts `message`; a transport extent is defined, and a
   FIN's position owes no coverage. No byte of an existing file changes.
4. A `RELEASE-0.24-PLAN.md` line in `README.md`, and the status history if the
   release earns a "first".
5. python-zipline reads the branch. Then the PR, and Adam merges, tags `v0.24`,
   and closes the five issues.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| D1's coverage sentence reads as *zero-length records are owed nothing* and swallows a real gap before a pure ACK | **high**, since it is the shorter sentence | the sentence names the FIN's position only. `closed-final-ack` could carry a lost-tail stream too, if the trace stays readable |
| The extent definition contradicts the unplaceable paragraph (*contributes nothing to the extent*) | medium | define it in terms of *placeable* records, in the same paragraph or the next |
| D2's `message` wording lets any message-oriented record cross a seam for any reason | medium | the permission is for a record that **is** one message built from the units it cites. A record that joins two messages is not one message, and the flag is already a claim the writer answers for |
| `copy` is read as covering TCP | low–medium | the `seq_start` exclusion is normative, and the paragraph keeps `duplicate-discarded` as the TCP path |
| A new multi-file vector owes `merged` and is built before Phase 1 | low | Phase 1 comes first, and `build.py` refuses an unowed shape once it lands |

---

## Definition of done

- [ ] D1–D4 decided and dated here, and posted on their issues.
- [ ] A transport extent is defined once, and the coverage guarantee owes a
      FIN's position nothing (#168).
- [ ] A transport record carrying `message` may cross input units or a declared
      break, and one with neither `seq_start` nor `message` owes both duties
      (#166).
- [ ] `copy` defined at `0x0100`, with its two `MUST NOT`s accounted for (#169).
- [ ] Multi-file `merged` items name their file, and `chain` declares its
      three orders (#163).
- [ ] The seven vectors above, or what the build made of them (#166–#169).
- [ ] `python3 vectors/check.py` green at 0.24, with the real counts recorded;
      `reject-unknown-minor` at `0/25`.
- [ ] Keyword counts recorded, with every change accounted for.
- [ ] `ruff check` and `ruff format` clean.
- [ ] `CHANGELOG.md` `[0.24]` dated; python-zipline reviewed the branch; `v0.24`
      tagged; #163 and #166–#169 closed.
