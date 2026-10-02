"""AT03: artifact integrity and installation crash windows."""
import os
import time

import pytest

from gabriel_agent.artifacts import ObjectStore
from gabriel_agent.contracts import GabrielError, Code


class Crash(Exception):
    pass


def test_put_get_verify_roundtrip(tmp_path):
    store = ObjectStore.create(tmp_path / "store")
    raw = "Prüfung \U0001F600".encode("utf8")
    ref = store.put(raw, "text/plain; charset=utf-8")
    assert store.get(ref) == raw
    assert store.put(raw, "text/plain; charset=utf-8") == ref  # idempotent
    assert store.exists(ref) and store.verify(ref)
    assert store.fsck([ref])["status"] == "passed"


def test_crash_before_rename_leaves_no_object_but_temporary(tmp_path):
    store = ObjectStore.create(tmp_path / "store")

    def hook(stage):
        if stage == "before_rename":
            raise Crash()
    store._hook = hook
    with pytest.raises(Crash):
        store.put(b"payload")
    ref = {"sha256": __import__("hashlib").sha256(b"payload").hexdigest(), "bytes": 7, "media_type": "application/octet-stream"}
    assert not store.exists(ref)
    with pytest.raises(GabrielError) as info:
        store.get(ref)
    assert info.value.code is Code.ARTIFACT_MISSING
    assert store.fsck([])["stray_temporaries"] == []  # temporary was unlinked on failure


def test_crash_after_rename_is_a_retained_orphan_until_grace(tmp_path):
    store = ObjectStore.create(tmp_path / "store")

    def hook(stage):
        if stage == "after_rename":
            raise Crash()
    store._hook = hook
    with pytest.raises(Crash):
        store.put(b"orphan bytes")
    store._hook = None
    ref = store.put(b"orphan bytes")  # the object already exists and verifies
    assert store.get(ref) == b"orphan bytes"
    now = time.time()
    assert store.scan_orphans(set(), grace_seconds=3600, now=now) == []
    assert store.scan_orphans(set(), grace_seconds=0, now=now + 1) == [ref["sha256"]]
    assert store.scan_orphans({ref["sha256"]}, grace_seconds=0, now=now + 1) == []
    assert store.collect([ref["sha256"]]) == 1
    assert not store.exists(ref)


def test_corruption_is_a_visible_storage_fault(tmp_path):
    store = ObjectStore.create(tmp_path / "store")
    ref = store.put(b"committed bytes")
    path = store.path_for(ref["sha256"])
    os.chmod(path, 0o600)
    path.write_bytes(b"committed byteX")
    with pytest.raises(GabrielError) as info:
        store.get(ref)
    assert info.value.code is Code.STORAGE_FAULT
    report = store.fsck([ref])
    assert report["status"] == "storage_fault" and report["faults"][ref["sha256"]] == "corrupt"
    path.write_bytes(b"short")
    assert store.verify_all([ref])[ref["sha256"]] == "corrupt"
    with pytest.raises(GabrielError):
        store.put(b"committed bytes")  # existing corrupt object is never overwritten silently


def test_invalid_reference_rejected(tmp_path):
    store = ObjectStore.create(tmp_path / "store")
    with pytest.raises(GabrielError) as info:
        store.get({"sha256": "A" * 64, "bytes": 1, "media_type": "text/plain"})
    assert info.value.code is Code.INVALID_SCHEMA
