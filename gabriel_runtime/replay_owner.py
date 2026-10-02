"""Full semantic replay with direct comparison of freshly expected JSON bytes.

Commands remain independently parsed and every transition is recomputed. Stored
records, receipts and final states are accepted only when their exact canonical
text equals the value regenerated from the commands. No replay checkpoint or
cross-call audit cache is introduced. Live operations are inherited unchanged.
"""
from .canonical import canonical, digest
from .engine import _command, _stored
from .fast_owner import FastStore, _text_digest


class ReplayStore(FastStore):
    """Alternative owner for deterministic, value-based trusted adapters."""

    def _audit(self, expected_head, expected_events):
        mode = self._db.execute("PRAGMA journal_mode").fetchone()[0].lower()
        synchronous = self._db.execute("PRAGMA synchronous").fetchone()[0]
        if mode != "delete" or synchronous != 3:
            raise ValueError("required SQLite journal/synchronization settings are absent")
        header_text, final_head, final_count, final_bytes, final_at = self._meta()
        header = self._header(header_text)
        head, count, byte_count, last_at = digest(header), 0, 0, -1
        bindings, state_texts, ids = {}, {}, set()
        limits = header["limits"]
        for seq, command_id, contract_id, command_text, record_text, receipt_text in self._db.execute(
                "SELECT sequence,command_id,contract_id,command_text,record_text,receipt_text "
                "FROM journal ORDER BY sequence"):
            command = _stored(command_text)
            _command(command)
            if (seq != count + 1 or command_id != command["id"]
                    or contract_id != command["contract"] or command_id in ids
                    or command["expected_head"] != head or command["at"] < last_at):
                raise ValueError("journal order or command identity mismatch")
            size = len(command_text.encode("ascii"))
            if (size > limits["max_command_bytes"] or count + 1 > limits["max_events"]
                    or byte_count + size > limits["max_bytes"]):
                raise ValueError("replayed budget exceeds header limits")
            try:
                binding, pre_hash, result = self._transition_with_text(
                    command, bindings, state_texts.get(contract_id))
            except Exception as exc:
                raise ValueError("semantic replay rejected: " + str(exc)) from exc
            state_text = canonical(binding["state"])
            expected_record = {"sequence": count + 1, "command": command,
                               "prior_head": head, "pre_state_hash": pre_hash,
                               "post_state_hash": _text_digest(state_text), "result": result}
            expected_record["hash"] = digest(expected_record)
            expected_receipt = {"sequence": count + 1, "command_id": command_id,
                                "contract": contract_id, "result": result,
                                "head": expected_record["hash"]}
            if (record_text != canonical(expected_record)
                    or receipt_text != canonical(expected_receipt)):
                raise ValueError("semantic record or receipt mismatch")
            bindings[contract_id] = binding
            state_texts[contract_id] = state_text
            ids.add(command_id)
            head = expected_record["hash"]
            count += 1
            byte_count += size
            last_at = command["at"]
        # Preserve the reference's aggregate JSON-domain/depth constraint;
        # separate per-state validation alone would accept extra deep values.
        canonical(bindings)
        seen = set()
        for contract, name, config_text, state_text in self._db.execute(
                "SELECT contract_id,adapter,config_text,state_text FROM contracts"):
            if contract in seen or contract not in bindings:
                raise ValueError("duplicate or unexpected contract")
            expected = bindings[contract]
            if (name != expected["adapter"] or config_text != canonical(expected["config"])
                    or state_text != state_texts[contract]):
                raise ValueError("stored bindings or states disagree with replay")
            seen.add(contract)
        if seen != set(bindings):
            raise ValueError("missing contract")
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
