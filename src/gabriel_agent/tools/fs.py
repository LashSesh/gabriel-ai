"""Filesystem containment through the OS boundary, not string-prefix checks.

Every path is resolved component by component from a directory file
descriptor with ``O_NOFOLLOW``; a symlink at any component rejects, as do
absolute paths, empty components and ``..``. Writes are atomic renames
inside the resolved directory.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import stat

from ..contracts.errors import Code, GabrielError

_MAX_COMPONENTS = 64


def split_relative(path: str) -> list:
    if not isinstance(path, str) or not path or path.startswith("/") or "\x00" in path:
        raise GabrielError(Code.POLICY_DENIED, "path must be a non-empty relative path", obj=path)
    parts = path.split("/")
    if len(parts) > _MAX_COMPONENTS:
        raise GabrielError(Code.POLICY_DENIED, "path has too many components", obj=path)
    for part in parts:
        if part in ("", ".", ".."):
            raise GabrielError(Code.POLICY_DENIED, "path contains an empty, current or parent component", obj=path)
    return parts


class ContainedRoot:
    """A directory file descriptor and operations that cannot leave it."""

    def __init__(self, root: str):
        self.root = os.path.realpath(root)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        if not stat.S_ISDIR(os.fstat(self.fd).st_mode):
            os.close(self.fd)
            raise GabrielError(Code.POLICY_DENIED, "root is not a directory", obj=root)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _descend(self, parts, create=False):
        """Open each directory component without following symlinks; return (dir_fd, leaf)."""
        dir_fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                try:
                    st = os.stat(part, dir_fd=dir_fd, follow_symlinks=False)
                except FileNotFoundError:
                    if not create:
                        raise GabrielError(Code.POLICY_DENIED, "directory does not exist: " + part, obj="/".join(parts))
                    os.mkdir(part, 0o755, dir_fd=dir_fd)
                    st = os.stat(part, dir_fd=dir_fd, follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode):
                    raise GabrielError(Code.POLICY_DENIED, "symlink in path rejected: " + part, obj="/".join(parts))
                if not stat.S_ISDIR(st.st_mode):
                    raise GabrielError(Code.POLICY_DENIED, "path component is not a directory: " + part, obj="/".join(parts))
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
                os.close(dir_fd)
                dir_fd = next_fd
            return dir_fd, parts[-1]
        except BaseException:
            os.close(dir_fd)
            raise

    def read(self, path: str) -> bytes:
        parts = split_relative(path)
        dir_fd, leaf = self._descend(parts)
        try:
            try:
                fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
            except OSError as exc:
                if exc.errno == 40:  # ELOOP: symlink leaf
                    raise GabrielError(Code.POLICY_DENIED, "symlink leaf rejected", obj=path)
                raise GabrielError(Code.UNKNOWN_OBJECT, "cannot open %s: %s" % (path, exc.strerror), obj=path)
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    raise GabrielError(Code.POLICY_DENIED, "not a regular file", obj=path)
                chunks = []
                while True:
                    chunk = os.read(fd, 1 << 20)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                os.close(fd)
        finally:
            os.close(dir_fd)

    def exists(self, path: str) -> bool:
        parts = split_relative(path)
        try:
            dir_fd, leaf = self._descend(parts)
        except GabrielError:
            return False
        try:
            os.stat(leaf, dir_fd=dir_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
        finally:
            os.close(dir_fd)

    def digest(self, path: str):
        return hashlib.sha256(self.read(path)).hexdigest()

    def write(self, path: str, data: bytes, create_dirs: bool = True) -> str:
        parts = split_relative(path)
        dir_fd, leaf = self._descend(parts, create=create_dirs)
        try:
            try:
                st = os.stat(leaf, dir_fd=dir_fd, follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    raise GabrielError(Code.POLICY_DENIED, "target exists and is not a regular file", obj=path)
            except FileNotFoundError:
                pass
            temp = ".gabriel-tmp-" + secrets.token_hex(6)
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dir_fd)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.rename(temp, leaf, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            except BaseException:
                try:
                    os.unlink(temp, dir_fd=dir_fd)
                except FileNotFoundError:
                    pass
                raise
            os.fsync(dir_fd)
            return hashlib.sha256(data).hexdigest()
        finally:
            os.close(dir_fd)

    def delete(self, path: str) -> None:
        parts = split_relative(path)
        dir_fd, leaf = self._descend(parts)
        try:
            st = os.stat(leaf, dir_fd=dir_fd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode):
                raise GabrielError(Code.POLICY_DENIED, "only regular files are deleted", obj=path)
            os.unlink(leaf, dir_fd=dir_fd)
            os.fsync(dir_fd)
        except FileNotFoundError:
            raise GabrielError(Code.UNKNOWN_OBJECT, "file does not exist", obj=path)
        finally:
            os.close(dir_fd)

    def manifest(self, ignore=(".git",)) -> dict:
        """{relative path: {"sha256", "bytes", "kind"}} without following symlinks.
        Entries named in ``ignore`` (a .git directory or worktree pointer file) are skipped at any level."""
        result = {}

        def walk(dir_fd, prefix):
            names = sorted(os.listdir(dir_fd))
            for name in names:
                if name in ignore:
                    continue
                rel = prefix + name if not prefix else prefix + "/" + name
                st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode):
                    result[rel] = {"kind": "symlink", "bytes": 0, "sha256": None}
                elif stat.S_ISDIR(st.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
                    try:
                        walk(child, rel)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(st.st_mode):
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
                    try:
                        h = hashlib.sha256()
                        size = 0
                        while True:
                            chunk = os.read(fd, 1 << 20)
                            if not chunk:
                                break
                            h.update(chunk)
                            size += len(chunk)
                    finally:
                        os.close(fd)
                    result[rel] = {"kind": "file", "bytes": size, "sha256": h.hexdigest()}
                else:
                    result[rel] = {"kind": "special", "bytes": 0, "sha256": None}
        walk(self.fd, "")
        return result


def path_in_scope(path: str, allowed_prefixes) -> bool:
    """Scope check on an already validated relative path (prefix list from the task binding)."""
    parts = split_relative(path)
    joined = "/".join(parts)
    for prefix in allowed_prefixes:
        prefix = prefix.rstrip("/")
        if prefix == "" or joined == prefix or joined.startswith(prefix + "/"):
            return True
    return False
