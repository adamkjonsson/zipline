# Zipline

The **Zipline Payload Format** (`.zpf`) is a file format for the payload of
network traffic — the bytes that flow between endpoints once packets have been
reassembled into sessions, plus the metadata needed to consume them.

It is designed to:

- hold **many sessions** per file, each modelled as **N participants** (both
  directions of a TCP connection, or every speaker in a chat room);
- keep **raw reassembled bytes** as the source of truth, with **decoded** views
  produced as separate, provenance-linked files;
- be **append-only and streamable**, so writers stay memory-bounded on
  unbounded input;
- order participants by **TCP seq/ack causality**, not just timestamps, so two
  sides captured separately with skewed clocks still interleave correctly.

The format is tool-independent — any program can read or write it.

## Key ideas

**Payloads, not packets.** A capture file answers *what was on the wire*; a
`.zpf` answers *what did they say*. Reassembly happens before anything is
written, so consumers get clean per-sender byte streams — retransmits,
reordering, and packet boundaries are already gone.

**One shape for every conversation.** A session is N participants exchanging
records. Both directions of a TCP connection (N = 2), a five-person chat room,
a one-way multicast feed — the same model, with no special cases.

**Causality beats clocks.** When each direction is captured at a different tap,
the clocks disagree — sorting by timestamp can put an answer before its
question. Zipline stores the TCP seq/ack numbers and orders records by their
happens-before relation instead; timestamps only break ties. A producer can
even bake the resolved order into the file, so every reader gets a correct
timeline for free.

**Raw bytes are the source of truth.** Decoding (TLS → HTTP → …) produces new
files that reference the original by content hash and byte ranges — like build
artifacts pointing at their sources. Every byte of input is either decoded or
explicitly marked undecoded, so nothing vanishes silently and any decode can be
verified or re-derived.

**Streamable at both ends.** Sessions are declared when they first appear and
closed when they finish, so a writer ingesting unbounded live traffic — and a
reader tailing the file behind it — both run in bounded memory.

**Cheap to read.** Fixed little-endian layout, 4-byte alignment,
skip-what-you-don't-know framing, and a line-per-object JSON projection for
eyeballs and scripts. The work sits with writers so that readers stay simple.

## Status

**Version 1.0 — the specification is final.** The format is stable for
implementation and interchange; future changes arrive only as version bumps
(minor bumps add blocks/options that old readers safely skip). No reference
implementation exists yet — implementations are welcome.

## Documentation

- [docs/payload-format.md](docs/payload-format.md) — the specification:
  conceptual model, normative binary container, JSON-Lines projection, causal
  ordering, and the raw → decoded derivation workflow.

## License

See [LICENSE](LICENSE).
