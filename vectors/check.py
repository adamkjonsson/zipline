#!/usr/bin/env python3
"""Check the vectors are internally consistent and behave as the manifest says.

This is deliberately NOT a conformant reader. It knows only the frame -- type,
reserved, length -- plus the File Header body, because that is all it takes to
tell a structurally-corrupt file from a well-framed one. Semantic expectations
(the isolate tier) are stated in the manifest for a human and for an
implementation's test harness; nothing here adjudicates them, because a checker
that ruled on semantics would become a second normative authority, which is
exactly what the README says a vector must never be.

The one exception is `chain/`, where a little arithmetic is unavoidable: its
entire value is that the digests and offsets agree, and a fixture whose numbers
have silently drifted is worse than none. Those checks verify the fixture against
itself, not the specification against anything, and they are specific to those
three files -- every other check here applies to any fixture.

What it does verify:
  * every committed file matches what build.py produces (no drift)
  * every vector's declared violation count agrees with its declared tier --
    accept 0, reject 1, isolate 1. The count is declared, never computed from
    the file; see VIOLATIONS_BY_TIER
  * every capability the format defines is exercised by some vector: option ids
    and block types parsed from the specification's own tables, plus the rules
    declared in RULES. What each vector exercises is recorded by build.py, which
    built the bytes -- nothing here parses a block body
  * every site that enumerates a set the model treats as one names every member
    of it, per ENUMERATIONS -- the failure 0.17 committed four times over
  * no claim the model has retired is still in the specification or the suite, per
    RETIRED_CLAIMS. This is textual, not semantic: it holds a claim retired once
    from quietly returning, and cannot find one nobody has noticed
  * accept/isolate vectors are well-framed: block walk lands exactly on EOF,
    every length is a multiple of 4, magic and version are what this version
    defines. Multi-file fixtures are walked file by file, same as any vector
  * reject vectors actually contain the structural defect they claim
  * each accept vector's .jsonl parses and has one line per block
  * every key in every .jsonl is one the JSONL mapping defines, spelled the way
    it spells it -- a body field's or a registered option's canonical name,
    except where the alias table gives it a shorter one
  * for chain/ specifically: every declared digest is the real SHA-256 of the
    sibling file it names, and decoded.zpf's spans plus Undecoded blocks cover
    exactly the streams raw.zpf actually contains

Usage:  python3 check.py
"""

import json
import os
import re
import struct
import subprocess
import sys
from collections.abc import Iterator

HERE = os.path.dirname(os.path.abspath(__file__))


def read_bytes(path: str) -> bytes:
    """Read a file whole, in binary."""
    with open(path, "rb") as f:
        return f.read()


def read_text(path: str) -> str:
    """Read a file whole, as UTF-8 text."""
    with open(path, encoding="utf-8") as f:
        return f.read()


MAGIC = 0x5A495046
MAJOR, MINOR = 0, 19

# How many violations each tier must declare. A negative vector carrying two
# silently tests whichever the reader detects first, and passes implementations
# that never exercised the rule it was built for -- isolate-coverage-gap did
# exactly that through 0.12. This compares the *declared* count against the
# *declared* tier; it never inspects a file to count them, because a checker that
# ruled on semantics would become a second normative authority.
VIOLATIONS_BY_TIER = {"accept": 0, "reject": 1, "isolate": 1}

# One violation does not isolate: an advisory MUST NOT, where the file stays
# readable and a reader carries on having reported it. 0.16 gained the first
# (content_type on a transport-layer record, #95) and the three tiers could not
# say it -- `accept` means zero violations, `isolate` means the reader may
# discard something, and this is neither.
#
# It is a key on an accept entry rather than a fourth tier because the tier names
# what a READER does, and a reader accepts this file completely. `advisory: true`
# says the acceptance is not because the file is clean. tcp_role escapes the
# question only because an unrecognised enum value is not a violation at all.
ADVISORY_VIOLATIONS = 1

SPEC = os.path.join(HERE, os.pardir, "docs", "zipline-payload-format.md")

# The rationale companion: where the argument that produced a rule lives, so the
# specification can hold the rule alone. Written during the 0.18 re-issue (see
# docs/RATIONALE-EXTRACTION-PLAN.md). It is SCANNED, because a claim retired from
# the specification and reasserted here is still a stale claim in the tree, and an
# implementer reading the companion for context will believe it. Phase 0 measured
# the cost of that decision before taking it: of 480 paragraphs, 11 recount a
# superseded rule and NONE matches a retired spelling, so the allowlist is empty
# today. If it grows longer than the check is worth, the exit is in the plan.
RATIONALE = os.path.join(HERE, os.pardir, "docs", "zipline-payload-format-rationale.md")

# What the specification said at v0.18, before a paragraph of it moved.
#
# Extraction moves the ARGUMENT and leaves the rule, so every one of these
# survives the work. A count that drops means a normative sentence went with its
# justification, which is this work's characteristic failure and the reason the
# baseline is a constant rather than something regenerated on demand. `MUST`
# includes the `MUST NOT`s; both are counted so that a MUST silently weakened to a
# MUST NOT (or the reverse) still moves a number.
#
# This dict is frozen: it is what v0.18 said, and it is never edited.
NORMATIVE_V018 = {"MUST": 143, "MUST NOT": 53, "SHOULD": 27, "MAY": 54}

# Normative statements deliberately removed from the specification, with the
# keywords each took and why.
#
# Phase 1 found the case the count invariant could not have anticipated, and it is
# the good kind: extraction SURFACES rules stated twice. A sentence that restates a
# rule whose home is elsewhere reads as ordinary prose until the section around it
# moves and the duplicate stands alone. Every entry here has that one shape -- a
# restatement replaced by a cross-reference to where the rule actually lives -- and
# an entry of any other shape is a normative change wearing extraction's clothes.
#
# The expected counts are DERIVED from this table rather than typed, so a count
# cannot be lowered without naming the sentence that went, and a named sentence
# still present in the specification fails the check. That is what keeps the
# baseline from being a knob to turn when the build goes red.
NORMATIVE_REMOVALS = (
    (
        r"a reader MUST NOT gate parsing on `version_minor`",
        {"MUST": 1, "MUST NOT": 1},
        "Design decisions not taken restated the File Header's version-gating rule "
        "while arguing against a re-stamp option; the section moved to the companion "
        "and the restatement became a cross-reference to the rule's home",
    ),
)

# Capabilities that are RULES rather than syntax, and the vector exercising each.
# Session fan-out shipped in 0.13 as a Clarified item with nothing exercising it,
# and nobody noticed until an implementation reviewed the release -- so a purely
# mechanical check over the registry would not have caught the very thing that
# motivated this one. A rule has no id to derive, so it is declared here.
#
# Add a rule when the specification gains one. Adding it with no vector fails,
# which is the point: the failure is what makes the gap impossible to forget.
RULES = {
    # F0's four: the two axes stated independent, and the three cells that
    # follow from it. Each is a permission, and a permission with no vector is
    # how #66 happened.
    "axes-independent": (
        "provenance and layer are independent; a capture-sourced stream may be decoded",
        "proxy-decoded",
    ),
    "undecoded-capture-sourced": (
        "a capture-sourced stream may declare what its reassembler did not carry",
        "undecoded-in-capture",
    ),
    "per-stream-transform": (
        "one file MAY create one stream and preserve another; the bar is per participant",
        "mixed-derivation",
    ),
    "no-intra-file-derivation": (
        "a file MUST NOT derive one of its own streams from another",
        "isolate-self-derived",
    ),
    # F1's three. The option id is covered mechanically by the registry parse;
    # the enum tables are not parsed, so the VALUES are covered only by these
    # entries naming vectors -- the statement-of-intent limit again.
    "decoder-declares-layer": (
        "a decoder declares the layer it emits; reassembly is a decoder",
        "sessionization-stage",
    ),
    "reassembler-may-declare": (
        "a head-of-pipeline reassembler MAY declare itself; the asymmetry is deliberate",
        "reassembler-declared",
    ),
    "unknown-output-layer-isolates": (
        "an unrecognised output_layer leaves offsets uncomputable; MUST NOT guess",
        "isolate-unknown-output-layer",
    ),
    "spans-correspondence": (
        "a decoder may transform; spans name what a unit corresponds to",
        "chain",
    ),
    "session-fan-out": (
        "a stage's output sessions need not mirror its input's",
        "session-fan-out",
    ),
    "coverage-at-least-once": (
        "two records MAY cite one input region; coverage is at least once",
        "session-fan-out",
    ),
    "discontinuity-known-width": (
        "a declared width is a term in the positional arithmetic",
        "discontinuity-known-width",
    ),
    "discontinuity-unknown-width": (
        "an absent width contributes 0; the join is still marked",
        "discontinuity-unknown-width",
    ),
    "extents-self-verifiable": (
        "input_extents makes the coverage guarantee checkable from one file",
        "isolate-extent-exceeds-coverage",
    ),
    "broken-provenance-walk": (
        "bytes unavailable is not the same as no bytes exist",
        "broken-chain",
    ),
    # The two halves of the block's duty, and they read as a pair: originate a
    # break where one first appears, then carry it down the chain. 0.13 shipped
    # only the second, which is what #78 found.
    "discontinuity-origination": (
        "a stage MUST declare a break in its OWN output, not only carry one forward",
        "isolate-unmarked-break",
    ),
    "discontinuity-no-splice": (
        "a stage MUST NOT emit a unit whose spans cross a declared break "
        "without declaring one of its own",
        "splice",
    ),
    "discontinuity-reordering": (
        "stored neighbours that were never adjacent do not join, so each seam is declared",
        "reordered-decoded",
    ),
    "discontinuity-passthrough-renumber": (
        "a pass-through renumbers a Discontinuity but copies Undecoded verbatim",
        "passthrough-discontinuity",
    ),
    # 0.16's four. Each is a MUST the syntax already allowed you to break, which
    # is why each needed a vector before it needed a checker.
    "layer-consistency": (
        "every record of one participant MUST resolve to the same layer",
        "isolate-mixed-layer-participant",
    ),
    "zpf-stream-created-or-preserved": (
        "a zpf-sourced participant MUST carry origin or hold records with spans, never neither",
        "isolate-unbound-zpf-stream",
    ),
    "undecoded-capture-bytes-only": (
        "against a capture source the hole class is unavailable -- "
        "the transport offsets already carry the gap",
        "isolate-hole-against-capture",
    ),
    # One MUST NOT, two labels, and a vector for each: 0.17 extended the bar to
    # `role` in one sentence and shipped a vector for one half (#118). The
    # strength is the part implementations guess wrong, and role is the likelier
    # mistake -- its vocabulary is open, so a plausible word always exists where
    # prim:bytes at least looked wrong on a slice.
    "content-type-transport-advisory": (
        "content_type at the transport layer is a MUST NOT whose violation is ADVISORY: "
        "a reader reports it, ignores the label, and accepts the file",
        "advisory-transport-content-type",
    ),
    "role-transport-advisory": (
        "role at the transport layer is the same MUST NOT with the same ADVISORY "
        "strength; a label asserting a unit where the reassembler left a slice",
        "advisory-transport-role",
    ),
    # 0.17's option. The id is covered mechanically by the registry parse; what
    # is not is the SCOPING, which is the whole of what makes role more than a
    # comment and is stated in prose no table sees.
    "role-decoder-scoped": (
        "a record MAY carry its type and its name at once; role names the record in a "
        "vocabulary scoped to its decoder's name, as a dec: token is, and asserts no tree",
        "decoded-field-roles",
    ),
    # 0.18's placement rule. The below-origin half has a vector that shows the
    # cost (bytes excluded from the space); the seq_start-less half is the
    # commoner shape and rides on a vector that has carried it since 0.12
    # without anyone saying where the record goes.
    "unplaceable-record-placement": (
        "an unplaceable record sits at a zero-width range at the highest off_end "
        "reached, contributing nothing -- below the origin, or with no seq_start",
        "advisory-below-origin-payload",
    ),
    # 0.18's one rule with a vector. The ordering MUST has never said whether
    # two records may share a seq_start; 0.17's handshake MUST makes the tie
    # mandatory in every file recording a handshake, and no vector carried one.
    "seq-start-order-non-descending": (
        "two records MAY share a seq_start and stored order decides which comes first; "
        "a reader comparing with < rejects every capture that records a handshake",
        "handshake-at-origin",
    ),
    # 0.17's second decidable case. The hole-class one has had a vector since
    # 0.15 (isolate-unmarked-break); this is the bytes-class half, which could
    # not be tested at all while one word did both jobs.
    "dropped-is-a-break": (
        "a bytes-class `dropped` region between two adjacent units requires a "
        "Discontinuity; `skipped` does not, and the word is the producer's statement",
        "isolate-unmarked-drop",
    ),
    # 0.17's floor. Like 0.16's four, a MUST the syntax already let you break --
    # and the second MUST NOT whose violation is advisory rather than isolating.
    "seq-start-origin-floor": (
        "a record's seq_start MUST NOT precede the stream origin; the violation is "
        "ADVISORY and the record is unplaceable, zero-width at the current position",
        "advisory-seq-start-below-origin",
    ),
    # Also NOT in this table, and for the same reason as #94 below: 0.18's rule
    # that a stage removing content MUST write `reason = dropped` rather than a
    # more specific word (#117). A file writing `filtered` for removed content and
    # one writing it for anything else are byte-identical, so no vector can
    # express it. Recorded here rather than omitted silently.
    #
    # NOT in this table, deliberately: "a stage emitting a transport layer MUST
    # NOT withhold content from a stream whose offsets are not sequence-anchored"
    # (#94). It is a writer obligation with no file-visible signature -- a stream
    # that withheld and one that did not are byte-identical, which is the whole
    # reason the rule is needed. No vector can express it, so listing it here
    # would fail the build forever for a rule that is correctly unverifiable.
    # Recorded here rather than omitted silently, so the gap is a decision.
}


# Claims the model has retired, and MUST NOT reappear in the specification.
#
# #70 added a release checklist step: grep every restatement of a rule before
# changing it. 0.15 changed the layer rule and shipped two paragraphs asserting
# the old one anyway, and the step did not catch either -- because neither
# paragraph RESTATES the rule. The layer rule is stated exactly once, so a check
# that counted its copies would have reported one site, correct, and passed
# clean. What the stale copies do is assert its negation, in words that share no
# phrase with it.
#
# So the mechanism is a ratchet, not a detector. It cannot find a stale claim
# nobody has noticed; what it guarantees is that a claim retired once can never
# quietly return -- which is the failure mode this repository keeps hitting
# (#63 in 0.14, #89 and #91 in 0.15).
#
# Add an entry whenever a release retires a claim, in the release that retires
# it. Patterns match against whitespace-collapsed text, so a copy that happens to
# wrap differently is still caught -- the 0.14 sweep nearly missed one for exactly
# that reason.
#
# 0.18 (#111) widened the scan from the specification to SCANNED, because 0.17
# retired two claims that were also asserted in the suite -- in a vector summary,
# which reaches manifest.json and therefore an implementation's harness, and in a
# README row. Both were found by grepping and fixed by hand; nothing would have
# stopped them coming back.
#
# Widening the scan alone would have caught neither, which Phase 0 measured before
# building this. The suite PARAPHRASES: where the specification said "it is the
# only MUST NOT in this document with that strength", build.py said "the only one
# in the format whose violation is ADVISORY" and the README said "the only one
# whose violation is advisory". A pattern written against the sentence being
# deleted -- which is how an entry is always written, since the entry exists
# because that sentence is going -- matches none of them.
#
# So an entry carries a TUPLE of spellings, and the author who greps the tree
# while retiring a claim records what they found. That adds no detection power
# and is not meant to: it is still a ratchet, and the paraphrase nobody noticed is
# still invisible. What it adds is that the spellings someone DID find cannot
# quietly return.
RETIRED_CLAIMS = {
    "transport-carries-no-undecoded": (
        (r"neither carries Undecoded blocks, because no decoder ran",),
        "0.16",
        89,
        "a transport-layer stream MAY carry Undecoded blocks; the input is the "
        "capture and the stage is the reassembler",
    ),
    "only-advisory-must-not": (
        (
            r"it is the only MUST NOT in this\s+document with that strength",
            # build.py, and so manifest.json
            r"the only one in the format whose violation is ADVISORY",
            # vectors/README.md
            r"the only one whose violation is advisory",
        ),
        "0.17",
        108,
        "the origin floor is a second advisory MUST NOT; the document gives that "
        "strength wherever it can say exactly what a reader does instead",
    ),
    "derived-file-is-not-a-mix": (
        # No suite spelling: mixed-derivation's summary quotes this claim
        # deliberately, as history ("Before 0.15 a derived file was ..."), and a
        # spelling loose enough to catch a stale copy would catch that too.
        (r"exactly one of a \*decode stage\* or a \*pass-through transform\*, never a\s+mix",),
        "0.17",
        103,
        "the discriminator binds per participant, not per file; one file MAY hold a "
        "created stream beside a preserved one (mixed-derivation)",
    ),
    "filter-writes-skipped": (
        # No suite spelling: filtered-decoded moved onto `dropped` in 0.17 and
        # its summary describes the move rather than asserting the old rule.
        (
            r"region it dropped is marked \[Undecoded\]\(#undecoded-0x21\)"
            r" with\s+`reason = skipped`",
        ),
        "0.18",
        119,
        "a filter writes reason = dropped; `skipped` is the deliberate decline "
        "that withholds no content, and the survivors join",
    ),
    "only-holes-are-decidable": (
        (
            r"One case is decidable from a single file",
            # build.py, and so manifest.json
            r"is the one shape of the duty that is decidable",
            # vectors/README.md
            r"is the one shape of the duty decidable",
        ),
        "0.17",
        98,
        "two cases are: a hole-class region between two adjacent units, and a "
        "bytes-class region carrying reason = dropped",
    ),
    # 0.19's clarification. The paragraph that DEFINED "decoder" carried the
    # pre-0.15 model in words no existing entry matched -- the same paraphrase
    # blindness 0.18's Phase 0 measured, on the highest-traffic paragraph in the
    # document. `byte-run-has-no-decoder-id` below was written to stop exactly
    # this idea returning and could not see it.
    "decoder-derives-decoded-from-transport": (
        (
            r"the \*\*decoder\*\*, which derives a decoded stream from a transport one",
            # the stale count in the same sentence: the document defines two KINDS
            # of transform, not two transforms, and named neither of the kinds
            r"This spec defines two:",
        ),
        "0.19",
        None,
        "a decoder is the identity a decoder_id resolves to; it may produce a "
        "transport stream, consume a decoded one, or consume no stream in a file "
        "at all -- and reassembly is a decoder",
    ),
    "byte-run-has-no-decoder-id": (
        (r"A byte run carries none",),
        "0.16",
        91,
        "a reassembly record is a byte run AND carries a decoder_id; the "
        "distinction is the layer, not the presence of the field",
    ),
}


# Sites that ENUMERATE the members of a set the model treats as one, and the
# members each must name.
#
# 0.17 added `role` beside `content_type` and stated the transport-layer bar once,
# for both. Four other sites enumerate that bar or the labels a stage carries
# forward, and none was updated: two in Conformance (#120), the pass-through
# carry-forward bullet and the annotator worked example (#121). Nothing was
# RETIRED there -- every sentence was true before `role` existed and merely
# incomplete after -- so RETIRED_CLAIMS is structurally blind to it, and a
# release adding a third label would stale them all again.
#
# Phase 0 measured the obvious detector first and it does not work. "A unit naming
# one member of a set must name them all" reports 19 units across the two sets,
# of which 6 are real; filtered to units carrying MUST/SHOULD/MAY it reports 8 and
# catches only 3 of the 6, missing the join table and the filter instruction --
# the two sharpest. A check whose output is two thirds allowlist teaches nothing,
# and one that misses the defects that motivated it is worse.
#
# So the sites are DECLARED, the way RULES declares a rule with no id to derive:
# a locator phrase identifying the paragraph or table row, and the members it owes.
# Zero false positives by construction, and adding a member to a set fails the
# build at every site until each is updated -- which is the whole point, and is
# what nobody did in 0.17.
#
# Choose a locator the FIX will not touch. "Two further requirements" is not one:
# correcting the site changes the count. A phrase that survives the edit is.
#
# NOT here, deliberately: the `skipped`/`dropped` split (#119, #122). Those sites
# do not owe every member -- a filter's instruction owes `dropped` ALONE, and the
# join table's rows owe one word each. That is a wrong member, not a missing one,
# so it is RETIRED_CLAIMS' shape and it is entered there instead.
ENUMERATIONS = {
    # 0.19. A transform creates a layer or preserves one, and those two kinds are
    # the whole set. The sentence this replaces said "this spec defines two" and
    # then named the decoder and the merge -- one kind and one instance, counted
    # together. A third kind of transform must fail the build at every site that
    # enumerates them, which is what nobody had when the count went stale.
    "transform kinds": (
        ("decode stage", "pass-through"),
        (
            # Terminology -- where the pair is introduced
            "always file to file, never a layer inside a record",
            # Conformance -- where the pair is stated
            "the difference is whether",
        ),
    ),
    "transport-layer labels": (
        ("content_type", "role"),
        (
            # Conformance -- what binds on the layer (#120). Anchored on the
            # OTHER requirement in the paragraph: 0.18's own fix rewrote the
            # sentence this was first anchored on, and the check caught it, which
            # is the second-order lesson -- a locator inside the clause being
            # corrected is not a locator.
            "having no way to express the break",
            # Conformance -- the sessionization-stage bullet (#120)
            "since a hole is expressible without one",
            # Conformance -- what a pass-through preserving a decoded layer owes (#121)
            "re-emit every Undecoded block",
            # Annotating a decoded file -- the worked example an annotator is
            # written from (#121)
            "provenance is the participants' `origin`",
            # The two that were already right when 0.18 opened, so the check is
            # exercised in both directions from the start.
            "including one emitted by a reassembly decoder",
            "whether or not it has a decoder",
        ),
    ),
}


def spec_units() -> list[str]:
    """Split the specification into paragraphs, plus each table row on its own.

    A row is a unit because an enumeration can be one: the join table states the
    origination duty a row at a time.
    """
    text = read_text(SPEC)
    units = re.split(r"\n\s*\n", text)
    units += [line for line in text.splitlines() if line.startswith("|")]
    return [re.sub(r"\s+", " ", u) for u in units]


def check_enumerations() -> list[str]:
    """Every declared enumeration site names every member of its set."""
    units = spec_units()
    out = []
    for label, (members, locators) in sorted(ENUMERATIONS.items()):
        for locator in locators:
            found = [u for u in units if locator in u]
            if len(found) != 1:
                out.append(
                    f"enumeration '{label}': locator {locator!r} matches "
                    f"{len(found)} units, not 1 -- the site moved or the phrase "
                    f"was not stable; re-anchor it on text the fix does not touch"
                )
                continue
            # A member counts only where it is MARKED -- `code` for an option or
            # field name, **bold** for a defined prose term. Both are deliberate
            # markup, so an incidental mention still does not count, which is the
            # property that keeps this check free of false positives. 0.19 added
            # the bold form when the first set of prose terms (the two kinds of
            # transform) was declared; before that every member was an identifier.
            missing = [
                m for m in members if f"`{m}`" not in found[0] and f"**{m}**" not in found[0]
            ]
            if missing:
                out.append(
                    f"enumeration '{label}': the site at {locator!r} names "
                    f"{', '.join(m for m in members if m not in missing)} but not "
                    f"{', '.join(missing)} -- an enumeration of this set owes every member"
                )
    if not out:
        sites = sum(len(v[1]) for v in ENUMERATIONS.values())
        print(f"  enumerations: {len(ENUMERATIONS)} sets, {sites} sites -- all complete")
    return out


# Keys the projection defines structurally. Neither the option registry nor a
# block's body table can supply them, because they name no binary field and no
# option: the block discriminator, the two escapes that carry unrecognised data
# (see "Unrecognised data: the four escapes"), and the one member of a structured
# option's entries that is not itself a field or option name.
#
# Declared, for the reason RULES is declared: derived from nothing, so a check
# over the tables alone would report them as unknown keys. Everything else must
# come from the specification.
PROJECTION_KEYS = {
    "type": "the block discriminator",
    "options": "the unrecognised-option escape, an array of {id, value}",
    "id": "an entry in that array",
    "value": "an entry in that array",
    "content": "the unrecognised-block escape, the whole content as base64",
    "extent": "a member of an `input_extents` entry",
}

# Fields the mapping says have no JSON key at all: framing and on-disk-only.
# `type`, `reserved` and `length` are frame fields and appear in no body table;
# the version pair projects only through the `format` alias, so writing either
# half as a key is the same defect as writing a binary name that has an alias.
NOT_PROJECTED = {
    "magic",
    "end_magic",
    "payload_len",
    "_reserved",
    "version_major",
    "version_minor",
}


def spec_body_fields() -> set[str]:
    """Return every block body field the specification names.

    One table per block, found by its header row, in the same way spec_tables()
    finds the registry -- a looser match picks up the value tables that follow
    several of them.
    """
    fields: set[str] = set()
    in_table = False
    for line in read_text(SPEC).splitlines():
        if line.startswith("| Field"):
            in_table = True
            continue
        if in_table:
            m = re.match(r"^\| `([^`]+)`", line)
            if m:
                fields.add(m.group(1))
            elif not line.startswith("|"):
                in_table = False
    return fields


def spec_aliases() -> tuple[set[str], dict[str, str]]:
    """Return the brevity aliases: the JSON keys, and the binary names they replace.

    A row is a *rename* only where its right column is a bare binary name (with
    an optional parenthetical saying where it applies). The other rows describe a
    *rendering* -- the version pair as one `format` string, a flags bit as a
    boolean -- and rename nothing, so `flags` stays a legal key. Reading every
    row as a rename would forbid it.
    """
    keys: set[str] = set()
    renamed: dict[str, str] = {}
    in_table = False
    for line in read_text(SPEC).splitlines():
        if line.startswith("| JSONL key"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            m = re.match(r"^`([^`]+)`$", cells[0])
            if not m:
                continue  # the ---- separator row
            keys.add(m.group(1))
            rename = re.match(r"^`(\w+)`(?:\s*\([^)]*\))?$", cells[1])
            if rename:
                renamed[rename.group(1)] = m.group(1)
    return keys, renamed


def jsonl_keys(path: str) -> Iterator[tuple[int, str]]:
    """Yield (line number, key) for every key in one projection, nested included."""

    def walk_value(value: object) -> Iterator[str]:
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from walk_value(v)
        elif isinstance(value, list):
            for v in value:
                yield from walk_value(v)

    for i, line in enumerate(read_text(path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # check_jsonl reports it; one defect, one message
        for key in walk_value(obj):
            yield i, key


def check_jsonl_keys() -> list[str]:
    """Every JSONL key must be one the mapping defines, spelled the way it says.

    The mapping is one rule plus a short list of exceptions: a key is a body
    field's or a registered option's canonical name, except where the alias table
    gives it a shorter one -- and then the alias is the spelling, not a second
    one. `flow_key` shipped in two fixtures against a table saying `key` (#104),
    which no check could see, because both spellings name something real.

    A key outside all of that is an "unknown key on a known block", which the
    projection deliberately gives no escape: a converter must reject or drop it.
    A fixture is the wrong place to find out.

    Mechanical, and ground rule 2 holds: it compares the tree's key names against
    the specification's own tables. Nothing here parses a block body or rules on
    what a value means.
    """
    opts, _blocks = spec_tables()
    alias_keys, renamed = spec_aliases()
    body = spec_body_fields()
    if not opts or not body or not alias_keys:
        return ["jsonl keys: could not parse the specification's tables"]

    allowed = (body | set(opts.values()) | alias_keys | set(PROJECTION_KEYS)) - NOT_PROJECTED
    allowed -= set(renamed)

    out, seen, files = [], set(), 0
    for root, _dirs, names in sorted(os.walk(HERE)):
        for fn in sorted(names):
            if not fn.endswith(".jsonl"):
                continue
            files += 1
            label = os.path.relpath(os.path.join(root, fn), HERE)
            for i, key in jsonl_keys(os.path.join(root, fn)):
                seen.add(key)
                if key in allowed:
                    continue
                if key in renamed:
                    out.append(
                        f"{label}:{i}: key '{key}' is the binary name of a listed "
                        f"brevity alias -- the projection spells it '{renamed[key]}'"
                    )
                elif key in NOT_PROJECTED:
                    out.append(
                        f"{label}:{i}: key '{key}' is framing or on-disk-only and has no JSON key"
                    )
                else:
                    out.append(
                        f"{label}:{i}: key '{key}' is neither a body field, a "
                        f"registry option name, nor a listed alias"
                    )
    if not out:
        print(
            f"  jsonl keys: {len(seen)} distinct across {files} files -- "
            f"every one a body field, an option or an alias"
        )
    return out


# Where a retired claim is looked for. The specification states the rules; the
# suite illustrates them, and a summary here reaches manifest.json and so an
# implementation's harness.
#
# CHANGELOG.md and the release plans are excluded BY CONSTRUCTION rather than by
# an exception, because a retired claim belongs in both: the changelog records
# what a release fixed, by quoting it, and a plan records what it decided. Two
# entries match the changelog today, correctly. Scanning them would mean an
# allowlist whose every line says "this one is history", which is the whole file.
#
# manifest.json is scanned as well as build.py, and not redundantly: build.py
# breaks a long summary across source lines, so a spelling spanning the break sits
# either side of a quote pair and does not match there. manifest.json holds the
# assembled string. One of the five copies reproduced from v0.16 is visible only
# in the generated file, which is also the file an implementation's harness reads.
SCANNED = (
    SPEC,
    RATIONALE,
    os.path.join(HERE, "build.py"),
    os.path.join(HERE, "manifest.json"),
    os.path.join(HERE, "README.md"),
)


def check_retired_claims() -> list[str]:
    """No claim the model has retired may appear in the specification or the suite.

    Whitespace is collapsed before matching so a line-wrapped copy is still
    found; the 0.14 sweep nearly missed a third statement of the coverage
    guarantee because the phrase spanned a line break.

    Each spelling is reported against the file it is found in, because the fix
    differs: in the specification a stale claim is a rule to rewrite, and in the
    suite it is a summary describing a vector in the words of a model that has
    moved on.
    """
    out = []
    scanned = [p for p in SCANNED if os.path.exists(p)]
    for path in scanned:
        flat = re.sub(r"\s+", " ", read_text(path))
        label = os.path.relpath(path, os.path.dirname(HERE))
        for name, (spellings, retired_in, issue, instead) in sorted(RETIRED_CLAIMS.items()):
            for pattern in spellings:
                if re.search(pattern, flat):
                    out.append(
                        f"{label}: retired claim '{name}' is still asserted "
                        f"(retired in {retired_in}, #{issue}) -- {instead}"
                    )
                    break
    if not out:
        spellings = sum(len(v[0]) for v in RETIRED_CLAIMS.values())
        print(
            f"  retired claims: {len(RETIRED_CLAIMS)} claims, {spellings} spellings, "
            f"{len(scanned)} files -- none present"
        )
    return out


# Normative keywords the companion is allowed to carry, as (pattern, why) pairs.
#
# Empty, and it should stay that way for as long as it can. The rationale document
# explains rules; it does not state them. Where history genuinely needs to recount
# a rule that once bound -- "the older rule REQUIRED a reassembler to ..." -- the
# first move is to rephrase it in the past tense without the keyword, because a
# normative word in a non-normative document is what a hurried reader quotes.
RATIONALE_QUOTES: tuple[tuple[str, str], ...] = ()


def _headings(text: str) -> list[str]:
    """Return a markdown document's ATX headings, skipping fenced code.

    The specification's byte-level worked example carries
    `# -- File Header (0x01) --` comment lines inside a fence. They are not
    headings, nothing links to their slugs, and counting them would let a real
    anchor resolve against a comment.
    """
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        m = re.match(r"^#{1,6} +(.+?)\s*$", line)
        if not fenced and m:
            out.append(m.group(1))
    return out


def _slug(heading: str) -> str:
    """Slugify a heading the way GitHub anchors it.

    Lowercase, drop everything that is not a word character, a space or a hyphen,
    then hyphenate the spaces **one for one**. An `&` leaves a gap that becomes a
    double hyphen, which is why *TLV option framing & id registry* anchors as
    `tlv-option-framing--id-registry`. Collapsing runs of whitespace instead
    mis-resolves three of the specification's own links -- found by writing this
    the wrong way first.
    """
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.lower())).strip("-")


def check_anchor_links() -> list[str]:
    """Every in-document link must resolve to a heading that exists.

    The specification carries 214 anchor links across 37 targets, and moving a
    section to the companion breaks them in both directions: a link into text that
    left, and a link out of text that arrived. Hand-checking 214 links is not a
    plan, and a dead anchor is silent in a rendered page -- it scrolls nowhere and
    reports nothing.

    A bare `](#x)` resolves against **its own file**. A paragraph that moves to the
    companion carrying `](#coverage-honesty-undecoded-blocks)` is precisely the
    defect this catches: valid before the move, dead after it, and unchanged.

    Phase 3 widened it past the two documents. The suite's README, the changelog
    and every plan link into the specification by heading, and a section that moves
    breaks those exactly as it breaks an internal one -- with the same silence, and
    further from the person who moved it. So every tracked `.md` is read for links
    INTO the pair, while only the pair is read for links out.

    `#L120-L130` line anchors are skipped, and deliberately. The one file carrying
    them says of itself that it is a historical record pinned to `v1.0`, its links
    went stale several releases before this work, and repairing them would falsify
    the record. The lesson is the reason this check resolves headings only: a
    line-anchored link into the specification does not survive it being edited.
    """
    docs = {os.path.basename(p): read_text(p) for p in (SPEC, RATIONALE) if os.path.exists(p)}
    slugs = {name: {_slug(h) for h in _headings(text)} for name, text in docs.items()}

    root = os.path.dirname(HERE)
    others = []
    for base, _dirs, names in os.walk(root):
        if ".git" in base:
            continue
        for n in names:
            p = os.path.join(base, n)
            if n.endswith((".md", ".py", ".json")) and os.path.basename(p) not in docs:
                others.append(p)

    bad, seen = [], set()
    sources = [(n, t, n) for n, t in sorted(docs.items())]
    sources += [(os.path.relpath(p, root), read_text(p), None) for p in sorted(others)]

    for label, text, own in sources:
        for target, anchor in re.findall(r"\]?\(?([\w.-]*\.md)?#([A-Za-z0-9_-]+)\)", text):
            where = os.path.basename(target) if target else own
            if (
                where not in slugs
                or (where, anchor) in seen
                or re.fullmatch(r"L\d+(-L\d+)?", anchor)
            ):
                continue
            seen.add((where, anchor))
            if anchor not in slugs[where]:
                bad.append(f"{label}: anchor '#{anchor}' does not resolve in {where}")

    if not bad:
        print(
            f"  anchor links: {len(seen)} distinct targets, {len(docs)} documents "
            f"+ {len(others)} files linking in -- all resolve"
        )
    return bad


def check_normative_split() -> list[str]:
    """Keep every rule in the specification, and let only the argument move.

    Three parts. The specification's normative keyword counts must match `v0.18`
    less whatever `NORMATIVE_REMOVALS` accounts for, so a MUST cannot leave with
    the paragraph that explains it. Every removal it names must genuinely be gone,
    so the table cannot be padded to absorb a loss it does not describe. And the
    companion must carry **no** normative keyword at all: a reader who finds a MUST
    in the rationale document has found one the specification lost.

    Counts rather than a regenerated list of sentences, on purpose. A list you
    regenerate when it goes red is a record of what happened, not a check on it.
    """
    out = []
    spec = read_text(SPEC)

    for pattern, _kws, why in NORMATIVE_REMOVALS:
        if re.search(pattern, re.sub(r"\s+", " ", spec)):
            out.append(
                f"removal '{pattern[:48]}...' names a sentence still in the specification "
                f"-- the table accounts for a loss that did not happen ({why[:60]}...)"
            )

    for kw, base in sorted(NORMATIVE_V018.items()):
        want = base - sum(k.get(kw, 0) for _p, k, _w in NORMATIVE_REMOVALS)
        got = len(re.findall(r"\b" + kw.replace(" ", r"\s+") + r"\b", spec))
        if got != want:
            verb = "lost" if got < want else "gained"
            out.append(
                f"specification {verb} a normative keyword: {kw} is {got}, expected {want} "
                f"(v0.18 had {base}) -- extraction moves the argument and leaves the rule"
            )

    if os.path.exists(RATIONALE):
        allowed = [p for p, _ in RATIONALE_QUOTES]
        for n, line in enumerate(read_text(RATIONALE).split("\n"), 1):
            kws = {
                k for k in NORMATIVE_V018 if re.search(r"\b" + k.replace(" ", r"\s+") + r"\b", line)
            }
            if kws and not any(re.search(p, line) for p in allowed):
                out.append(
                    f"rationale:{n}: carries {'/'.join(sorted(kws))} -- the companion explains "
                    f"rules, it does not state them"
                )

    if not out:
        counts = ", ".join(
            f"{k} {v - sum(x.get(k, 0) for _p, x, _w in NORMATIVE_REMOVALS)}"
            for k, v in sorted(NORMATIVE_V018.items())
        )
        home = "companion clean" if os.path.exists(RATIONALE) else "no companion yet"
        print(
            f"  normative split: {counts} -- v0.18 less "
            f"{len(NORMATIVE_REMOVALS)} accounted removal(s), {home}"
        )
    return out


def spec_tables() -> tuple[dict[str, str], dict[str, str]]:
    """Return every option id and block type the specification defines.

    Parsed from the two tables by their header rows, not by row shape: the flags
    enum table has rows of the same shape (an id, then a name in backticks) and a
    looser match silently swallows them.
    """
    opts, blocks = {}, {}
    table, header = None, None
    with open(SPEC, encoding="utf-8") as fh:
        spec_lines = fh.readlines()
    for line in spec_lines:
        if line.startswith("| Type | Name"):
            table, header = blocks, True
            continue
        if line.startswith("| Id       | Name"):
            table, header = opts, True
            continue
        if table is not None:
            m = re.match(r"^\| `?(0x[0-9A-F]{2,4})`? +\| ([^ |]+)", line)
            if m:
                table[m.group(1)] = m.group(2).strip("`")
                header = False
            elif not line.startswith("|"):
                table, header = None, None
            elif header and set(line.strip()) <= set("|- "):
                continue  # the ---- separator row
    return opts, blocks


class Corrupt(Exception):
    """A structural defect: the file cannot be walked as blocks."""


def check_file_header(raw: bytes, off: int, btype: int) -> None:
    """Check the first block is a File Header this version can read.

    One raise per rule, because each is a distinct entry in the reject tier.
    """
    if btype != 0x01:
        raise Corrupt("first block is not a File Header")
    magic, major, minor = struct.unpack_from("<IHH", raw, off + 8)
    if magic != MAGIC:
        raise Corrupt(f"bad magic 0x{magic:08X}")
    if major != MAJOR:
        raise Corrupt(f"version_major {major} not implemented")
    if major == 0 and minor != MINOR:
        raise Corrupt(f"version_minor {minor} not implemented (0.x)")


def walk(raw: bytes) -> Iterator[tuple[int, int, int]]:
    """Yield (offset, type, length) per block.

    Raises Corrupt on a structural defect, mirroring the reject tier in
    Conformance.
    """
    if len(raw) < 8:
        raise Corrupt("shorter than one frame")
    off = 0
    first = True
    while off < len(raw):
        if off + 8 > len(raw):
            raise Corrupt(f"truncated frame at 0x{off:04X}")
        btype, _res, length = struct.unpack_from("<HHI", raw, off)
        if length % 4:
            raise Corrupt(f"length {length} at 0x{off:04X} is not a multiple of 4")
        end = off + 8 + length
        if end > len(raw):
            raise Corrupt(f"block at 0x{off:04X} runs past end of file")
        if first:
            check_file_header(raw, off, btype)
            first = False
        if btype == 0x20:  # Record -- check payload_len fits its own block
            plen = struct.unpack_from("<I", raw, off + 8 + 24)[0]
            if 28 + plen > length:
                raise Corrupt(f"payload_len {plen} overruns block at 0x{off:04X}")
        yield off, btype, length
        off = end
    if off != len(raw):
        raise Corrupt("trailing bytes")


def chain_lines(d: str, n: str) -> list[dict]:
    """Read one chain file's JSONL projection."""
    text = read_text(os.path.join(d, f"{n}.jsonl"))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def check_chain_digests(d: str) -> list[str]:
    """Check every declared digest is the real SHA-256 of the file it names."""
    import hashlib

    real = {
        f"{n}.zpf": "sha256:" + hashlib.sha256(read_bytes(os.path.join(d, f"{n}.zpf"))).hexdigest()
        for n in ("raw", "decoded", "annotated")
    }
    out = []
    for n in ("decoded", "annotated"):
        for o in chain_lines(d, n):
            if o.get("type") == "source" and "digest" in o:
                want = real.get(o["uri"])
                if want is None:
                    out.append(f"chain/{n}: cites unknown file {o['uri']}")
                elif o["digest"] != want:
                    out.append(f"chain/{n}: digest for {o['uri']} is stale")
    return out


def chain_raw_extents(d: str) -> dict[int, int]:
    """Reconstruct raw.zpf's per-stream extents from seq_start - (isn + 1)."""
    import base64

    isn, ext = {}, {}
    for o in chain_lines(d, "raw"):
        if o.get("type") == "participant":
            isn[o["pid"]] = o["isn"]
        elif o.get("type") == "record":
            off = o["seq_start"] - (isn[o["sender_pid"]] + 1)
            end = off + len(base64.b64decode(o["payload"]))
            ext[o["sender_pid"]] = max(ext.get(o["sender_pid"], 0), end)
    return ext


def merge_ranges(rs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Coalesce sorted, possibly-touching ranges."""
    merged: list[tuple[int, int]] = []
    for a, b in sorted(rs):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def check_chain_coverage(d: str, ext: dict[int, int]) -> list[str]:
    """Confirm decoded.zpf accounts for every byte raw.zpf holds."""
    cov: dict[int, list[tuple[int, int]]] = {}
    for o in chain_lines(d, "decoded"):
        for s in o.get("spans", []):
            cov.setdefault(s["pid"], []).append((s["off_start"], s["off_end"]))
        if o.get("type") == "undecoded":
            cov.setdefault(o["pid"], []).append((o["off_start"], o["off_end"]))

    out = []
    for pid, want_end in sorted(ext.items()):
        merged = merge_ranges(cov.get(pid, []))
        if merged != [(0, want_end)]:
            out.append(f"chain: pid {pid} covered {merged}, raw stream is [0,{want_end})")
    return out


def check_chain() -> list[str]:
    """Verify the chain against itself.

    Its numbers must agree, or the fixture is worthless.
    """
    d = os.path.join(HERE, "chain")
    if not os.path.isdir(d):
        return ["chain/ missing"]
    ext = chain_raw_extents(d)
    out = check_chain_digests(d) + check_chain_coverage(d, ext)
    if not out:
        print(
            f"  chain: 3 files, digests match, coverage complete "
            f"({', '.join(f'pid {p} [0,{e})' for p, e in sorted(ext.items()))})"
        )
    return out


def tunnel_lines(d: str, n: str) -> list[dict]:
    """Read one tunnel file's JSONL projection."""
    text = read_text(os.path.join(d, f"{n}.jsonl"))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def tunnel_digests(d: str) -> list[str]:
    """Check each hop cites the real SHA-256 of the file before it."""
    import hashlib

    real = {
        f"{n}.zpf": "sha256:" + hashlib.sha256(read_bytes(os.path.join(d, f"{n}.zpf"))).hexdigest()
        for n in ("outer", "packets", "inner", "http")
    }
    out = []
    for n in ("packets", "inner", "http"):
        for o in tunnel_lines(d, n):
            if o.get("type") == "source" and "digest" in o:
                want = real.get(o["uri"])
                if want is None:
                    out.append(f"tunnel/{n}: cites unknown file {o['uri']}")
                elif o["digest"] != want:
                    out.append(f"tunnel/{n}: digest for {o['uri']} is stale")
    return out


def tunnel_covers(d: str, stage: str, sess: int, pid: int, want_end: int) -> list[str]:
    """Confirm one hop accounts for every offset of the input stream it reads.

    Accumulated across the WHOLE file rather than per output session: under
    fan-out one input stream feeds several output sessions and no single one
    covers it, which is the property inner.zpf exists to show.
    """
    cov: list[tuple[int, int]] = []
    for o in tunnel_lines(d, stage):
        for s in o.get("spans", []):
            if (s["session_id"], s["pid"]) == (sess, pid):
                cov.append((s["off_start"], s["off_end"]))
        if o.get("type") == "undecoded" and (o["session_id"], o["pid"]) == (sess, pid):
            cov.append((o["off_start"], o["off_end"]))
    merged = merge_ranges(cov)
    if merged != [(0, want_end)]:
        return [f"tunnel/{stage}: covers {merged} of session {sess} pid {pid}, want [0,{want_end})"]
    return []


def tunnel_inner_extent(d: str, sess: int, pid: int) -> int:
    """Reconstruct one inner stream's extent from seq_start - (isn + 1).

    The same arithmetic chain_raw_extents() does, one level further down: it is
    what proves inner.zpf's hole is really in the sequence numbers rather than
    merely asserted in a comment.
    """
    import base64

    isn, end = None, 0
    for o in tunnel_lines(d, "inner"):
        if o.get("type") == "participant" and (o["session_id"], o["pid"]) == (sess, pid):
            isn = o["isn"]
        elif o.get("type") == "record" and (o["session_id"], o["sender_pid"]) == (sess, pid):
            off = o["seq_start"] - (isn + 1)
            end = max(end, off + len(base64.b64decode(o["payload"])))
    return end


def check_tunnel() -> list[str]:
    """Verify the four-file tunnel walks: digests, coverage, and the inner hole.

    Specific to this fixture, as check_chain() is. A generic per-hop walker
    would be most of a conformant reader, which the module docstring rules out.
    """
    d = os.path.join(HERE, "tunnel")
    if not os.path.isdir(d):
        return ["tunnel/ missing"]

    out = tunnel_digests(d)
    # outer -> packets: the whole capture stream, framing included.
    out += tunnel_covers(d, "packets", 1, 0, 320)
    # packets -> inner: the union across BOTH output sessions, not either alone.
    out += tunnel_covers(d, "inner", 5, 0, 150)
    # inner -> http: flow A only; session 11 is not an input to that hop.
    out += tunnel_covers(d, "http", 10, 0, 110)

    # The inner stream's own extent, re-derived from the sequence numbers, must
    # agree with what the next hop declares it to be.
    derived = tunnel_inner_extent(d, 10, 0)
    declared = [
        e["extent"]
        for o in tunnel_lines(d, "http")
        if o.get("type") == "session_end"
        for e in o.get("input_extents", [])
        if (e["session_id"], e["pid"]) == (10, 0)
    ]
    if declared != [derived]:
        out.append(
            f"tunnel: inner flow A is [0,{derived}) by seq_start - (isn + 1), "
            f"but http declares {declared}"
        )

    if not out:
        print(
            f"  tunnel: 4 files, digests match, coverage complete "
            f"(outer [0,320) -> packets [0,150) fan-out -> inner flow A [0,{derived}))"
        )
    return out


def check_capability_coverage(manifest: dict) -> list[str]:
    """Every capability the format defines must be exercised by some vector.

    Fan-out shipped in 0.13 with nothing exercising it, and the gap survived a
    release. This is the check that would have caught it -- and it hard-fails
    rather than warning, because an advisory line is exactly what gets scrolled
    past. A capability with no vector should stop the build until either a vector
    exists or the capability does not.

    Syntax comes from the specification, so a new option or block cannot ship
    uncovered. Rules are declared in RULES, since a permission has no id to
    derive. Neither half inspects a file: what a vector exercises is recorded by
    build.py, which built the bytes.
    """
    opts, blocks = spec_tables()
    if not opts or not blocks:
        return ["capability coverage: could not parse the specification's tables"]

    used_o, used_b = set(), set()
    for v in manifest["vectors"]:
        used_o.update(v.get("options", ()))
        used_b.update(v.get("blocks", ()))

    out = []
    for oid, name in sorted(opts.items()):
        if oid not in used_o:
            out.append(f"option {oid} ({name}) is in the registry but no vector exercises it")
    for btype, name in sorted(blocks.items()):
        if btype not in used_b:
            out.append(f"block {btype} ({name}) is defined but no vector exercises it")
    for rule, (what, vector) in sorted(RULES.items()):
        if vector is None:
            out.append(f"rule '{rule}' has no vector -- {what}")
        elif not any(x["name"] == vector for x in manifest["vectors"]):
            out.append(f"rule '{rule}' names vector '{vector}', which does not exist")

    if not out:
        print(
            f"  capabilities: {len(opts)} options, {len(blocks)} blocks, "
            f"{len(RULES)} rules -- all exercised"
        )
    return out


def check_violations(v: dict) -> list[str]:
    """Check one vector's declared violation count against its declared tier.

    Applies to the chain fixture too, so a fixture cannot dodge it by being
    shaped differently.
    """
    name, tier = v["name"], v["tier"]
    if "violations" not in v:
        return [f"{name}: no declared violation count"]
    advisory = bool(v.get("advisory"))
    if advisory and tier != "accept":
        return [
            f"{name}: declares advisory on tier '{tier}'. An advisory "
            f"violation is one a reader reports and then accepts; on a tier "
            f"where the reader may discard something it says nothing."
        ]
    expected = ADVISORY_VIOLATIONS if advisory else VIOLATIONS_BY_TIER[tier]
    if v["violations"] != expected:
        return [
            f"{name}: declares {v['violations']} violation(s) but tier "
            f"'{tier}'{' (advisory)' if advisory else ''} requires exactly "
            f"{expected}. A "
            f"negative vector carries exactly one violation -- with two it "
            f"tests whichever a reader detects first. Split it, or fix the "
            f"vector so it carries only the one it was built for."
        ]
    return []


def check_jsonl(label: str, path: str, block_count: int) -> list[str]:
    """Check a projection parses and has one line per block."""
    jl = [x for x in read_text(path).splitlines() if x.strip()]
    out = []
    for i, line in enumerate(jl, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            out.append(f"{label}:{i}: invalid JSON -- {e}")
    if len(jl) != block_count:
        out.append(f"{label}: {block_count} blocks but {len(jl)} JSONL lines")
    return out


def fixture_files(v: dict) -> list[tuple[str, str]]:
    """Yield (label, .zpf path) for every file in a fixture.

    A single-file vector lives at <name>/<name>.zpf; a multi-file fixture lists
    its members in the manifest. Both are walked identically -- before 0.14
    anything with a `files` key was skipped entirely, so a second multi-file
    fixture would have been checked by nothing at all.
    """
    name = v["name"]
    if "files" not in v:
        return [(name, os.path.join(HERE, name, f"{name}.zpf"))]
    return [
        (f"{name}/{fn}", os.path.join(HERE, name, fn)) for fn in v["files"] if fn.endswith(".zpf")
    ]


def check_one_file(label: str, path: str, tier: str, has_jsonl: bool) -> list[str]:
    """Walk one .zpf and check it behaves as its tier says."""
    out = []
    try:
        blocks = list(walk(read_bytes(path)))
        corrupt = None
    except Corrupt as e:
        blocks, corrupt = None, str(e)

    if tier == "reject":
        if corrupt is None:
            out.append(f"{label}: claims the reject tier but walks cleanly")
        else:
            print(f"  {label}: correctly rejected -- {corrupt}")
        return out

    if corrupt is not None:
        out.append(f"{label}: must be well-framed but {corrupt}")
        return out
    if has_jsonl:
        out += check_jsonl(label, path[: -len(".zpf")] + ".jsonl", len(blocks))
    print(f"  {label}: {len(blocks)} blocks, well-framed")
    return out


def check_vector(v: dict) -> list[str]:
    """Check a fixture's bytes against the tier and size the manifest declares.

    Handles single-file vectors and multi-file fixtures alike; `bytes` is the
    total across the fixture, so it is checked once rather than per file.
    """
    name, tier = v["name"], v["tier"]
    files = fixture_files(v)
    out = []

    total = sum(len(read_bytes(p)) for _, p in files)
    if total != v["bytes"]:
        out.append(f"{name}: manifest says {v['bytes']} bytes, files total {total}")

    for label, path in files:
        out += check_one_file(label, path, tier, v["has_jsonl"])
    return out


def main() -> int:
    """Verify the vector tree, and return a process exit status."""
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "build.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode:
        print("FAIL: committed vectors do not match build.py")
        return 1

    manifest = json.loads(read_text(os.path.join(HERE, "manifest.json")))
    failures = []
    for v in manifest["vectors"]:
        failures += check_violations(v)
        failures += check_vector(v)

    failures += check_chain()
    failures += check_tunnel()
    failures += check_capability_coverage(manifest)
    failures += check_jsonl_keys()
    failures += check_retired_claims()
    failures += check_enumerations()
    failures += check_normative_split()
    failures += check_anchor_links()

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(manifest['vectors'])} vectors consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
