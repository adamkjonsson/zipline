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

## Status

Early design. The format is not yet implemented; the specification is being
worked out.

## Documentation

- [docs/payload-format.md](docs/payload-format.md) — the format design sketch:
  conceptual model, binary container, JSON-Lines projection, causal ordering,
  and the raw → decoded derivation workflow.

## License

See [LICENSE](LICENSE).
