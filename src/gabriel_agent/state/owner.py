"""Single-owner SQLite journal for ``gabriel.command/1`` / ``gabriel.event/1``.

One transaction commits the event, receipt, projection, derived tables and
accounting. Model calls, filesystem tools and network requests never run
inside it. SQLite uses the DELETE rollback journal with ``synchronous=EXTRA``
and ``BEGIN IMMEDIATE`` so that a single writer is explicit.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path

from .. import CODEC_VERSION
from ..artifacts import ObjectStore
from ..contracts.codec import CodecError, canonical, digest, loads, sha256_hex
from ..contracts.errors import Code, GabrielError
from ..contracts.rules import approval_digest, event_hash
from ..contracts.schemas import (OP_TO_EVENT, payload_schema_for_op, registry_digest, validate, validate_bytes)
from ..policy import grants as grant_rules
from ..policy.principals import Credential, authenticate
from .reducer import TERMINAL_STATES, projection_digest, reduce, reducer_identity

FORMAT = "gabriel.agent-journal/1"
GENESIS = "0" * 64
CHECKPOINT_SCHEMA = "gabriel.checkpoint/2"
CHECKPOINT_STATE_SCHEMA = "gabriel.checkpoint-state/1"

_DDL = """
CREATE TABLE meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    format TEXT NOT NULL, workspace_id TEXT NOT NULL, codec_version TEXT NOT NULL,
    catalog_digest TEXT NOT NULL, schema_registry_digest TEXT NOT NULL, reducer_identity TEXT NOT NULL,
    head TEXT NOT NULL, inputs_head TEXT NOT NULL, event_count INTEGER NOT NULL,
    last_owner_time_unix_ms INTEGER NOT NULL);
CREATE TABLE principals (principal_id TEXT PRIMARY KEY, secret_sha256 TEXT NOT NULL);
CREATE TABLE grants (grant_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    task_id TEXT NOT NULL, grant_text TEXT NOT NULL, registered_owner_time_unix_ms INTEGER NOT NULL,
    revoked_at_unix_ms INTEGER);
CREATE TABLE approvals (approval_digest TEXT PRIMARY KEY, intent_id TEXT NOT NULL, principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    registered_owner_time_unix_ms INTEGER NOT NULL);
CREATE TABLE commands (command_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE, command_text TEXT NOT NULL,
    receipt_text TEXT NOT NULL);
CREATE TABLE events (sequence INTEGER PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL,
    run_revision INTEGER NOT NULL, kind TEXT NOT NULL, command_id TEXT NOT NULL UNIQUE REFERENCES commands(command_id),
    payload_sha256 TEXT NOT NULL, event_text TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,
    inputs_text TEXT NOT NULL, inputs_hash TEXT NOT NULL, projection_digest TEXT NOT NULL);
CREATE INDEX events_run_sequence ON events(run_id, sequence);
CREATE TABLE tasks (task_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, principal_id TEXT NOT NULL,
    grant_id TEXT NOT NULL REFERENCES grants(grant_id), task_spec_sha256 TEXT NOT NULL, task_spec_revision INTEGER NOT NULL,
    active_run_id TEXT NOT NULL, created_sequence INTEGER NOT NULL);
CREATE TABLE runs (run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id), run_revision INTEGER NOT NULL,
    state TEXT NOT NULL, pause_requested INTEGER NOT NULL, projection_text TEXT NOT NULL, updated_sequence INTEGER NOT NULL);
CREATE TABLE plan_nodes (run_id TEXT NOT NULL REFERENCES runs(run_id), plan_id TEXT NOT NULL, node_id TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL, PRIMARY KEY (run_id, plan_id, node_id));
CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), intent_id TEXT NOT NULL UNIQUE,
    lease_id TEXT NOT NULL UNIQUE, fencing_token INTEGER NOT NULL, step_id TEXT NOT NULL, status TEXT NOT NULL,
    effect_state TEXT NOT NULL, target_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    lease_expires_at_unix_ms INTEGER NOT NULL, capability_id TEXT NOT NULL, reconciliation TEXT NOT NULL);
CREATE INDEX attempts_target_key ON attempts(target_id, idempotency_key);
CREATE TABLE outbox (intent_id TEXT PRIMARY KEY REFERENCES attempts(intent_id), run_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    state TEXT NOT NULL, lease_id TEXT NOT NULL, lease_expires_at_unix_ms INTEGER NOT NULL);
CREATE TABLE reservations (attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id), run_id TEXT NOT NULL,
    demand_text TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE observations (observation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
    payload_sha256 TEXT NOT NULL, source_id TEXT NOT NULL, source_object_id TEXT NOT NULL, source_revision INTEGER NOT NULL,
    UNIQUE (source_id, source_object_id, source_revision));
CREATE TABLE claims (claim_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id), claim_text TEXT NOT NULL);
CREATE TABLE assessments (assessment_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
    check_id TEXT NOT NULL, outcome TEXT NOT NULL, eligible INTEGER NOT NULL, payload_sha256 TEXT NOT NULL);
CREATE TABLE artifact_refs (sha256 TEXT PRIMARY KEY, bytes INTEGER NOT NULL, media_type TEXT NOT NULL,
    first_sequence INTEGER NOT NULL);
CREATE TABLE checkpoints (checkpoint_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, head TEXT NOT NULL,
    projection_digest TEXT NOT NULL, manifest_text TEXT NOT NULL);
CREATE TABLE catalog_records (catalog_digest TEXT PRIMARY KEY, record_sha256 TEXT NOT NULL, record_bytes INTEGER NOT NULL);
"""


def _walk_refs(value, found):
    if isinstance(value, dict):
        if set(value) == {"sha256", "bytes", "media_type"}:
            found[value["sha256"]] = value
        for item in value.values():
            _walk_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _walk_refs(item, found)
    return found


def catalog_digest(catalog: dict) -> str:
    return digest({"tools": catalog.get("tools", {}), "verifiers": catalog.get("verifiers", {})})


class Owner:
    """Authoritative task/run owner. Use ``create``/``open``."""

    def __init__(self, connection, store: ObjectStore, workspace_id: str, catalog: dict, clock):
        self._db = connection
        self.store = store
        self.workspace_id = workspace_id
        self.catalog = {"tools": dict(catalog.get("tools", {})), "verifiers": dict(catalog.get("verifiers", {}))}
        self.catalog_digest = catalog_digest(self.catalog)
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._hook = None  # test-only: hook(stage) with stage before_commit/after_commit
        self._closed = False
        # identities registered in the journal (set by open; a new journal registers the running code's)
        self.registered = {"catalog_digest": self.catalog_digest, "schema_registry_digest": registry_digest(), "reducer_identity": reducer_identity()}
        self.pending_migration = None

    # ------------------------------------------------------------ lifecycle
    @staticmethod
    def _connect(path):
        db = sqlite3.connect(str(path), isolation_level=None, timeout=30, check_same_thread=False)
        try:
            mode = db.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode.lower() != "delete":
                raise GabrielError(Code.STORAGE_FAULT, "SQLite DELETE journal is required")
            db.execute("PRAGMA synchronous=EXTRA")
            db.execute("PRAGMA foreign_keys=ON")
            return db
        except BaseException:
            db.close()
            raise

    @classmethod
    def create(cls, path, store, workspace_id, catalog, *, principals: dict, clock=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise GabrielError(Code.STORAGE_FAULT, "journal already exists: " + str(path)) from exc
        os.close(fd)
        db = cls._connect(path)
        owner = cls(db, store, workspace_id, catalog, clock)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.executescript(_DDL)
            db.execute("INSERT INTO meta VALUES (1,?,?,?,?,?,?,?,?,0,0)",
                       (FORMAT, workspace_id, CODEC_VERSION, owner.catalog_digest, registry_digest(),
                        reducer_identity(), GENESIS, GENESIS))
            for principal_id, secret_sha in principals.items():
                db.execute("INSERT INTO principals VALUES (?,?)", (principal_id, secret_sha))
            owner._retain_catalog()  # the catalog in force from sequence 0: replay uses it for this epoch's events
            db.commit()
        except BaseException:
            db.close()
            path.unlink(missing_ok=True)
            raise
        return owner

    @classmethod
    def open(cls, path, store, catalog, *, clock=None, expected_anchor=None, tolerate_mismatch=False):
        """Open a journal. The registered catalog, schema registry and reducer identities must
        match the running code; otherwise an explicit migration is required (``tolerate_mismatch``
        returns the owner with ``pending_migration`` set, for the migration command only)."""
        if not Path(path).is_file():
            raise GabrielError(Code.STORAGE_FAULT, "journal does not exist: " + str(path))
        db = cls._connect(path)
        row = db.execute("SELECT format, workspace_id, codec_version, catalog_digest, schema_registry_digest, reducer_identity FROM meta").fetchone()
        if row is None or row[0] != FORMAT or row[2] != CODEC_VERSION:
            db.close()
            raise GabrielError(Code.UNSUPPORTED, "journal format or codec version is not supported")
        owner = cls(db, store, row[1], catalog, clock)
        owner.registered = {"catalog_digest": row[3], "schema_registry_digest": row[4], "reducer_identity": row[5]}
        problems = []
        if row[3] != owner.catalog_digest:
            problems.append("capability catalog differs from the registered catalog; an explicit migration is required")
        if row[4] != registry_digest():
            problems.append("schema registry differs from the journal's registry identity; an explicit migration is required")
        if row[5] != reducer_identity():
            problems.append("reducer identity differs from the journal's reducer identity; an explicit migration is required")
        owner.pending_migration = {"problems": problems, "registered": owner.registered} if problems else None
        if problems and not tolerate_mismatch:
            db.close()
            raise GabrielError(Code.UNSUPPORTED, "; ".join(problems))
        if expected_anchor is not None:
            owner.verify_anchor(expected_anchor)
        return owner

    def close(self):
        if not self._closed:
            self._db.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------ helpers
    def _meta(self):
        row = self._db.execute("SELECT head, inputs_head, event_count, last_owner_time_unix_ms FROM meta").fetchone()
        return {"head": row[0], "inputs_head": row[1], "event_count": row[2], "last_owner_time_unix_ms": row[3]}

    def owner_time(self) -> int:
        """Trusted, monotone owner time in unix milliseconds."""
        now = int(self._clock())
        last = self._meta()["last_owner_time_unix_ms"]
        return max(now, last)

    def _principals(self):
        return {row[0]: row[1] for row in self._db.execute("SELECT principal_id, secret_sha256 FROM principals")}

    def authenticate(self, credential: Credential) -> str:
        return authenticate(self._principals(), credential)

    def _grant_row(self, grant_id):
        row = self._db.execute("SELECT grant_text, revoked_at_unix_ms FROM grants WHERE grant_id=?", (grant_id,)).fetchone()
        if row is None:
            return None, None
        return loads(row[0]), row[1]

    # ------------------------------------------------------------ policy records
    def register_grant(self, grant: dict, credential: Credential) -> dict:
        validate(grant, "grant")
        principal_id = self.authenticate(credential)
        if grant["principal_id"] != principal_id:
            raise GabrielError(Code.POLICY_DENIED, "credential does not belong to the grant principal", obj=grant["grant_id"])
        if grant["workspace_id"] != self.workspace_id:
            raise GabrielError(Code.POLICY_DENIED, "grant belongs to another workspace", obj=grant["grant_id"])
        text = canonical(grant).decode("ascii")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing, _ = self._grant_row(grant["grant_id"])
            if existing is not None:
                if canonical(existing) != canonical(grant):
                    raise GabrielError(Code.ID_REUSE, "grant id reused with different bytes", obj=grant["grant_id"])
                self._db.commit()
                return grant
            if grant["parent_grant_id"] is not None:
                parent, parent_revoked = self._grant_row(grant["parent_grant_id"])
                if parent is None:
                    raise GabrielError(Code.UNKNOWN_OBJECT, "parent grant is unknown", obj=grant["parent_grant_id"])
                grant_rules.check_child_subset(parent, grant)
            self._db.execute("INSERT INTO grants VALUES (?,?,?,?,?,NULL)",
                             (grant["grant_id"], principal_id, grant["task_id"], text, self.owner_time()))
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        return grant

    def revoke_grant(self, grant_id: str, credential: Credential) -> int:
        principal_id = self.authenticate(credential)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            grant, revoked = self._grant_row(grant_id)
            if grant is None:
                raise GabrielError(Code.UNKNOWN_OBJECT, "unknown grant", obj=grant_id)
            if grant["principal_id"] != principal_id:
                raise GabrielError(Code.POLICY_DENIED, "only the grant principal may revoke", obj=grant_id)
            at = revoked if revoked is not None else self.owner_time()
            self._db.execute("UPDATE grants SET revoked_at_unix_ms=? WHERE grant_id=?", (at, grant_id))
            self._db.commit()
            return at
        except BaseException:
            self._db.rollback()
            raise

    def register_approval(self, intent: dict, credential: Credential) -> str:
        validate(intent, "intent")
        principal_id = self.authenticate(credential)
        approval = approval_digest(intent)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("INSERT OR IGNORE INTO approvals VALUES (?,?,?,?)",
                             (approval, intent["intent_id"], principal_id, self.owner_time()))
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        return approval

    def grant(self, grant_id):
        grant, revoked = self._grant_row(grant_id)
        if grant is None:
            raise GabrielError(Code.UNKNOWN_OBJECT, "unknown grant", obj=grant_id)
        return {"grant": grant, "revoked_at_unix_ms": revoked}

    # ------------------------------------------------------------ command admission
    def submit(self, command: dict, *, credential: Credential) -> dict:
        """Admit one command. The journal commit is measured as a telemetry span when a tracer is
        attached; the audit event is committed whether or not the span can be exported."""
        tracer = getattr(self, "tracer", None)
        if tracer is None:
            return self._submit_inner(command, credential=credential)
        with tracer.span("journal_commit", task_id=command.get("task_id"), run_id=command.get("run_id"), op=command.get("op")):
            return self._submit_inner(command, credential=credential)

    def _submit_inner(self, command: dict, *, credential: Credential) -> dict:
        validate(command, "command")
        command_text = canonical(command).decode("ascii")
        principal_id = self.authenticate(credential)
        if command["workspace_id"] != self.workspace_id:
            raise GabrielError(Code.POLICY_DENIED, "command belongs to another workspace", obj=command["command_id"])
        if self._closed:
            raise GabrielError(Code.STORAGE_FAULT, "owner is closed")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            found = self._db.execute("SELECT command_text, receipt_text FROM commands WHERE command_id=?",
                                     (command["command_id"],)).fetchone()
            if found is not None:
                if found[0] != command_text:
                    raise GabrielError(Code.ID_REUSE, "command id reused with different bytes", obj=command["command_id"])
                receipt = loads(found[1])
                self._db.commit()
                return receipt
            # Payload bytes are installed objects read from the store; they were installed
            # before this command referenced them.
            payload_raw = self.store.get(command["payload_ref"])
            payload = validate_bytes(payload_raw, payload_schema_for_op(command["op"]))
            task_spec_ref = None
            if command["op"] in ("admit_task", "amend_task"):
                task_spec_ref = self.store.put(canonical(payload["task"]), "application/json")
            meta = self._meta()
            owner_time = max(int(self._clock()), meta["last_owner_time_unix_ms"])
            row = self._db.execute("SELECT projection_text FROM runs WHERE run_id=?", (command["run_id"],)).fetchone()
            projection = loads(row[0]) if row else None
            if projection is None and command["op"] != "admit_task":
                raise GabrielError(Code.UNKNOWN_OBJECT, "unknown run " + command["run_id"], obj=command["run_id"])
            task = projection["task"] if projection else payload["task"]
            retained, derived = self._build_inputs(command, payload, projection, task, principal_id, owner_time, task_spec_ref)
            result = reduce(projection, command, payload, dict(retained, **derived))
            sequence = meta["event_count"] + 1
            envelope = {"schema": "gabriel.event/1", "sequence": sequence, "task_id": command["task_id"],
                        "run_id": command["run_id"], "run_revision": result.projection["run"]["run_revision"],
                        "kind": result.event_kind, "command_id": command["command_id"],
                        "payload_ref": command["payload_ref"], "previous_hash": meta["head"]}
            validate(envelope, "event")
            head = event_hash(envelope)
            inputs_text = canonical(retained).decode("ascii")
            inputs_head = sha256_hex((meta["inputs_head"] + inputs_text).encode("ascii"))
            pdigest = projection_digest(result.projection)
            receipt = {"schema": "gabriel.receipt/1", "command_id": command["command_id"], "sequence": sequence,
                       "task_id": command["task_id"], "run_id": command["run_id"],
                       "run_revision": envelope["run_revision"], "event_kind": result.event_kind,
                       "event_hash": head, "head": head, "inputs_digest": sha256_hex(inputs_text.encode("ascii")),
                       "projection_digest": pdigest, "run_state": result.run_state, "notes": result.notes[:32]}
            validate(receipt, "receipt")
            self._db.execute("INSERT INTO commands VALUES (?,?,?,?)",
                             (command["command_id"], sequence, command_text, canonical(receipt).decode("ascii")))
            self._db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (sequence, command["task_id"], command["run_id"], envelope["run_revision"], result.event_kind,
                              command["command_id"], command["payload_ref"]["sha256"], canonical(envelope).decode("ascii"),
                              head, inputs_text, inputs_head, pdigest))
            self._persist_projection(result.projection, command, sequence, task_spec_ref)
            for ref in _walk_refs(payload, {}).values():
                self._db.execute("INSERT OR IGNORE INTO artifact_refs VALUES (?,?,?,?)",
                                 (ref["sha256"], ref["bytes"], ref["media_type"], sequence))
            self._db.execute("INSERT OR IGNORE INTO artifact_refs VALUES (?,?,?,?)",
                             (command["payload_ref"]["sha256"], command["payload_ref"]["bytes"],
                              command["payload_ref"]["media_type"], sequence))
            self._db.execute("UPDATE meta SET head=?, inputs_head=?, event_count=?, last_owner_time_unix_ms=? WHERE singleton=1",
                             (head, inputs_head, sequence, owner_time))
            if self._hook:
                self._hook("before_commit")
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        if self._hook:
            self._hook("after_commit")
        return receipt

    def _build_inputs(self, command, payload, projection, task, principal_id, owner_time, task_spec_ref):
        """Retained inputs are serialized beside the event; derived inputs come from the
        catalog whose digest is retained, and from referenced immutable artifacts."""
        grant, revoked = self._grant_row(task["grant_id"])
        approvals = [r[0] for r in self._db.execute("SELECT approval_digest FROM approvals")]
        refs = _walk_refs(payload, {})
        if projection is not None:
            for entry in projection["assessments"].values():
                _walk_refs(entry["evidence_ref"], refs)
                _walk_refs(entry["input_refs"], refs)
            for node in projection["nodes"].values():
                _walk_refs(node["outputs"], refs)
                if node["result_ref"]:
                    _walk_refs(node["result_ref"], refs)
        verification = self.store.verify_all(refs.values())
        retained = {"owner_time_unix_ms": owner_time, "workspace_id": self.workspace_id, "principal_id": principal_id,
                    "payload_ref": command["payload_ref"], "grant": grant, "grant_revoked_at": revoked,
                    "approvals": sorted(approvals), "catalog_digest": self.catalog_digest,
                    "artifact_verification": verification, "task_spec_ref": task_spec_ref}
        derived = self._derived_inputs(command, payload, projection)
        return retained, derived

    def _derived_inputs(self, command, payload, projection, catalog: dict | None = None, cache: dict | None = None):
        """Inputs recomputed from the store and the catalog. ``cache`` (ADR-26) memoizes a validated
        artifact by its digest for the duration of one replay: the bytes behind a digest never
        change, so validating them once is the same work as validating them per event."""
        catalog = catalog or self.catalog
        derived = {"catalog_tools": catalog["tools"], "catalog_verifiers": catalog["verifiers"]}
        binding_ref = payload.get("binding_ref") if command["op"] == "admit_task" else (projection or {}).get("binding_ref")
        if binding_ref is not None:
            derived["binding"] = self._validated_artifact(binding_ref, "task-binding", cache)
        report_ref = payload.get("compilation_report_ref") if command["op"] in ("admit_task", "amend_task") else None
        if report_ref is not None:
            derived["compilation_report"] = self._validated_artifact(report_ref, "compilation-report", cache)
        return derived

    def _validated_artifact(self, ref: dict, schema: str, cache: dict | None):
        """The artifact behind ``ref`` parsed and validated against ``schema``, or None when it is
        missing, changed or invalid; memoized by digest in ``cache`` when one is given."""
        key = (canonical(ref), schema)  # the whole reference: a digest with another byte count or media type is another read
        if cache is not None and key in cache:
            return cache[key]
        try:
            value = validate_bytes(self.store.get(ref), schema)
        except GabrielError:
            value = None
        if cache is not None:
            cache[key] = value
        return value

    def _persist_projection(self, projection, command, sequence, task_spec_ref):
        run, task = projection["run"], projection["task"]
        if command["op"] == "admit_task":
            self._db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                             (task["task_id"], task["workspace_id"], task["principal_id"], task["grant_id"],
                              task_spec_ref["sha256"], task["task_spec_revision"], run["run_id"], sequence))
            self._db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                             (run["run_id"], task["task_id"], run["run_revision"], run["state"],
                              int(run["pause_requested"]), canonical(projection).decode("ascii"), sequence))
        else:
            if command["op"] == "amend_task":
                self._db.execute("UPDATE tasks SET task_spec_sha256=?, task_spec_revision=? WHERE task_id=?",
                                 (task_spec_ref["sha256"], task["task_spec_revision"], task["task_id"]))
            self._db.execute("UPDATE runs SET run_revision=?, state=?, pause_requested=?, projection_text=?, updated_sequence=? WHERE run_id=?",
                             (run["run_revision"], run["state"], int(run["pause_requested"]),
                              canonical(projection).decode("ascii"), sequence, run["run_id"]))
        run_id = run["run_id"]
        self._db.execute("DELETE FROM plan_nodes WHERE run_id=?", (run_id,))
        if projection["plan"]:
            for node_id, state in projection["nodes"].items():
                self._db.execute("INSERT INTO plan_nodes VALUES (?,?,?,?,?)",
                                 (run_id, projection["plan"]["plan_id"], node_id, state["status"], state["attempts"]))
        for attempt in projection["attempts"].values():
            self._db.execute("INSERT OR REPLACE INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (attempt["attempt_id"], run_id, attempt["intent_id"], attempt["lease_id"], attempt["fencing_token"],
                              attempt["step_id"], attempt["status"], attempt["effect_state"], attempt["target_id"],
                              attempt["idempotency_key"], attempt["lease_expires_at_unix_ms"], attempt["capability_id"],
                              attempt["reconciliation"]))
            self._db.execute("INSERT OR REPLACE INTO outbox VALUES (?,?,?,?,?,?)",
                             (attempt["intent_id"], run_id, attempt["attempt_id"], attempt["effect_state"],
                              attempt["lease_id"], attempt["lease_expires_at_unix_ms"]))
            self._db.execute("INSERT OR REPLACE INTO reservations VALUES (?,?,?,?)",
                             (attempt["attempt_id"], run_id, canonical(attempt["reservation"]).decode("ascii"),
                              "reserved" if attempt["status"] in ("issued", "marked") else "settled"))
        for observation_id, entry in projection["observations"].items():
            self._db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)",
                             (observation_id, run_id, entry["ref"]["sha256"], entry["source_id"], entry["source_object_id"],
                              entry["source_revision"]))
        for assessment_id, entry in projection["assessments"].items():
            self._db.execute("INSERT OR REPLACE INTO assessments VALUES (?,?,?,?,?,?)",
                             (assessment_id, run_id, entry["check_id"], entry["outcome"], int(entry["eligible"]),
                              entry["assessment_ref"]["sha256"]))

    # ------------------------------------------------------------ reads
    def projection(self, run_id: str) -> dict:
        row = self._db.execute("SELECT projection_text FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise GabrielError(Code.UNKNOWN_OBJECT, "unknown run " + run_id, obj=run_id)
        return loads(row[0])

    def run_record(self, run_id: str) -> dict:
        return self.projection(run_id)["run"]

    def task(self, task_id: str) -> dict:
        row = self._db.execute("SELECT active_run_id FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise GabrielError(Code.UNKNOWN_OBJECT, "unknown task " + task_id, obj=task_id)
        projection = self.projection(row[0])
        return {"task": projection["task"], "active_run_id": row[0], "state": projection["run"]["state"]}

    def list_tasks(self) -> list:
        return [{"task_id": r[0], "active_run_id": r[1], "state": r[2]} for r in self._db.execute(
            "SELECT t.task_id, t.active_run_id, r.state FROM tasks t JOIN runs r ON r.run_id=t.active_run_id ORDER BY t.created_sequence")]

    def events(self, run_id=None, after: int = 0) -> list:
        query = "SELECT event_text, hash, inputs_text, projection_digest FROM events WHERE sequence>?"
        args = [after]
        if run_id is not None:
            query += " AND run_id=?"
            args.append(run_id)
        return [{"event": loads(r[0]), "hash": r[1], "inputs": loads(r[2]), "projection_digest": r[3]}
                for r in self._db.execute(query + " ORDER BY sequence", args)]

    def receipt(self, command_id: str) -> dict:
        row = self._db.execute("SELECT receipt_text FROM commands WHERE command_id=?", (command_id,)).fetchone()
        if row is None:
            raise GabrielError(Code.UNKNOWN_OBJECT, "unknown command", obj=command_id)
        return loads(row[0])

    def expired_attempts(self, owner_time_unix_ms: int | None = None) -> list:
        """Marked attempts whose lease expired: possibly executed, never automatically repeated."""
        now = self.owner_time() if owner_time_unix_ms is None else owner_time_unix_ms
        return [{"attempt_id": r[0], "run_id": r[1], "intent_id": r[2], "status": r[3], "reconciliation": r[4]}
                for r in self._db.execute("SELECT attempt_id, run_id, intent_id, status, reconciliation FROM attempts "
                                          "WHERE status IN ('issued','marked') AND lease_expires_at_unix_ms<=? ORDER BY attempt_id", (now,))]

    def referenced_artifacts(self) -> set:
        return {r[0] for r in self._db.execute("SELECT sha256 FROM artifact_refs")}

    # ------------------------------------------------------------ explicit migrations (catalog, registry, reducer epochs)
    def _has_table(self, name: str) -> bool:
        return self._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _retain_catalog(self) -> dict:
        """Retain the running catalog's content under its digest (inside the caller's transaction):
        replay reproduces the events of an epoch with the catalog that was in force then."""
        ref = self.store.put(canonical(self.catalog), "application/json")
        self._db.execute("CREATE TABLE IF NOT EXISTS catalog_records (catalog_digest TEXT PRIMARY KEY, record_sha256 TEXT NOT NULL, record_bytes INTEGER NOT NULL)")
        self._db.execute("INSERT OR IGNORE INTO catalog_records VALUES (?,?,?)", (self.catalog_digest, ref["sha256"], ref["bytes"]))
        return ref

    def _catalog_for_digest(self, catalog_digest: str) -> dict | None:
        """The retained catalog content for a digest, or None for an epoch whose catalog was never retained
        (journals created before catalog records existed): such events replay with the running catalog."""
        if catalog_digest == self.catalog_digest:
            return self.catalog
        if not self._has_table("catalog_records"):
            return None
        row = self._db.execute("SELECT record_sha256, record_bytes FROM catalog_records WHERE catalog_digest=?", (catalog_digest,)).fetchone()
        if row is None:
            return None
        return loads(self.store.get({"sha256": row[0], "bytes": row[1], "media_type": "application/json"}))

    def migrations(self) -> list:
        """Every recorded migration in order; a journal created before the migrations table exists has none."""
        if not self._has_table("migrations"):
            return []
        rows = self._db.execute("SELECT record_text FROM migrations ORDER BY sequence, migration_id").fetchall()
        return [loads(r[0]) for r in rows]

    def _catalog_epochs(self, pending_from_digest: str | None = None) -> list:
        """Catalog digest in force up to and including each boundary sequence, oldest first; the
        last entry (sequence None) is the digest in force now."""
        epochs = [(m["sequence"], m["from_catalog_digest"]) for m in self.migrations()]
        if pending_from_digest is not None:
            epochs.append((self._meta()["event_count"], pending_from_digest))
        epochs.append((None, self.catalog_digest))
        return epochs

    @staticmethod
    def _catalog_digest_at(sequence: int, epochs: list) -> str:
        for boundary, digest_ in epochs:
            if boundary is None or sequence <= boundary:
                return digest_
        return epochs[-1][1]

    def record_migration(self, *, reason: str, backup_manifest_sha256: str, replayed_events: int) -> dict:
        """Record the move of this journal to the running code's identities. Only the migration
        command calls this, after a backup and a passed equivalence replay; no event is rewritten."""
        if self.pending_migration is None:
            raise GabrielError(Code.POLICY_DENIED, "nothing to migrate: the journal already matches the running code")
        meta = self._meta()
        registered = self.pending_migration["registered"]
        migration_id = "migration-%d-%s" % (len(self.migrations()) + 1, self.catalog_digest[:12])
        record = {"schema": "gabriel.migration/1", "migration_id": migration_id, "workspace_id": self.workspace_id, "sequence": meta["event_count"],
                  "from_catalog_digest": registered["catalog_digest"], "to_catalog_digest": self.catalog_digest,
                  "from_schema_registry_digest": registered["schema_registry_digest"], "to_schema_registry_digest": registry_digest(),
                  "from_reducer_identity": registered["reducer_identity"], "to_reducer_identity": reducer_identity(),
                  "backup_manifest_sha256": backup_manifest_sha256, "replayed_events": int(replayed_events),
                  "owner_time_unix_ms": self.owner_time(), "reason": reason[:1024]}
        validate(record, "migration")
        text = canonical(record).decode("ascii")
        # the record's object is stored before the row that names it: a crash in between leaves an unreferenced object,
        # never a recorded migration whose record the backup closure (ADR-25) cannot find
        self.store.put(canonical(record), "application/json")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("CREATE TABLE IF NOT EXISTS migrations (migration_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, "
                             "from_catalog TEXT NOT NULL, to_catalog TEXT NOT NULL, record_text TEXT NOT NULL)")
            self._db.execute("INSERT INTO migrations VALUES (?,?,?,?,?)", (migration_id, meta["event_count"], registered["catalog_digest"], self.catalog_digest, text))
            self._db.execute("UPDATE meta SET catalog_digest=?, schema_registry_digest=?, reducer_identity=? WHERE singleton=1",
                             (self.catalog_digest, registry_digest(), reducer_identity()))
            self._retain_catalog()  # events from here on replay with this catalog; earlier epochs keep theirs
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        self.registered = {"catalog_digest": self.catalog_digest, "schema_registry_digest": registry_digest(), "reducer_identity": reducer_identity()}
        self.pending_migration = None
        return record

    # ------------------------------------------------------------ anchors, replay, checkpoints
    def anchor(self) -> dict:
        meta = self._meta()
        anchor = {"schema": "gabriel.anchor/1", "workspace_id": self.workspace_id, "sequence": meta["event_count"],
                  "head": meta["head"], "inputs_head": meta["inputs_head"]}
        return validate(anchor, "anchor")

    def verify_anchor(self, anchor: dict) -> dict:
        validate(anchor, "anchor")
        meta = self._meta()
        if anchor["workspace_id"] != self.workspace_id:
            raise GabrielError(Code.STORAGE_FAULT, "anchor belongs to another workspace")
        if anchor["sequence"] > meta["event_count"]:
            raise GabrielError(Code.STORAGE_FAULT, "journal is shorter than the retained anchor: suffix deleted or replaced")
        row = self._db.execute("SELECT hash, inputs_hash FROM events WHERE sequence=?", (anchor["sequence"],)).fetchone()
        head, inputs_head = (row if row else (GENESIS, GENESIS))
        if head != anchor["head"] or inputs_head != anchor["inputs_head"]:
            raise GabrielError(Code.STORAGE_FAULT, "journal head at the anchored sequence differs from the retained anchor")
        return {"status": "passed", "anchored_sequence": anchor["sequence"], "current_sequence": meta["event_count"]}

    def replay(self, *, expected_anchor=None, pending_from_digest: str | None = None, from_checkpoint: bool = False,
               record_checkpoint: str | None = None, reason: str | None = None) -> dict:
        """Recorded replay: verify the chain and references, re-run the pure reducer over
        retained payloads and inputs, compare every projection digest. No port is called.
        ``pending_from_digest`` is the equivalence check of a migration: every retained event
        still carries the registered catalog digest while the running code's catalog differs.

        ADR-26: with ``from_checkpoint`` the replay starts from the latest usable verified
        checkpoint (its identities and epoch current, its binding intact): both hash chains are
        still verified over every event, but only the events after the checkpoint are reduced,
        from the checkpoint's retained state. Without it the replay starts from genesis and
        verifies every checkpoint it passes against the state it reproduced. With
        ``record_checkpoint`` the state the replay reached is retained as a new checkpoint
        named by that id, verified from genesis or from the checkpoint it started at."""
        if expected_anchor is not None:
            self.verify_anchor(expected_anchor)
        epochs = self._catalog_epochs(pending_from_digest)
        catalogs, artifacts = {}, {}
        head, inputs_head, count = GENESIS, GENESIS, 0
        projections, digests, missing_refs, verified_refs = {}, {}, [], 0
        start, skipped, state = None, [], {}
        if from_checkpoint:
            start, skipped = self._usable_checkpoint(epochs)
        if start is not None:
            state = self._checkpoint_state(start, check_bytes=True)
            digests = {run_id: ref["sha256"] for run_id, ref in state.items()}
        boundary = start["sequence"] if start is not None else 0
        pending = {}  # sequence -> the checkpoints recorded there (several replays may record at the same head)
        for manifest in self.checkpoints():
            after_start = manifest["sequence"] > boundary or (start is None and manifest["sequence"] == 0)
            if manifest["schema"] == CHECKPOINT_SCHEMA and after_start:
                pending.setdefault(manifest["sequence"], []).append(manifest)
        verified_checkpoints = []
        prefix_head, prefix_inputs_head, prefix_count = GENESIS, GENESIS, 0
        recorded = None
        self._db.execute("BEGIN IMMEDIATE" if record_checkpoint else "BEGIN")
        try:
            for manifest in pending.pop(0, ()):
                # a checkpoint of the empty journal binds the empty state and the genesis heads
                self._verify_checkpoint_state(manifest, {}, GENESIS, GENESIS)
                verified_checkpoints.append(manifest["checkpoint_id"])
            rows = self._db.execute("SELECT sequence, event_text, hash, inputs_text, inputs_hash, projection_digest, command_id FROM events ORDER BY sequence").fetchall()
            for sequence, event_text, stored_hash, inputs_text, stored_inputs_hash, stored_pdigest, command_id in rows:
                envelope = loads(event_text)
                if sequence <= boundary:
                    # the prefix the checkpoint already verified: both chains and the retained epoch are checked, nothing is
                    # reduced and no payload is read (the audit from genesis does both)
                    if sequence != prefix_count + 1 or envelope["sequence"] != sequence or envelope["previous_hash"] != prefix_head:
                        raise GabrielError(Code.STORAGE_FAULT, "event chain order mismatch at %d" % sequence)
                    if event_hash(envelope) != stored_hash:
                        raise GabrielError(Code.STORAGE_FAULT, "event hash mismatch at %d" % sequence)
                    if sha256_hex((prefix_inputs_head + inputs_text).encode("ascii")) != stored_inputs_hash:
                        raise GabrielError(Code.STORAGE_FAULT, "inputs chain mismatch at %d" % sequence)
                    if loads(inputs_text)["catalog_digest"] != self._catalog_digest_at(sequence, epochs):
                        raise GabrielError(Code.UNSUPPORTED, "catalog differs from the retained catalog digest at %d" % sequence)
                    prefix_head, prefix_inputs_head, prefix_count = stored_hash, stored_inputs_hash, sequence
                    if sequence == boundary:
                        if (prefix_head, prefix_inputs_head) != (start["head"], start["inputs_head"]):
                            raise GabrielError(Code.STORAGE_FAULT, "journal chains at the checkpoint differ from the checkpoint binding")
                        head, inputs_head, count = prefix_head, prefix_inputs_head, prefix_count
                    continue
                validate(envelope, "event")
                if sequence != count + 1 or envelope["sequence"] != sequence or envelope["previous_hash"] != head:
                    raise GabrielError(Code.STORAGE_FAULT, "event chain order mismatch at %d" % sequence)
                if event_hash(envelope) != stored_hash:
                    raise GabrielError(Code.STORAGE_FAULT, "event hash mismatch at %d" % sequence)
                computed_inputs_hash = sha256_hex((inputs_head + inputs_text).encode("ascii"))
                if computed_inputs_hash != stored_inputs_hash:
                    raise GabrielError(Code.STORAGE_FAULT, "inputs chain mismatch at %d" % sequence)
                crow = self._db.execute("SELECT command_text FROM commands WHERE command_id=?", (command_id,)).fetchone()
                if crow is None:
                    raise GabrielError(Code.STORAGE_FAULT, "command of event %d is missing" % sequence)
                command = loads(crow[0])
                validate(command, "command")
                if OP_TO_EVENT[command["op"]] != envelope["kind"] or canonical(command["payload_ref"]) != canonical(envelope["payload_ref"]):
                    raise GabrielError(Code.STORAGE_FAULT, "event does not match its command at %d" % sequence)
                payload = validate_bytes(self.store.get(command["payload_ref"]), payload_schema_for_op(command["op"]))
                verified_refs += 1
                retained = loads(inputs_text)
                epoch_digest = self._catalog_digest_at(sequence, epochs)
                if retained["catalog_digest"] != epoch_digest:
                    raise GabrielError(Code.UNSUPPORTED, "catalog differs from the retained catalog digest at %d" % sequence)
                # the catalog in force at this sequence, when retained; otherwise the running catalog has to reproduce the event
                if epoch_digest not in catalogs:
                    catalogs[epoch_digest] = self._catalog_for_digest(epoch_digest)
                run_id = command["run_id"]
                if run_id not in projections and run_id in state:
                    # the run's projection as of the checkpoint, from its retained object (bytes verified by the store)
                    projections[run_id] = loads(self.store.get(state[run_id]))
                derived = self._derived_inputs(command, payload, projections.get(run_id), catalog=catalogs[epoch_digest], cache=artifacts)
                result = reduce(projections.get(run_id), command, payload, dict(retained, **derived))
                pdigest = projection_digest(result.projection)
                if pdigest != stored_pdigest:
                    raise GabrielError(Code.STORAGE_FAULT, "replayed projection differs at %d" % sequence)
                projections[run_id] = result.projection
                digests[run_id] = pdigest
                head, inputs_head, count = stored_hash, stored_inputs_hash, sequence
                for manifest in pending.get(sequence, ()):
                    # a checkpoint recorded at this sequence must bind exactly the chains and the state the replay reached here
                    self._verify_checkpoint_state(manifest, digests, head, inputs_head)
                    verified_checkpoints.append(manifest["checkpoint_id"])
            if start is not None and prefix_count != boundary:
                raise GabrielError(Code.STORAGE_FAULT, "journal is shorter than the checkpoint it names")
            meta = self._meta()
            if (meta["head"], meta["inputs_head"], meta["event_count"]) != (head, inputs_head, count):
                raise GabrielError(Code.STORAGE_FAULT, "journal metadata disagrees with replay")
            for run_id, expected in digests.items():
                row = self._db.execute("SELECT projection_text FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if row is None or projection_digest(loads(row[0])) != expected:
                    raise GabrielError(Code.STORAGE_FAULT, "stored projection for %s disagrees with replay" % run_id)
            for sha in self.referenced_artifacts():
                if not self.store.path_for(sha).is_file():
                    missing_refs.append(sha)
            if record_checkpoint is not None and not missing_refs:
                recorded = self._record_checkpoint(record_checkpoint, projections, state, head, inputs_head, count, epochs,
                                                   verified_from=start["checkpoint_id"] if start is not None else "genesis",
                                                   events_reduced=count - boundary, reason=reason or "")
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        return {"status": "passed" if not missing_refs else "storage_fault", "events": count, "head": head,
                "inputs_head": inputs_head, "runs": len(digests), "payloads_verified": verified_refs,
                "missing_referenced_artifacts": missing_refs, "external_calls": 0,
                "anchor_checked": expected_anchor is not None,
                "checkpoint": None if start is None else {"checkpoint_id": start["checkpoint_id"], "sequence": start["sequence"],
                                                           "verified_from": start["verified_from"]},
                "checkpoints_skipped": skipped, "events_reduced": count - boundary, "checkpoints_verified": verified_checkpoints,
                "checkpoint_recorded": recorded}

    # ------------------------------------------------------------ verified state checkpoints (ADR-26)
    def checkpoints(self) -> list:
        """Every retained checkpoint manifest, oldest first."""
        rows = self._db.execute("SELECT manifest_text FROM checkpoints ORDER BY sequence, checkpoint_id").fetchall()
        manifests = [loads(r[0]) for r in rows]
        # the latest at a sequence is the one recorded last (several replays may record at the same head)
        return sorted(manifests, key=lambda m: (m["sequence"], m.get("created_owner_time_unix_ms", 0), m["checkpoint_id"]))

    def _usable_checkpoint(self, epochs: list):
        """The latest checkpoint a replay may start from, and why the later ones cannot be used: a
        checkpoint is usable while the reducer, the schema registry, the codec and the catalog of its
        epoch read the same as the running code's, the journal still carries its sequence and the
        chains at that sequence still carry its binding."""
        meta = self._meta()
        skipped = []
        for manifest in reversed(self.checkpoints()):
            reason = None
            if manifest.get("schema") != CHECKPOINT_SCHEMA:
                reason = "a checkpoint of an earlier contract without a retained state"
            elif manifest["reducer_identity"] != reducer_identity() or manifest["schema_registry_digest"] != registry_digest() \
                    or manifest["codec_version"] != CODEC_VERSION:
                reason = "produced by a different reducer, schema registry or codec"
            elif manifest["sequence"] > meta["event_count"]:
                reason = "the journal is shorter than its sequence"
            elif manifest["catalog_digest"] != self._catalog_digest_at(manifest["sequence"], epochs):
                reason = "the catalog of its epoch reads differently now"
            else:
                try:
                    self.verify_anchor({"schema": "gabriel.anchor/1", "workspace_id": self.workspace_id, "sequence": manifest["sequence"],
                                        "head": manifest["head"], "inputs_head": manifest["inputs_head"]})
                except GabrielError as exc:
                    reason = "its binding no longer matches the journal: " + exc.message
            if reason is None:
                return manifest, skipped
            skipped.append({"checkpoint_id": manifest["checkpoint_id"], "sequence": manifest["sequence"], "reason": reason})
        return None, skipped

    def _checkpoint_state(self, manifest: dict, *, check_bytes: bool) -> dict:
        """The retained state of a checkpoint: run id to the reference of its projection object. With
        ``check_bytes`` every projection object is read and verified against its reference (the
        store's byte check), so a missing or changed one is a fault before anything trusts the state."""
        state = validate(loads(self.store.get(manifest["state_ref"])), "checkpoint-state")
        if state["checkpoint_id"] != manifest["checkpoint_id"] or state["workspace_id"] != self.workspace_id or state["sequence"] != manifest["sequence"]:
            raise GabrielError(Code.STORAGE_FAULT, "checkpoint state does not belong to the checkpoint that names it")
        if digest({run_id: ref["sha256"] for run_id, ref in state["runs"].items()}) != manifest["projection_digest"]:
            raise GabrielError(Code.STORAGE_FAULT, "checkpoint state does not match the checkpoint's projection digest")
        if check_bytes:
            for run_id, ref in state["runs"].items():
                try:
                    self.store.get(ref)
                except GabrielError as exc:
                    raise GabrielError(Code.STORAGE_FAULT, "checkpoint %s names a projection object of %s that is missing or changed: %s"
                                       % (manifest["checkpoint_id"], run_id, exc.message)) from exc
        return state["runs"]

    def _verify_checkpoint_state(self, manifest: dict, digests: dict, head: str, inputs_head: str) -> None:
        """The audit's check of a checkpoint it passes: its binding is the chains the replay just verified
        at its sequence, its state is the state the replay reached, and every state object is intact."""
        if manifest["workspace_id"] != self.workspace_id or manifest["head"] != head or manifest["inputs_head"] != inputs_head:
            raise GabrielError(Code.STORAGE_FAULT, "checkpoint %s does not bind the chains at %d" % (manifest["checkpoint_id"], manifest["sequence"]))
        state = self._checkpoint_state(manifest, check_bytes=True)
        expected = {run_id: ref["sha256"] for run_id, ref in state.items()}
        if expected != digests:
            raise GabrielError(Code.STORAGE_FAULT, "checkpoint %s does not bind the state the replay reached at %d"
                               % (manifest["checkpoint_id"], manifest["sequence"]))

    def _record_checkpoint(self, checkpoint_id: str, projections: dict, state: dict, head: str, inputs_head: str, count: int,
                           epochs: list, *, verified_from: str, events_reduced: int, reason: str) -> dict:
        """Retain the state a verifying replay reached (inside the replay's transaction): one object per
        run projection (its sha256 is the run's projection digest; an unchanged run's object is the one
        the previous checkpoint named), a state object listing them, and the manifest row."""
        runs = {}
        for run_id in sorted(set(projections) | set(state)):
            if run_id in projections:
                runs[run_id] = self.store.put(canonical(projections[run_id]), "application/json")
            else:
                runs[run_id] = state[run_id]
        state_record = {"schema": CHECKPOINT_STATE_SCHEMA, "checkpoint_id": checkpoint_id, "workspace_id": self.workspace_id,
                        "sequence": count, "runs": runs}
        validate(state_record, "checkpoint-state")
        state_ref = self.store.put(canonical(state_record), "application/json")
        manifest = {"schema": CHECKPOINT_SCHEMA, "checkpoint_id": checkpoint_id, "workspace_id": self.workspace_id,
                    "sequence": count, "head": head, "inputs_head": inputs_head,
                    "projection_digest": digest({run_id: ref["sha256"] for run_id, ref in runs.items()}), "state_ref": state_ref,
                    "run_count": len(runs), "catalog_digest": self._catalog_digest_at(count, epochs), "reducer_identity": reducer_identity(),
                    "schema_registry_digest": registry_digest(), "codec_version": CODEC_VERSION, "created_owner_time_unix_ms": self.owner_time(),
                    "verified_from": verified_from, "events_reduced": int(events_reduced), "reason": reason[:1024]}
        validate(manifest, "checkpoint")
        try:
            self._db.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?)",
                             (checkpoint_id, count, head, manifest["projection_digest"], canonical(manifest).decode("ascii")))
        except sqlite3.IntegrityError as exc:
            raise GabrielError(Code.ID_REUSE, "checkpoint id already used", obj=checkpoint_id) from exc
        return manifest

    def verify_checkpoint(self, manifest: dict, projections: dict | None = None) -> dict:
        """A checkpoint is trusted only when its identities are current, its binding matches the
        retained journal and its state object is intact; a supplied projection is trusted only
        when the state binds its digest."""
        validate(manifest, "checkpoint")
        if manifest["workspace_id"] != self.workspace_id:
            raise GabrielError(Code.STORAGE_FAULT, "checkpoint belongs to another workspace")
        if manifest["reducer_identity"] != reducer_identity() or manifest["schema_registry_digest"] != registry_digest():
            raise GabrielError(Code.UNSUPPORTED, "checkpoint was produced by a different reducer or schema registry")
        self.verify_anchor({"schema": "gabriel.anchor/1", "workspace_id": self.workspace_id, "sequence": manifest["sequence"],
                            "head": manifest["head"], "inputs_head": manifest["inputs_head"]})
        if manifest["catalog_digest"] != self._catalog_digest_at(manifest["sequence"], self._catalog_epochs()):
            raise GabrielError(Code.UNSUPPORTED, "checkpoint names a catalog that is not the one of its epoch")
        state = self._checkpoint_state(manifest, check_bytes=True)
        for run_id, projection in (projections or {}).items():
            if run_id not in state or projection_digest(projection) != state[run_id]["sha256"]:
                raise GabrielError(Code.STORAGE_FAULT, "supplied projection does not match the checkpoint binding; replay from genesis instead")
        return {"status": "passed", "sequence": manifest["sequence"], "runs": len(state)}

    def backup(self, destination) -> dict:
        """Coherent snapshot through SQLite's online backup API, never a raw file copy."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination))
        try:
            self._db.backup(target)
        finally:
            target.close()
        return {"database": str(destination), "anchor": self.anchor()}
