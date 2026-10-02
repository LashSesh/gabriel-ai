"""Semantics-preserving materialization alternative for the SQLite owner.

The reference Store remains the wire-format and transition specification.  This
implementation replaces redundant JSON round trips by checked structural copies
and reuses already validated canonical text for state hashing and persistence.
It retains one durable transaction per command and complete semantic replay.
"""
from __future__ import annotations

import hashlib

from .canonical import MAX_DEPTH, MAX_INTEGER, canonical, loads
from .engine import Store, _command, _identifier, _stored


def checked_clone(value):
    """Match ``loads(canonical(value))`` on the exact Gabriel JSON domain.

    Dictionaries must be rebuilt in sorted-key order: even though the wire
    representation sorts keys, trusted adapters can observe insertion order.
    Aliases are expanded as they are by the reference JSON round trip.  No
    mutable child is shared with the input; scalar values are immutable.
    """
    def visit(item, depth):
        if depth > MAX_DEPTH:
            raise ValueError("JSON nesting exceeds 64")
        kind = type(item)
        if item is None or kind is bool:
            return item
        if kind is int:
            if not -MAX_INTEGER <= item <= MAX_INTEGER:
                raise ValueError("JSON integer exceeds exact interchange domain")
            return item
        if kind is str:
            if not item.isascii():
                raise ValueError("JSON strings must be ASCII")
            return item
        if kind is list:
            return [visit(child, depth + 1) for child in item]
        if kind is dict:
            for key in item:
                if type(key) is not str or not key.isascii():
                    raise ValueError("JSON object keys must be exact ASCII strings")
            return {key: visit(item[key], depth + 1) for key in sorted(item)}
        raise ValueError("unsupported JSON value type: " + kind.__name__)
    try:
        return visit(value, 0)
    except RecursionError as exc:
        raise ValueError("cyclic or excessively nested JSON") from exc


def _text_digest(text):
    """Only call with text already produced or validated by canonical()."""
    return hashlib.sha256(text.encode("ascii")).hexdigest()


class FastStore(Store):
    """Execution alternative for value-based adapters with reference durability.

    No state cache survives a call.  Existing stores can be opened using either
    owner with the same adapter registry.  An adapter's numerical work and
    outputs are unchanged for adapters depending on JSON values and container
    order, not Python object identity or allocation behavior. Source identity
    remains the registry's responsibility.
    """

    def _transition_with_text(self, command, bindings, pre_state_text=None):
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
            state = checked_clone(adapter.initialize(checked_clone(payload["config"])))
            result = checked_clone(adapter.view(checked_clone(state)))
            if type(result) is not dict:
                raise ValueError("adapter view must be a JSON object")
            return {"adapter": name, "config": checked_clone(payload["config"]),
                    "state": state}, None, result
        if contract not in bindings:
            raise ValueError("unknown contract")
        previous = bindings[contract]
        adapter = self._registry[previous["adapter"]]
        if pre_state_text is None:
            pre_state_text = canonical(previous["state"])
        pre_hash = _text_digest(pre_state_text)
        pair = adapter.apply(checked_clone(previous["state"]), command["op"],
                             checked_clone(command["payload"]), command["at"])
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise ValueError("adapter apply must return state and result")
        state, result = pair
        binding = {"adapter": previous["adapter"],
                   "config": checked_clone(previous["config"]),
                   "state": checked_clone(state)}
        return binding, pre_hash, checked_clone(result)

    def _transition(self, command, bindings):
        # Called by the inherited complete semantic audit.  That audit computes
        # and compares every expected record and the final materialized state.
        return self._transition_with_text(command, bindings)

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
            pre_state_text = None
            if row is not None:
                # Retain duplicate-key, exact-type, depth and canonical-byte
                # checks for every value read from potentially modified storage.
                bindings[command["contract"]] = {
                    "adapter": row[0], "config": _stored(row[1]), "state": _stored(row[2])}
                pre_state_text = row[2]
            try:
                binding, pre_hash, result = self._transition_with_text(
                    command, bindings, pre_state_text)
            except Exception as exc:
                raise ValueError("adapter transition rejected: " + str(exc)) from exc
            # This one validated representation supplies both the post-state
            # digest and stored state.  It is never accepted from an adapter.
            state_text = canonical(binding["state"])
            record = {"sequence": count + 1, "command": command, "prior_head": head,
                      "pre_state_hash": pre_hash, "post_state_hash": _text_digest(state_text),
                      "result": result}
            record["hash"] = _text_digest(canonical(record))
            receipt = {"sequence": count + 1, "command_id": command["id"],
                       "contract": command["contract"], "result": result,
                       "head": record["hash"]}
            self._db.execute("INSERT INTO contracts VALUES (?,?,?,?) "
                             "ON CONFLICT(contract_id) DO UPDATE SET state_text=excluded.state_text",
                             (command["contract"], binding["adapter"],
                              canonical(binding["config"]), state_text))
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
        return checked_clone(receipt)

    def view(self, contract_id):
        _identifier(contract_id)
        if self._closed:
            raise ValueError("store is closed")
        row = self._db.execute("SELECT adapter,state_text FROM contracts WHERE contract_id=?",
                               (contract_id,)).fetchone()
        if row is None:
            raise ValueError("unknown contract")
        result = checked_clone(self._registry[row[0]].view(checked_clone(_stored(row[1]))))
        if type(result) is not dict:
            raise ValueError("adapter view must be a JSON object")
        return result
