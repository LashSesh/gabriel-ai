"""In-namespace init for the linux_namespace backend.

Runs as PID 1 of fresh user/mount/pid/net/ipc/uts namespaces created by
unshare(1). Reads a JSON configuration from stdin, builds a tmpfs root with
read-only system binds and the writable working tree, pivots into it,
applies resource limits, drops every capability with no_new_privs and
execs the target command. Exits 124 with a diagnostic on setup failure.
Only the standard library is imported; nothing from the package is loaded
after the pivot.
"""
import ctypes
import json
import os
import resource
import socket
import sys

MS_RDONLY, MS_NOSUID, MS_NODEV, MS_NOEXEC = 1, 2, 4, 8
MS_REMOUNT, MS_BIND, MS_REC, MS_PRIVATE = 32, 4096, 16384, 1 << 18
MNT_DETACH = 2
RO_SYSTEM = ("/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin")
RO_ETC = ("passwd", "group", "ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives", "localtime",
          "nsswitch.conf", "hosts", "python3", "python3.11", "python3.12", "python3.13", "ssl", "ca-certificates", "mime.types")

libc = ctypes.CDLL(None, use_errno=True)


def fail(message):
    sys.stderr.write("GABRIEL_JAIL_SETUP_FAILED: %s\n" % message)
    sys.stderr.flush()
    os._exit(124)


def mount(source, target, fstype, flags, data=None):
    rc = libc.mount(source.encode() if source else None, target.encode(), fstype.encode() if fstype else None,
                    ctypes.c_ulong(flags), data.encode() if data else None)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, "mount(%s -> %s, %s): %s" % (source, target, fstype, os.strerror(err)))


def bind_ro(source, target, recursive=True):
    flags = MS_BIND | (MS_REC if recursive else 0)
    mount(source, target, None, flags)
    mount(None, target, None, MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV | (MS_REC if recursive else 0))


def ensure(path, is_dir):
    if is_dir:
        os.makedirs(path, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            open(path, "w").close()


def build_root(config):
    root = "/tmp/gabriel-jail-root-%d" % os.getpid()
    os.makedirs(root, exist_ok=True)
    mount(None, "/", None, MS_REC | MS_PRIVATE)
    mount("tmpfs", root, "tmpfs", MS_NOSUID | MS_NODEV, "size=256m,mode=755")
    for name in ("proc", "tmp", "dev", "etc", "work", "oldroot", "dev/shm"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    for system in RO_SYSTEM:
        if os.path.isdir(system) and not os.path.islink(system):
            target = root + system
            os.makedirs(target, exist_ok=True)
            bind_ro(system, target)
        elif os.path.islink(system):
            os.symlink(os.readlink(system), root + system)
    for name in RO_ETC:
        source = os.path.join("/etc", name)
        if not os.path.exists(source):
            continue
        target = os.path.join(root, "etc", name)
        if os.path.isdir(source):
            os.makedirs(target, exist_ok=True)
            bind_ro(source, target)
        else:
            ensure(target, False)
            bind_ro(source, target, recursive=False)
    for extra in config.get("ro_binds", []):
        if os.path.isdir(extra):
            target = os.path.join(root, "ro", extra.lstrip("/"))
            os.makedirs(target, exist_ok=True)
            bind_ro(extra, target)
    mount("proc", root + "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC)
    mount("tmpfs", root + "/tmp", "tmpfs", MS_NOSUID | MS_NODEV, "size=64m")
    mount("tmpfs", root + "/dev/shm", "tmpfs", MS_NOSUID | MS_NODEV, "size=16m")
    mount("tmpfs", root + "/dev", "tmpfs", MS_NOSUID, "size=1m,mode=755")
    os.makedirs(root + "/dev/shm", exist_ok=True)
    mount("tmpfs", root + "/dev/shm", "tmpfs", MS_NOSUID | MS_NODEV, "size=16m")
    for dev in ("null", "zero", "urandom", "random", "tty"):
        source = "/dev/" + dev
        if os.path.exists(source):
            ensure(root + source, False)
            mount(source, root + source, None, MS_BIND)
    worktree = config["worktree"]
    if not os.path.isdir(worktree):
        raise OSError("worktree is not a directory: " + worktree)
    mount(worktree, root + "/work", None, MS_BIND | MS_REC)
    mount(None, root + "/work", None, MS_BIND | MS_REMOUNT | MS_NOSUID | MS_NODEV | MS_REC)
    os.chdir(root)
    if libc.pivot_root(b".", b"oldroot") != 0:
        err = ctypes.get_errno()
        raise OSError(err, "pivot_root: " + os.strerror(err))
    os.chdir("/")
    if libc.umount2(b"/oldroot", MNT_DETACH) != 0:
        err = ctypes.get_errno()
        raise OSError(err, "umount old root: " + os.strerror(err))
    os.rmdir("/oldroot")


def apply_limits(limits):
    resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu"], limits["cpu"]))
    resource.setrlimit(resource.RLIMIT_AS, (limits["as"], limits["as"]))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits["fsize"], limits["fsize"]))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits["nofile"], limits["nofile"]))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    try:
        config = json.loads(sys.stdin.read())
        build_root(config)
        try:
            socket.sethostname(config.get("hostname", "gabriel-worker"))
        except OSError:
            pass
        apply_limits(config["rlimits"])
        cwd = os.path.normpath(os.path.join("/work", config.get("cwd", ".")))
        if not cwd.startswith("/work"):
            raise OSError("cwd escapes the working tree")
        os.chdir(cwd)
        env = dict(config["env"])
        argv = ["/usr/bin/setpriv", "--inh-caps=-all", "--bounding-set=-all", "--no-new-privs", "--"] + list(config["argv"])
        devnull = os.open("/dev/null", os.O_RDONLY)
        os.dup2(devnull, 0)
        os.close(devnull)
        os.execve(argv[0], argv, env)
    except BaseException as exc:  # noqa: BLE001 - any setup failure must be visible
        fail("%s: %s" % (type(exc).__name__, exc))


if __name__ == "__main__":
    main()
