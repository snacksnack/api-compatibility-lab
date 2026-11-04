"""The integration inventory: what the customer's workflows actually read.

Phase 3's findings already carry a `workflow` and a `step`, because the corpus
was captured workflow-shaped. So grouping findings by workflow is a `groupby`,
and a `groupby` is not an impact report. What the findings cannot say is the
thing that decides whether a difference matters: **which of these fields does
the client read, and what does it do with the value.**

That is not inferable from traffic. The `{{step.field}}` references in the
corpus prove a handful of reads — every one of them an `id` — and nothing
about what happens to a value after the response is parsed. So it is declared,
in `workflows/*.json`, and on a real engagement it is declared *by the
customer*: this is the artifact an FDE fills in during discovery, and it is
the reason the output is a customer deliverable rather than a diff.

Three properties keep a declaration from being a hand-written answer key:

1. **It contains no verdicts.** A read declares a locus, what the client does
   with the value, and a note. Severity, consequence, and blast radius are
   derived in `compatlab.impact` from the declaration joined to the findings.
   Nothing in this file names a break.
2. **It is validated against the captured traffic, not trusted.** Every
   declared step must exist in the corpus, in captured order, and every
   declared locus must actually be present in that step's version-A response.
   An integration note that has gone stale fails the build instead of
   producing a confident claim about a field nobody returns.
3. **A declaration is allowed to be wrong about where the risk is.** The join
   reports workflows that come out clear and reads that nothing touched, and
   the report prints both counts. A model that only ever confirms its author's
   expectations would show up there as every read touched.

What a read's `use` means, since the whole consequence table keys off it:

- `request_input` — the value is sent in a later call. Lose it and the
  sequence cannot continue.
- `decision` — the client branches or computes on it: a loop bound, a
  conditional, a comparison, an exhaustive switch.
- `record` — the client stores it: a ledger row, a warehouse column, its own
  database. A change here is wrong data at rest.
- `display` — shown to a person and nothing more.

This is also what resolves the `risky` severity. Phase 3 calls a difference
`risky` when it depends on how the client was written — and a declared read is
exactly that missing fact. 44 of the 93 findings are risky; the inventory is
what turns one of them into "this breaks your nightly reconciliation" or into
"nothing you read is affected".
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from compatlab.loci import READABLE_ROOTS, LocusError, parse, readable, resolve

REQUEST_INPUT = "request_input"
DECISION = "decision"
RECORD = "record"
DISPLAY = "display"
USES = (REQUEST_INPUT, DECISION, RECORD, DISPLAY)
USE_SUMMARY = {
    REQUEST_INPUT: "sent in a later call in the same workflow",
    DECISION: "branched or computed on",
    RECORD: "stored by the client",
    DISPLAY: "shown to a person",
}

CRITICALITIES = ("high", "medium", "low")
WORKFLOW_DIR = pathlib.Path(__file__).resolve().parent.parent / "workflows"


class DeclarationError(ValueError):
    """A declaration that cannot be loaded at all. Validation comes later."""


@dataclass(frozen=True)
class Read:
    """One field the client reads, and what it does with the value."""

    locus: str
    use: str
    note: str
    feeds: str | None = None

    def to_dict(self) -> dict:
        out = {"locus": self.locus, "use": self.use, "note": self.note}
        if self.feeds:
            out["feeds"] = self.feeds
        return out


@dataclass(frozen=True)
class Call:
    """One step of a customer workflow, named by the corpus step it replays."""

    corpus: str
    reads: tuple[Read, ...] = ()

    @property
    def workflow(self) -> str:
        return self.corpus.split(".", 1)[0]

    @property
    def step(self) -> str:
        return self.corpus.split(".", 1)[1]

    @property
    def key(self) -> tuple[str, str]:
        return (self.workflow, self.step)


@dataclass(frozen=True)
class Workflow:
    """One named customer workflow: a business process over captured calls."""

    name: str
    purpose: str
    criticality: str
    owner: str
    sequence: tuple[Call, ...]
    source: str = ""

    @property
    def reads(self) -> list[tuple[Call, Read]]:
        return [(call, read) for call in self.sequence for read in call.reads]

    @property
    def length(self) -> int:
        return len(self.sequence)

    def position(self, key: tuple[str, str]) -> int | None:
        """1-based position of a corpus step in this workflow, or None."""
        for index, call in enumerate(self.sequence, start=1):
            if call.key == key:
                return index
        return None

    def to_dict(self) -> dict:
        return {
            "workflow": self.name,
            "purpose": self.purpose,
            "criticality": self.criticality,
            "owner": self.owner,
            "sequence": [
                {"corpus": call.corpus,
                 "reads": [read.to_dict() for read in call.reads]}
                for call in self.sequence
            ],
        }


def _read(raw: dict, where: str) -> Read:
    missing = [key for key in ("locus", "use", "note") if not raw.get(key)]
    if missing:
        raise DeclarationError(f"{where}: read missing {', '.join(missing)}")
    use = raw["use"]
    if use not in USES:
        raise DeclarationError(
            f"{where}: unknown use {use!r}; expected one of {', '.join(USES)}")
    return Read(locus=raw["locus"], use=use, note=raw["note"],
                feeds=raw.get("feeds"))


def load(path: pathlib.Path) -> Workflow:
    """One declaration file into a Workflow. Shape errors only."""
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise DeclarationError(f"{path.name}: not valid JSON ({exc})") from exc
    for key in ("workflow", "purpose", "criticality", "owner", "sequence"):
        if not raw.get(key):
            raise DeclarationError(f"{path.name}: missing `{key}`")
    if raw["criticality"] not in CRITICALITIES:
        raise DeclarationError(
            f"{path.name}: criticality must be one of "
            f"{', '.join(CRITICALITIES)}, not {raw['criticality']!r}")
    sequence = []
    for index, item in enumerate(raw["sequence"], start=1):
        corpus = item.get("corpus")
        if not corpus or "." not in corpus:
            raise DeclarationError(
                f"{path.name}: sequence[{index}] needs `corpus` as "
                f"`<capture-workflow>.<step>`")
        where = f"{path.name}:{corpus}"
        sequence.append(Call(
            corpus=corpus,
            reads=tuple(_read(r, where) for r in item.get("reads", ())),
        ))
    return Workflow(
        name=raw["workflow"], purpose=raw["purpose"],
        criticality=raw["criticality"], owner=raw["owner"],
        sequence=tuple(sequence), source=path.name,
    )


def load_all(directory: pathlib.Path = WORKFLOW_DIR) -> list[Workflow]:
    """Every declaration in a directory, by filename."""
    paths = sorted(p for p in directory.glob("*.json"))
    workflows = [load(path) for path in paths]
    seen: dict[str, str] = {}
    for workflow in workflows:
        if workflow.name in seen:
            raise DeclarationError(
                f"{workflow.source}: workflow {workflow.name!r} is already "
                f"declared in {seen[workflow.name]}")
        seen[workflow.name] = workflow.source
    return workflows


@dataclass
class Validation:
    """What is wrong with the inventory, as against what the corpus shows."""

    problems: list[str] = field(default_factory=list)
    reads_checked: int = 0
    steps_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def validate(workflows: list[Workflow],
             canon_a: dict[tuple[str, str], dict],
             seqs: dict[tuple[str, str], int]) -> Validation:
    """Check every declaration against the version-A traffic it describes.

    This is the gate that makes the inventory evidence rather than assertion.
    Five things are checked, and each one has a failure mode that would
    otherwise reach the report as a confident sentence about nothing:

    - a declared step the corpus never captured (the inventory and the capture
      have drifted apart);
    - a declared sequence that runs backwards through the captured order (it
      cannot be the sequence that was replayed, so no claim about "where in
      the sequence" would mean anything);
    - the same corpus step declared twice in one workflow, which makes "where
      in the sequence" ambiguous;
    - a declared locus absent from that step's version-A response (a stale
      integration note; also the case where the field is simply misspelled);
    - a `request_input` read that feeds a step not later in this workflow
      (the propagation claim it licenses would be unfounded).
    """
    out = Validation()
    for workflow in workflows:
        last_seq = -1
        seen: set[str] = set()
        for position, call in enumerate(workflow.sequence, start=1):
            where = f"{workflow.source}:{workflow.name}[{position}] {call.corpus}"
            out.steps_checked += 1
            if call.corpus in seen:
                out.problems.append(
                    f"{where}: declared twice in this workflow, which leaves "
                    f"no single answer to where in the sequence a break lands")
            seen.add(call.corpus)
            record = canon_a.get(call.key)
            if record is None:
                out.problems.append(
                    f"{where}: no such step in the version-A corpus")
                continue
            seq = seqs.get(call.key)
            if seq is not None and seq <= last_seq:
                out.problems.append(
                    f"{where}: declared after a step that was captured later; "
                    f"a customer workflow has to run in captured order to be "
                    f"replayable from this corpus")
            if seq is not None:
                last_seq = seq
            out.reads_checked += len(call.reads)
            out.problems += _check_reads(workflow, call, record, where)
    return out


def _check_reads(workflow: Workflow, call: Call, record: dict,
                 where: str) -> list[str]:
    problems: list[str] = []
    later = {c.corpus for c in workflow.sequence[workflow.position(call.key):]}
    for read in call.reads:
        try:
            parse(read.locus)
        except LocusError as exc:
            problems.append(f"{where}: {exc}")
            continue
        if not readable(read.locus):
            problems.append(
                f"{where}: read {read.locus} must name one of "
                f"{', '.join(READABLE_ROOTS)}")
            continue
        if not resolve(record, read.locus):
            problems.append(
                f"{where}: read {read.locus} is not present in the version-A "
                f"response for this step; the integration note is stale or "
                f"the locus is misspelled")
        if read.use == REQUEST_INPUT and not read.feeds:
            problems.append(
                f"{where}: read {read.locus} is `{REQUEST_INPUT}` but names no "
                f"`feeds` step, so there is nothing to claim it propagates to")
        elif read.use == REQUEST_INPUT and read.feeds not in later:
            problems.append(
                f"{where}: read {read.locus} feeds {read.feeds!r}, which is "
                f"not a later step of {workflow.name}")
    return problems
