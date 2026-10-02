"""Single-process API over a serialized SQLite operational journal.

Each accepted unique command, reducer state, result and accounting change shares
one SQLite transaction. Replay adapters are trusted local deterministic code,
not sandboxed plugins. Hashes are integrity identifiers, not authentication.
"""
import os
from pathlib import Path
import sqlite3

from .canonical import MAX_INTEGER, canonical, digest, loads

DEFAULT_LIMITS = {"max_events": 10000, "max_bytes": 10000000,
                  "max_command_bytes": 65536}
COMMAND_FIELDS = {"id", "contract", "op", "at", "expected_head", "payload"}
RECORD_FIELDS = {"sequence", "command", "prior_head", "pre_state_hash",
                 "post_state_hash", "result", "hash"}


def _clone(value):
    return loads(canonical(value))


def _identifier(value):
    if (type(value) is not str or not 1 <= len(value) <= 128
            or any(not 33 <= ord(ch) <= 126 for ch in value)):
        raise ValueError("identifier must contain 1..128 visible ASCII characters")


def _integer(value, name):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise ValueError(name + " must be an exact nonnegative integer")


def _hash(value):
    if (type(value) is not str or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)):
        raise ValueError("invalid SHA-256 identifier")


def _command(value):
    text = canonical(value)
    if type(value) is not dict or set(value) != COMMAND_FIELDS:
        raise ValueError("command fields do not match schema")
    for name in ("id", "contract", "op"):
        _identifier(value[name])
    _integer(value["at"], "at")
    _hash(value["expected_head"])
    if type(value["payload"]) is not dict:
        raise ValueError("payload must be an exact JSON object")
    return text


def _limits(value):
    if value is None:
        return dict(DEFAULT_LIMITS)
    canonical(value)
    if type(value) is not dict or not set(value) <= set(DEFAULT_LIMITS):
        raise ValueError("unknown budget limit")
    result = dict(DEFAULT_LIMITS)
    result.update(value)
    for name, number in result.items():
        _integer(number, name)
    return result


def _registry(value):
    if type(value) is not dict or not value:
        raise ValueError("registry must be a nonempty exact dict")
    result = {}
    for name, adapter in value.items():
        _identifier(name)
        for method in ("fingerprint", "initialize", "apply", "view"):
            if not callable(getattr(adapter, method, None)):
                raise ValueError("adapter does not implement " + method)
        result[name] = _clone(adapter.fingerprint())
    return result


def _stored(text):
    value = loads(text)
    if canonical(value) != text:
        raise ValueError("stored JSON is not canonical")
    return value


class Store:
    """Atomic reference owner. Use create/open rather than direct construction."""

    def __init__(self, connection, registry):
        self._db = connection
        self._registry = dict(registry)
        self._closed = False

    @staticmethod
    def _connect(path):
        db = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        try:
            mode = db.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode.lower() != "delete":
                raise ValueError("SQLite DELETE journal is required")
            # EXTRA includes the directory synchronization required after a
            # DELETE rollback journal is unlinked. Actual power-loss durability
            # still depends on SQLite's VFS and storage honoring synchronization.
            db.execute("PRAGMA synchronous=EXTRA")
            db.execute("PRAGMA foreign_keys=ON")
            return db
        except BaseException:
            db.close()
            raise

    @classmethod
    def create(cls, path, registry, limits=None):
        fingerprints = _registry(registry)
        header = {"format": "gabriel-runtime/v1", "registry": fingerprints,
                  "limits": _limits(limits)}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ValueError("store already exists") from exc
        os.close(descriptor)
        db = None
        try:
            db = cls._connect(path)
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    header_text TEXT NOT NULL, head TEXT NOT NULL,
                    event_count INTEGER NOT NULL, byte_count INTEGER NOT NULL,
                    last_at INTEGER NOT NULL);
                CREATE TABLE contracts (
                    contract_id TEXT PRIMARY KEY, adapter TEXT NOT NULL,
                    config_text TEXT NOT NULL, state_text TEXT NOT NULL);
                CREATE TABLE journal (
                    sequence INTEGER PRIMARY KEY,
                    command_id TEXT NOT NULL UNIQUE, contract_id TEXT NOT NULL,
                    command_text TEXT NOT NULL, record_text TEXT NOT NULL,
                    receipt_text TEXT NOT NULL);
            """)
            db.execute("INSERT INTO meta VALUES (1,?,?,?,?,?)",
                       (canonical(header), digest(header), 0, 0, -1))
            db.commit()
            return cls(db, registry)
        except BaseException:
            if db is not None:
                db.close()
            path.unlink(missing_ok=True)
            Path(str(path) + "-journal").unlink(missing_ok=True)
            raise

    @classmethod
    def open(cls, path, registry, expected_head=None, expected_events=None):
        if not Path(path).is_file():
            raise ValueError("store does not exist")
        store = cls(cls._connect(path), registry)
        try:
            store.audit(expected_head=expected_head, expected_events=expected_events)
            return store
        except BaseException:
            store.close()
            raise

    def _meta(self):
        if self._closed:
            raise ValueError("store is closed")
        rows = self._db.execute("SELECT header_text,head,event_count,byte_count,last_at "
                                "FROM meta").fetchall()
        if len(rows) != 1:
            raise ValueError("invalid metadata row count")
        return rows[0]

    def _header(self, text):
        header = _stored(text)
        if (type(header) is not dict or set(header) != {"format", "registry", "limits"}
                or header["format"] != "gabriel-runtime/v1"
                or canonical(header["registry"]) != canonical(_registry(self._registry))
                or canonical(header["limits"]) != canonical(_limits(header["limits"]))):
            raise ValueError("header or adapter fingerprint mismatch")
        return header

    @property
    def head(self):
        return self._meta()[1]

    @property
    def budget(self):
        meta = self._meta()
        return {"events": meta[2], "bytes": meta[3]}

    def _transition(self, command, bindings):
        contract = command["contract"]
        if command["op"] == "bind":
            if contract in bindings:
                raise ValueError("contract binding is immutable")
            payload = command["payload"]
            if set(payload) != {"adapter", "config"}:
                raise ValueError("bind requires exactly adapter and config")
            name = payload["adapter"]
            _identifier(name)
            if name not in self._registry:
                raise ValueError("unknown adapter")
            adapter = self._registry[name]
            state = _clone(adapter.initialize(_clone(payload["config"])))
            result = _clone(adapter.view(_clone(state)))
            if type(result) is not dict:
                raise ValueError("adapter view must be a JSON object")
            return {"adapter": name, "config": _clone(payload["config"]),
                    "state": state}, None, result
        if contract not in bindings:
            raise ValueError("unknown contract")
        previous = bindings[contract]
        adapter = self._registry[previous["adapter"]]
        pre_hash = digest(previous["state"])
        pair = adapter.apply(_clone(previous["state"]), command["op"],
                             _clone(command["payload"]), command["at"])
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise ValueError("adapter apply must return state and result")
        state, result = pair
        binding = {"adapter": previous["adapter"],
                   "config": _clone(previous["config"]), "state": _clone(state)}
        return binding, pre_hash, _clone(result)

    def submit(self, command):
        command_text = _command(command)
        command = loads(command_text)
        if self._closed:
            raise ValueError("store is closed")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            found = self._db.execute("SELECT command_text,receipt_text FROM journal "
                                     "WHERE command_id=?", (command["id"],)).fetchone()
            if found is not None:
                if found[0] != command_text:
                    raise ValueError("conflicting command id reuse")
                receipt = _stored(found[1])
                self._db.commit()
                return receipt
            header_text, head, count, byte_count, last_at = self._meta()
            header = self._header(header_text)
            limits = header["limits"]
            size = len(command_text.encode("ascii"))
            if command["expected_head"] != head:
                raise ValueError("stale expected journal head")
            if command["at"] < last_at:
                raise ValueError("backdated owner receipt time")
            if (size > limits["max_command_bytes"] or count + 1 > limits["max_events"]
                    or byte_count + size > limits["max_bytes"]):
                raise ValueError("journal budget exceeded")
            row = self._db.execute("SELECT adapter,config_text,state_text FROM contracts "
                                  "WHERE contract_id=?", (command["contract"],)).fetchone()
            bindings = {}
            if row is not None:
                bindings[command["contract"]] = {
                    "adapter": row[0], "config": _stored(row[1]), "state": _stored(row[2])}
            try:
                binding, pre_hash, result = self._transition(command, bindings)
            except Exception as exc:
                raise ValueError("adapter transition rejected: " + str(exc)) from exc
            record = {"sequence": count + 1, "command": command, "prior_head": head,
                      "pre_state_hash": pre_hash, "post_state_hash": digest(binding["state"]),
                      "result": result}
            record["hash"] = digest(record)
            receipt = {"sequence": count + 1, "command_id": command["id"],
                       "contract": command["contract"], "result": result,
                       "head": record["hash"]}
            self._db.execute("INSERT INTO contracts VALUES (?,?,?,?) "
                             "ON CONFLICT(contract_id) DO UPDATE SET state_text=excluded.state_text",
                             (command["contract"], binding["adapter"],
                              canonical(binding["config"]), canonical(binding["state"])))
            self._db.execute("INSERT INTO journal VALUES (?,?,?,?,?,?)",
                             (count + 1, command["id"], command["contract"], command_text,
                              canonical(record), canonical(receipt)))
            self._db.execute("UPDATE meta SET head=?,event_count=?,byte_count=?,last_at=? "
                             "WHERE singleton=1", (record["hash"], count + 1,
                                                  byte_count + size, command["at"]))
            hook = getattr(self, "_test_hook", None)
            if hook is not None:
                hook("before_commit")
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        hook = getattr(self, "_test_hook", None)
        if hook is not None:
            hook("after_commit")
        return _clone(receipt)

    def view(self, contract_id):
        _identifier(contract_id)
        if self._closed:
            raise ValueError("store is closed")
        row = self._db.execute("SELECT adapter,state_text FROM contracts WHERE contract_id=?",
                               (contract_id,)).fetchone()
        if row is None:
            raise ValueError("unknown contract")
        result = _clone(self._registry[row[0]].view(_clone(_stored(row[1]))))
        if type(result) is not dict:
            raise ValueError("adapter view must be a JSON object")
        return result

    def audit(self, expected_head=None, expected_events=None):
        """Replay all semantics and storage. Optional external anchors detect a
        valid truncated prefix; a self-consistent journal alone cannot do so.
        """
        if expected_head is not None:
            _hash(expected_head)
        if expected_events is not None:
            _integer(expected_events, "expected_events")
        if self._closed:
            raise ValueError("store is closed")
        self._db.execute("BEGIN")
        try:
            result = self._audit(expected_head, expected_events)
            self._db.commit()
            return result
        except BaseException:
            self._db.rollback()
            raise

    def _audit(self, expected_head, expected_events):
        mode = self._db.execute("PRAGMA journal_mode").fetchone()[0].lower()
        synchronous = self._db.execute("PRAGMA synchronous").fetchone()[0]
        if mode != "delete" or synchronous != 3:
            raise ValueError("required SQLite journal/synchronization settings are absent")
        header_text, final_head, final_count, final_bytes, final_at = self._meta()
        header = self._header(header_text)
        head, count, byte_count, last_at = digest(header), 0, 0, -1
        bindings, ids = {}, set()
        limits = header["limits"]
        for seq, command_id, contract_id, command_text, record_text, receipt_text in self._db.execute(
                "SELECT sequence,command_id,contract_id,command_text,record_text,receipt_text "
                "FROM journal ORDER BY sequence"):
            command, record, receipt = map(_stored, (command_text, record_text, receipt_text))
            _command(command)
            if (type(record) is not dict or set(record) != RECORD_FIELDS
                    or seq != count + 1 or command_id != command["id"]
                    or contract_id != command["contract"] or command_id in ids
                    or command["expected_head"] != head or command["at"] < last_at):
                raise ValueError("journal order or command identity mismatch")
            size = len(command_text.encode("ascii"))
            if (size > limits["max_command_bytes"] or count + 1 > limits["max_events"]
                    or byte_count + size > limits["max_bytes"]):
                raise ValueError("replayed budget exceeds header limits")
            try:
                binding, pre_hash, result = self._transition(command, bindings)
            except Exception as exc:
                raise ValueError("semantic replay rejected: " + str(exc)) from exc
            expected_record = {"sequence": count + 1, "command": command,
                               "prior_head": head, "pre_state_hash": pre_hash,
                               "post_state_hash": digest(binding["state"]), "result": result}
            expected_record["hash"] = digest(expected_record)
            expected_receipt = {"sequence": count + 1, "command_id": command_id,
                                "contract": contract_id, "result": result,
                                "head": expected_record["hash"]}
            if (canonical(record) != canonical(expected_record)
                    or canonical(receipt) != canonical(expected_receipt)):
                raise ValueError("semantic record or receipt mismatch")
            bindings[contract_id] = binding
            ids.add(command_id)
            head = expected_record["hash"]
            count += 1
            byte_count += size
            last_at = command["at"]
        stored_bindings = {}
        for contract, name, config_text, state_text in self._db.execute(
                "SELECT contract_id,adapter,config_text,state_text FROM contracts"):
            if contract in stored_bindings:
                raise ValueError("duplicate contract")
            stored_bindings[contract] = {"adapter": name, "config": _stored(config_text),
                                         "state": _stored(state_text)}
        if canonical(stored_bindings) != canonical(bindings):
            raise ValueError("stored bindings or states disagree with replay")
        # Comparing canonical representations also distinguishes SQL values that
        # are numerically equal but have the wrong storage type.
        actual_meta = [final_head, final_count, final_bytes, final_at]
        wanted_meta = [head, count, byte_count, last_at]
        if canonical(actual_meta) != canonical(wanted_meta):
            raise ValueError("journal metadata disagrees with replay")
        if expected_head is not None and head != expected_head:
            raise ValueError("external expected head mismatch")
        if expected_events is not None and count != expected_events:
            raise ValueError("external expected event count mismatch")
        return {"status": "passed", "head": head, "events": count, "bytes": byte_count,
                "contracts": len(bindings), "semantic_replay": True,
                "journal_mode": mode, "synchronous": synchronous,
                "external_anchor_checked": expected_head is not None or expected_events is not None}

    def export(self):
        if self._closed:
            raise ValueError("store is closed")
        self._db.execute("BEGIN")
        try:
            header = _stored(self._meta()[0])
            records = [_stored(row[0]) for row in self._db.execute(
                "SELECT record_text FROM journal ORDER BY sequence")]
            self._db.commit()
            return {"header": header, "records": records}
        except BaseException:
            self._db.rollback()
            raise

    def close(self):
        if not self._closed:
            self._db.close()
            self._closed = True

    def __enter__(self):
        if self._closed:
            raise ValueError("store is closed")
        return self

    def __exit__(self, *_):
        self.close()
