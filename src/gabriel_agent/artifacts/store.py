"""Content-addressed immutable object store.

Install protocol: write a temporary file inside the store root, flush and
fsync it, atomically rename it into ``objects/<aa>/<sha256>`` and fsync the
directory. The referring event is committed only afterwards. A missing or
changed committed object is a storage fault, never silently regenerated.
"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from ..contracts.codec import CodecError, artifact_ref, require_ref, sha256_hex
from ..contracts.errors import Code, GabrielError


class ObjectStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.tmp = self.root / "tmp"
        self._hook = None  # test-only crash injection: hook(stage)

    @classmethod
    def create(cls, root):
        store = cls(root)
        store.objects.mkdir(parents=True, exist_ok=False)
        store.tmp.mkdir(parents=True, exist_ok=True)
        return store

    @classmethod
    def open(cls, root):
        store = cls(root)
        if not store.objects.is_dir():
            raise GabrielError(Code.STORAGE_FAULT, "object store root is missing: " + str(root))
        store.tmp.mkdir(parents=True, exist_ok=True)
        return store

    def path_for(self, sha256: str) -> Path:
        return self.objects / sha256[:2] / sha256

    def _fsync_dir(self, path: Path):
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _io(self, operation: str, nbytes: int, started: float) -> None:
        """Artifact I/O counters on the innermost open telemetry span, when a tracer is attached."""
        tracer = getattr(self, "tracer", None)
        if tracer is not None:
            tracer.add(operation + "_calls", 1)
            tracer.add(operation + "_bytes", nbytes)
            tracer.add("io_ms", int((time.monotonic() - started) * 1000))

    def put(self, raw: bytes, media_type: str = "application/octet-stream") -> dict:
        started = time.monotonic()
        ref = artifact_ref(raw, media_type)
        final = self.path_for(ref["sha256"])
        if final.exists():
            self._verify_file(final, ref)
            self._io("put", len(raw), started)
            return ref
        final.parent.mkdir(parents=True, exist_ok=True)
        temp = self.tmp / ("install-" + secrets.token_hex(8))
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if self._hook:
                self._hook("before_rename")
            os.rename(temp, final)
            self._fsync_dir(final.parent)
            if self._hook:
                self._hook("after_rename")
        except BaseException:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise
        self._io("put", len(raw), started)
        return ref

    def _verify_file(self, path: Path, ref: dict) -> bytes:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise GabrielError(Code.ARTIFACT_MISSING, "artifact bytes are missing", obj=ref["sha256"])
        except OSError as exc:
            raise GabrielError(Code.STORAGE_FAULT, "cannot read artifact: " + str(exc), obj=ref["sha256"])
        if len(raw) != ref["bytes"] or sha256_hex(raw) != ref["sha256"]:
            raise GabrielError(Code.STORAGE_FAULT, "committed artifact bytes changed", obj=ref["sha256"])
        return raw

    def get(self, ref: dict) -> bytes:
        started = time.monotonic()
        try:
            require_ref(ref)
        except CodecError as exc:
            raise GabrielError(Code.INVALID_SCHEMA, str(exc)) from exc
        raw = self._verify_file(self.path_for(ref["sha256"]), ref)
        self._io("get", len(raw), started)
        return raw

    def exists(self, ref: dict) -> bool:
        return self.path_for(ref["sha256"]).is_file()

    def verify(self, ref: dict) -> bool:
        self.get(ref)
        return True

    def verify_all(self, refs) -> dict:
        """Verify every reference; return {sha256: 'ok'|'missing'|'corrupt'}."""
        report = {}
        for ref in refs:
            try:
                self.get(ref)
                report[ref["sha256"]] = "ok"
            except GabrielError as exc:
                report[ref["sha256"]] = "missing" if exc.code is Code.ARTIFACT_MISSING else "corrupt"
        return report

    def list_objects(self):
        for bucket in sorted(self.objects.iterdir()) if self.objects.is_dir() else []:
            if bucket.is_dir():
                for item in sorted(bucket.iterdir()):
                    yield item.name, item

    def scan_orphans(self, referenced: set, grace_seconds: int = 3600, now: float | None = None) -> list:
        """Objects not referenced by any committed record and older than grace."""
        now = time.time() if now is None else now
        found = []
        for name, path in self.list_objects():
            if name in referenced:
                continue
            age = now - path.stat().st_mtime
            if age >= grace_seconds:
                found.append(name)
        return found

    def collect(self, names) -> int:
        removed = 0
        for name in names:
            path = self.path_for(name)
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
        return removed

    def fsck(self, referenced_refs) -> dict:
        """Report integrity of every referenced object and stray temporaries."""
        report = self.verify_all(referenced_refs)
        stray = sorted(p.name for p in self.tmp.iterdir()) if self.tmp.is_dir() else []
        bad = {k: v for k, v in report.items() if v != "ok"}
        return {"referenced": len(report), "faults": bad, "stray_temporaries": stray,
                "status": "passed" if not bad else "storage_fault"}
