#!/usr/bin/env python3
"""Bounded live-file persistence probe; never reads or edits prior raw evidence.

Three controls use the same numbered stages: ordinary fsynced bytes, standard
library SQLite DELETE/EXTRA, and the original Store with a tiny pure adapter.
Open read-only descriptors distinguish pathname replacement from modification
of the committed inode. This is not a power-loss or storage durability test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.engine import Store


def clock():
    return {'monotonic_ns': time.monotonic_ns(), 'wall_ns': time.time_ns()}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stat_record(stat):
    return {name: getattr(stat, name) for name in
            ('st_dev', 'st_ino', 'st_size', 'st_nlink', 'st_mtime_ns', 'st_ctime_ns')}


def fd_record(fd):
    before = os.fstat(fd)
    data = os.pread(fd, before.st_size + 1, 0)
    after = os.fstat(fd)
    return {**stat_record(after), 'sha256': sha(data), 'read_bytes': len(data),
            'stable_during_read': stat_record(before) == stat_record(after)}


def path_record(path):
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            record = fd_record(fd)
            named = os.stat(path)
            record['path_still_names_open_inode'] = (
                named.st_ino == record['st_ino'] and named.st_dev == record['st_dev'])
            return record
        finally:
            os.close(fd)
    except OSError as exc:
        return {'error': type(exc).__name__, 'errno': exc.errno}


def fsync_path(path):
    results = []
    for target, flags in ((path, os.O_RDONLY), (path.parent, os.O_RDONLY | os.O_DIRECTORY)):
        fd = os.open(target, flags)
        try:
            os.fsync(fd)
            results.append({'target': str(target), 'returned_successfully': True})
        finally:
            os.close(fd)
    return results


def write_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_path(path)


class CounterAdapter:
    """No native executable, subprocess, file access, clock, or mutable fields."""
    def fingerprint(self):
        return {'adapter': 'persistence-probe-counter/v1'}

    def initialize(self, config):
        return {'stage': 0, 'seed': config['seed'], 'payload': ''}

    def apply(self, state, operation, payload, at):
        if operation != 'advance' or payload['stage'] != state['stage'] + 1:
            raise ValueError('not the next stage')
        next_state = {'stage': payload['stage'], 'seed': state['seed'],
                      'payload': payload['payload']}
        return next_state, self.view(next_state)

    def view(self, state):
        return {'stage': state['stage'], 'seed': state['seed'],
                'payload_sha256': sha(state['payload'].encode())}


REGISTRY = {'probe': CounterAdapter()}


def content(seed, stage):
    header = json.dumps({'seed': seed, 'stage': stage}, sort_keys=True).encode() + b'\n'
    return header + bytes([65 + stage % 26]) * (65536 - len(header))


def sql_read(path, kind):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True,
                         isolation_level=None, timeout=1)
    try:
        integrity = db.execute('PRAGMA integrity_check').fetchall()
        if kind == 'sqlite':
            seed, stage, payload = db.execute('SELECT seed,stage,payload FROM marker').fetchone()
            return {'integrity': integrity, 'seed': seed, 'stage': stage,
                    'payload_sha256': sha(payload.encode())}
        head, events = db.execute('SELECT head,event_count FROM meta').fetchone()
        state = json.loads(db.execute('SELECT state_text FROM contracts').fetchone()[0])
        return {'integrity': integrity, 'head': head, 'events': events,
                'seed': state['seed'], 'stage': state['stage']}
    finally:
        db.close()


def logical_read(path, kind):
    try:
        if kind == 'plain':
            return json.loads(path.read_bytes().split(b'\n', 1)[0])
        return sql_read(path, kind)
    except Exception as exc:
        return {'error': repr(exc)}


def snapshot(case, label):
    return {**clock(), 'label': label, 'path': path_record(case['path']),
            'held_inode': fd_record(case['read_fd']),
            'logical': logical_read(case['path'], case['kind']),
            'sidecars': {suffix: path_record(Path(str(case['path']) + suffix))
                         for suffix in ('-journal', '-wal', '-shm')
                         if Path(str(case['path']) + suffix).exists()}}


def make_case(location, directory, seed, kind):
    path = directory / f'{kind}_{seed:02d}.{"bin" if kind == "plain" else "sqlite"}'
    case = {'location': location, 'path': path, 'seed': seed, 'kind': kind, 'history': []}
    if kind == 'plain':
        case['writer'] = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(case['writer'], content(seed, 0))
        os.fsync(case['writer'])
    elif kind == 'sqlite':
        db = sqlite3.connect(str(path), isolation_level=None)
        assert db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete'
        db.execute('PRAGMA synchronous=EXTRA')
        db.execute('CREATE TABLE marker(seed INTEGER,stage INTEGER,payload TEXT)')
        db.execute('INSERT INTO marker VALUES(?,?,?)', (seed, 0, content(seed, 0).decode()))
        case['writer'] = db
        case['settings'] = {'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0],
                            'synchronous': db.execute('PRAGMA synchronous').fetchone()[0],
                            'database_list': db.execute('PRAGMA database_list').fetchall()}
    else:
        owner = Store.create(path, REGISTRY)
        owner.submit({'id': 'bind', 'contract': 'counter', 'op': 'bind', 'at': 0,
                      'expected_head': owner.head,
                      'payload': {'adapter': 'probe', 'config': {'seed': seed}}})
        case['writer'] = owner
    case['read_fd'] = os.open(path, os.O_RDONLY)
    case['history'].append(snapshot(case, 'initialized'))
    return case


def advance(case, stage, final_stage):
    payload = content(case['seed'], stage)
    if case['kind'] == 'plain':
        fd = case['writer']
        written = os.pwrite(fd, payload, 0)
        if written != len(payload):
            raise RuntimeError('short control write')
        os.ftruncate(fd, len(payload))
        os.fsync(fd)
    elif case['kind'] == 'sqlite':
        db = case['writer']
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE marker SET stage=?,payload=?', (stage, payload.decode()))
        db.commit()
    else:
        owner = case['writer']
        receipt = owner.submit({'id': f'stage-{stage}', 'contract': 'counter',
            'op': 'advance', 'at': stage, 'expected_head': owner.head,
            'payload': {'stage': stage, 'payload': payload[:2048].decode()}})
        case['expected_anchor'] = {'head': receipt['head'], 'events': receipt['sequence']}
    case['history'].append(snapshot(case, f'committed-{stage}'))
    if stage == final_stage:
        committed = case['history'][-1]
        case['final_committed_sha256'] = (sha(content(case['seed'], stage))
            if case['kind'] == 'plain' else committed['held_inode']['sha256'])
        case['final_baseline_observation'] = committed['label']
        case['final_baseline_monotonic_ns'] = committed['monotonic_ns']


def stable_record(record, named=False):
    return (record.get('stable_during_read') is True and
            record.get('read_bytes') == record.get('st_size') and
            (not named or record.get('path_still_names_open_inode') is True))


def environment():
    scripts = {}
    sync_script = Path('/usr/local/scripts/sync_share.sh')
    if sync_script.exists():
        raw = sync_script.read_bytes()
        selected = ('rsync -a', '--delay-updates', '--update --times', 'inotifywait -rq',
                    'sleep 2 # debounce', 'close_write,create,delete,move')
        scripts[str(sync_script)] = {'sha256': sha(raw),
            'relevant_lines': [line.strip() for line in raw.decode().splitlines()
                               if any(token in line for token in selected)]}
    daemon = Path('/etc/rsyncd.conf')
    scratch = {}
    if daemon.exists():
        section = ''
        for line in daemon.read_text().splitlines():
            if line.strip().startswith('['):
                section = line.strip()
            elif section == '[scratch]' and line.strip().startswith(('path =', 'read only =')):
                key, value = line.split('=', 1)
                scratch[key.strip()] = value.strip()
    processes = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            comm = (proc / 'comm').read_text().strip()
            if comm in ('rsync', 'sync_share.sh', 'inotifywait'):
                processes.append({'pid': int(proc.name), 'comm': comm})
        except OSError:
            pass
    mount = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        if fields[4] == '/':
            split = fields.index('-')
            mount.append({'mountpoint': '/', 'device': fields[2], 'type': fields[split + 1],
                          'volatile_sync_reported': 'fsync=volatile' in line or ',volatile' in line})
    return {'clock': clock(), 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
            'pid': os.getpid(), 'kernel': platform.release(), 'root_mount': mount,
            'service_sources': scripts, 'rsync_scratch_module': scratch,
            'relevant_processes': processes,
            'source_sha256': {str(path.relative_to(ROOT)): sha(path.read_bytes())
                for path in (Path(__file__), ROOT / 'gabriel_runtime/engine.py',
                             ROOT / 'gabriel_runtime/canonical.py')}}


def result_case(case, steps):
    history = case['history']
    final = history[-1]
    init_inode = (history[0]['held_inode']['st_dev'], history[0]['held_inode']['st_ino'])
    def matches(entry):
        anchor_ok = (case['kind'] != 'store' or
            all(entry['logical'].get(k) == v for k, v in case.get('expected_anchor', {}).items()))
        return (stable_record(entry['path'], named=True) and
                entry['logical'].get('stage') == steps and anchor_ok and
                entry['path'].get('sha256') == case.get('final_committed_sha256'))
    return {key: str(value) if isinstance(value, Path) else value for key, value in case.items()
            if key not in ('writer', 'read_fd')} | {
                'expected_stage': steps,
                'path_inode_changed': any(stable_record(h['path'], named=True) and
                    (h['path']['st_dev'], h['path']['st_ino']) != init_inode for h in history),
                'unavailable_or_raced_observations': sum(not stable_record(h['path'], named=True)
                    or not stable_record(h['held_inode']) for h in history),
                'held_inode_final_preserves_committed_bytes':
                    stable_record(final['held_inode']) and
                    final['held_inode']['sha256'] == case.get('final_committed_sha256'),
                'final_path_matches_committed': matches(final),
                'all_postclose_path_checks_match': 'final_committed_sha256' in case and
                    all(matches(h) for h in history
                        if h['label'].startswith(('after-close', 'settle-'))),
                'explicit_store_reopen_passed': case['kind'] != 'store' or
                    case.get('explicit_store_reopen_audit', {}).get('status') == 'passed'}


def check_manifest(source, output):
    original = json.loads(source.read_text())
    checks = []
    for record in original['cases']:
        path = Path(record['path'])
        actual = path_record(path)
        logical = logical_read(path, record['kind'])
        checks.append({'path': str(path), 'actual': actual, 'logical': logical,
                       'expected_sha256': record.get('final_committed_sha256'),
                       'passed': stable_record(actual, named=True) and
                       actual.get('sha256') == record.get('final_committed_sha256') and
                       logical.get('stage') == record['expected_stage'] and
                       all(logical.get(k) == v for k, v in record.get('expected_anchor', {}).items())})
    result = {'schema': 'gabriel.persistence-boundary.recheck.v1', 'source': str(source),
              'source_sha256': sha(source.read_bytes()), 'environment': environment(),
              'checks': checks, 'all_passed': all(r['passed'] for r in checks)}
    write_json(output, result)
    print(json.dumps({'rechecked': len(checks), 'passed': sum(r['passed'] for r in checks),
                      'output': str(output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--location', action='append', nargs=2, metavar=('NAME', 'NEW_DIRECTORY'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check', type=Path)
    parser.add_argument('--records', type=int, default=4)
    parser.add_argument('--steps', type=int, default=14)
    parser.add_argument('--interval', type=float, default=0.5)
    parser.add_argument('--settle', type=float, default=12)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be new')
    if args.check:
        check_manifest(args.check.resolve(), args.output.resolve())
        return
    if (not args.location or not 1 <= args.records <= 8 or not 1 <= args.steps <= 32
            or not 0 <= args.interval <= 2 or not 0 <= args.settle <= 30):
        parser.error('locations required; records 1..8, steps 1..32, interval 0..2, settle 0..30')
    locations = [(name, Path(directory).resolve()) for name, directory in args.location]
    if len(set(name for name, _ in locations)) != len(locations):
        parser.error('unique location names required')
    for _, directory in locations:
        directory.mkdir(parents=True, exist_ok=False)
    start = environment()
    # Native Linux inotify is read-only. It records replacement-related names,
    # but does not identify the writer PID; do not infer a PID from this alone.
    watch = subprocess.Popen(['inotifywait', '-m', '-r', '-q', '--format', '%w|%e|%f',
        '-e', 'close_write,create,delete,move,attrib', *[str(p) for _, p in locations]],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    os.set_blocking(watch.stdout.fileno(), False)
    events = []
    def drain():
        while select.select([watch.stdout], [], [], 0)[0]:
            data = os.read(watch.stdout.fileno(), 262144)
            if not data:
                break
            events.append({**clock(), 'observations': data.decode(errors='replace')})
    cases = []
    failure = None
    try:
        time.sleep(0.05)
        if watch.poll() is not None:
            raise RuntimeError('inotify watcher did not start: ' + watch.stderr.read().decode())
        for seed in range(args.records):
            for kind in ('plain', 'sqlite', 'store'):
                for name, directory in locations:
                    cases.append(make_case(name, directory, seed, kind))
                    drain()
        for stage in range(1, args.steps + 1):
            for case in cases:
                advance(case, stage, args.steps)
                drain()
            time.sleep(args.interval)
            drain()
        for case in cases:
            if case['kind'] == 'plain':
                os.close(case['writer'])
            else:
                case['writer'].close()
            case['writer'] = None
            case['explicit_final_fsync'] = fsync_path(case['path'])
            case['history'].append(snapshot(case, 'after-close-and-extra-fsync'))
            if case['kind'] == 'store':
                try:
                    anchor = case['expected_anchor']
                    with Store.open(case['path'], REGISTRY, expected_head=anchor['head'],
                                    expected_events=anchor['events']) as reopened:
                        case['explicit_store_reopen_audit'] = reopened.audit(**{
                            'expected_head': anchor['head'], 'expected_events': anchor['events']})
                except Exception as exc:
                    case['explicit_store_reopen_audit'] = {'error': repr(exc)}
            drain()
        until = time.monotonic() + args.settle
        tick = 0
        while time.monotonic() < until:
            time.sleep(min(0.5, max(0, until - time.monotonic())))
            for case in cases:
                case['history'].append(snapshot(case, f'settle-{tick}'))
            tick += 1
            drain()
    except Exception as exc:
        failure = repr(exc)
    finally:
        drain()
        watcher = {'alive_before_cleanup': watch.poll() is None}
        try:
            watch.terminate()
            watch.wait(timeout=3)
        except Exception as exc:
            watcher['cleanup_error'] = repr(exc)
            watch.kill()
            watch.wait(timeout=3)
        drain()
        watcher.update(returncode=watch.returncode, stderr=watch.stderr.read().decode(errors='replace'))
        watch.stdout.close()
        watch.stderr.close()
        records = [result_case(case, args.steps) for case in cases]
        for case in cases:
            if case.get('writer') is not None:
                os.close(case['writer']) if case['kind'] == 'plain' else case['writer'].close()
            os.close(case['read_fd'])
    result = {'schema': 'gabriel.persistence-boundary.v1',
        'kind': 'controlled live pathname and inode probe; no power-loss claim',
        'command': sys.argv, 'environment_before': start, 'environment_after': environment(),
        'settings': vars(args) | {'output': str(args.output), 'check': None},
        'failure': failure, 'cases': records, 'inotify_events': events, 'watcher': watcher,
        'summary': {'completed': len(records),
            'pathname_replacements': sum(r['path_inode_changed'] for r in records),
            'final_path_failures': sum(not r['final_path_matches_committed'] for r in records),
            'held_inode_failures': sum(not r['held_inode_final_preserves_committed_bytes'] for r in records)}}
    write_json(args.output.resolve(), result)
    print(json.dumps(result['summary'] | {'output': str(args.output), 'failure': failure}), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == '__main__':
    main()
