# ADR 0005: affected-workflow mapping and the impact report (RC1-609)

Status: accepted
Date: 2026-11-04

## Context

Phase 3 left `findings/findings.jsonl`: 93 findings over 29 replayed steps,
25 of them classified `breaking`, every one adjudicated against Stripe's
changelog. That answers *what changed between these two API versions*. It does
not answer the question a customer actually asks, which is **will this upgrade
break us, and where**.

The epic calls the affected-workflow mapping required scope rather than a
stretch, and says why: detecting a behavioral diff is the tooling half, and a
tool that stops there is a testing tool. It also records the lane risk — an
API platform team builds a differ, an FDE uses one — and names the impact
report as the thing that holds the lane.

The output is `workflows/` (the inventory, an input), `pins/pins.jsonl` (Phase
5's input), and the generated `docs/impact-report.md` and
`docs/impact-report.html`.

Result: of five declared customer workflows, **one stops outright, two keep
running and go silently wrong, one is visibly degraded, and one is
unaffected**. 13 impact claims, all 13 confirmed against the replay record by
a checker that does not read the classifier's rule table. 11 regression tests
specified. 13 of 36 declared reads are touched; 8 real differences fall
outside the inventory entirely.

## D1. A groupby is not a mapping

The corpus was captured workflow-shaped, so every finding already carries a
`workflow` and a `step`. Grouping findings by workflow is one line of code and
it produces a grouped finding list, not an impact report. The
`{{step.field}}` reference graph was the obvious second source of signal and
it turned out to be nearly empty: every reference in the corpus resolves an
`id`, and no finding sits on an id, because canonicalization removes them. A
mapping built only on observed propagation would report nothing.

What the findings cannot say is the fact that decides whether a difference
matters: **which of these fields does the client read, and what does it do
with the value**. That is not inferable from traffic, in principle and not
just in this corpus — nothing about a response says what happens to it after
it is parsed.

So it is declared, in `workflows/*.json`, and on a real engagement it is
declared *by the customer*. This is the artifact an FDE fills in during
discovery, and the reason the output is a customer deliverable rather than a
diff. Declaring it is not a weakness of the design; the conversation it forces
is the deliverable.

## D2. The declaration contains no verdicts

The obvious objection is that an inventory written by the same person who ran
the differ is a hand-written answer key. Three things are in place against it.

**A read declares facts, not conclusions**: a locus, what the client does with
the value (`request_input` / `decision` / `record` / `display`), a note, and
for a `request_input` read, which later step it feeds. Nothing in `workflows/`
names a break, a severity, or a consequence. Severity and consequence are
derived in `compatlab/impact.py`.

**It is validated against the captured traffic, not trusted.**
`compatlab impact` fails outright, publishing nothing, on: a declared step the
corpus never captured; a declared sequence that runs backwards through the
captured order; the same step declared twice in one workflow; a declared locus
absent from that step's version-A response; a `request_input` read that feeds
a step not later in the same workflow. The locus gate is the one that earns
its keep — a stale integration note is the normal way this input goes wrong,
and it would otherwise produce a confident claim about a field nobody returns.

**The report publishes the numbers that would expose a rigged inventory.** How
many declared reads this version change touches (13 of 36), how many real
differences fall on calls the inventory does not describe (8), and which
workflows came out clear (1). An inventory written backwards from the findings
would touch every read, cover every finding, and leave nothing clear. A test
asserts all three stay real.

## D3. The consequence is a cell in a table, not a judgment per finding

Two facts meet: what the finding did to the value, and what the client does
with it. The first is an **effect** class, assigned once per classification
rule; the second is the declared **use**. The consequence is the cell.

| Effect | request_input | decision | record | display |
|--------|---------------|----------|--------|---------|
| loss | blocks | corrupts | corrupts | degrades |
| change | corrupts | corrupts | corrupts | degrades |
| novel | corrupts | corrupts | degrades | degrades |
| addition | tolerates | tolerates | degrades | tolerates |

- **blocks** — the sequence stops; the customer sees an error.
- **corrupts** — the sequence finishes and is silently wrong: a decision made
  on changed data, or wrong data written down. This is the class the project
  exists to find and the one a schema diff cannot reach.
- **degrades** — a person sees something different; nothing decided or stored
  is wrong.
- **tolerates** — additive material the declared use cannot notice.

Two cells carry the argument. A `loss` on a `request_input` read **blocks**
rather than corrupts, because the next call has nothing to send — the one
place the mapping reasons across steps rather than within one. And `novel` on
a `decision` read **corrupts**: a value the client has never been handed,
reaching an exhaustive switch or a comparison, is the classic quiet failure.

A rule missing from the effect table raises rather than defaulting, and a test
asserts every rule in `classify.RULES` has been placed. A default would be the
quiet way the mapping stops reporting a whole class of difference.

## D4. Two rules are about the call, not about a value in it

`step-missing` and `status-class-changed` override the table and always block,
they apply to **every** read declared on that call rather than only the ones
whose locus they match, and they produce an impact even on a call with no
declared reads at all. All three follow from one fact: when the request itself
stops working, the client never reaches any field.

This was wrong in the first version, which matched them by locus like
everything else. A `status-class-changed` finding sits at `$.status`, which
touches no `$.body.*` read, so `subscription_renewal_billing` — whose third
call went 200 to 404 — came out as *corrupted at call 1* with the 404 reported
nowhere. The whole workflow had stopped and the report said it was fine. The
live data caught it; no unit test would have, because the fixture would have
been written with the same wrong assumption.

## D5. The inventory is what resolves a `risky` finding

Phase 3's severity is a property of the API change. The consequence here is a
property of one customer's integration. They disagree on purpose, and the
report cross-tabs them rather than implying they agree.

`risky` is Phase 3 saying *it depends how the client was written* — a strict
deserializer, a regex over an error message, an exhaustive switch, a
dependence on list position. A declared read is exactly that missing fact. 44
of the 93 findings are risky, and on this inventory three of them resolve into
concrete consequences: `payment_method_types` gaining four members and
`automatic_payment_methods` arriving non-null both corrupt a storefront that
branches on them, and the reworded `total_count` error degrades an alert that
quotes the message. None of those is reportable from the finding alone.

This is why risky findings are joined rather than filtered to `breaking`
first, and it is the clearest single answer to what the inventory buys.

## D6. The precision number is verified, and it is not an accuracy number

The mapper reads the findings; the findings came from the classifier. Scoring
the mapping against the findings would score it against its own input, and a
mapping bug — a claim on the wrong step, a read whose locus does not actually
differ, a `blocks` on a call that completed fine — would score 100%.

So `compatlab/verify.py` goes back to `replay/pairs.jsonl` and re-derives each
claim from the two canonical responses. It never imports the rule table, never
looks at a severity, and asks only questions with observable answers: was the
step really replayed on both sides; does the **declared read** really resolve
to something different on the new version; did a changed status really cross
between success and failure; does a blocking propagation claim really have
nothing left to send. **Workflow-mapping precision is confirmed claims over
all claims: 13 of 13.**

What it does not verify is the judgment — whether a difference deserves to be
called breaking, or whether a client's exhaustive switch really falls through
on a value it has not seen. Neither is mechanically checkable, which is why
the number is named *mapping* precision and not impact accuracy. Severity has
its own honesty mechanism, the hand adjudication in Phase 3.

`compatlab impact` **exits non-zero while any claim is unconfirmed and
publishes no rate**, the same gate shape as `score`. A precision computed over
whichever claims happened to verify is the likeliest way this figure would get
flattering by accident. CI runs it.

The report also carries a ground-truth coverage table, and it is labelled a
**regression guard, not evidence**: the inventory is authored in this
repository, so a break landing on a declared read says as much about its
author as about the tool. What it catches is the mapping quietly losing a
break Phase 3 found, through a step dropped from every declaration or a locus
a read no longer covers.

## D7. Phase 4 specifies the pins; Phase 5 compiles them

The epic puts "here is the regression test that pins it" in the impact report
and gives executable test generation its own phase (RC1-610). The seam is that
Phase 4 emits a **specification** — `pins/pins.jsonl`, one per place a
declared read is blocked or corrupted, naming the step to replay, the locus,
the assertion, and both versions' values — and Phase 5 compiles each into a
test and verifies the defining property, that it fails on B and passes on A.

A pin cannot always quote the old value back. Findings truncate their recorded
values for readability, and an assertion built from a clipped JSON blob is a
test nobody can write, so where the value does not fit the pin names the
property instead (`comes back as a non-empty collection`) and the full values
stay on the record.

## D8. What is deferred, with the reason

**The inventory is authored here, not supplied by a customer.** There is no
customer. Stating the number of untouched reads and uncovered differences is
the honest substitute for an inventory somebody else wrote, and the report
says so in the section that reports them.

**Nothing is inferred from the reference graph.** The corpus's
`{{step.field}}` references would license propagation claims without a
declaration, and a future corpus with richer references should use them — as
corroboration for a declared `request_input` read, which is a second gate the
validator could enforce. Today every reference resolves an id that
canonicalization removes, so the check would pass vacuously on all of them and
mean nothing.

**A read cannot name `$.duration_ms`.** The timing axis is benign by rule
forever (ADR 0004 D7), so a declared read of it could only produce a claim the
project has promised not to make. Refused in `loci.readable`.

**The account-state caveat is carried, not re-derived.** A finding under
`data` on a list endpoint arrives with the caveat ADR 0004 attached, and the
impact prints it verbatim rather than deciding again whether a list difference
is real. One place to be wrong is better than two.
