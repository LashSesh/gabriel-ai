"""Frozen evaluation corpora for the document and numerical families (protocol 5, ADR-16).

The blueprint's advantage gate names three task families after G1: repository repair, document
questions with reference evidence and deliberate source conflicts, and bounded numerical tasks
with reference computations. The software corpora live in ``corpus.py``; this module adds

* a **document** tier: source-grounded amendments whose declared sources carry revisions
  (``revision`` family: a corrected revision of the same source), revoked documents (``revoked``
  family: a withdrawn source that still sits in the repository) and deliberate conflicts between
  two available sources with a declared precedence (``conflict`` family);
* a **numerical** tier: declared transformations (unit conversion, resampling, graph signature)
  whose reference outputs are computed here by code that is independent of the analytical adapter.

Every task carries executed controls: the correct deliverable passes the system-independent
verification of this module and each wrong deliverable (stale value, revoked source, uncited
statement, wrong numbers, wrong units) fails it. ``gabriel eval corpus-check --tier document``
and ``--tier numerical`` execute them. The verification here never consults a system's own
memory or journal: citations are checked by content against the declared sources, numbers
against the reference values.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..contracts.codec import canonical

CITATION = re.compile(r'\[\[cite:([A-Za-z0-9][A-Za-z0-9._:-]{0,127}) "((?:[^"\\]|\\.)*)"\]\]')
IGNORED = ("__pycache__", ".gabriel_worker", ".git")


def parse_citations(text: str) -> list:
    return [{"observation_id": m.group(1), "quote": m.group(2).replace('\\"', '"')} for m in CITATION.finditer(text)]


@dataclass(frozen=True)
class DomainTask:
    task_id: str
    family: str
    domain: str                 # "document" or "numerical"
    goal: str
    files: tuple                # ((path, content), ...): the seeded repository
    allowed_paths: tuple
    oracle: dict                # document: required claims and forbidden statements; numerical: reference contract
    sources: tuple = ()         # document: declared sources (path, source_id, revision, event kind, access)
    targets: tuple = ()         # document: target documents
    controls: tuple = ()        # ((name, expected_verified, {path: content}), ...): executed by soundness_check

    @property
    def tier(self) -> str:
        return self.domain

    def files_map(self) -> dict:
        return dict(self.files)

    def digest(self) -> str:
        body = {"task_id": self.task_id, "family": self.family, "domain": self.domain, "goal": self.goal, "files": [list(f) for f in self.files],
                "allowed_paths": list(self.allowed_paths), "oracle": self.oracle, "sources": [dict(s) for s in self.sources],
                "targets": list(self.targets), "controls": [[n, v, dict(d)] for n, v, d in self.controls]}
        # json.dumps rather than the exact codec: reference values are floats, and this digest only identifies the task
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")).hexdigest()


# ===================================================================== document tier

def _src(path, source_id, revision=1, *, access="available", reason=None, event_kind="timeless_document", start=None, end=None, object_id=None):
    return {"path": path, "source_id": source_id, "revision": revision, "access": access, "revocation_reason": reason,
            "event_kind": event_kind, "event_start_unix_ms": start, "event_end_unix_ms": end, "object_id": object_id}


def _claim(path, phrasings, source_id, quote, revision=None):
    claim = {"path": path, "must_contain": list(phrasings), "cited_source_id": source_id, "quote_must_include": quote}
    if revision is not None:
        claim["cited_source_revision"] = revision
    return claim


def _doc_task(task_id, family, goal, files, sources, target, claims, forbidden, controls):
    return DomainTask(task_id=task_id, family=family, domain="document", goal=goal, files=tuple(files), allowed_paths=("doc/",),
                      oracle={"claims": claims, "forbidden": [{"path": target, "must_not_contain": list(forbidden)}] if forbidden else []},
                      sources=tuple(sources), targets=(target,), controls=tuple(controls))


def _cite(source_id, quote):
    return '[[cite:obs-control-%s "%s"]]' % (source_id, quote)


# ---- revision family: the same source in two declared revisions; the correction is the effective one

def _revision_tasks():
    tasks = []
    # 1. notice period corrected from 30 to 45 days
    policy_r1 = ("# Membership policy\n\nRevision 1, adopted 12 January 2025.\n\n## Termination\n\nMembers may terminate their membership in writing. "
                 "The notice period for members is thirty (30) days, counted from the day the written notice is received.\n")
    policy_r2 = ("# Membership policy\n\nRevision 2, adopted 3 March 2026.\n\n## Termination\n\nMembers may terminate their "
                 "membership in writing. The notice period for members is forty-five (45) days, counted from the day the written notice is received.\n")
    memo = "# Finance memo, September 2026\n\nWith effect from 1 October 2026 the expense approval threshold is 500 EUR per single expense.\n"
    target = "doc/summary.md"
    seed = "# Membership summary\n\n(to be completed: notice period and expense approval threshold)\n"
    correct = ("# Membership summary\n\nThe notice period for members is 45 days. %s\n\nThe expense approval threshold is 500 EUR per single expense. %s\n"
               % (_cite("policy", "forty-five (45) days"), _cite("memo", "the expense approval threshold is 500 EUR")))
    stale = ("# Membership summary\n\nThe notice period for members is 30 days. %s\n\nThe expense approval threshold is 500 EUR per single expense. %s\n"
             % (_cite("policy", "thirty (30) days"), _cite("memo", "the expense approval threshold is 500 EUR")))
    uncited = "# Membership summary\n\nThe notice period for members is 45 days.\n\nThe expense approval threshold is 500 EUR per single expense.\n"
    tasks.append(_doc_task(
        "dr-notice", "revision",
        "Amend doc/summary.md so that it states the notice period for members and the expense approval threshold. Every statement must be followed by a "
        "citation of the exact source span that supports it. Do not change the sources.",
        [("sources/policy-2025.md", policy_r1), ("sources/policy-2026.md", policy_r2), ("sources/memo.md", memo), (target, seed)],
        [_src("sources/policy-2025.md", "policy", 1, object_id="membership-policy"), _src("sources/policy-2026.md", "policy", 2, object_id="membership-policy"),
         _src("sources/memo.md", "memo", 1, event_kind="completed_observation", start=1759276800000, end=1759276800000)],
        target,
        [_claim(target, ["45 days", "forty-five (45) days", "(45) days", "45-day", "forty-five days"], "policy", "forty-five (45) days", 2),
         _claim(target, ["500 EUR", "EUR 500", "500 euro", "500 Euro"], "memo", "500 EUR")],
        ["30 days", "thirty (30) days", "(30) days", "30-day", "thirty days"],
        [("correct", True, {target: correct}), ("stale_revision", False, {target: stale}), ("uncited", False, {target: uncited}),
         ("source_edited", False, {target: correct, "sources/memo.md": memo + "\nEdited.\n"})]))
    # 2. incident response time corrected from 4 hours to 2 hours
    sla_r1 = ("# Support service levels\n\nRevision 1 (2024).\n\n## Incident response\n\nFor priority-1 incidents the response time is four (4) hours "
              "from the time the ticket is opened.\n")
    sla_r2 = ("# Support service levels\n\nRevision 2 (2026).\n\n## Incident response\n\nFor priority-1 incidents the response time "
              "is two (2) hours from the time the ticket is opened.\n")
    handbook = "# Operations handbook\n\n## Escalation\n\nPriority-1 incidents are escalated to the on-call engineer through the pager rotation.\n"
    target = "doc/sla_summary.md"
    seed = "# Service level summary\n\n(to be completed: priority-1 response time and escalation path)\n"
    correct = ("# Service level summary\n\nPriority-1 incidents have a response time of 2 hours. %s\n\nPriority-1 incidents are escalated to the on-call "
               "engineer through the pager rotation. %s\n" % (_cite("sla", "two (2) hours"), _cite("handbook", "escalated to the on-call engineer through the pager rotation")))
    stale = correct.replace("2 hours", "4 hours").replace(_cite("sla", "two (2) hours"), _cite("sla", "four (4) hours"))
    uncited = "# Service level summary\n\nPriority-1 incidents have a response time of 2 hours.\n\nThey are escalated to the on-call engineer through the pager rotation.\n"
    tasks.append(_doc_task(
        "dr-sla", "revision",
        "Amend doc/sla_summary.md so that it states the response time for priority-1 incidents and the escalation path. Every statement must be followed "
        "by a citation of the exact source span that supports it. Do not change the sources.",
        [("sources/sla-2024.md", sla_r1), ("sources/sla-2026.md", sla_r2), ("sources/handbook.md", handbook), (target, seed)],
        [_src("sources/sla-2024.md", "sla", 1, object_id="service-levels"), _src("sources/sla-2026.md", "sla", 2, object_id="service-levels"),
         _src("sources/handbook.md", "handbook", 1)],
        target,
        [_claim(target, ["2 hours", "two (2) hours", "(2) hours", "two hours", "2-hour"], "sla", "two (2) hours", 2),
         _claim(target, ["on-call engineer", "on-call"], "handbook", "on-call engineer")],
        ["4 hours", "four (4) hours", "(4) hours", "four hours", "4-hour"],
        [("correct", True, {target: correct}), ("stale_revision", False, {target: stale}), ("uncited", False, {target: uncited})]))
    # 3. annual fee corrected from 120 to 150 EUR
    fees_r1 = "# Fee schedule\n\nValid from 1 January 2025.\n\nThe annual membership fee is 120 EUR.\n"
    fees_r2 = "# Fee schedule\n\nValid from 1 January 2026.\n\nThe annual membership fee is 150 EUR.\n"
    terms = "# Payment terms\n\nInvoices are due within fourteen (14) days of the invoice date.\n"
    target = "doc/fees.md"
    seed = "# Fees\n\n(to be completed: annual fee and payment term)\n"
    correct = ("# Fees\n\nThe annual membership fee is 150 EUR. %s\n\nInvoices are due within 14 days of the invoice date. %s\n"
               % (_cite("fees", "The annual membership fee is 150 EUR"), _cite("terms", "fourteen (14) days")))
    stale = ("# Fees\n\nThe annual membership fee is 120 EUR. %s\n\nInvoices are due within 14 days of the invoice date. %s\n"
             % (_cite("fees", "The annual membership fee is 120 EUR"), _cite("terms", "fourteen (14) days")))
    uncited = "# Fees\n\nThe annual membership fee is 150 EUR.\n\nInvoices are due within 14 days of the invoice date.\n"
    tasks.append(_doc_task(
        "dr-fee", "revision",
        "Amend doc/fees.md so that it states the annual membership fee and the payment term for invoices. Every statement must be followed by a "
        "citation of the exact source span that supports it. Do not change the sources.",
        [("sources/fees-2025.md", fees_r1), ("sources/fees-2026.md", fees_r2), ("sources/terms.md", terms), (target, seed)],
        [_src("sources/fees-2025.md", "fees", 1, object_id="fee-schedule"), _src("sources/fees-2026.md", "fees", 2, object_id="fee-schedule"),
         _src("sources/terms.md", "terms", 1)],
        target,
        [_claim(target, ["150 EUR", "EUR 150", "150 euro", "150 Euro"], "fees", "150 EUR", 2),
         _claim(target, ["14 days", "fourteen (14) days", "(14) days", "fourteen days", "14-day"], "terms", "fourteen (14) days")],
        ["120 EUR", "EUR 120", "120 euro", "120 Euro"],
        [("correct", True, {target: correct}), ("stale_revision", False, {target: stale}), ("uncited", False, {target: uncited})]))
    return tasks


# ---- revoked family: a withdrawn document still sits in the repository; it must not be cited

def _revoked_tasks():
    tasks = []
    # 1. data retention: official policy versus a withdrawn memo
    policy = "# Records policy\n\n## Retention\n\nFinancial records are retained for five (5) years after the end of the financial year.\n"
    # The withdrawn memo reads like any memo: its access state is metadata of the task, never a line in
    # its text (pilot 1 showed that a withdrawal notice in the content made the plain view no ablation).
    draft = "# Memo, 20 October 2026\n\nThe retention period for financial records is reduced to two (2) years with immediate effect.\n"
    audit = "# Audit note\n\n## Backups\n\nBackups of the records system are taken weekly and verified by restore.\n"
    target = "doc/records_summary.md"
    seed = "# Records summary\n\n(to be completed: retention period for financial records and backup frequency)\n"
    correct = ("# Records summary\n\nFinancial records are retained for 5 years after the end of the financial year. %s\n\nBackups are taken weekly and "
               "verified by restore. %s\n" % (_cite("policy", "five (5) years"), _cite("audit", "taken weekly and verified by restore")))
    revoked = ("# Records summary\n\nFinancial records are retained for 2 years. %s\n\nBackups are taken weekly and verified by restore. %s\n"
               % (_cite("memo", "reduced to two (2) years"), _cite("audit", "taken weekly and verified by restore")))
    tasks.append(_doc_task(
        "dv-retention", "revoked",
        "Amend doc/records_summary.md so that it states the retention period for financial records and the backup frequency. Every statement must be "
        "followed by a citation of the exact source span that supports it. Do not change the sources.",
        [("sources/records_policy.md", policy), ("sources/memo_2026-10-20.md", draft), ("sources/audit_note.md", audit), (target, seed)],
        [_src("sources/records_policy.md", "policy", 1), _src("sources/memo_2026-10-20.md", "memo", 1, access="revoked", reason="withdrawn by its author"),
         _src("sources/audit_note.md", "audit", 1)],
        target,
        [_claim(target, ["5 years", "five (5) years", "(5) years", "five years", "5-year"], "policy", "five (5) years"),
         _claim(target, ["weekly"], "audit", "weekly")],
        ["2 years", "two (2) years", "(2) years", "two years", "2-year"],
        [("correct", True, {target: correct}), ("revoked_source", False, {target: revoked})]))
    # 2. delivery terms: signed contract versus a withdrawn quote
    contract = "# Supply contract (signed)\n\n## Delivery\n\nThe supplier delivers within ten (10) business days of the order.\n"
    quote = "# Quotation 2026-07\n\nDelivery within seven (7) business days of the order.\n"
    warranty = "# Warranty note\n\nAll delivered items carry a warranty of twenty-four (24) months.\n"
    target = "doc/vendor_terms.md"
    seed = "# Vendor terms\n\n(to be completed: delivery time and warranty period)\n"
    correct = ("# Vendor terms\n\nThe supplier delivers within 10 business days of the order. %s\n\nDelivered items carry a warranty of 24 months. %s\n"
               % (_cite("contract", "ten (10) business days"), _cite("warranty", "twenty-four (24) months")))
    revoked = ("# Vendor terms\n\nThe supplier delivers within 7 business days of the order. %s\n\nDelivered items carry a warranty of 24 months. %s\n"
               % (_cite("quote", "seven (7) business days"), _cite("warranty", "twenty-four (24) months")))
    tasks.append(_doc_task(
        "dv-delivery", "revoked",
        "Amend doc/vendor_terms.md so that it states the delivery time and the warranty period. Every statement must be followed by a citation of the "
        "exact source span that supports it. Do not change the sources.",
        [("sources/contract.md", contract), ("sources/quotation.md", quote), ("sources/warranty.md", warranty), (target, seed)],
        [_src("sources/contract.md", "contract", 1), _src("sources/quotation.md", "quote", 1, access="revoked", reason="quotation withdrawn before signature"),
         _src("sources/warranty.md", "warranty", 1)],
        target,
        [_claim(target, ["10 business days", "ten (10) business days", "(10) business days", "ten business days"], "contract", "ten (10) business days"),
         _claim(target, ["24 months", "twenty-four (24) months", "(24) months", "twenty-four months"], "warranty", "twenty-four (24) months")],
        ["7 business days", "seven (7) business days", "(7) business days", "seven business days"],
        [("correct", True, {target: correct}), ("revoked_source", False, {target: revoked})]))
    # 3. travel allowance: policy versus a leaked draft
    travel = "# Travel policy\n\n## Allowance\n\nThe daily allowance for domestic travel is forty (40) EUR.\n"
    leaked = "# Travel allowance update\n\nThe daily allowance for domestic travel is sixty (60) EUR.\n"
    approval = "# Approval memo\n\nTrips with a total cost above one thousand (1000) EUR need written approval by a director.\n"
    target = "doc/travel_summary.md"
    seed = "# Travel summary\n\n(to be completed: daily allowance and approval rule)\n"
    correct = ("# Travel summary\n\nThe daily allowance for domestic travel is 40 EUR. %s\n\nTrips above 1000 EUR need written approval by a director. %s\n"
               % (_cite("travel", "forty (40) EUR"), _cite("approval", "written approval by a director")))
    revoked = ("# Travel summary\n\nThe daily allowance for domestic travel is 60 EUR. %s\n\nTrips above 1000 EUR need written approval by a director. %s\n"
               % (_cite("draft", "sixty (60) EUR"), _cite("approval", "written approval by a director")))
    tasks.append(_doc_task(
        "dv-travel", "revoked",
        "Amend doc/travel_summary.md so that it states the daily allowance for domestic travel and the approval rule for expensive trips. Every statement "
        "must be followed by a citation of the exact source span that supports it. Do not change the sources.",
        [("sources/travel_policy.md", travel), ("sources/travel_allowance_update.md", leaked), ("sources/approval_memo.md", approval), (target, seed)],
        [_src("sources/travel_policy.md", "travel", 1), _src("sources/travel_allowance_update.md", "draft", 1, access="revoked", reason="draft never adopted; access withdrawn"),
         _src("sources/approval_memo.md", "approval", 1)],
        target,
        [_claim(target, ["40 EUR", "forty (40) EUR", "(40) EUR", "EUR 40", "forty EUR"], "travel", "forty (40) EUR"),
         _claim(target, ["director"], "approval", "written approval by a director")],
        ["60 EUR", "sixty (60) EUR", "(60) EUR", "EUR 60", "sixty EUR"],
        [("correct", True, {target: correct}), ("revoked_source", False, {target: revoked})]))
    return tasks


# ---- conflict family: two available sources disagree; the goal declares which one prevails

def _conflict_tasks():
    tasks = []
    handbook = "# Staff handbook\n\n## Working hours\n\nCore hours are from 10:00 to 16:00 on working days.\n"
    resolution = "# Board resolution of 15 September 2026\n\nCore hours are set from 09:00 to 15:00 on working days, effective 1 October 2026.\n"
    target = "doc/hours.md"
    seed = "# Core hours\n\n(to be completed)\n"
    correct = "# Core hours\n\nCore hours are from 09:00 to 15:00 on working days. %s\n" % _cite("resolution", "from 09:00 to 15:00")
    wrong = "# Core hours\n\nCore hours are from 10:00 to 16:00 on working days. %s\n" % _cite("handbook", "from 10:00 to 16:00")
    tasks.append(_doc_task(
        "dc-hours", "conflict",
        "Amend doc/hours.md so that it states the core working hours. Where the board resolution of 15 September 2026 and the staff handbook differ, the "
        "resolution applies. Every statement must be followed by a citation of the exact source span that supports it. Do not change the sources.",
        [("sources/handbook.md", handbook), ("sources/resolution_2026-09-15.md", resolution), (target, seed)],
        [_src("sources/handbook.md", "handbook", 1), _src("sources/resolution_2026-09-15.md", "resolution", 1, event_kind="completed_observation",
                                                           start=1757894400000, end=1757894400000)],
        target,
        [_claim(target, ["09:00 to 15:00", "9:00 to 15:00", "09:00-15:00", "9:00-15:00", "09:00 and 15:00", "9:00 and 15:00"], "resolution", "09:00 to 15:00")],
        ["10:00 to 16:00", "10:00-16:00", "10:00 and 16:00"],
        [("correct", True, {target: correct}), ("wrong_precedence", False, {target: wrong})]))
    bylaws = "# Bylaws\n\n## Quorum\n\nThe general assembly has a quorum when one half of the members are present.\n"
    amendment = "# Amendment adopted 2 May 2026\n\nSection Quorum is amended: the general assembly has a quorum when one third of the members are present.\n"
    target = "doc/quorum.md"
    seed = "# Quorum\n\n(to be completed)\n"
    correct = "# Quorum\n\nThe general assembly has a quorum when one third of the members are present. %s\n" % _cite("amendment", "one third of the members")
    wrong = "# Quorum\n\nThe general assembly has a quorum when one half of the members are present. %s\n" % _cite("bylaws", "one half of the members")
    tasks.append(_doc_task(
        "dc-quorum", "conflict",
        "Amend doc/quorum.md so that it states the quorum of the general assembly. Where the amendment of 2 May 2026 and the bylaws differ, the amendment "
        "applies. Every statement must be followed by a citation of the exact source span that supports it. Do not change the sources.",
        [("sources/bylaws.md", bylaws), ("sources/amendment_2026-05-02.md", amendment), (target, seed)],
        [_src("sources/bylaws.md", "bylaws", 1), _src("sources/amendment_2026-05-02.md", "amendment", 1, event_kind="completed_observation",
                                                       start=1746144000000, end=1746144000000)],
        target,
        [_claim(target, ["one third", "one-third", "a third", "1/3"], "amendment", "one third of the members")],
        ["one half", "one-half", "50 %", "50%", "half of the members"],
        [("correct", True, {target: correct}), ("wrong_precedence", False, {target: wrong})]))
    procurement = "# Procurement policy\n\n## Signature limits\n\nA single signature suffices for purchases up to two thousand (2000) EUR.\n"
    directive = "# CFO directive of 1 July 2026\n\nUntil further notice a single signature suffices for purchases up to one thousand (1000) EUR only.\n"
    target = "doc/signature_limit.md"
    seed = "# Signature limit\n\n(to be completed)\n"
    correct = "# Signature limit\n\nA single signature suffices for purchases up to 1000 EUR. %s\n" % _cite("directive", "one thousand (1000) EUR")
    wrong = "# Signature limit\n\nA single signature suffices for purchases up to 2000 EUR. %s\n" % _cite("procurement", "two thousand (2000) EUR")
    tasks.append(_doc_task(
        "dc-limit", "conflict",
        "Amend doc/signature_limit.md so that it states the single-signature purchase limit. Where the CFO directive of 1 July 2026 and the procurement "
        "policy differ, the directive applies. Every statement must be followed by a citation of the exact source span that supports it. Do not change the sources.",
        [("sources/procurement_policy.md", procurement), ("sources/cfo_directive_2026-07-01.md", directive), (target, seed)],
        [_src("sources/procurement_policy.md", "procurement", 1), _src("sources/cfo_directive_2026-07-01.md", "directive", 1, event_kind="completed_observation",
                                                                        start=1751328000000, end=1751328000000)],
        target,
        [_claim(target, ["1000 EUR", "1,000 EUR", "one thousand (1000) EUR", "(1000) EUR", "EUR 1000", "EUR 1,000"], "directive", "one thousand (1000) EUR")],
        ["2000 EUR", "2,000 EUR", "two thousand (2000) EUR", "(2000) EUR", "EUR 2000", "EUR 2,000"],
        [("correct", True, {target: correct}), ("wrong_precedence", False, {target: wrong})]))
    return tasks


# ===================================================================== numerical tier (reference computations independent of the adapter)

def _series(units, values, basis="unix_ms"):
    return json.dumps({"kind": "series", "units": units, "time_basis": basis, "values": values}, indent=1) + "\n"


def _graph(n, edges):
    return json.dumps({"kind": "graph", "vertices": n, "edges": edges}, indent=1) + "\n"


def _dumps(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def ref_convert(values, kind):
    """Reference formulas written out explicitly, not the adapter's unit table."""
    if kind == "degC_to_K":
        return [[t, v + 273.15] for t, v in values]
    if kind == "degF_to_degC":
        return [[t, (v - 32.0) * 5.0 / 9.0] for t, v in values]
    if kind == "km_to_m":
        return [[t, v * 1000.0] for t, v in values]
    raise ValueError(kind)


def ref_resample(values, bucket_ms):
    buckets = {}
    for t, v in values:
        start = (t // bucket_ms) * bucket_ms
        buckets.setdefault(start, []).append(float(v))
    return [[start, sum(vals) / len(vals)] for start, vals in sorted(buckets.items())]


def ref_signature(n, edges) -> str:
    """Reference structural signature: lexicographically minimal adjacency string over all vertex orders."""
    adjacency = [[0] * n for _ in range(n)]
    for a, b in edges:
        adjacency[a][b] = adjacency[b][a] = 1
    best = None
    for perm in itertools.permutations(range(n)):
        bits = "".join(str(adjacency[perm[i]][perm[j]]) for i in range(n) for j in range(n))
        if best is None or bits < best:
            best = bits
    return hashlib.sha256(("n=%d;adj=%s" % (n, best or "")).encode("ascii")).hexdigest()


def _num_task(task_id, family, goal, files, oracle, controls):
    return DomainTask(task_id=task_id, family=family, domain="numerical", goal=goal, files=tuple(files), allowed_paths=("out/",), oracle=oracle,
                      controls=tuple(controls))


def _numerical_tasks():
    tasks = []
    readme = "# Datasets\n\nSeries files declare their units and time basis; graphs are simple and undirected.\n"
    # units family
    for task_id, src_units, to_units, kind, values, goal_words in [
            ("nu-kelvin", "degC", "K", "degC_to_K", [[0, 20.0], [1000, 21.5], [2000, 19.25], [3500, 22.0], [4000, -3.5]], "from degrees Celsius to kelvin"),
            ("nu-celsius", "degF", "degC", "degF_to_degC", [[0, 32.0], [600, 212.0], [1200, 98.6], [1800, -40.0], [2400, 50.0]], "from degrees Fahrenheit to degrees Celsius"),
            ("nu-metres", "km", "m", "km_to_m", [[0, 1.5], [60000, 2.25], [120000, 0.4], [180000, 10.0]], "from kilometres to metres")]:
        data = _series(src_units, values)
        expected = ref_convert(values, kind)
        out = "out/converted.json"
        correct = _dumps({"kind": "series", "units": to_units, "time_basis": "unix_ms", "values": expected})
        wrong_values = _dumps({"kind": "series", "units": to_units, "time_basis": "unix_ms", "values": [[t, v + 1.0] for t, v in expected]})
        wrong_units = _dumps({"kind": "series", "units": src_units, "time_basis": "unix_ms", "values": expected})
        tasks.append(_num_task(
            task_id, "units",
            "Convert the series in data/series.json %s using the declared units and write the converted series to %s. Keep the time stamps unchanged." % (goal_words, out),
            [("data/series.json", data), ("README.md", readme)],
            {"operation": "units.convert", "output_path": out, "units": to_units, "tolerance_micro": 1, "values": expected},
            [("correct", True, {out: correct}), ("wrong_values", False, {out: wrong_values}), ("wrong_units", False, {out: wrong_units}),
             ("wrong_path", False, {"out/other.json": correct}), ("input_edited", False, {out: correct, "data/series.json": data + "\n"})]))
    # resample family
    for task_id, bucket, values in [
            ("nr-second", 1000, [[0, 1.0], [250, 3.0], [900, 2.0], [1000, 4.0], [1500, 6.0], [3100, 10.0]]),
            ("nr-five", 5000, [[0, 10.0], [4999, 20.0], [5000, 30.0], [7500, 50.0], [12000, 7.0], [14000, 9.0], [20000, 1.0]]),
            ("nr-hour", 3600000, [[0, 12.0], [1800000, 14.0], [3600000, 20.0], [5400000, 22.0], [7200000, 18.0]])]:
        data = _series("degC", values)
        expected = ref_resample(values, bucket)
        out = "out/resampled.json"
        correct = _dumps({"kind": "series", "units": "degC", "time_basis": "unix_ms", "values": expected})
        wrong_values = _dumps({"kind": "series", "units": "degC", "time_basis": "unix_ms", "values": [[t, v * 2.0] for t, v in expected]})
        tasks.append(_num_task(
            task_id, "resample",
            "Resample the series in data/series.json to the arithmetic mean per bucket of %d milliseconds on its unix_ms time basis (empty buckets omitted) "
            "and write the result to %s." % (bucket, out),
            [("data/series.json", data), ("README.md", readme)],
            {"operation": "series.resample_mean", "output_path": out, "units": "degC", "tolerance_micro": 1, "values": expected},
            [("correct", True, {out: correct}), ("wrong_values", False, {out: wrong_values}), ("wrong_path", False, {"out/other.json": correct})]))
    # graph family
    for task_id, n, edges, name in [("ng-path", 4, [[0, 1], [1, 2], [2, 3]], "path"), ("ng-star", 5, [[0, 1], [0, 2], [0, 3], [0, 4]], "star"),
                                    ("ng-cycle", 5, [[0, 1], [1, 2], [2, 3], [3, 4], [4, 0]], "cycle")]:
        data = _graph(n, edges)
        signature = ref_signature(n, edges)
        out = "out/signature.json"
        correct = _dumps({"kind": "graph_signature", "vertices": n, "signature": signature})
        wrong = _dumps({"kind": "graph_signature", "vertices": n, "signature": ref_signature(n, edges[:-1])})
        wrong_n = _dumps({"kind": "graph_signature", "vertices": n + 1, "signature": signature})
        tasks.append(_num_task(
            task_id, "graph",
            "Compute the canonical structural signature of the simple undirected graph in data/graph.json (a %s on %d vertices) and write it to %s." % (name, n, out),
            [("data/graph.json", data), ("README.md", readme)],
            {"operation": "graph.small_signature", "output_path": out, "units": None, "vertices": n, "signature": signature},
            [("correct", True, {out: correct}), ("wrong_signature", False, {out: wrong}), ("wrong_vertices", False, {out: wrong_n})]))
    return tasks


DOCUMENT_TASKS = _revision_tasks() + _revoked_tasks() + _conflict_tasks()
NUMERICAL_TASKS = _numerical_tasks()
DOMAIN_TASKS = DOCUMENT_TASKS + NUMERICAL_TASKS
DOMAIN_TIERS = ("document", "numerical")


def tasks(tier: str | None = None) -> list:
    return [t for t in DOMAIN_TASKS if tier is None or t.tier == tier]


# ===================================================================== materialization and task specs

_GIT_ENV = dict(GIT_AUTHOR_NAME="corpus", GIT_AUTHOR_EMAIL="corpus@invalid", GIT_COMMITTER_NAME="corpus",
                GIT_COMMITTER_EMAIL="corpus@invalid", GIT_CONFIG_NOSYSTEM="1")


def write_files(root: Path, files: dict) -> None:
    for rel, content in files.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def materialize(task: DomainTask, repo: Path) -> str:
    repo = Path(repo)
    write_files(repo, task.files_map())
    env = dict(os.environ, **_GIT_ENV)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "seed %s" % task.task_id], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def write_oracle(task: DomainTask, directory: Path) -> Path:
    path = Path(directory) / ("oracle_%s.json" % task.task_id)
    path.write_text(json.dumps(task.oracle, indent=1) + "\n")
    return path


def task_spec(task: DomainTask, repo: Path, base_commit: str, oracle_path: Path, provider: dict, budget: dict, **over) -> dict:
    spec = {"domain": task.domain, "goal": task.goal, "repository": str(repo), "base_commit": base_commit, "allowed_paths": list(task.allowed_paths),
            "provider": provider, "budget": budget}
    if task.domain == "document":
        spec["sources"] = [dict(s) for s in task.sources]
        spec["targets"] = list(task.targets)
        spec["checks"] = [{"check_id": "citations", "kind": "document/citations_bound", "independent": True, "role": "acceptance_only"},
                          {"check_id": "claims", "kind": "document/required_claims", "independent": True, "role": "acceptance_only",
                           "oracle_files": [{"path": "oracle/required_claims.json", "source": str(oracle_path)}]}]
    else:
        spec["checks"] = [{"check_id": "reference", "kind": "numerical/reference_contract", "independent": True, "role": "acceptance_only",
                           "oracle_files": [{"path": "oracle/expected.json", "source": str(oracle_path)}]}]
    spec.update(over)
    return spec


# ===================================================================== system-independent verification

def _tree(root: Path) -> dict:
    """Every regular file under root (relative path -> text), ignoring scratch and version control."""
    result = {}
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in IGNORED or part.endswith(".pyc") for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("oracle_") or rel.startswith("oracle/"):
            continue
        try:
            result[rel] = path.read_text()
        except UnicodeDecodeError:
            result[rel] = path.read_bytes().hex()
    return result


def _in_scope(path: str, allowed) -> bool:
    return any(path == a or path.startswith(a.rstrip("/") + "/") for a in allowed)


def changed_paths(task: DomainTask, root: Path) -> list:
    seeded = task.files_map()
    tree = _tree(root)
    return sorted(p for p in set(seeded) | set(tree) if seeded.get(p) != tree.get(p))


def verify_document(task: DomainTask, root: Path) -> dict:
    """Content-based verification against the declared sources: every citation quotes an available
    source verbatim, every required claim is present and cited from the expected source revision
    with its decisive text, no forbidden statement appears, nothing outside the scope changed."""
    tree = _tree(root)
    changed = changed_paths(task, root)
    out_of_scope = [p for p in changed if not _in_scope(p, task.allowed_paths)]
    seeded = task.files_map()
    available = {(s["source_id"], s["revision"]): seeded[s["path"]] for s in task.sources if s["access"] == "available"}
    revoked = {(s["source_id"], s["revision"]): seeded[s["path"]] for s in task.sources if s["access"] != "available"}
    problems, citations_total = [], 0
    for target in task.targets:
        text = tree.get(target)
        if text is None:
            problems.append("%s is absent" % target)
            continue
        citations = parse_citations(text)
        citations_total += len(citations)
        if not citations:
            problems.append("%s carries no citation" % target)
        for cite in citations:
            quote = cite["quote"]
            if not quote.strip():
                problems.append("%s: empty quote" % target)
            elif not any(quote in content for content in available.values()):
                if any(quote in content for content in revoked.values()):
                    problems.append("%s: quote %r is found only in a revoked source" % (target, quote[:60]))
                else:
                    problems.append("%s: quote %r is not a verbatim span of any available source" % (target, quote[:60]))
    claims = []
    for claim in task.oracle["claims"]:
        text = tree.get(claim["path"], "")
        present = any(p in text for p in claim["must_contain"])
        expected = [content for (sid, rev), content in available.items()
                    if sid == claim["cited_source_id"] and (claim.get("cited_source_revision") is None or rev == claim["cited_source_revision"])]
        cited = any(claim["quote_must_include"] in c["quote"] and any(c["quote"] in content for content in expected) for c in parse_citations(text))
        claims.append({"claim": " | ".join(claim["must_contain"])[:120], "present": present, "cited_from_expected_source": cited})
        if not present:
            problems.append("required statement missing: " + claims[-1]["claim"])
        if not cited:
            problems.append("required statement not cited from %s with %r" % (claim["cited_source_id"], claim["quote_must_include"]))
    for rule in task.oracle.get("forbidden", []):
        text = tree.get(rule["path"], "")
        hits = [p for p in rule["must_not_contain"] if p in text]
        if hits:
            problems.append("forbidden statement present in %s: %s" % (rule["path"], ", ".join(hits)))
    verified = not out_of_scope and not problems
    return {"verified": verified, "problems": problems[:32], "changed_paths": changed, "out_of_scope_paths": out_of_scope, "citations": citations_total,
            "claims": claims, "targets": {t: tree.get(t, "")[:8000] for t in task.targets}}


def verify_numerical(task: DomainTask, root: Path) -> dict:
    """The output file at the reference path matches the reference contract; nothing else changed."""
    tree = _tree(root)
    changed = changed_paths(task, root)
    out_of_scope = [p for p in changed if not _in_scope(p, task.allowed_paths)]
    oracle = task.oracle
    problems = []
    text = tree.get(oracle["output_path"])
    output = None
    if text is None:
        problems.append("output %s is absent" % oracle["output_path"])
    else:
        try:
            output = json.loads(text)
        except ValueError:
            problems.append("output is not JSON")
    if isinstance(output, dict):
        if "values" in oracle:
            if output.get("units") != oracle.get("units"):
                problems.append("output units %r differ from the reference %r" % (output.get("units"), oracle.get("units")))
            got = output.get("values")
            expected = oracle["values"]
            tolerance = float(oracle.get("tolerance_micro", 0)) / 1e6
            if not isinstance(got, list) or len(got) != len(expected):
                problems.append("row count %s differs from the reference %d" % (len(got) if isinstance(got, list) else None, len(expected)))
            else:
                worst = 0.0
                for (t_e, v_e), row in zip(expected, got):
                    if not (isinstance(row, list) and len(row) == 2) or row[0] != t_e:
                        problems.append("time stamp %r differs from the reference %r" % (row, t_e))
                        break
                    try:
                        worst = max(worst, abs(float(row[1]) - float(v_e)))
                    except (TypeError, ValueError):
                        problems.append("value %r is not a number" % (row[1],))
                        break
                else:
                    if worst > tolerance:
                        problems.append("maximum deviation %r exceeds tolerance %r" % (worst, tolerance))
        else:
            if output.get("signature") != oracle["signature"]:
                problems.append("signature differs from the reference")
            if output.get("vertices") != oracle.get("vertices"):
                problems.append("vertex count %r differs from the reference %r" % (output.get("vertices"), oracle.get("vertices")))
    elif output is not None:
        problems.append("output is not a JSON object")
    verified = not out_of_scope and not problems
    return {"verified": verified, "problems": problems[:32], "changed_paths": changed, "out_of_scope_paths": out_of_scope,
            "output": (text or "")[:8000]}


def verify(task: DomainTask, root: Path) -> dict:
    return verify_document(task, root) if task.domain == "document" else verify_numerical(task, root)


# ===================================================================== executed corpus invariants

def soundness_check(task: DomainTask) -> dict:
    """Execute the controls: the correct deliverable is verified, every wrong one is not."""
    results = {}
    with tempfile.TemporaryDirectory(prefix="gabriel-domain-corpus-") as directory:
        for name, expected, deliverable in task.controls:
            root = Path(directory) / name
            write_files(root, task.files_map())
            write_files(root, dict(deliverable))
            outcome = verify(task, root)
            results[name] = {"expected_verified": expected, "verified": outcome["verified"], "problems": outcome["problems"][:4]}
    sound = bool(results) and all(r["verified"] == r["expected_verified"] for r in results.values()) \
        and any(r["expected_verified"] for r in results.values()) and any(not r["expected_verified"] for r in results.values())
    return {"task_id": task.task_id, "family": task.family, "tier": task.tier, "sound": sound, "controls": results, "digest": task.digest()}


def check_all(tier: str | None = None) -> list:
    return [soundness_check(task) for task in tasks(tier)]
