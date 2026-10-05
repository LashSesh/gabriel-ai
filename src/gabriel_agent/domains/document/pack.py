"""Document DomainPack (WP10): source-grounded document amendment.

Observe: every declared source becomes a versioned observation in the memory service (source
identity, revision, event kind and interval, extraction identity); the snapshot retains the
frontier at which the sources were available and an as-of retrieval manifest. Propose: the
model amends the target document and binds every statement to a cited span with
``[[cite:<observation_id> "exact quote"]]``. Execute: file operations inside the admitted
scope (the sources are never editable). Read-back: fresh observation. Verify: the citation
binding verifier resolves every cited reference through the memory service at the observed
frontier (exists, available, not revoked, quote present) and the independent required-claims
oracle, kept outside the repository, decides whether the amendment states what was asked with
the right sources. A syntactically valid citation alone is insufficient (R10).
"""
from __future__ import annotations

import hashlib
import re

from pathlib import Path

from ...contracts.codec import canonical, dumps_utf8, loads, sha256_hex
from ...contracts.errors import Code, GabrielError
from ...contracts.schemas import validate
from ...memory import Frontier, association
from ...models import ModelGenerateTool
from ...tools import fs
from ...workers.supervisor import ToolOutcome
from ..base import DomainPack, compile_generic, descriptor
from ..software.pack import (PROMPT_SOURCE_BUDGET, ApplyPatchTool, BaseCommitPinnedVerifier, ChecksIntactVerifier, DiffInScopeVerifier,
                             NoSecretsVerifier, OutputValidVerifier, ReviewTool, _record, _retain_sources, normalize_patch_proposal)

NAMESPACE = "document"
PACK_ID = "document-amendment"
PACK_VERSION = "0.1.0"
EXTRACTION_PROFILE = "text-utf8-v1"
# ADR-20/21: views that re-rank the provenance view by the engine's walk; `associative` tells carried
# sources apart in the prompt, `associative_unlabeled` is the declared ablation of that presentation
ASSOCIATIVE_VIEWS = ("associative", "associative_unlabeled")
# ADR-21: the default view since protocol 7 met its declared rules (evidence/wp15/run7); without history
# or executables the associative view ranks exactly like the provenance view and the manifest says so
DEFAULT_VIEW = "associative"
# ADR-22: the pack's declared progress channels for the policy route, in declared order
PROGRESS_SCHEMA_ID = "document-progress-v1"
PROGRESS_CHANNELS = ("required_missing", "required_uncited", "forbidden_present", "expected_source_absent", "citations_unbound", "carried_sources")
EXTRACTION_DIGEST = hashlib.sha256(b"gabriel.document.extraction/text-utf8-v1").hexdigest()
TRANSFORM_PROFILE = "document-compile-v1"
SUPPORTED_KINDS = {"document/citations_bound": "document.citations_bound", "document/required_claims": "document.required_claims",
                   "document/diff_in_scope": "document.diff_in_scope", "document/base_commit_pinned": "document.base_commit_pinned",
                   "document/checks_intact": "document.checks_intact", "document/no_secrets": "document.no_secrets", "owner/output_valid": "document.output_valid"}
STRUCTURAL = [("scope", "document/diff_in_scope"), ("base-commit", "document/base_commit_pinned"),
              ("checks-intact", "document/checks_intact"), ("no-secrets", "document/no_secrets")]
OUTPUT_SLOTS = {"document.observe": ["snapshot"], "document.apply_amendment": ["apply_report"], "document.read_back": ["snapshot", "read_back"],
                "document.review": ["review", "patch", "citations"], "model.generate": ["model_output", "raw_response", "request", "envelope"]}
RETRY_CLASS = {"document.observe": "read_retry", "document.apply_amendment": "reconcile_before_retry", "document.read_back": "read_retry",
               "document.review": "read_retry", "model.generate": "target_idempotent_retry"}
CITATION = re.compile(r'\[\[cite:([A-Za-z0-9][A-Za-z0-9._:-]{0,127}) "((?:[^"\\]|\\.)*)"\]\]')


def parse_citations(text: str) -> list:
    return [{"observation_id": m.group(1), "quote": m.group(2).replace('\\"', '"')} for m in CITATION.finditer(text)]


# ===================================================================== compile port

def compile_task(spec: dict, store, **ids):
    sources = spec.get("sources") or []
    targets = spec.get("targets") or []
    if not sources or not targets:
        raise GabrielError(Code.INVALID_SCHEMA, "a document task declares at least one source and one target")
    declaration = {"schema": "gabriel.document-sources/1",
                   "sources": [{"path": s["path"], "source_id": s["source_id"], "source_revision": int(s.get("revision", 1)),
                                "event_kind": s.get("event_kind", "timeless_document"), "event_start_unix_ms": s.get("event_start_unix_ms"),
                                "event_end_unix_ms": s.get("event_end_unix_ms"), "source_time_basis": s.get("source_time_basis", "source_declared"),
                                "access": s.get("access", "available"), "revocation_reason": s.get("revocation_reason"),
                                "object_id": s.get("object_id")} for s in sources],
                   "targets": list(targets),
                   # The production default: the effective revision of every authorized, available source. The other
                   # views are declared ablations for evaluation (ADR-16); a task carries its view in its base inputs.
                   "retrieval_view": spec.get("retrieval_view", DEFAULT_VIEW)}
    validate(declaration, "document-sources")
    for target in targets:
        if not fs.path_in_scope(target, spec.get("allowed_paths") or []):
            raise GabrielError(Code.INVALID_SCHEMA, "target %s is outside the allowed paths" % target)
    for source in declaration["sources"]:
        if fs.path_in_scope(source["path"], spec.get("allowed_paths") or []):
            raise GabrielError(Code.POLICY_DENIED, "source %s lies inside the editable scope; sources are never editable" % source["path"])

    def hook(raw, check_spec):
        if check_spec["predicate_kind"] == "document/required_claims":
            if len(check_spec["oracle_files"]) != 1:
                return "a required-claims check needs exactly one oracle file (kept outside the repository)"
            try:
                oracle = loads(store.get(check_spec["oracle_files"][0]["artifact_ref"]), ascii_only=False)
            except GabrielError:
                return "the required-claims oracle is not a JSON document"
            if not isinstance(oracle.get("claims"), list) or not oracle["claims"]:
                return "the required-claims oracle declares no claims"
        return None
    pin = {"schema": "gabriel.software-repository-pin/1", "repository_path": str(spec["repository"]), "base_commit": ids["base_commit"], "pinned_by": ids["principal_id"]}
    validate(pin, "software-repository-pin")
    base_inputs = [store.put(canonical(pin), "application/json"), store.put(canonical(declaration), "application/json")]
    return compile_generic(spec, store, pack=DocumentPack(None, None), transform_profile=TRANSFORM_PROFILE, supported_kinds=SUPPORTED_KINDS, structural=STRUCTURAL,
                           independent_kinds=("document/required_claims", "document/citations_bound"), base_inputs=base_inputs, check_hook=hook, **ids)


def declaration_for(task: dict, store) -> dict:
    for ref in task["base_inputs"]:
        record = loads(store.get(ref))
        if record.get("schema") == "gabriel.document-sources/1":
            return record
    raise GabrielError(Code.UNKNOWN_OBJECT, "task carries no document source declaration")


# ===================================================================== plans

def reference_plan_proposal(task: dict, binding: dict, repair_round: int = 0) -> dict:
    suffix = "" if repair_round == 0 else "-r%d" % repair_round
    specs = {s["check_id"]: s for s in binding["check_specs"]}
    review_checks = [cid for cid, _ in STRUCTURAL if cid in specs] + [cid for cid, s in specs.items() if s["predicate_kind"] in ("document/citations_bound", "document/required_claims")]
    nodes = [{"node_id": "observe" + suffix, "capability_id": "document.observe", "depends_on": [], "check_ids": ["output-valid"],
              "purpose": "ingest the declared sources and pin the worktree", "args": {}},
             {"node_id": "propose" + suffix, "capability_id": "model.generate", "depends_on": ["observe" + suffix], "check_ids": ["output-valid"],
              "purpose": "propose the amendment with cited spans", "args": {"role": "worker"}},
             {"node_id": "apply" + suffix, "capability_id": "document.apply_amendment", "depends_on": ["propose" + suffix], "check_ids": ["output-valid"],
              "purpose": "apply the amendment", "args": {"from_node": "propose" + suffix}},
             {"node_id": "read-back" + suffix, "capability_id": "document.read_back", "depends_on": ["apply" + suffix], "check_ids": ["output-valid"],
              "purpose": "observe the changed tree", "args": {}},
             {"node_id": "review" + suffix, "capability_id": "document.review", "depends_on": ["read-back" + suffix], "check_ids": review_checks,
              "purpose": "scope, identity, secret and citation review", "args": {}}]
    return {"nodes": nodes, "rationale": "reference document plan (round %d)" % repair_round}


# ===================================================================== observe port

def take_snapshot(worktree, binding: dict, store, frontier: int, *, memory, principal_id: str, declaration: dict, task_id: str, goal: bytes,
                  received_at_unix_ms: int) -> tuple:
    manifest = worktree.manifest()
    sources = []
    with fs.ContainedRoot(str(worktree.path)) as root:
        _retain_sources(root, manifest, binding["allowed_paths"], store)
        for declared in declaration["sources"]:
            entry = manifest.get(declared["path"])
            if entry is None or entry["kind"] != "file":
                sources.append(dict(path=declared["path"], source_id=declared["source_id"], source_revision=declared["source_revision"], observation_id=None,
                                    sha256="0" * 64, bytes=0, extraction="unsupported", event_kind=declared["event_kind"],
                                    event_start_unix_ms=declared["event_start_unix_ms"], event_end_unix_ms=declared["event_end_unix_ms"],
                                    access=declared.get("access", "available")))
                continue
            raw = root.read(declared["path"])
            observation_id = None
            extraction = "unsupported"
            try:
                raw.decode("utf8")
                extraction = "text_utf8"
            except UnicodeDecodeError:
                pass
            access = declared.get("access", "available")
            if extraction == "text_utf8" and memory is not None:
                # Revisions of the same document share the declared object identity (default: the path), so the
                # memory's revision rule applies across files that hold different revisions of one document.
                # ADR-25: the observation is identified by what was observed (key, revision, bytes, extraction, principal scope),
                # not by which task observed it: a later task that declares the same bytes under the same key gets the
                # retained observation back instead of a new one per task, so the index and every retrieval stay bounded
                # by the distinct sources, and a revocation of the observation holds for every later task
                record = memory.ingest(source_id=declared["source_id"], source_object_id=declared.get("object_id") or declared["path"].replace("/", ":"),
                                       source_revision=declared["source_revision"],
                                       content=raw, event_kind=declared["event_kind"], event_start_unix_ms=declared["event_start_unix_ms"],
                                       event_end_unix_ms=declared["event_end_unix_ms"], received_at_unix_ms=received_at_unix_ms,
                                       source_time_basis=declared["source_time_basis"], extraction_digest=EXTRACTION_DIGEST,
                                       scope={"principals": [principal_id], "source_kind": "document"})
                observation_id = record["observation_id"]
                if access == "revoked" and not memory.is_revoked(observation_id):
                    # Declared revoked: the bytes stay retained for audit (AT15) and the access policy
                    # excludes the observation from every later retrieval and citation binding.
                    memory.revoke(observation_id, principal_id=principal_id, reason=declared.get("revocation_reason") or "declared revoked by the task")
            sources.append(dict(path=declared["path"], source_id=declared["source_id"], source_revision=declared["source_revision"], observation_id=observation_id,
                                sha256=entry["sha256"], bytes=entry["bytes"], extraction=extraction, event_kind=declared["event_kind"],
                                event_start_unix_ms=declared["event_start_unix_ms"], event_end_unix_ms=declared["event_end_unix_ms"], access=access))
    view = declaration.get("retrieval_view", DEFAULT_VIEW)
    retrieval_ref = None
    if memory is not None:
        current = memory.frontier()
        if view == "plain":
            # Declared ablation of provenance filtering (ADR-16): every declared source file enters the
            # prompt by its observation id, whatever its revision or access state. Not a memory retrieval.
            items = []
            for source in sources:
                if source["observation_id"] is None:
                    continue
                observation = memory.observation(source["observation_id"])
                items.append({"observation_id": source["observation_id"], "source_id": source["source_id"], "source_revision": source["source_revision"],
                              "artifact_ref": observation["content_ref"], "span_start": 0, "span_end": observation["content_ref"]["bytes"], "score_milli": 0,
                              "source_kind": "document", "label": "file " + source["path"]})
            manifest_record = {"schema": "gabriel.document-source-view/1", "view": "plain", "frontier": current.record(), "items": items, "excluded": []}
        else:
            # associative (ADR-20): the provenance view re-ranked by the engine's walk over the co-citation
            # graph of supported claims; the manifest retains the association record
            manifest_record = memory.retrieve(principal_id=principal_id, task_id=task_id, frontier=current, query=goal, allowed_source_kinds=["document"],
                                              version_policy="all_revisions" if view == "all_revisions" else "highest_revision",
                                              max_bytes=PROMPT_SOURCE_BUDGET, max_items=32,
                                              association=association.PROFILE if view in ASSOCIATIVE_VIEWS else None)
        retrieval_ref = store.put(canonical(manifest_record), "application/json")
        frontier_record = current.record()
    else:
        frontier_record = {"owner_sequence": frontier, "memory_sequence": 0}
    manifest_ref = store.put(dumps_utf8(manifest), "application/json; charset=utf-8")
    snapshot = {"schema": "gabriel.document-snapshot/1", "worktree_id": "worktree", "base_commit": worktree.base_commit, "head_commit": worktree.head(),
                "manifest_ref": manifest_ref, "tree_digest": sha256_hex(canonical(manifest)), "sources": sources[:256], "targets": list(declaration["targets"])[:64],
                "frontier": frontier_record, "retrieval_manifest_ref": retrieval_ref, "retrieval_view": view, "extraction_profile": EXTRACTION_PROFILE,
                "coverage": {"observes": ["file bytes and digests", "declared sources as versioned observations", "as-of retrieval at the frontier"],
                             "does_not_observe": ["semantic truth of any source", "sources ingested after the frontier"]}, "observed_frontier": frontier}
    validate(snapshot, "document-snapshot")
    return snapshot, manifest


def _observe(ctx):
    declaration = declaration_for(ctx.projection["task"], ctx.store)
    goal = ctx.store.get(ctx.projection["task"]["goal_ref"])
    return take_snapshot(ctx.worktree, ctx.binding, ctx.store, ctx.owner.anchor()["sequence"], memory=ctx.extras.get("memory"),
                         principal_id=ctx.extras.get("principal_id", "local-user"), declaration=declaration, task_id=ctx.intent["task_id"], goal=goal,
                         received_at_unix_ms=ctx.owner.owner_time())


class ObserveTool:
    def __call__(self, intent, args, ctx):
        snapshot, _ = _observe(ctx)
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("snapshot", canonical(snapshot), "application/json", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


class ReadBackTool:
    def __call__(self, intent, args, ctx):
        pre = validate(loads(ctx.store.get(args["pre_snapshot_ref"])), "document-snapshot")
        pre_manifest = loads(ctx.store.get(pre["manifest_ref"]), ascii_only=False)
        snapshot, manifest = _observe(ctx)
        # the frontier of the run is the one at which the sources were first observed; a read-back keeps it
        snapshot["frontier"] = pre["frontier"]
        snapshot["retrieval_manifest_ref"] = pre["retrieval_manifest_ref"]
        changed = sorted(p for p in set(pre_manifest) | set(manifest) if pre_manifest.get(p, {}).get("sha256") != manifest.get(p, {}).get("sha256"))
        out_of_scope = [p for p in changed if not fs.path_in_scope(p, ctx.binding["allowed_paths"])]
        record = {"schema": "gabriel.read-back/1", "read_back_id": "readback-" + intent["attempt_id"], "task_id": intent["task_id"], "run_id": intent["run_id"],
                  "intent_id": intent["intent_id"], "attempt_id": intent["attempt_id"], "pre_snapshot_ref": args["pre_snapshot_ref"],
                  "post_snapshot_ref": ctx.store.put(canonical(snapshot), "application/json"), "changed_resources": changed[:4096],
                  "invalidated_observation_ids": ["obs-" + sha256_hex(p.encode("utf8"))[:40] for p in changed][:4096], "postcondition_profile_id": "document-readback-v1",
                  "outcome": "confirmed" if not out_of_scope else "mismatch",
                  "detail": "changes confined to the admitted scope" if not out_of_scope else "out-of-scope changes: " + ",".join(out_of_scope)[:400]}
        validate(record, "read-back")
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("snapshot", canonical(snapshot), "application/json", d), ("read_back", canonical(record), "application/json", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


# ===================================================================== propose port

def build_prompt(task_goal: str, binding: dict, snapshot: dict, manifest: dict, store, *, failure_context: list, round_index: int, memory=None):
    lines = ["You are the worker role of Gabriel for a source-grounded document amendment.",
             "Goal (verbatim user request):", task_goal.strip(), "",
             "Acceptance checks (independent oracles decide completion; you cannot change them):"]
    for s in binding["check_specs"]:
        if s["role"] != "structural":
            lines.append("- %s [%s] independent=%s" % (s["check_id"], s["predicate_kind"], s["independent"]))
    lines += ["", "Editable paths (changes elsewhere are rejected; sources are never editable): " + ", ".join(binding["allowed_paths"]),
              "Base commit: " + snapshot["base_commit"], "", "Target documents (path sha256 bytes):"]
    entries, observation_ids = [], []
    for path in snapshot["targets"]:
        entry = manifest.get(path)
        if entry is None:
            lines.append("  %s (absent; create it)" % path)
            continue
        lines.append("  %s %s %d" % (path, entry["sha256"], entry["bytes"]))
        ref = {"sha256": entry["sha256"], "bytes": entry["bytes"], "media_type": "text/plain; charset=utf-8"}
        try:
            data = store.get(ref)
            lines += ["=== %s (sha256 %s) ===" % (path, entry["sha256"]), data[:PROMPT_SOURCE_BUDGET].decode("utf8", "replace"), ""]
        except GabrielError:
            lines += ["=== %s (sha256 %s) === [CONTENT NOT RETAINED]" % (path, entry["sha256"]), ""]
        entries.append({"entry_id": "target-%d" % len(entries), "kind": "source", "artifact_ref": ref, "source_id": "worktree", "source_revision": None,
                        "observation_id": None, "span_start": 0, "span_end": min(entry["bytes"], PROMPT_SOURCE_BUDGET), "purpose": "target",
                        "truncated": entry["bytes"] > PROMPT_SOURCE_BUDGET, "omitted_bytes": max(0, entry["bytes"] - PROMPT_SOURCE_BUDGET), "disclosure_scope": "provider"})
    lines += ["", "Sources (cite them by observation id; quotes must be exact substrings of the cited source):"]
    retrieval = loads(store.get(snapshot["retrieval_manifest_ref"])) if snapshot.get("retrieval_manifest_ref") else {"items": [], "excluded": []}
    # ADR-21: under the associative view a source whose rank came from the walk (structural score above
    # its lexical score) is told apart from the lexically retrieved ones, with the reason the manifest
    # retains: the seed it was cited together with and the verified run that cited them together
    labeled = snapshot.get("retrieval_view") == "associative"
    links = (retrieval.get("association") or {}).get("links") or {}
    budget, shown_items, carried = PROMPT_SOURCE_BUDGET, [], []
    for item in retrieval["items"]:
        try:
            content = store.get(item["artifact_ref"])
        except GabrielError:
            continue
        shown = content[:max(0, min(len(content), budget))]
        budget -= len(shown)
        # carried = the manifest links it (mass from the walk and not a seed itself); a seed keeps its lexical place
        is_carried = labeled and any(key.startswith(item["source_id"] + "/") for key in links)
        (carried if is_carried else shown_items).append((item, content, shown))
        if budget <= 0:
            break
    if carried:
        shown_items += [("association", None, None)] + carried
    for item, content, shown in shown_items:
        if item == "association":
            lines += ["", "Sources associated by verified history (not retrieved for the goal's words: each was cited together with a source above "
                      "in an earlier verified run; use one only where the goal needs it):"]
            continue
        label = item.get("label") or ("source %s revision %d" % (item["source_id"], item["source_revision"]))
        reason = ""
        link = next((v for k, v in links.items() if k.startswith(item["source_id"] + "/")), None) if labeled else None
        if link is not None:
            seeds = ", ".join(sorted({k.split("/", 1)[0] for k in link.get("seeds", [])})) or "sources above (indirectly)"
            runs = ", ".join(link.get("task_ids", [])[:2]) or "an earlier run"
            reason = "; associated: cited together with %s in verified run %s" % (seeds, runs)
        lines += ["=== %s observation %s (%d bytes%s%s) ===" % (label, item["observation_id"], len(content), "" if len(shown) == len(content) else ", truncated", reason),
                  shown.decode("utf8", "replace"), ""]
        observation_ids.append(item["observation_id"])
        entries.append({"entry_id": "obs-%d" % len(entries), "kind": "observation", "artifact_ref": item["artifact_ref"], "source_id": item["source_id"],
                        "source_revision": item["source_revision"], "observation_id": item["observation_id"], "span_start": 0, "span_end": len(shown),
                        "purpose": "retrieval", "truncated": len(shown) < len(content), "omitted_bytes": len(content) - len(shown), "disclosure_scope": "provider"})
    unsupported = [s["path"] for s in snapshot["sources"] if s["extraction"] == "unsupported"]
    if unsupported:
        lines += ["Sources that could not be extracted (never cite them): " + ", ".join(unsupported)]
    for excluded in retrieval.get("excluded", []):
        if excluded["reason"] == "kind_not_allowed":
            continue  # observations of other kinds (router decisions, episodes) are not document sources
        lines.append("Observation %s is not available: %s" % (excluded["observation_id"], excluded["reason"]))
    if failure_context:
        lines += ["", "Previous attempt failed verification (round %d). Diagnostics:" % round_index]
        for item in failure_context:
            lines += ["--- %s ---" % item["check_id"], item["text"][:4000], ""]
    lines += ["", "Every statement you add must be followed by a citation marker of the form",
              '[[cite:<observation id> "exact quote from that source"]] where the quote is copied verbatim from the cited source.',
              "Respond with exactly one JSON object and nothing else:",
              '{"operations": [{"kind": "modify", "path": "<target path>", "expected_sha256": "<sha256 listed above>", "content": "<complete new file content>"}],',
              ' "rationale": "<short explanation>"}',
              "Rules: kind is one of create, modify, delete. For modify/delete expected_sha256 must equal the listed digest. For create expected_sha256 is null.",
              "Do not touch sources or oracle files. Do not claim completion; the independent checks decide."]
    if carried:
        lines.append("State only what the goal asks for; a source associated by history is available, not required.")
    return "\n".join(lines).encode("utf8"), entries, observation_ids


# ===================================================================== review and verifiers

class DocumentReviewTool(ReviewTool):
    """Worktree review plus the citation binding of every target document at the run's frontier."""

    def __call__(self, intent, args, ctx):
        outcome = super().__call__(intent, args, ctx)
        snapshot = validate(loads(ctx.store.get(args["snapshot_ref"])), "document-snapshot")
        memory, principal = ctx.extras.get("memory"), ctx.extras.get("principal_id", "local-user")
        targets = []
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            for path in snapshot["targets"]:
                if not root.exists(path):
                    targets.append({"path": path, "present": False, "content_ref": None, "citations": [], "all_resolved": False})
                    continue
                raw = root.read(path)
                citations = parse_citations(raw.decode("utf8", "replace"))
                if memory is not None:
                    check = memory.verify_citations(citations, frontier=Frontier.of(snapshot["frontier"]), principal_id=principal)
                else:
                    check = {"all_resolved": False, "citations": [dict(c, resolved=False, reason="no memory service") for c in citations]}
                targets.append({"path": path, "present": True, "content_ref": ctx.store.put(raw, "text/plain; charset=utf-8"), "citations": check["citations"],
                                "all_resolved": bool(citations) and check["all_resolved"]})
        # ADR-22: which sources the worker could cite at all (the retrieval manifest's items) is a committed fact
        # of the run; the claims verifier records per claim whether its expected source was among them
        retrieved = []
        if snapshot.get("retrieval_manifest_ref"):
            try:
                retrieved = sorted({item["source_id"] for item in loads(ctx.store.get(snapshot["retrieval_manifest_ref"]))["items"]})
            except (GabrielError, KeyError, ValueError):
                retrieved = []
        report = {"frontier": snapshot["frontier"], "targets": targets, "sources": [{"source_id": s["source_id"], "observation_id": s["observation_id"],
                                                                                     "extraction": s["extraction"]} for s in snapshot["sources"]],
                  "retrieved_source_ids": retrieved[:256]}
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        outcome.outputs.append(("citations", dumps_utf8(report), "application/json; charset=utf-8", d))
        return outcome


class CitationsBoundVerifier:
    def __call__(self, spec, outputs, ctx):
        report = _record(outputs, "citations")
        if report is None:
            return "not_run", {"reason": "no citation report"}
        problems = []
        for target in report["targets"]:
            if not target["present"]:
                problems.append("%s is absent" % target["path"])
                continue
            if not target["citations"]:
                problems.append("%s carries no citation" % target["path"])
            for cite in target["citations"]:
                if not cite["resolved"]:
                    problems.append("%s: citation of %s not bound: %s" % (target["path"], cite["observation_id"], cite["reason"]))
        return ("passed" if not problems else "failed"), {"problems": problems[:32], "frontier": report["frontier"],
                                                          "resolved": [{"path": t["path"], "spans": [{"observation_id": c["observation_id"], "source_id": c["source_id"],
                                                                                                      "span_start": c["span_start"], "span_end": c["span_end"]}
                                                                                                     for c in t["citations"] if c["resolved"]]} for t in report["targets"]]}


class RequiredClaimsVerifier:
    """Independent oracle: each required claim must appear in the target and be cited from the
    named source with a quote that includes the expected text."""

    def __call__(self, spec, outputs, ctx):
        report = _record(outputs, "citations")
        if report is None:
            return "not_run", {"reason": "no citation report"}
        if not spec["oracle_files"]:
            return "inconclusive", {"reason": "no oracle bound to the check"}
        oracle = loads(ctx.store.get(spec["oracle_files"][0]["artifact_ref"]), ascii_only=False)
        contents = {}
        for target in report["targets"]:
            if target["present"] and target["content_ref"]:
                contents[target["path"]] = ctx.store.get(target["content_ref"]).decode("utf8", "replace")
        results = []
        retrieved = report.get("retrieved_source_ids")  # absent in reports written before ADR-22
        for claim in oracle["claims"]:
            path = claim.get("path") or (report["targets"][0]["path"] if report["targets"] else None)
            text = contents.get(path, "")
            phrasings = claim["must_contain"] if isinstance(claim["must_contain"], list) else [claim["must_contain"]]
            present = any(phrase in text for phrase in phrasings)
            target = next((t for t in report["targets"] if t["path"] == path), None)
            cited = False
            if target:
                for cite in target["citations"]:
                    if cite["resolved"] and cite["source_id"] == claim["cited_source_id"] and claim.get("quote_must_include", "") in cite["quote"]:
                        cited = True
                        break
            results.append({"claim": " | ".join(phrasings)[:200], "present": present, "cited_from_expected_source": cited, "path": path,
                            "expected_source_retrieved": (claim["cited_source_id"] in retrieved) if retrieved is not None else None})
        # The oracle may also forbid statements (a stale value, a withdrawn figure): their presence fails the claim check.
        forbidden = []
        for rule in oracle.get("forbidden") or []:
            text = contents.get(rule.get("path") or (report["targets"][0]["path"] if report["targets"] else None), "")
            hits = [p for p in rule.get("must_not_contain", []) if p in text]
            if hits:
                forbidden.append({"path": rule.get("path"), "present": hits[:8]})
        ok = bool(results) and all(r["present"] and r["cited_from_expected_source"] for r in results) and not forbidden
        return ("passed" if ok else "failed"), {"claims": results, "forbidden_present": forbidden}


class DocumentOutputValidVerifier(OutputValidVerifier):
    SLOT_SCHEMAS = {"snapshot": "document-snapshot", "apply_report": "software-apply-report", "read_back": "read-back", "review": "software-review",
                    "citations": None, "request": "model-request", "envelope": None, "raw_response": None, "patch": None, "model_output": None}


# ===================================================================== pack

class DocumentPack(DomainPack):
    namespace, pack_id, pack_version = NAMESPACE, PACK_ID, PACK_VERSION
    task_noun = "document amendment"
    snapshot_schema, proposal_schema, candidate_schema = "document-snapshot", "document-amendment-proposal", "software-patch"
    normalization_profile_id = "document-amendment-v1"
    output_slots, retry_class, verifier_ids = OUTPUT_SLOTS, RETRY_CLASS, SUPPORTED_KINDS

    def __init__(self, provider_factory, backend_resolver):
        self.provider_factory = provider_factory
        self.backend_resolver = backend_resolver

    def register(self, registry) -> None:
        def desc(tool_id, effect, reconciliation, key, slot=None, forms=("worktree",)):
            return descriptor(tool_id, effect, reconciliation, key, pack_label="document", observation_slot=slot, forms=forms)
        registry.register_tool(desc("document.observe", "read", "read_back", "read", "snapshot"), ObserveTool())
        registry.register_tool(desc("document.apply_amendment", "local_reversible_write", "read_back", "writer"), ApplyPatchTool())
        registry.register_tool(desc("document.read_back", "read", "read_back", "read", "snapshot"), ReadBackTool())
        registry.register_tool(desc("document.review", "read", "read_back", "read"), DocumentReviewTool())
        if registry.tool_or_none("model.generate") is None:
            registry.register_tool(desc("model.generate", "external_idempotent_effect", "same_key_retry", "model", forms=("provider",)),
                                   ModelGenerateTool(self.provider_factory))
        for verifier_id, kind, impl in [("document.citations_bound", "document/citations_bound", CitationsBoundVerifier()),
                                        ("document.required_claims", "document/required_claims", RequiredClaimsVerifier()),
                                        ("document.diff_in_scope", "document/diff_in_scope", DiffInScopeVerifier()),
                                        ("document.base_commit_pinned", "document/base_commit_pinned", BaseCommitPinnedVerifier()),
                                        ("document.checks_intact", "document/checks_intact", ChecksIntactVerifier()),
                                        ("document.no_secrets", "document/no_secrets", NoSecretsVerifier()),
                                        ("document.output_valid", "owner/output_valid", DocumentOutputValidVerifier())]:
            registry.register_verifier({"verifier_id": verifier_id, "version": "v1", "predicate_kind": kind, "implementation_fingerprint": "0" * 64,
                                        "profile_digest": sha256_hex(verifier_id.encode()), "independent": verifier_id != "document.output_valid",
                                        "description": "document pack verifier " + verifier_id}, impl)
        registry.register_pack(self.manifest(registry))

    def manifest(self, registry) -> dict:
        def ref(value):
            raw = canonical(value)
            return {"sha256": sha256_hex(raw), "bytes": len(raw), "media_type": "application/json"}
        schema_ref = ref({"schema": "fixture"})
        ports = {}
        for port, tool_id, effect in [("compile", "document.observe", "read"), ("observe", "document.observe", "read"), ("evaluate", "document.review", "read"),
                                      ("propose", "model.generate", "external_idempotent_effect"), ("execute", "document.apply_amendment", "local_reversible_write"),
                                      ("read_back", "document.read_back", "read")]:
            impl = registry.tool(tool_id)[0]["implementation_fingerprint"]
            ports[port] = {"capability_id": tool_id, "input_schema_ref": schema_ref, "output_schema_ref": schema_ref,
                           "implementation_ref": {"sha256": impl, "bytes": 0, "media_type": "application/json"}, "effect_class": effect}
        manifest = {"schema": "gabriel.domain-pack/1", "pack_id": PACK_ID, "namespace": NAMESPACE, "pack_version": PACK_VERSION,
                    "manifest_kind": "implementation_release", "ports": ports,
                    "observation_coverage_ref": ref({"observes": ["file bytes", "declared sources as versioned observations", "as-of retrieval"],
                                                     "does_not_observe": ["semantic truth", "sources after the frontier"]}),
                    "evaluation_profiles": [{"profile_id": "document-citations-bound-v1", "spec_ref": ref({"rule": "every citation resolves at the frontier and quotes its source"})},
                                            {"profile_id": "document-required-claims-v1", "spec_ref": ref({"rule": "required claims present and cited from the expected source"})}],
                    "transformation_profiles": [{"profile_id": TRANSFORM_PROFILE, "spec_ref": ref({"rule": "loss-preserving compile"})},
                                                {"profile_id": EXTRACTION_PROFILE, "spec_ref": ref({"extraction_digest": EXTRACTION_DIGEST})}],
                    "capability_requirements": ["document.observe", "document.apply_amendment", "document.read_back", "document.review", "model.generate"],
                    "conventions_ref": ref({"missingness": "absent source is unsupported, not empty", "time": "source-declared event intervals; owner and memory sequences for availability",
                                            "units": ["bytes"], "citation": "[[cite:<observation_id> \"quote\"]]"}),
                    "fixtures": [{"fixture_id": "valid", "port": "evaluate", "case_kind": "valid", "input_ref": schema_ref, "expected_ref": schema_ref},
                                 {"fixture_id": "invalid", "port": "evaluate", "case_kind": "invalid", "input_ref": schema_ref, "expected_ref": schema_ref},
                                 {"fixture_id": "out_of_scope", "port": "evaluate", "case_kind": "out_of_scope", "input_ref": schema_ref, "expected_ref": schema_ref}]}
        return validate(manifest, "domain-pack")

    # ---------------------------------------------------------------- ports
    def compile_task(self, spec, store, **ids):
        return compile_task(spec, store, **ids)

    def reference_plan_proposal(self, task, binding, repair_round=0):
        return reference_plan_proposal(task, binding, repair_round=repair_round)

    def build_prompt(self, goal_text, binding, snapshot, manifest, store, *, failure_context, round_index, memory=None, principal_id=None, episodes=()):
        return build_prompt(goal_text, binding, snapshot, manifest, store, failure_context=failure_context, round_index=round_index, memory=memory)

    def normalize_proposal(self, proposal, snapshot, manifest, binding, store, *, task_id, run_id, proposal_ref, protected, goal_id, policy_digest):
        patch, loss, problem = normalize_patch_proposal(proposal, snapshot, manifest, binding, store, task_id=task_id, run_id=run_id, proposal_ref=proposal_ref,
                                                        protected=protected, goal_id=goal_id, policy_digest=policy_digest)
        if patch is None:
            return None, loss, problem
        known = {s["observation_id"] for s in snapshot["sources"] if s["observation_id"]}
        for op in patch["operations"]:
            if op["content_ref"] is None:
                continue
            text = store.get(op["content_ref"]).decode("utf8", "replace")
            for cite in parse_citations(text):
                if cite["observation_id"] not in known:
                    loss.append("citation of %s in %s names no observed source" % (cite["observation_id"], op["path"]))
        return patch, loss, None

    def default_policy(self) -> dict | None:
        """ADR-22: the readout promoted under protocol 8 (`policies/readout-channels-v2.json`, with its
        provenance beside it) is the routing policy of a document task that pins none. It decides at
        a failed verification from the generic channels and this pack's declared channels, abstains
        where those channels are missing, and can only stop a repair earlier than the rule."""
        path = Path(__file__).parent / "policies" / "readout-channels-v2.json"
        if not path.is_file():
            return None
        return validate(loads(path.read_bytes()), "router-policy")

    def progress_channels(self, projection: dict, store) -> dict | None:
        """ADR-22: the document pack's declared channels at a decision point, read from the retained
        evidence of the latest review's `claims` and `citations` checks and from the retrieval
        manifest of the observed snapshot. Every value is a committed fact of the run, never a
        judgement: how many required claims are missing or uncited, whether a forbidden statement
        is present, how many unmet claims expect a source the retrieval did not carry, how many
        citations failed to bind, and how many retrieved sources came from association."""
        values = {name: None for name in PROGRESS_CHANNELS}
        latest = {}
        for entry in projection["assessments"].values():
            if entry["check_id"] in ("claims", "citations") and entry["outcome"] in ("passed", "failed"):
                key = (len(entry["node_id"]), entry["node_id"])
                if entry["check_id"] not in latest or key > latest[entry["check_id"]][0]:
                    latest[entry["check_id"]] = (key, entry)
        evidence = {}
        for check_id, (_, entry) in latest.items():
            try:
                record = loads(store.get(entry["evidence_ref"]), ascii_only=False)
            except (GabrielError, ValueError):
                continue
            evidence[check_id] = record["evidence"] if isinstance(record.get("evidence"), dict) else record
        claims = evidence.get("claims")
        if isinstance(claims, dict) and isinstance(claims.get("claims"), list) and claims["claims"]:
            rows = claims["claims"]
            values["required_missing"] = sum(1 for r in rows if not r.get("present")) / len(rows)
            values["required_uncited"] = sum(1 for r in rows if r.get("present") and not r.get("cited_from_expected_source")) / len(rows)
            values["forbidden_present"] = 1.0 if claims.get("forbidden_present") else 0.0
            unmet = [r for r in rows if not (r.get("present") and r.get("cited_from_expected_source"))]
            if unmet and all(r.get("expected_source_retrieved") is not None for r in unmet):
                values["expected_source_absent"] = sum(1 for r in unmet if not r["expected_source_retrieved"]) / len(unmet)
            elif not unmet:
                values["expected_source_absent"] = 0.0
        citations = evidence.get("citations")
        if isinstance(citations, dict) and isinstance(citations.get("problems"), list):
            unbound = sum(1 for p in citations["problems"] if "not bound" in p)
            resolved = sum(len(r.get("spans", [])) for r in citations.get("resolved", []) if isinstance(r, dict))
            values["citations_unbound"] = (unbound / (unbound + resolved)) if (unbound + resolved) else 0.0
        snapshot_ref = projection["run_meta"].get("observed_snapshot_ref")
        if snapshot_ref:
            try:
                snapshot = loads(store.get(snapshot_ref))
                manifest = loads(store.get(snapshot["retrieval_manifest_ref"])) if snapshot.get("retrieval_manifest_ref") else None
            except (GabrielError, KeyError, ValueError):
                manifest = None
            if manifest is not None and manifest.get("items"):
                links = (manifest.get("association") or {}).get("links") or {}
                values["carried_sources"] = len(links) / len(manifest["items"])
        return {"schema_id": PROGRESS_SCHEMA_ID, "names": list(PROGRESS_CHANNELS), "values": values}

    def claims_after_success(self, projection: dict, store) -> list:
        """The claims a succeeded run establishes (ADR-20): every target whose citations all resolved
        at the run's frontier, as a proposition supported by the cited observations. Read from the
        retained citation report of the last review node; never from the model's own text."""
        reports = []
        for node_id, state in projection["nodes"].items():
            if state["status"] in ("completed", "verified") and "citations" in state["outputs"]:
                reports.append((node_id, state["outputs"]["citations"]))
        if not reports:
            return []
        reports.sort(key=lambda pair: (len(pair[0]), pair[0]))  # the last repair round reviews last
        try:
            report = loads(store.get(reports[-1][1]), ascii_only=False)
        except (GabrielError, ValueError):
            return []
        claims = []
        for target in report.get("targets", []):
            if not target.get("present") or not target.get("all_resolved"):
                continue
            supporting = sorted({c["observation_id"] for c in target.get("citations", []) if c.get("resolved")})
            if not supporting:
                continue
            try:
                proposition = store.get(target["content_ref"])
            except GabrielError:
                continue
            claims.append({"proposition": proposition, "supporting": supporting, "frontier": report["frontier"], "verifier_id": "document.citations_bound",
                           "reason": "every citation of %s resolved at the run's frontier and the run's independent checks passed" % target["path"]})
        return claims

    def node_args(self, capability, declared, helper):
        if capability == "document.apply_amendment":
            patch_ref, problem = helper.candidate_for(declared["from_node"])
            if patch_ref is None:
                raise GabrielError(Code.STALE_EVIDENCE, "no admissible amendment from %s: %s" % (declared["from_node"], problem))
            return {"patch_ref": patch_ref}
        if capability == "document.read_back":
            return {"pre_snapshot_ref": helper.observed_snapshot_ref}
        if capability == "document.review":
            return {"snapshot_ref": helper.observed_snapshot_ref}
        return {}
