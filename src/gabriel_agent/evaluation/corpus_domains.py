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
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..contracts.codec import canonical
from .fixtures import graph_readout as gro
from .fixtures import graph_walk as gwf

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
    tier_name: str = ""         # a tier distinct from the domain (the graph tier runs in the numerical domain)
    history: tuple = ()         # task ids run first in the same workspace with their correct deliverable (ADR-20 association history)
    role: str = "evaluated"     # "evaluated": an evaluation unit; "history": run only as another task's history, never as a unit

    @property
    def tier(self) -> str:
        return self.tier_name or self.domain

    def files_map(self) -> dict:
        return dict(self.files)

    def digest(self) -> str:
        body = {"task_id": self.task_id, "family": self.family, "domain": self.domain, "goal": self.goal, "files": [list(f) for f in self.files],
                "allowed_paths": list(self.allowed_paths), "oracle": self.oracle, "sources": [dict(s) for s in self.sources],
                "targets": list(self.targets), "controls": [[n, v, dict(d)] for n, v, d in self.controls]}
        if self.history or self.role != "evaluated":
            body.update({"history": list(self.history), "role": self.role})
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


def _doc_task(task_id, family, goal, files, sources, target, claims, forbidden, controls, *, tier_name="", history=(), role="evaluated"):
    return DomainTask(task_id=task_id, family=family, domain="document", goal=goal, files=tuple(files), allowed_paths=("doc/",),
                      oracle={"claims": claims, "forbidden": [{"path": target, "must_not_contain": list(forbidden)}] if forbidden else []},
                      sources=tuple(sources), targets=(target,), controls=tuple(controls), tier_name=tier_name, history=tuple(history), role=role)


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
    if kind == "degC_to_degF":
        return [[t, v * 9.0 / 5.0 + 32.0] for t, v in values]
    if kind == "K_to_degF":
        return [[t, (v - 273.15) * 9.0 / 5.0 + 32.0] for t, v in values]
    if kind == "degF_to_K":
        return [[t, (v - 32.0) * 5.0 / 9.0 + 273.15] for t, v in values]
    if kind == "degR_to_K":
        return [[t, v * 5.0 / 9.0] for t, v in values]
    if kind == "km_to_cm":
        return [[t, v * 100000.0] for t, v in values]
    if kind == "min_to_ms":
        return [[t, v * 60000.0] for t, v in values]
    if kind == "m_to_mm":
        return [[t, v * 1000.0] for t, v in values]
    if kind == "m_to_km":
        return [[t, v / 1000.0] for t, v in values]
    if kind == "min_to_s":
        return [[t, v * 60.0] for t, v in values]
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


# ---- numerical decision families (ADR-24): first attempts that fail at a measurable rate with both outcomes.
# `numerical-prerequisite`: the observed input dataset carries a declared contract problem (a reading that is
# not a number, a time stamp that is not an integer, a malformed row, a unit outside the catalogue), so the
# declared worker refuses every job on it and no repair can succeed; the correct deliverable exists (the
# conversion of the valid rows) but needs the input cleaned, which lies outside the admitted scope: a
# documented prerequisite. `numerical-undeclared`: the target unit is declared in a conventions file the
# numerical pack observes as a dataset of unknown kind and never shows the model, so a first attempt that
# guesses the obvious unit fails on the units and the diagnostic names the declared unit: a recoverable
# repair. Held-out topics are declared per family and never used to construct or validate a readout.

PREREQUISITE_README = "# Datasets\n\nSeries files declare their units and time basis as delivered; nothing under data/ may be edited.\n"
UNDECLARED_README = "# Datasets\n\nSeries files declare their units; the reporting conventions are kept in data/conventions.json.\n"


def _prerequisite_convert(task_id, family, src_units, to_units, kind, goal_words, valid_rows, rows):
    out = "out/converted.json"
    expected = ref_convert(valid_rows, kind)
    correct = _dumps({"kind": "series", "units": to_units, "time_basis": "unix_ms", "values": expected})
    wrong_values = _dumps({"kind": "series", "units": to_units, "time_basis": "unix_ms", "values": [[t, v + 1.0] for t, v in expected]})
    return _num_task(
        task_id, family,
        "Convert the series in data/series.json %s using the declared units and write the converted series to %s. Keep the time stamps unchanged." % (goal_words, out),
        [("data/series.json", _series(src_units, rows)), ("README.md", PREREQUISITE_README)],
        {"operation": "units.convert", "output_path": out, "units": to_units, "tolerance_micro": 1, "values": expected},
        [("correct", True, {out: correct}), ("wrong_values", False, {out: wrong_values}),
         ("input_edited", False, {out: correct, "data/series.json": _series(to_units, expected)})])  # converting the input in place is out of scope


def _prerequisite_resample(task_id, family, bucket, valid_rows, rows):
    out = "out/resampled.json"
    expected = ref_resample(valid_rows, bucket)
    correct = _dumps({"kind": "series", "units": "degC", "time_basis": "unix_ms", "values": expected})
    wrong_values = _dumps({"kind": "series", "units": "degC", "time_basis": "unix_ms", "values": [[t, v * 2.0] for t, v in expected]})
    return _num_task(
        task_id, family,
        "Resample the series in data/series.json to the arithmetic mean per bucket of %d milliseconds on its unix_ms time basis (empty buckets omitted) "
        "and write the result to %s." % (bucket, out),
        [("data/series.json", _series("degC", rows)), ("README.md", PREREQUISITE_README)],
        {"operation": "series.resample_mean", "output_path": out, "units": "degC", "tolerance_micro": 1, "values": expected},
        [("correct", True, {out: correct}), ("wrong_values", False, {out: wrong_values}),
         ("input_edited", False, {out: correct, "data/series.json": _series("degC", valid_rows)})])


def _undeclared(task_id, family, src_units, declared_units, kind, obvious_units, obvious_kind, values):
    out = "out/converted.json"
    expected = ref_convert(values, kind)
    conventions = json.dumps({"reporting": {"units": declared_units, "note": "every reported series is converted to the reporting unit before publication"}}, indent=1) + "\n"
    correct = _dumps({"kind": "series", "units": declared_units, "time_basis": "unix_ms", "values": expected})
    obvious = _dumps({"kind": "series", "units": obvious_units, "time_basis": "unix_ms", "values": ref_convert(values, obvious_kind)})
    dimension = {"degC": "temperatures", "degF": "temperatures", "K": "temperatures", "km": "lengths", "m": "lengths", "min": "durations"}[src_units]
    # amendment after the protocol 10 pilot (evidence/wp17/protocol10_declaration.md): the goal names the two admissible
    # units of the dimension, the obvious one first; which applies stays in the conventions file the pack never shows
    return _num_task(
        task_id, family,
        "Convert the series in data/series.json to the reporting unit declared in data/conventions.json (field reporting.units; the conventions admit "
        "%s or %s for %s) and write the converted series to %s. Keep the time stamps unchanged." % (obvious_units, declared_units, dimension, out),
        [("data/series.json", _series(src_units, values)), ("data/conventions.json", conventions), ("README.md", UNDECLARED_README)],
        {"operation": "units.convert", "output_path": out, "units": declared_units, "tolerance_micro": 1, "values": expected},
        [("correct", True, {out: correct}), ("obvious_guess", False, {out: obvious}), ("wrong_path", False, {"out/other.json": correct})])


def _numerical_decision_tasks():
    tasks = []
    # prerequisite family: three seen topics, two held out
    celsius = [[0, 20.0], [1000, 21.5], [2000, 19.25], [3500, 22.0], [4000, -3.5]]
    tasks.append(_prerequisite_convert("np-null", "numerical-prerequisite", "degC", "K", "degC_to_K", "from degrees Celsius to kelvin",
                                       celsius, celsius[:2] + [[2000, None]] + celsius[3:]))
    seconds = [[0, 1.0], [250, 3.0], [900, 2.0], [1000, 4.0], [1500, 6.0], [3100, 10.0]]
    tasks.append(_prerequisite_resample("np-stamp", "numerical-prerequisite", 1000, seconds, seconds[:4] + [[1500.5, 6.0]] + seconds[5:]))
    kilometres = [[0, 1.5], [60000, 2.25], [120000, 0.4], [180000, 10.0]]
    tasks.append(_prerequisite_convert("np-pair", "numerical-prerequisite", "km", "m", "km_to_m", "from kilometres to metres",
                                       kilometres, kilometres[:2] + [[120000]] + kilometres[3:]))
    fahrenheit = [[0, 32.0], [600, 212.0], [1200, 98.6], [1800, -40.0], [2400, 50.0]]
    tasks.append(_prerequisite_convert("np-text", "numerical-prerequisite-held-out", "degF", "degC", "degF_to_degC", "from degrees Fahrenheit to degrees Celsius",
                                       fahrenheit, fahrenheit[:2] + [[1200, "98.6"]] + fahrenheit[3:]))
    rankine = [[0, 491.67], [1000, 527.67], [2000, 459.67], [3000, 671.67]]
    tasks.append(_prerequisite_convert("np-rankine", "numerical-prerequisite-held-out", "degR", "K", "degR_to_K", "from degrees Rankine to kelvin", rankine, rankine))
    # undeclared family: three seen topics, two held out; the obvious guess is the other unit of the dimension
    tasks.append(_undeclared("nd-fahrenheit", "numerical-undeclared", "degC", "degF", "degC_to_degF", "K", "degC_to_K", celsius))
    tasks.append(_undeclared("nd-centimetres", "numerical-undeclared", "km", "cm", "km_to_cm", "m", "km_to_m", kilometres))
    minutes = [[0, 1.5], [60000, 12.0], [120000, 0.25], [180000, 90.0]]
    tasks.append(_undeclared("nd-millis", "numerical-undeclared", "min", "ms", "min_to_ms", "s", "min_to_s", minutes))
    tasks.append(_undeclared("nd-kelvin", "numerical-undeclared-held-out", "degF", "K", "degF_to_K", "degC", "degF_to_degC", fahrenheit))
    metres = [[0, 1.5], [60000, 2.25], [120000, 0.4], [180000, 10.0]]
    tasks.append(_undeclared("nd-millimetres", "numerical-undeclared-held-out", "m", "mm", "m_to_mm", "km", "m_to_km", metres))
    return tasks


# ===================================================================== graph tier (native PSE worker, ADR-18; references independent of the engine)

RING = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 0]]
RING_SOURCE = [(0, 1.0, 0.0), (1, 0.0, 0.0), (2, 0.0, 0.0), (3, 0.0, 0.0), (4, 0.0, 0.0)]


def _graph_task(task_id, family, goal, files, oracle, controls):
    return DomainTask(task_id=task_id, family=family, domain="numerical", goal=goal, files=tuple(files), allowed_paths=("out/",), oracle=oracle,
                      controls=tuple(controls), tier_name="graph")


def _mass_values(rows):
    return [{"time_bits": t, "mass_bits": gwf.bits(m), "decision": d} for t, m, d in rows]


def _graph_tasks():
    """Snapshot identities, regional masses and window certificates of the native graph engine; the
    references are the reconstruction of the declared construction rule, a standard-library
    spectral decomposition and the closed-form harmonic model of a uniform clique."""
    tasks = []
    readme = "# Observation batches\n\nEntities co-observed per batch; queries declare source, targets, times, thresholds and windows as binary64 bits.\n"
    for task_id, batches, name in [("gs-mixed", gwf.BATCHES, "mixed"), ("gs-ring", RING, "ring")]:
        data = gwf.text(gwf.batches_dataset(batches))
        identity, order = gwf.reference_identity(batches), gwf.vertex_order(batches)
        out = "out/snapshot.json"
        vertices = [{"entity": e, "vertex_id": str(gwf.sensor_vertex_id(e))} for e in order]
        correct = _dumps({"kind": "graph_snapshot", "snapshot": {"identity": identity, "vertices": vertices}})
        wrong_identity = _dumps({"kind": "graph_snapshot", "snapshot": {"identity": gwf.reference_identity(batches[:-1]), "vertices": vertices}})
        wrong_vertices = _dumps({"kind": "graph_snapshot", "snapshot": {"identity": identity, "vertices": vertices[:-1]}})
        tasks.append(_graph_task(
            task_id, "graph-snapshot",
            "Condition the native graph engine on the observation batches in data/batches.json (%s history of %d entities) and write its conditioned "
            "snapshot (identity, vertices, walk backend, engine statistics) to %s." % (name, len(order), out),
            [("data/batches.json", data), ("README.md", readme)],
            {"operation": "graph.snapshot", "output_path": out, "units": None, "identity": identity, "vertices": len(order)},
            [("correct", True, {out: correct}), ("wrong_identity", False, {out: wrong_identity}), ("wrong_vertices", False, {out: wrong_vertices}),
             ("wrong_path", False, {"out/other.json": correct})]))
    for task_id, batches, source, targets, times, threshold, deadband, name in [
            ("gm-mixed", gwf.BATCHES, gwf.SOURCE, gwf.TARGETS, gwf.TIMES, 0.2, 0.01, "mixed"),
            ("gm-ring", RING, RING_SOURCE, [2, 3], [0.5, 1.0, 1.5, 3.0], 0.3, 0.02, "ring")]:
        data = gwf.text(gwf.query_dataset(batches=batches, source=source, targets=targets, times=times, threshold=threshold, deadband=deadband))
        rows = gwf.reference_mass_rows(batches, source, targets, times, threshold, deadband)
        out = "out/mass.json"
        correct = _dumps({"kind": "region_mass", "values": _mass_values(rows)})
        wrong_mass = _dumps({"kind": "region_mass", "values": _mass_values([[t, m + 1e-3, d] for t, m, d in rows])})
        wrong_decision = _dumps({"kind": "region_mass", "values": _mass_values([[t, m, "ambiguous" if d != "ambiguous" else "below"] for t, m, d in rows])})
        wrong_time = _dumps({"kind": "region_mass", "values": _mass_values([[gwf.bits(gwf.number(t) + 1.0), m, d] for t, m, d in rows])})
        tasks.append(_graph_task(
            task_id, "graph-mass",
            "Read out the regional mass of the source-conditioned walk declared in data/query.json (%s history) at its declared times with its "
            "threshold and deadband rule and write the result to %s." % (name, out),
            [("data/query.json", data), ("README.md", readme)],
            {"operation": "graph.region_mass", "output_path": out, "units": None, "tolerance_micro": 1, "masses": rows},
            [("correct", True, {out: correct}), ("wrong_mass", False, {out: wrong_mass}), ("wrong_decision", False, {out: wrong_decision}),
             ("wrong_time", False, {out: wrong_time})]))
    # readout and detection families (ADR-19): the specified readout and its admitted gate crossings
    readme_stream = "# Declared observation streams\n\nEach observation declares entity, phase in [0, 2pi) and amplitude in [0, 1] as binary64 bits; the profile declares carriers, coherence parameters, normalization and thresholds.\n"
    ring_stream = [[(0, 0.3, 0.9), (1, 0.4, 0.9)], [(1, 0.4, 0.9), (2, 0.5, 0.9)], [(2, 0.5, 0.9), (3, 0.6, 0.9)], [(3, 0.6, 0.9), (4, 0.7, 0.9)],
                   [(4, 0.7, 0.9), (0, 0.3, 0.9)], [(0, 0.3, 0.9), (2, 0.5, 0.9), (4, 0.7, 0.9)]]
    for task_id, stream, prof, name in [("gr-fixture", gro.STREAM, gro.profile(), "four-entity"), ("gr-ring", ring_stream, gro.profile(carriers=2, adaptive_carrier=False), "ring")]:
        data = gro.text(gro.stream_dataset(stream, prof))
        oracle = gro.readout_oracle(stream, prof)
        out = "out/readout.json"
        def deliverable(steps, kairos_flip=False, metric_shift=0.0, drop_vertex=False):
            ticks = []
            for s in steps:
                ticks.append({"tick": s["tick"], "vertices": s["vertices"][:-1] if drop_vertex else s["vertices"], "edges": s["edges"],
                              "carrier": {"index": s["admissible_carriers"][0]}, "kairos": (not s["kairos"]) if kairos_flip else s["kairos"],
                              "metrics": {k: gwf.bits(v + metric_shift) for k, v in s["metrics"].items()}})
            return _dumps({"kind": "state_readout", "ticks": ticks})
        correct = deliverable(oracle["readout"])
        tasks.append(_graph_task(
            task_id, "graph-readout",
            "Run the native engine's specified state readout over the declared observation stream in data/stream.json (%s stream: embedding, data helix, "
            "active carrier, gate metrics and gate verdict per step) and write it to %s." % (name, out),
            [("data/stream.json", data), ("README.md", readme_stream)], oracle,
            [("correct", True, {out: correct}), ("wrong_metric", False, {out: deliverable(oracle["readout"], metric_shift=1e-3)}),
             ("wrong_kairos", False, {out: deliverable(oracle["readout"], kairos_flip=True)}), ("wrong_vertices", False, {out: deliverable(oracle["readout"], drop_vertex=True)})]))
    for task_id, stream, prof, schedule, name in [("gd-fixture", gro.STREAM, gro.profile(), gro.SCHEDULE, "four-entity"),
                                                  ("gd-none", gro.STREAM, gro.profile(), gro.no_detection_schedule(), "four-entity, nothing admitted")]:
        data = gro.text(gro.detection_dataset(stream, prof, schedule))
        oracle = gro.detections_oracle(stream, prof, schedule)
        out = "out/detections.json"
        ticks, vertices = oracle["detection_ticks"], oracle["detection_vertices"]
        correct = _dumps({"kind": "detections", "detections": [{"tick": t, "vertices": v} for t, v in zip(ticks, vertices)]})
        spurious = _dumps({"kind": "detections", "detections": [{"tick": t, "vertices": v} for t, v in zip(ticks, vertices)] + [{"tick": 2, "vertices": [0, 1, 2, 3]}]})
        controls = [("correct", True, {out: correct}), ("spurious_detection", False, {out: spurious}), ("wrong_path", False, {"out/other.json": correct})]
        if ticks:
            controls.append(("missing_detection", False, {out: _dumps({"kind": "detections", "detections": [{"tick": t, "vertices": v} for t, v in zip(ticks[1:], vertices[1:])]})}))
        tasks.append(_graph_task(
            task_id, "graph-detections",
            "Compute the detections of the declared observation stream in data/detection_query.json (%s) under its thresholds and schedule and write them to %s." % (name, out),
            [("data/detection_query.json", data), ("README.md", readme_stream)], oracle, controls))
    for task_id, threshold in [("gw-clique", 0.2), ("gw-clique-low", 0.1)]:
        data = gwf.text(gwf.window_dataset(threshold=threshold))
        statuses = gwf.reference_window_statuses(threshold=threshold)
        out = "out/window.json"
        correct = _dumps({"kind": "window_reachability", "stage": "certified", "statuses": statuses})
        wrong_status = _dumps({"kind": "window_reachability", "stage": "certified", "statuses": [("excluded" if s == "reachable" else "reachable") for s in statuses]})
        uncertified = _dumps({"kind": "window_reachability", "stage": "snapshot", "statuses": statuses})
        tasks.append(_graph_task(
            task_id, "graph-window",
            "Certify, for every closed window declared in data/window.json (a four-clique history, threshold %s), whether the regional mass of the "
            "declared walk exceeds the threshold somewhere in the window, and write the certificates to %s." % (threshold, out),
            [("data/window.json", data), ("README.md", readme)],
            {"operation": "graph.window_reachability", "output_path": out, "units": None, "statuses": statuses},
            [("correct", True, {out: correct}), ("wrong_status", False, {out: wrong_status}), ("uncertified", False, {out: uncertified})]))
    return tasks


# ===================================================================== association tier (ADR-20: the associative memory layer)
#
# The evaluated task needs a source whose words share no token with the goal (not even a stop
# word), so a budgeted lexical retrieval never carries it; thirty-six scored distractors fill the
# budget. The history task, run first in the same workspace with its correct deliverable, cites
# the visible and the hidden source together; a verified run records that as a supported claim,
# and the associative view's walk from the visible source carries the hidden one into the prompt.
#
# Precondition, executed at construction under the memory service's own scorer
# (`_assert_ranking`): for every evaluated goal the visible source scores strictly above every
# distractor, every distractor scores above zero, and the hidden source scores zero. Protocol 6
# (evidence/wp15/run6) was run before this invariant existed, with distractors that named the
# visible source's subject ("The statute states that the committee meets ..."): they tied with
# the visible source under the scorer in three of five topics, the tie-break by observation id
# then dropped the visible source itself below the budget in most workspaces, and the walk had no
# seed. The run is retained; the distractors were changed and the invariant added afterwards
# (evidence/wp15/protocol6_declaration.md, amendment).

ASSOCIATION_DISTRACTORS = 36
ASSOCIATION_README = "# Documents\n\nThe main document, its annex and the committee notes.\n"


def _association_distractor(index: int) -> str:
    """A scored distractor: it shares the goal's function words (so it outranks the hidden source
    and fills the budget) but names no subject of any source and never ties with a visible one."""
    return ("# Note %d\n\nMinutes of the committee meeting held on the %s Tuesday: quorum reached, no resolutions.\n"
            % (index, ("first", "second", "third", "fourth")[index % 4]))


def _association_goal(target: str, ask: str) -> str:
    return ("Amend %s so that it states %s. Every statement must be followed by a citation of the exact source span that supports it. "
            "Do not change the sources." % (target, ask))


ASSOCIATION_TOPICS = [
    # name, visible source (id, subject word, text, quote, phrasings), hidden source (id, text, quote, phrasings), evaluated ask, history ask
    ("fee", ("charter", "charter", "# Club charter\n\n## Membership fee\n\nEach member pays a yearly contribution; the amount is fixed in the annex of this charter.\n",
             "fixed in the annex", ["annex"]),
     ("annex", "# Annex\n\nOrdinary contributions: one hundred twenty (120) EUR, payable within January.\n", "one hundred twenty (120) EUR", ["120 EUR", "120"]),
     "what the charter says about the membership fee and the amount a member pays each year",
     "the yearly contribution rule of the charter and, from the annex, the ordinary contributions of one hundred twenty EUR payable within January"),
    ("parking", ("handbook", "handbook", "# Site handbook\n\n## Parking\n\nVehicles of members are parked according to the plan in the appendix of this handbook.\n",
                 "according to the plan in the appendix", ["appendix"]),
     ("appendix", "# Appendix\n\nBays twelve through thirty: blocked, supplier vans only, midday deadline.\n", "Bays twelve through thirty", ["twelve through thirty", "12 through 30", "bays 12"]),
     "the handbook's parking rule and which spaces are reserved and the time limit",
     "the parking rule of the handbook and, from the appendix, bays twelve through thirty blocked for supplier vans with a midday deadline"),
    ("archive", ("statute", "statute", "# Archive statute\n\n## Retention\n\nRecords of the society are retained for the period named in the schedule of this statute.\n",
                 "the period named in the schedule", ["schedule"]),
     ("schedule", "# Schedule\n\nLedgers: eleven calendar years, shredding afterwards.\n", "eleven calendar years", ["eleven", "11 years", "eleven years"]),
     "the statute's retention rule and how long the records are kept",
     "the retention rule of the statute and, from the schedule, ledgers kept eleven calendar years with shredding afterwards"),
    ("library", ("bylaws", "bylaws", "# Library bylaws\n\n## Loans\n\nBooks are lent to members under the terms of the loan table of these bylaws.\n",
                 "the terms of the loan table", ["loan table"]),
     ("table", "# Loan table\n\nNovels: twenty-one days, renewable twice.\n", "twenty-one days", ["twenty-one days", "21 days"]),
     "the bylaws' lending rule for books and how long a member may keep them",
     "the lending rule of the bylaws and, from the loan table, novels twenty-one days renewable twice"),
    ("garden", ("agreement", "agreement", "# Garden agreement\n\n## Plots\n\nPlots are allocated to members as listed in the register of this agreement.\n",
                "as listed in the register", ["register"]),
     ("register", "# Register\n\nAllotments: forty square metres each; hedge trimming before October.\n", "forty square metres", ["forty square metres", "40 square metres", "40 m"]),
     "the agreement's allocation rule for plots and how large a plot is",
     "the allocation rule of the agreement and, from the register, plots of forty square metres with hedges trimmed by October"),
]


def _association_files(topic, with_distractors=True) -> list:
    name, (vid, subject, vtext, _, _), (hid, htext, _, _), _, _ = topic
    files = [("sources/%s.md" % vid, vtext), ("sources/%s.md" % hid, htext), ("README.md", ASSOCIATION_README),
             ("doc/notes.md", "# Notes\n\n(to be completed)\n"), ("doc/summary.md", "# Summary\n\n(to be completed)\n")]
    if with_distractors:
        files += [("sources/note-%02d.md" % i, _association_distractor(i)) for i in range(ASSOCIATION_DISTRACTORS)]
    return files


def _association_sources(topic, with_distractors=True) -> list:
    name, (vid, _, _, _, _), (hid, _, _, _), _, _ = topic
    out = [_src("sources/%s.md" % vid, vid), _src("sources/%s.md" % hid, hid)]
    if with_distractors:
        out += [_src("sources/note-%02d.md" % i, "note%02d" % i) for i in range(ASSOCIATION_DISTRACTORS)]
    return out


def _assert_hidden(goal: str, hidden_text: str, visible_text: str) -> None:
    """The hidden source shares no token with the goal; the visible one shares several."""
    from ..memory.service import _tokens
    goal_tokens = set(_tokens(goal.encode("utf8")))
    hidden_tokens = set(_tokens(hidden_text.encode("utf8")))
    if goal_tokens & hidden_tokens:
        raise ValueError("hidden source shares tokens with the goal: %s" % sorted(goal_tokens & hidden_tokens))
    if len(goal_tokens & set(_tokens(visible_text.encode("utf8")))) < 4:
        raise ValueError("visible source shares too few tokens with the goal")


def association_scores(goal: str, texts: dict) -> dict:
    """Lexical score in milli of every text for the goal under the memory service's own scorer."""
    from ..memory.service import MemoryService, _tokens
    query_tokens = set(_tokens(goal.encode("utf8")))
    return {name: MemoryService._best_span(text.encode("utf8"), query_tokens)[2] for name, text in texts.items()}


def _assert_ranking(goal: str, visible_text: str, hidden_text: str, distractors: list) -> None:
    """Under the memory service's scorer the visible source outranks every distractor strictly and
    every distractor outranks the hidden source strictly: a budgeted lexical retrieval keeps the
    visible source (and seeds the walk with it) and drops the hidden one, whatever the tie-break.
    (`_assert_hidden` adds, for the needed goal, that the hidden source shares no token at all.)"""
    scores = association_scores(goal, {"visible": visible_text, "hidden": hidden_text, **{"note%02d" % i: d for i, d in enumerate(distractors)}})
    notes = [scores["note%02d" % i] for i in range(len(distractors))]
    if not notes or min(notes) < 1:
        raise ValueError("a distractor scores zero for the goal: %s" % goal)
    if scores["visible"] <= max(notes):
        raise ValueError("visible source (%d) does not outrank the distractors (%d) for the goal: %s" % (scores["visible"], max(notes), goal))
    if scores["hidden"] >= min(notes):
        raise ValueError("hidden source (%d) is not below every distractor (%d) for the goal: %s" % (scores["hidden"], min(notes), goal))


def _association_tasks():
    tasks = []
    for index, topic in enumerate(ASSOCIATION_TOPICS):
        name, (vid, subject, vtext, vquote, vphr), (hid, htext, hquote, hphr), ask, history_ask = topic
        files_full, files_small = _association_files(topic, True), _association_files(topic, False)
        goal = _association_goal("doc/summary.md", ask)
        distractors = [_association_distractor(i) for i in range(ASSOCIATION_DISTRACTORS)]
        _assert_hidden(goal, htext, vtext)
        _assert_ranking(goal, vtext, htext, distractors)
        history_goal = _association_goal("doc/notes.md", history_ask)
        if min(association_scores(history_goal, {"visible": vtext, "hidden": htext}).values()) < 1:
            raise ValueError("the history goal does not reach both sources lexically: " + history_goal)
        correct_notes = ("# Notes\n\nThe %s: %s. %s\n\nFrom the %s: %s. %s\n" % (vid, vquote, _cite(vid, vquote), hid, hquote, _cite(hid, hquote)))
        correct_summary = ("# Summary\n\nThe %s: %s. %s\n\nThe %s: %s. %s\n" % (vid, vquote, _cite(vid, vquote), hid, hquote, _cite(hid, hquote)))
        visible_only = "# Summary\n\nThe %s: %s. %s\n" % (vid, vquote, _cite(vid, vquote))
        uncited = "# Summary\n\nThe %s: %s.\n\nThe %s: %s.\n" % (vid, vquote, hid, hquote)
        claims = [_claim("doc/summary.md", vphr, vid, vquote), _claim("doc/summary.md", hphr, hid, hquote)]
        history_claims = [_claim("doc/notes.md", vphr, vid, vquote), _claim("doc/notes.md", hphr, hid, hquote)]
        history_id = "dh-" + name
        # the history task (never a unit): its goal reaches both sources lexically
        tasks.append(_doc_task(history_id, "association-history", history_goal, files_small, _association_sources(topic, False), "doc/notes.md", history_claims, [],
                               [("correct", True, {"doc/notes.md": correct_notes}), ("uncited", False, {"doc/notes.md": "# Notes\n\nThe %s: %s.\n" % (vid, vquote)})],
                               tier_name="association", role="history"))
        # needed: the hidden source is required; seen families use the first three topics, the held-out family the last two
        family = "association-needed" if index < 3 else "association-needed-held-out"
        tasks.append(_doc_task("da-" + name, family, goal, files_full, _association_sources(topic, True), "doc/summary.md", claims, [],
                               [("correct", True, {"doc/summary.md": correct_summary}), ("visible_only", False, {"doc/summary.md": visible_only}),
                                ("uncited", False, {"doc/summary.md": uncited}), ("source_edited", False, {"doc/summary.md": correct_summary, "sources/%s.md" % hid: htext + "\nEdited.\n"})],
                               tier_name="association", history=(history_id,)))
        # cold (ADR-22): the needed task without any history, so no view can carry the hidden source under the
        # budget and every repair is hopeless; the policy route's negative class, seen and held out alike
        tasks.append(_doc_task("dc-" + name, "association-needed-cold" if index < 3 else "association-needed-cold-held-out", goal, files_full,
                               _association_sources(topic, True), "doc/summary.md", claims, [],
                               [("correct", True, {"doc/summary.md": correct_summary}), ("visible_only", False, {"doc/summary.md": visible_only}),
                                ("uncited", False, {"doc/summary.md": uncited})], tier_name="association"))
        # unneeded: the same history, but the evaluated goal needs the visible source only and the hidden figure is not to be stated
        ask_visible = "the %s's rule only, as written in the %s" % (vid, vid)
        goal_u = _association_goal("doc/summary.md", ask_visible)
        _assert_ranking(goal_u, vtext, htext, distractors)
        tasks.append(_doc_task("du-" + name, "association-unneeded" if index < 3 else "association-unneeded-held-out", goal_u, files_full,
                               _association_sources(topic, True), "doc/summary.md", [_claim("doc/summary.md", vphr, vid, vquote)], hphr,
                               [("correct", True, {"doc/summary.md": visible_only}), ("hidden_stated", False, {"doc/summary.md": correct_summary}),
                                ("uncited", False, {"doc/summary.md": "# Summary\n\nThe %s: %s.\n" % (vid, vquote)})],
                               tier_name="association", history=(history_id,)))
        if index < 2:
            # none: no history and no budget pressure (two sources only); both views reach the hidden source
            tasks.append(_doc_task("dn-" + name, "association-none", goal, files_small, _association_sources(topic, False), "doc/summary.md", claims, [],
                                   [("correct", True, {"doc/summary.md": correct_summary}), ("visible_only", False, {"doc/summary.md": visible_only}),
                                    ("uncited", False, {"doc/summary.md": uncited})], tier_name="association"))
    return tasks


def history_worker_steps(task: DomainTask) -> list:
    """The scripted worker that produces a history task's correct deliverable through the real run:
    the control's content with the control citations resolved to the prompt's observation ids."""
    correct = next(deliverable for name, expected, deliverable in task.controls if name == "correct")
    steps = []
    for target in task.targets:
        content = re.sub(r"obs-control-([A-Za-z0-9_-]+)", r"{{obs:\1}}", correct[target])
        steps.append({"kind": "template", "value": {"operations": [{"kind": "modify", "path": target, "expected_sha256": "{{sha:%s}}" % target, "content": content}],
                                                    "rationale": "history deliverable of " + task.task_id}})
    return steps


def task_named(task_id: str) -> DomainTask:
    return next(t for t in DOMAIN_TASKS if t.task_id == task_id)


def describe_problems(task: DomainTask) -> list:
    """The contract problems the numerical pack's observe step reports for the task's series dataset
    (ADR-24: the prerequisite family carries one by construction, the undeclared family none)."""
    from ..adapters import analytical
    return list(analytical.describe(task.files_map()["data/series.json"].encode("utf8"))["problems"])


DOCUMENT_TASKS = _revision_tasks() + _revoked_tasks() + _conflict_tasks()
NUMERICAL_TASKS = _numerical_tasks() + _numerical_decision_tasks()
GRAPH_TASKS = _graph_tasks()
ASSOCIATION_TASKS = _association_tasks()
DOMAIN_TASKS = DOCUMENT_TASKS + NUMERICAL_TASKS + GRAPH_TASKS + ASSOCIATION_TASKS
DOMAIN_TIERS = ("document", "numerical", "graph", "association")


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
        if "identity" in oracle:
            snapshot = output.get("snapshot") if isinstance(output.get("snapshot"), dict) else {}
            vertices = snapshot.get("vertices")
            if snapshot.get("identity") != oracle["identity"]:
                problems.append("snapshot identity differs from the reference")
            if not isinstance(vertices, list) or len(vertices) != oracle.get("vertices"):
                problems.append("vertex count differs from the reference %r" % (oracle.get("vertices"),))
        elif "masses" in oracle:
            got, expected = output.get("values"), oracle["masses"]
            tolerance = float(oracle.get("tolerance_micro", 0)) / 1e6
            if not isinstance(got, list) or len(got) != len(expected):
                problems.append("row count %s differs from the reference %d" % (len(got) if isinstance(got, list) else None, len(expected)))
            else:
                worst = 0.0
                for (t_e, m_e, d_e), item in zip(expected, got):
                    if not isinstance(item, dict) or item.get("time_bits") != t_e:
                        problems.append("time differs from the reference %r" % (t_e,))
                        break
                    try:
                        mass = struct.unpack(">d", bytes.fromhex(item.get("mass_bits")))[0]
                    except (TypeError, ValueError):
                        problems.append("mass at %s is not a binary64 bit string" % t_e)
                        break
                    worst = max(worst, abs(mass - float(m_e)))
                    if item.get("decision") != d_e:
                        problems.append("decision %r differs from the reference %r at %s" % (item.get("decision"), d_e, t_e))
                        break
                else:
                    if worst > tolerance:
                        problems.append("maximum mass deviation %r exceeds tolerance %r" % (worst, tolerance))
        elif "statuses" in oracle:
            if output.get("statuses") != oracle["statuses"]:
                problems.append("certificate statuses differ from the reference")
            if output.get("stage") != "certified":
                problems.append("output is not a certified result")
        elif "readout" in oracle:
            got, expected = output.get("ticks"), oracle["readout"]
            tolerance = float(oracle.get("tolerance_micro", 0)) / 1e6
            if output.get("kind") != "state_readout" or not isinstance(got, list) or len(got) != len(expected):
                problems.append("readout kind or step count differs from the reference")
            else:
                worst = 0.0
                for item, ref in zip(got, expected):
                    if not isinstance(item, dict) or item.get("tick") != ref["tick"] or item.get("vertices") != ref["vertices"] or item.get("edges") != ref["edges"]:
                        problems.append("step structure differs from the reference at tick %r" % (ref["tick"],))
                        break
                    if item.get("kairos") is not ref["kairos"]:
                        problems.append("gate verdict differs from the reference at tick %r" % (ref["tick"],))
                        break
                    if not isinstance(item.get("carrier"), dict) or item["carrier"].get("index") not in ref["admissible_carriers"]:
                        problems.append("active carrier is not admissible at tick %r" % (ref["tick"],))
                        break
                    try:
                        worst = max(worst, max(abs(struct.unpack(">d", bytes.fromhex(item["metrics"][name]))[0] - float(ref["metrics"][name])) for name in ref["metrics"]))
                    except (TypeError, ValueError, KeyError):
                        problems.append("metrics at tick %r are not binary64 bit strings" % (ref["tick"],))
                        break
                else:
                    if worst > tolerance:
                        problems.append("maximum metric deviation %r exceeds tolerance %r" % (worst, tolerance))
        elif "detection_ticks" in oracle:
            found = output.get("detections")
            ticks = [d.get("tick") for d in found] if isinstance(found, list) and all(isinstance(d, dict) for d in found) else None
            if output.get("kind") != "detections" or ticks != oracle["detection_ticks"]:
                problems.append("detections differ from the reference")
            elif "detection_vertices" in oracle and [d.get("vertices") for d in found] != oracle["detection_vertices"]:
                problems.append("detection vertices differ from the reference")
        elif "values" in oracle:
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
