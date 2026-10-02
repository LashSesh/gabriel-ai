"""Memory as a provenance service (WP09).

Three stores with different responsibilities (blueprint, section "Memory is a provenance
service"): the owner's event journal is the exact episodic history; this module is the
artifact/evidence index with its own append-only hash chain; task summaries are a derived
view that is never the only retained copy of evidence.

Temporal rules implemented here (requirement R10):

* An observation carries its source identity and revision, an immutable content reference,
  its ingestion sequence (the availability frontier), an optional event-time interval and the
  extraction identity. Ingestion is append-only; a correction is a new version linked to its
  predecessor, never an overwrite.
* For a source key ``k`` and a frontier ``s`` the eligible set is every observation of ``k``
  ingested at or before ``s``. The source's explicit revision rule chooses the effective version
  inside that set; it never silently uses the globally latest version. A tie between different
  contents is ``contested``; a contradictory supersedes chain is ``unresolved``.
* Retrieval authorizes and filters by frontier before any content is scored. The result is an
  ordered manifest of artifact/span references; scores rank relevance and are not factual
  confidence. A cached manifest is scoped by the same authorization (access policy revision)
  and frontier, so a revocation can never be served from the cache.
* A claim's generated assertion is ``unresolved`` until a named verifier assesses it; a
  retraction of a cited source creates a new assessment and an affected-claims work item.
* An outcome label refers to the original issuance; a correction supersedes the earlier label
  and replaces its effective contribution. Dry-run, skipped and unreconciled records never
  count as production outcomes. Promotion of a candidate policy requires held-out evidence.
* Compaction removes only derived rows (retrieval cache, summaries); every required artifact
  byte is verified. A record whose bytes are unavailable is a storage fault, never a
  successfully compacted record.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..contracts.codec import canonical, loads, sha256_hex
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import validate

CHAIN_PREFIX = "gabriel.memory/1:"
GENESIS = "0" * 64
CLAIM_STATUSES = ("supported", "contested", "unresolved", "out_of_scope", "invalid")
PRODUCTION_STATUS_KINDS = ("production",)
NON_COUNTING_STATUS_KINDS = ("dry_run", "skipped", "unreconciled")
_TOKEN = re.compile(r"[A-Za-z0-9_]{2,}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(singleton INTEGER PRIMARY KEY CHECK(singleton = 1), workspace_id TEXT NOT NULL,
    head TEXT NOT NULL, count INTEGER NOT NULL, policy_revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entries(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, record_sha TEXT NOT NULL, record_bytes INTEGER NOT NULL,
    record_media TEXT NOT NULL, owner_sequence INTEGER NOT NULL, prev TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations(observation_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, source_key TEXT NOT NULL, source_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL, source_revision INTEGER NOT NULL, content_sha TEXT NOT NULL, content_bytes INTEGER NOT NULL,
    content_media TEXT NOT NULL, scope_sha TEXT NOT NULL, scope_bytes INTEGER NOT NULL, source_kind TEXT NOT NULL, supersedes TEXT, record_sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS revocations(observation_id TEXT NOT NULL, seq INTEGER NOT NULL, policy_revision INTEGER NOT NULL, record_sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claims(claim_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, record_sha TEXT NOT NULL, status TEXT NOT NULL, task_id TEXT NOT NULL,
    supporting TEXT NOT NULL, refuting TEXT NOT NULL, assessment_id TEXT);
CREATE TABLE IF NOT EXISTS assessments(assessment_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, seq INTEGER NOT NULL, record_sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS labels(label_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, issue_id TEXT NOT NULL, source_id TEXT NOT NULL, revision INTEGER NOT NULL,
    status_kind TEXT NOT NULL, outcome TEXT NOT NULL, supersedes TEXT, record_sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policies(candidate_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, record_sha TEXT NOT NULL, decision TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS work_items(item_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL, detail TEXT NOT NULL, resolved INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, manifest_sha TEXT NOT NULL, manifest_bytes INTEGER NOT NULL, policy_revision INTEGER NOT NULL, memory_sequence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS summaries(task_id TEXT PRIMARY KEY, summary_sha TEXT NOT NULL, summary_bytes INTEGER NOT NULL, memory_sequence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS compactions(compaction_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, record_sha TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Frontier:
    owner_sequence: int
    memory_sequence: int

    def record(self) -> dict:
        return {"owner_sequence": int(self.owner_sequence), "memory_sequence": int(self.memory_sequence)}

    @classmethod
    def of(cls, value) -> "Frontier":
        if isinstance(value, Frontier):
            return value
        return cls(int(value["owner_sequence"]), int(value["memory_sequence"]))


def source_key(source_id: str, source_object_id: str) -> str:
    return source_id + "/" + source_object_id


def _ref(sha: str, size: int, media: str) -> dict:
    return {"sha256": sha, "bytes": int(size), "media_type": media}


def _tokens(data: bytes) -> list:
    return [t.lower() for t in _TOKEN.findall(data.decode("utf8", "replace"))]


class MemoryService:
    """Append-only evidence index beside the owner's journal."""

    def __init__(self, path, store, owner_sequence, workspace_id: str | None = None):
        self.path = Path(path)
        self.store = store
        self._owner_sequence = owner_sequence  # callable -> current owner anchor sequence
        self._db = sqlite3.connect(str(self.path), isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(_SCHEMA)
        row = self._db.execute("SELECT workspace_id FROM meta WHERE singleton = 1").fetchone()
        if row is None:
            if workspace_id is None:
                raise GabrielError(Code.STORAGE_FAULT, "memory index is not initialized: " + str(self.path))
            self._db.execute("INSERT INTO meta(singleton, workspace_id, head, count, policy_revision) VALUES (1, ?, ?, 0, 0)", (workspace_id, GENESIS))
            self.workspace_id = workspace_id
        else:
            self.workspace_id = row[0]
            if workspace_id is not None and workspace_id != row[0]:
                raise GabrielError(Code.STORAGE_FAULT, "memory index belongs to another workspace")

    @classmethod
    def create(cls, path, store, workspace_id: str, owner_sequence) -> "MemoryService":
        if Path(path).exists():
            raise GabrielError(Code.STORAGE_FAULT, "memory index already exists: " + str(path))
        return cls(path, store, owner_sequence, workspace_id)

    @classmethod
    def open(cls, path, store, owner_sequence) -> "MemoryService":
        if not Path(path).is_file():
            raise GabrielError(Code.STORAGE_FAULT, "memory index missing: " + str(path))
        return cls(path, store, owner_sequence, None)

    def close(self):
        self._db.close()

    # ------------------------------------------------------------ chain
    def _meta(self):
        row = self._db.execute("SELECT head, count, policy_revision FROM meta WHERE singleton = 1").fetchone()
        return {"head": row[0], "count": row[1], "policy_revision": row[2]}

    def frontier(self) -> Frontier:
        return Frontier(int(self._owner_sequence()), self._meta()["count"])

    def anchor(self) -> dict:
        meta = self._meta()
        return {"schema": "gabriel.memory-anchor/1", "workspace_id": self.workspace_id, "memory_sequence": meta["count"], "head": meta["head"],
                "owner_sequence": int(self._owner_sequence()), "policy_revision": meta["policy_revision"]}

    def access_policy_revision(self) -> int:
        return self._meta()["policy_revision"]

    def _append(self, kind: str, record: dict, schema_name: str, *, ascii_only=True) -> tuple:
        validate(record, schema_name, ascii_only=ascii_only)
        raw = canonical(record)
        ref = self.store.put(raw, "application/json")
        meta = self._meta()
        seq = meta["count"] + 1
        owner_seq = int(self._owner_sequence())
        line = "%s%s|%d|%s|%d|%s" % (CHAIN_PREFIX, kind, seq, ref["sha256"], owner_seq, meta["head"])
        head = hashlib.sha256(line.encode("ascii")).hexdigest()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("INSERT INTO entries(seq, kind, record_sha, record_bytes, record_media, owner_sequence, prev, hash) VALUES (?,?,?,?,?,?,?,?)",
                             (seq, kind, ref["sha256"], ref["bytes"], ref["media_type"], owner_seq, meta["head"], head))
            self._db.execute("UPDATE meta SET head = ?, count = ? WHERE singleton = 1", (head, seq))
            yield_ = (seq, ref)
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return yield_

    # ------------------------------------------------------------ observations
    def ingest(self, *, source_id: str, source_object_id: str, source_revision: int, content: bytes, media_type: str = "text/plain; charset=utf-8",
               event_kind: str = "timeless_document", event_start_unix_ms=None, event_end_unix_ms=None, published_at_unix_ms=None,
               received_at_unix_ms: int, source_time_basis: str = "source_declared", extraction_digest: str, scope: dict,
               supersedes: str | None = None, authentication: str = "unverified", observation_id: str | None = None) -> dict:
        """Append one observation. Returns the retained record (an existing record for an exact
        repeat of the same identity)."""
        key = source_key(source_id, source_object_id)
        content_ref = self.store.put(content, media_type)
        scope = dict(scope, workspace_id=self.workspace_id)
        scope_ref = self.store.put(canonical(scope), "application/json")
        if observation_id is None:
            observation_id = "obs-" + hashlib.sha256(canonical({"key": key, "revision": int(source_revision), "content": content_ref["sha256"],
                                                                 "extraction": extraction_digest, "scope": scope_ref["sha256"]})).hexdigest()[:40]
        existing = self.observation(observation_id)
        if existing is not None:
            return existing
        if supersedes is not None:
            prior = self.observation(supersedes)
            if prior is None:
                raise GabrielError(Code.UNKNOWN_OBJECT, "supersedes names an unknown observation: " + supersedes)
            if source_key(prior["source_id"], prior["source_object_id"]) != key:
                raise GabrielError(Code.INVALID_SCHEMA, "a correction must supersede an observation of the same source key")
        seq_after = self._meta()["count"] + 1
        record = {"schema": "gabriel.observation/1", "observation_id": observation_id, "workspace_id": self.workspace_id, "source_id": source_id,
                  "source_object_id": source_object_id, "source_revision": int(source_revision), "content_ref": content_ref,
                  "availability_sequence": seq_after, "event_kind": event_kind, "event_start_unix_ms": event_start_unix_ms,
                  "event_end_unix_ms": event_end_unix_ms, "published_at_unix_ms": published_at_unix_ms, "received_at_unix_ms": int(received_at_unix_ms),
                  "source_time_basis": source_time_basis, "extraction_digest": extraction_digest, "scope_ref": scope_ref, "supersedes": supersedes,
                  "authentication": authentication}
        seq, ref = self._append("observation", record, "observation")
        assert seq == seq_after
        self._db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (observation_id, seq, key, source_id, source_object_id, int(source_revision), content_ref["sha256"], content_ref["bytes"],
                          content_ref["media_type"], scope_ref["sha256"], scope_ref["bytes"], str(scope.get("source_kind", "unknown")), supersedes, ref["sha256"]))
        return record

    def observations_of_kind(self, source_kind: str) -> list:
        """Every retained observation whose scope declares the source kind, in ingestion order."""
        rows = self._db.execute("SELECT record_sha FROM observations WHERE source_kind = ? ORDER BY seq", (source_kind,)).fetchall()
        return [self._load(r[0]) for r in rows]

    def labels(self) -> list:
        rows = self._db.execute("SELECT label_id, issue_id, source_id, revision, status_kind, outcome, supersedes FROM labels ORDER BY seq").fetchall()
        return [{"label_id": r[0], "issue_id": r[1], "source_id": r[2], "revision": r[3], "status_kind": r[4], "outcome": r[5], "supersedes": r[6]} for r in rows]

    def observation(self, observation_id: str) -> dict | None:
        row = self._db.execute("SELECT record_sha FROM observations WHERE observation_id = ?", (observation_id,)).fetchone()
        if row is None:
            return None
        return self._load(row[0])

    def _load(self, sha: str) -> dict:
        return loads(self.store.get(_ref(sha, self._size(sha), "application/json")))

    def _size(self, sha: str) -> int:
        row = self._db.execute("SELECT record_bytes FROM entries WHERE record_sha = ?", (sha,)).fetchone()
        if row is None:
            raise GabrielError(Code.UNKNOWN_OBJECT, "record is not part of the memory chain: " + sha)
        return row[0]

    def content(self, observation: dict) -> bytes:
        return self.store.get(observation["content_ref"])

    def scope(self, observation: dict) -> dict:
        return loads(self.store.get(observation["scope_ref"]))

    def is_revoked(self, observation_id: str, policy_revision: int | None = None) -> bool:
        if policy_revision is None:
            row = self._db.execute("SELECT 1 FROM revocations WHERE observation_id = ? LIMIT 1", (observation_id,)).fetchone()
        else:
            row = self._db.execute("SELECT 1 FROM revocations WHERE observation_id = ? AND policy_revision <= ? LIMIT 1", (observation_id, policy_revision)).fetchone()
        return row is not None

    def eligible(self, key: str, frontier) -> list:
        """O(k, s): observations of the source key ingested at or before the frontier, in ingestion order."""
        f = Frontier.of(frontier)
        rows = self._db.execute("SELECT record_sha FROM observations WHERE source_key = ? AND seq <= ? ORDER BY seq", (key, f.memory_sequence)).fetchall()
        return [self._load(r[0]) for r in rows]

    def effective(self, key: str, frontier, version_policy: str = "highest_revision") -> dict:
        """Apply the source's explicit revision rule inside the eligible set."""
        candidates = self.eligible(key, frontier)
        if not candidates:
            return {"status": "unavailable", "observation": None, "candidates": [], "reason": "no observation of %s at the frontier" % key}
        known = {c["observation_id"]: c for c in candidates}
        for c in candidates:
            sup = c["supersedes"]
            if sup is not None:
                prior = known.get(sup) or self.observation(sup)
                if prior is None or prior["source_revision"] >= c["source_revision"]:
                    return {"status": "unresolved", "observation": None, "candidates": candidates,
                            "reason": "contradictory revision chain at %s: %s supersedes %s" % (key, c["observation_id"], sup)}
        if version_policy == "highest_revision":
            top = max(c["source_revision"] for c in candidates)
            best = [c for c in candidates if c["source_revision"] == top]
        elif version_policy == "earliest_ingested":
            best = [candidates[0]]
        else:
            raise GabrielError(Code.UNSUPPORTED, "unknown version policy " + version_policy)
        contents = {c["content_ref"]["sha256"] for c in best}
        if len(contents) > 1:
            return {"status": "contested", "observation": None, "candidates": candidates,
                    "reason": "%d observations of %s share revision %d with different content" % (len(best), key, best[0]["source_revision"])}
        return {"status": "resolved", "observation": best[-1], "candidates": candidates, "reason": version_policy}

    # ------------------------------------------------------------ access policy
    def revoke(self, observation_id: str, *, principal_id: str, reason: str) -> dict:
        if self.observation(observation_id) is None:
            raise GabrielError(Code.UNKNOWN_OBJECT, "cannot revoke an unknown observation: " + observation_id)
        meta = self._meta()
        revision = meta["policy_revision"] + 1
        record = {"schema": "gabriel.access-revocation/1", "revocation_id": "revoke-%s-%d" % (observation_id, revision), "observation_id": observation_id,
                  "principal_id": principal_id, "policy_revision": revision, "reason_ref": self.store.put(reason.encode("utf8"), "text/plain; charset=utf-8"),
                  "retained_for_audit": True}
        seq, ref = self._append("access_revocation", record, "access-revocation")
        self._db.execute("INSERT INTO revocations VALUES (?,?,?,?)", (observation_id, seq, revision, ref["sha256"]))
        self._db.execute("UPDATE meta SET policy_revision = ? WHERE singleton = 1", (revision,))
        return record

    def _authorized(self, observation: dict, principal_id: str) -> tuple:
        scope = self.scope(observation)
        if scope.get("workspace_id") != self.workspace_id:
            return False, "out_of_scope"
        principals = scope.get("principals") or []
        if "*" not in principals and principal_id not in principals:
            return False, "out_of_scope"
        if self.is_revoked(observation["observation_id"]):
            return False, "revoked"
        return True, None

    # ------------------------------------------------------------ retrieval
    def retrieve(self, *, principal_id: str, task_id: str | None, frontier, query: bytes, allowed_source_kinds: list,
                 version_policy: str = "highest_revision", max_bytes: int = 65536, max_items: int = 16) -> dict:
        f = Frontier.of(frontier)
        policy_revision = self.access_policy_revision()
        query_ref = self.store.put(query, "text/plain; charset=utf-8")
        cache_key = hashlib.sha256(canonical({"workspace": self.workspace_id, "principal": principal_id, "frontier": f.record(),
                                              "policy_revision": policy_revision, "query": query_ref["sha256"], "kinds": sorted(allowed_source_kinds),
                                              "version_policy": version_policy, "max_bytes": max_bytes, "max_items": max_items})).hexdigest()
        row = self._db.execute("SELECT manifest_sha, manifest_bytes FROM cache WHERE key = ? AND policy_revision = ?", (cache_key, policy_revision)).fetchone()
        if row is not None:
            manifest = loads(self.store.get(_ref(row[0], row[1], "application/json")))
            manifest["cached"] = True
            return manifest
        # 1. authorization and temporal filtering before any content is read for scoring
        keys = [r[0] for r in self._db.execute("SELECT DISTINCT source_key FROM observations WHERE seq <= ? ORDER BY source_key", (f.memory_sequence,)).fetchall()]
        items, excluded = [], []
        query_tokens = set(_tokens(query))
        for key in keys:
            if version_policy == "all_revisions":
                # Declared ablation of the revision rule (ADR-16): every eligible revision of the source is a
                # candidate; authorization, revocation and kind filtering still apply before scoring.
                chosen_set = self.eligible(key, f)
            else:
                choice = self.effective(key, f, version_policy)
                if choice["status"] != "resolved":
                    for c in choice["candidates"]:
                        excluded.append({"observation_id": c["observation_id"], "reason": choice["status"] if choice["status"] in ("contested",) else "unresolved_revision"})
                    continue
                chosen_set = [choice["observation"]]
                for c in choice["candidates"]:
                    if c["observation_id"] != choice["observation"]["observation_id"]:
                        excluded.append({"observation_id": c["observation_id"], "reason": "superseded"})
            for chosen in chosen_set:
                ok, why = self._authorized(chosen, principal_id)
                if not ok:
                    excluded.append({"observation_id": chosen["observation_id"], "reason": why})
                    continue
                kind = self.scope(chosen).get("source_kind", "unknown")
                if allowed_source_kinds and kind not in allowed_source_kinds:
                    excluded.append({"observation_id": chosen["observation_id"], "reason": "kind_not_allowed"})
                    continue
                # 2. scoring on authorized, eligible content only
                content = self.content(chosen)
                span_start, span_end, score = self._best_span(content, query_tokens)
                items.append({"observation_id": chosen["observation_id"], "source_id": chosen["source_id"], "source_revision": chosen["source_revision"],
                              "artifact_ref": chosen["content_ref"], "span_start": span_start, "span_end": span_end, "score_milli": score, "source_kind": kind})
        items.sort(key=lambda i: (-i["score_milli"], i["observation_id"]))
        budget, kept = max_bytes, []
        for item in items:
            size = item["span_end"] - item["span_start"]
            if len(kept) >= max_items or size > budget:
                excluded.append({"observation_id": item["observation_id"], "reason": "budget"})
                continue
            kept.append(item)
            budget -= size
        manifest = {"schema": "gabriel.retrieval-manifest/1", "manifest_id": "retrieval-" + cache_key[:24], "workspace_id": self.workspace_id,
                    "principal_id": principal_id, "task_id": task_id, "frontier": f.record(), "access_policy_revision": policy_revision,
                    "query_ref": query_ref, "allowed_source_kinds": sorted(allowed_source_kinds), "version_policy": version_policy,
                    "max_bytes": int(max_bytes), "max_items": int(max_items), "items": kept[:256], "excluded": excluded[:1024], "cache_key": cache_key, "cached": False}
        validate(manifest, "retrieval-manifest")
        ref = self.store.put(canonical(manifest), "application/json")
        self._db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?,?)", (cache_key, ref["sha256"], ref["bytes"], policy_revision, f.memory_sequence))
        return manifest

    @staticmethod
    def _best_span(content: bytes, query_tokens: set) -> tuple:
        """Lexical overlap per paragraph; the manifest cites the best paragraph's byte range."""
        if not content:
            return 0, 0, 0
        best = (0, len(content), 0)
        offset = 0
        for paragraph in content.split(b"\n\n"):
            tokens = set(_tokens(paragraph))
            score = int(1000 * len(tokens & query_tokens) / max(1, len(query_tokens))) if query_tokens else 0
            if score > best[2]:
                best = (offset, offset + len(paragraph), score)
            offset += len(paragraph) + 2
        if best[2] == 0:
            return 0, len(content), 0
        return best

    # ------------------------------------------------------------ claims
    def assert_claim(self, *, task_id: str, proposition: bytes, scope: dict, supporting: list, refuting: list, claim_id: str | None = None) -> dict:
        """A generated assertion starts unresolved: nothing but an assessment can change that."""
        prop_ref = self.store.put(proposition, "text/plain; charset=utf-8")
        scope_ref = self.store.put(canonical(dict(scope, workspace_id=self.workspace_id)), "application/json")
        claim_id = claim_id or ("claim-" + hashlib.sha256(canonical({"task": task_id, "prop": prop_ref["sha256"], "scope": scope_ref["sha256"]})).hexdigest()[:40])
        record = {"schema": "gabriel.claim/1", "claim_id": claim_id, "task_id": task_id, "proposition_ref": prop_ref,
                  "supporting_observation_ids": sorted(set(supporting)), "refuting_observation_ids": sorted(set(refuting)),
                  "assessment_status": "unresolved", "scope_ref": scope_ref, "assessment_id": None}
        seq, ref = self._append("claim", record, "claim")
        self._db.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?,?,?,?)",
                         (claim_id, seq, ref["sha256"], "unresolved", task_id, canonical(record["supporting_observation_ids"]).decode(),
                          canonical(record["refuting_observation_ids"]).decode(), None))
        return record

    def claim(self, claim_id: str) -> dict | None:
        row = self._db.execute("SELECT record_sha FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        return self._load(row[0]) if row else None

    def assess(self, claim_id: str, *, verifier_id: str, verifier_digest: str, status: str, evidence: dict, frontier, reason: str) -> dict:
        current = self.claim(claim_id)
        if current is None:
            raise GabrielError(Code.UNKNOWN_OBJECT, "unknown claim " + claim_id)
        if status not in CLAIM_STATUSES:
            raise GabrielError(Code.INVALID_SCHEMA, "unknown claim status " + status)
        f = Frontier.of(frontier)
        assessment_id = "assess-%s-%d" % (claim_id, self._meta()["count"] + 1)
        evidence_ref = self.store.put(canonical(evidence), "application/json")
        record = {"schema": "gabriel.claim-assessment/1", "assessment_id": assessment_id, "claim_id": claim_id, "verifier_id": verifier_id,
                  "verifier_digest": verifier_digest, "status": status, "frontier": f.record(), "evidence_ref": evidence_ref,
                  "supersedes": current["assessment_id"], "reason": reason[:512]}
        seq, ref = self._append("claim_assessment", record, "claim-assessment")
        self._db.execute("INSERT INTO assessments VALUES (?,?,?,?)", (assessment_id, claim_id, seq, ref["sha256"]))
        updated = dict(current, assessment_status=status, assessment_id=assessment_id)
        seq2, ref2 = self._append("claim", updated, "claim")
        self._db.execute("UPDATE claims SET seq = ?, record_sha = ?, status = ?, assessment_id = ? WHERE claim_id = ?",
                         (seq2, ref2["sha256"], status, assessment_id, claim_id))
        return record

    def verify_citations(self, citations: list, *, frontier, principal_id: str) -> dict:
        """Each citation names an observation and a quote. The reference must resolve (exists,
        available at the frontier, authorized) and the quote must occur in the cited bytes; the
        resolved byte span is retained. A syntactically valid citation alone is insufficient."""
        f = Frontier.of(frontier)
        results, ok = [], True
        for cite in citations:
            entry = {"observation_id": cite.get("observation_id"), "quote": cite.get("quote", ""), "resolved": False, "reason": None,
                     "span_start": None, "span_end": None, "source_id": None, "source_revision": None}
            observation = self.observation(cite.get("observation_id") or "")
            if observation is None:
                entry["reason"] = "unknown observation"
            elif observation["availability_sequence"] > f.memory_sequence:
                entry["reason"] = "not available at the issue frontier"
            else:
                authorized, why = self._authorized(observation, principal_id)
                if not authorized:
                    entry["reason"] = why
                else:
                    quote = cite.get("quote", "")
                    content = self.content(observation)
                    position = content.find(quote.encode("utf8")) if quote else -1
                    if position < 0:
                        entry["reason"] = "quote not found in the cited source"
                    else:
                        entry.update(resolved=True, span_start=position, span_end=position + len(quote.encode("utf8")),
                                     source_id=observation["source_id"], source_revision=observation["source_revision"])
            ok = ok and entry["resolved"]
            results.append(entry)
        return {"all_resolved": ok, "citations": results, "frontier": f.record()}

    def retract(self, observation_id: str, *, principal_id: str, reason: str) -> dict:
        """A retraction revokes access and reopens every claim that cited the source."""
        revocation = self.revoke(observation_id, principal_id=principal_id, reason=reason)
        affected = []
        for row in self._db.execute("SELECT claim_id, supporting, refuting FROM claims").fetchall():
            if observation_id in loads(row[1].encode()) or observation_id in loads(row[2].encode()):
                self.assess(row[0], verifier_id="memory.retraction", verifier_digest=sha256_hex(b"memory.retraction"), status="unresolved",
                            evidence={"retracted": observation_id, "revocation": revocation["revocation_id"]}, frontier=self.frontier(),
                            reason="cited source retracted: " + reason)
                item_id = "work-%s-%s" % (row[0], revocation["revocation_id"])
                self._db.execute("INSERT OR REPLACE INTO work_items VALUES (?,?,?,?,?,0)",
                                 (item_id, self._meta()["count"], "reassess_claim", row[0], "source %s retracted" % observation_id))
                affected.append(row[0])
        return {"revocation": revocation, "affected_claims": sorted(affected)}

    def work_items(self, resolved: bool = False) -> list:
        rows = self._db.execute("SELECT item_id, kind, subject, detail FROM work_items WHERE resolved = ? ORDER BY seq", (1 if resolved else 0,)).fetchall()
        return [{"item_id": r[0], "kind": r[1], "subject": r[2], "detail": r[3]} for r in rows]

    # ------------------------------------------------------------ outcome labels
    def record_outcome(self, *, issue_id: str, run_id: str, source_id: str, maturity_condition: dict, outcome: str, status_kind: str,
                       detail: dict | None = None, supersedes: str | None = None, label_id: str | None = None) -> dict:
        if status_kind not in PRODUCTION_STATUS_KINDS + NON_COUNTING_STATUS_KINDS:
            raise GabrielError(Code.INVALID_SCHEMA, "unknown outcome status kind " + status_kind)
        if outcome not in ("success", "failure", "inconclusive"):
            raise GabrielError(Code.INVALID_SCHEMA, "unknown outcome " + outcome)
        revision = 0
        if supersedes is not None:
            row = self._db.execute("SELECT issue_id, revision FROM labels WHERE label_id = ?", (supersedes,)).fetchone()
            if row is None:
                raise GabrielError(Code.UNKNOWN_OBJECT, "supersedes names an unknown label " + supersedes)
            if row[0] != issue_id:
                raise GabrielError(Code.INVALID_SCHEMA, "a corrected label must refer to the same issued outcome")
            revision = row[1] + 1
        seq_after = self._meta()["count"] + 1
        label_id = label_id or ("label-%s-r%d" % (issue_id, revision))
        existing = self._db.execute("SELECT status_kind, outcome, record_sha FROM labels WHERE label_id = ?", (label_id,)).fetchone()
        if existing is not None:
            # Repeated delivery of one outcome is idempotent: it never becomes a second sample.
            if (existing[0], existing[1]) != (status_kind, outcome):
                raise GabrielError(Code.INVALID_SCHEMA, "label %s already exists with a different value; a correction must supersede it" % label_id)
            return self._load(existing[2])
        label_ref = self.store.put(canonical({"outcome": outcome, "status_kind": status_kind, "detail": detail or {}}), "application/json")
        record = {"schema": "gabriel.outcome-label/1", "label_id": label_id, "issue_id": issue_id, "run_id": run_id, "source_id": source_id,
                  "revision": revision, "maturity_condition_ref": self.store.put(canonical(maturity_condition), "application/json"),
                  "label_ref": label_ref, "first_matured_sequence": seq_after, "supersedes": supersedes}
        seq, ref = self._append("outcome_label", record, "outcome-label")
        self._db.execute("INSERT INTO labels VALUES (?,?,?,?,?,?,?,?,?)", (label_id, seq, issue_id, source_id, revision, status_kind, outcome, supersedes, ref["sha256"]))
        return record

    def effective_support(self, source_id: str, frontier=None) -> dict:
        """Count each unique matured issued outcome once at its current label revision."""
        limit = Frontier.of(frontier).memory_sequence if frontier is not None else self._meta()["count"]
        rows = self._db.execute("SELECT label_id, issue_id, revision, status_kind, outcome FROM labels WHERE source_id = ? AND seq <= ? ORDER BY issue_id, revision",
                                (source_id, limit)).fetchall()
        current = {}
        for label_id, issue_id, revision, status_kind, outcome in rows:
            current[issue_id] = {"label_id": label_id, "revision": revision, "status_kind": status_kind, "outcome": outcome}
        support = refute = inconclusive = 0
        excluded = {k: 0 for k in NON_COUNTING_STATUS_KINDS}
        counted = []
        for issue_id, label in sorted(current.items()):
            if label["status_kind"] in NON_COUNTING_STATUS_KINDS:
                excluded[label["status_kind"]] += 1
                continue
            counted.append(issue_id)
            if label["outcome"] == "success":
                support += 1
            elif label["outcome"] == "failure":
                refute += 1
            else:
                inconclusive += 1
        return {"source_id": source_id, "support": support, "refute": refute, "inconclusive": inconclusive, "unique_outcomes": counted,
                "label_records": len(rows), "excluded": excluded, "current_labels": current}

    # ------------------------------------------------------------ policy promotion
    def promote(self, candidate: dict, *, held_out: dict | None, min_support: int = 1) -> dict:
        """Promotion needs held-out evidence whose task families are disjoint from the training
        manifest and whose effective support (unique matured outcomes) meets the threshold."""
        training = sorted(set(candidate["training_families"]))
        decision, reason, evaluation_ref = "rejected", "", None
        if held_out is None:
            reason = "no held-out evidence"
        elif set(held_out.get("families", [])) & set(training):
            reason = "held-out families overlap the training families: " + ",".join(sorted(set(held_out["families"]) & set(training)))
        elif not held_out.get("families"):
            reason = "held-out evidence names no task family"
        else:
            support = self.effective_support(held_out["source_id"])
            evaluation_ref = self.store.put(canonical({"held_out": held_out, "support": support}), "application/json")
            if support["support"] >= min_support and support["support"] > support["refute"]:
                decision, reason = "promoted", "held-out effective support %d > refutations %d" % (support["support"], support["refute"])
            else:
                reason = "held-out effective support %d does not exceed refutations %d (threshold %d)" % (support["support"], support["refute"], min_support)
        record = {"schema": "gabriel.policy-candidate/1", "candidate_id": candidate["candidate_id"], "policy_kind": candidate["policy_kind"],
                  "training_manifest_ref": candidate["training_manifest_ref"], "code_identity": candidate["code_identity"],
                  "config_ref": candidate["config_ref"], "metrics_ref": candidate["metrics_ref"], "training_families": training,
                  "held_out_families": sorted(set(held_out.get("families", []))) if held_out else [],
                  "promotion": {"decision": decision, "reason": reason[:512], "evaluation_ref": evaluation_ref, "decided_at_sequence": self._meta()["count"] + 1},
                  "supersedes": candidate.get("supersedes")}
        seq, ref = self._append("policy_candidate", record, "policy-candidate")
        self._db.execute("INSERT OR REPLACE INTO policies VALUES (?,?,?,?)", (record["candidate_id"], seq, ref["sha256"], decision))
        return record

    # ------------------------------------------------------------ summaries, compaction, integrity
    def summarize(self, task_id: str, text: bytes) -> dict:
        ref = self.store.put(text, "text/plain; charset=utf-8")
        self._db.execute("INSERT OR REPLACE INTO summaries VALUES (?,?,?,?)", (task_id, ref["sha256"], ref["bytes"], self._meta()["count"]))
        return ref

    def referenced_artifacts(self) -> set:
        refs = {r[0] for r in self._db.execute("SELECT record_sha FROM entries").fetchall()}
        for sha, scope in self._db.execute("SELECT content_sha, scope_sha FROM observations").fetchall():
            refs.add(sha)
            refs.add(scope)
        for row in self._db.execute("SELECT record_sha FROM entries WHERE kind IN ('claim', 'claim_assessment', 'outcome_label', 'policy_candidate', 'access_revocation', 'compaction')").fetchall():
            record = self._load(row[0])
            for key in ("proposition_ref", "scope_ref", "evidence_ref", "maturity_condition_ref", "label_ref", "reason_ref",
                        "training_manifest_ref", "config_ref", "metrics_ref"):
                if isinstance(record.get(key), dict):
                    refs.add(record[key]["sha256"])
            promo = record.get("promotion") or {}
            if isinstance(promo.get("evaluation_ref"), dict):
                refs.add(promo["evaluation_ref"]["sha256"])
        return refs

    def verify(self) -> dict:
        """Recompute the chain and check that every required byte is present and matches."""
        prev, faults, count = GENESIS, [], 0
        for seq, kind, sha, size, media, owner_seq, prev_recorded, head in self._db.execute(
                "SELECT seq, kind, record_sha, record_bytes, record_media, owner_sequence, prev, hash FROM entries ORDER BY seq").fetchall():
            count += 1
            if prev_recorded != prev:
                faults.append({"seq": seq, "fault": "chain_break"})
            expected = hashlib.sha256(("%s%s|%d|%s|%d|%s" % (CHAIN_PREFIX, kind, seq, sha, owner_seq, prev)).encode("ascii")).hexdigest()
            if expected != head:
                faults.append({"seq": seq, "fault": "hash_mismatch"})
            prev = head
        meta = self._meta()
        if meta["head"] != prev or meta["count"] != count:
            faults.append({"seq": count, "fault": "head_mismatch"})
        for sha in sorted(self.referenced_artifacts()):
            path = self.store.path_for(sha)
            try:
                raw = path.read_bytes()
            except OSError:
                faults.append({"sha256": sha, "fault": "missing"})
                continue
            if hashlib.sha256(raw).hexdigest() != sha:
                faults.append({"sha256": sha, "fault": "corrupt"})
        return {"status": "passed" if not faults else "storage_fault", "faults": faults, "entries": count, "head": meta["head"]}

    def compact(self) -> dict:
        """Drop derived rows only; verify required bytes; refuse to call it a success otherwise."""
        check = self.verify()
        retained = sorted(self.referenced_artifacts())
        cache_rows = self._db.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        summary_rows = self._db.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        self._db.execute("DELETE FROM cache")
        self._db.execute("DELETE FROM summaries")
        previous = [self._load(r[0]) for r in self._db.execute("SELECT record_sha FROM compactions ORDER BY seq").fetchall()]
        anchors = [{"memory_sequence": p["memory_sequence"], "head": p["memory_head"]} for p in previous]
        meta = self._meta()
        anchors.append({"memory_sequence": meta["count"], "head": meta["head"]})
        record = {"schema": "gabriel.compaction-manifest/1", "compaction_id": "compaction-%d" % (meta["count"] + 1), "workspace_id": self.workspace_id,
                  "memory_sequence": meta["count"], "memory_head": meta["head"], "owner_sequence": int(self._owner_sequence()),
                  "retained_artifacts": [{"sha256": sha, "bytes": self.store.path_for(sha).stat().st_size} for sha in retained if self.store.path_for(sha).is_file()][:4096],
                  "removed_derived": {"cache_entries": int(cache_rows), "summaries": int(summary_rows)},
                  "required_bytes_verified": check["status"] == "passed", "faults": check["faults"][:64], "anchors": anchors[:1024],
                  "status": "compacted" if check["status"] == "passed" else "storage_fault"}
        seq, ref = self._append("compaction", record, "compaction-manifest")
        self._db.execute("INSERT INTO compactions VALUES (?,?,?)", (record["compaction_id"], seq, ref["sha256"]))
        if check["status"] != "passed":
            raise GabrielError(Code.STORAGE_FAULT, "compaction found required bytes unavailable; recorded as a storage fault", details=record)
        return record

    def backup(self, destination) -> dict:
        target = sqlite3.connect(str(destination))
        try:
            self._db.backup(target)
        finally:
            target.close()
        return self.anchor()

    def entries(self) -> list:
        return [{"seq": r[0], "kind": r[1], "record_sha": r[2], "owner_sequence": r[3], "hash": r[4]}
                for r in self._db.execute("SELECT seq, kind, record_sha, owner_sequence, hash FROM entries ORDER BY seq").fetchall()]
