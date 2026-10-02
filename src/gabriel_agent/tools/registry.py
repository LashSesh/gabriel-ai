"""Capabilities are registered code, not model instructions.

A ToolDescriptor fixes identifier/version, effect class, schemas, limits and
reconciliation semantics. The registry binds each descriptor to a loaded
implementation whose source fingerprint must match the descriptor, and
derives the catalog that the owner pins and that models may see (filtered
by the current grant).
"""
from __future__ import annotations

import hashlib
import inspect

from ..contracts.codec import canonical, digest
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import validate


def fingerprint_of(implementation) -> str:
    """SHA-256 over the implementation's module source and qualified name."""
    module = inspect.getmodule(implementation)
    source = inspect.getsource(module).encode("utf8") if module is not None else b""
    qualname = getattr(implementation, "__qualname__", type(implementation).__qualname__)
    return hashlib.sha256(source + b"::" + qualname.encode("ascii")).hexdigest()


_VERIFIER_FIELDS = {"verifier_id", "version", "predicate_kind", "implementation_fingerprint", "profile_digest",
                    "independent", "description"}


def _check_verifier(record: dict) -> None:
    from ..contracts.codec import is_digest, is_identifier
    import re
    if set(record) != _VERIFIER_FIELDS:
        raise GabrielError(Code.INVALID_SCHEMA, "verifier record fields must be exactly " + ",".join(sorted(_VERIFIER_FIELDS)))
    if not (is_identifier(record["verifier_id"]) and is_identifier(record["version"]) and is_digest(record["profile_digest"])
            and is_digest(record["implementation_fingerprint"]) and type(record["independent"]) is bool
            and isinstance(record["description"], str) and record["description"].isascii()
            and re.fullmatch(r"[a-z][a-z0-9_]{0,47}/[a-z][a-z0-9_]{0,63}", record["predicate_kind"])):
        raise GabrielError(Code.INVALID_SCHEMA, "invalid verifier record " + str(record.get("verifier_id")))


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._verifiers = {}
        self._packs = {}

    def register_tool(self, descriptor: dict, implementation) -> dict:
        descriptor = dict(descriptor)
        descriptor.setdefault("schema", "gabriel.tool-descriptor/1")
        descriptor["implementation_fingerprint"] = fingerprint_of(implementation)
        validate(descriptor, "tool-descriptor")
        if descriptor["tool_id"] in self._tools:
            raise GabrielError(Code.ID_REUSE, "tool already registered: " + descriptor["tool_id"])
        self._tools[descriptor["tool_id"]] = (descriptor, implementation)
        return descriptor

    def register_verifier(self, record: dict, implementation) -> dict:
        record = dict(record)
        record["implementation_fingerprint"] = fingerprint_of(implementation)
        _check_verifier(record)
        if record["verifier_id"] in self._verifiers:
            raise GabrielError(Code.ID_REUSE, "verifier already registered: " + record["verifier_id"])
        self._verifiers[record["verifier_id"]] = (record, implementation)
        return record

    def register_pack(self, manifest: dict) -> dict:
        validate(manifest, "domain-pack")
        self._packs[manifest["pack_id"]] = manifest
        return manifest

    def tool(self, tool_id: str):
        if tool_id not in self._tools:
            raise GabrielError(Code.POLICY_DENIED, "unknown capability " + tool_id, obj=tool_id)
        return self._tools[tool_id]

    def tool_or_none(self, tool_id: str):
        return self._tools.get(tool_id)

    def verifier(self, verifier_id: str):
        if verifier_id not in self._verifiers:
            raise GabrielError(Code.POLICY_DENIED, "unregistered verifier " + verifier_id, obj=verifier_id)
        return self._verifiers[verifier_id]

    def verify_loaded(self) -> dict:
        """Check that every loaded implementation still matches its descriptor fingerprint."""
        report = {}
        for tool_id, (descriptor, impl) in self._tools.items():
            report[tool_id] = descriptor["implementation_fingerprint"] == fingerprint_of(impl)
        for verifier_id, (record, impl) in self._verifiers.items():
            report[verifier_id] = record["implementation_fingerprint"] == fingerprint_of(impl)
        return report

    def catalog(self) -> dict:
        """The owner-pinned catalog: descriptors and verifier records by id."""
        return {"tools": {k: v[0] for k, v in self._tools.items()},
                "verifiers": {k: v[0] for k, v in self._verifiers.items()}}

    def catalog_record(self, catalog_id: str = "catalog") -> dict:
        record = {"schema": "gabriel.catalog/1", "catalog_id": catalog_id,
                  "tools": [self._tools[k][0] for k in sorted(self._tools)],
                  "verifiers": [self._verifiers[k][0] for k in sorted(self._verifiers)],
                  "domain_packs": [{"pack_id": p["pack_id"], "pack_version": p["pack_version"],
                                    "manifest_digest": digest(p)} for p in self._packs.values()]}
        return validate(record, "catalog")

    def visible_catalog(self, grant: dict) -> dict:
        """What a model may be told about: granted tools only. A description is not permission."""
        tools = [self._tools[k][0] for k in sorted(self._tools) if k in grant["tool_ids"]
                 and self._tools[k][0]["effect_class"] in grant["effect_classes"]]
        view = {"schema": "gabriel.catalog/1", "catalog_id": "visible-" + grant["grant_id"], "tools": tools,
                "verifiers": [self._verifiers[k][0] for k in sorted(self._verifiers)], "domain_packs": []}
        return view

    def catalog_digest(self) -> str:
        return digest({"tools": self.catalog()["tools"], "verifiers": self.catalog()["verifiers"]})
