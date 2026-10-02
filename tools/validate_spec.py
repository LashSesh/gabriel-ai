#!/usr/bin/env python3
"""Validate PROPOSED Gabriel specification assets, never execute agent tools.

Requires jsonschema==4.25.1 and its declared dependencies. Schema identifiers
resolve from the local registry only; the validator performs no network request.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / 'contracts'
MAX_SAFE = 2**53 - 1
BASE = 'https://gabriel.invalid/spec/1/'


def strict_loads(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON object key: ' + key)
            result[key] = value
        return result

    def no_float(text):
        raise ValueError('floating/non-finite JSON token is outside the envelope: ' + text)

    return json.loads(text, object_pairs_hook=pairs, parse_float=no_float,
                      parse_constant=no_float)


def read(path):
    return strict_loads(path.read_text(encoding='utf-8'))


def walk(value):
    yield value
    if isinstance(value, dict):
        for sub in value.values():
            yield from walk(sub)
    elif isinstance(value, list):
        for sub in value:
            yield from walk(sub)


def ascii_envelope(value):
    for item in walk(value):
        if isinstance(item, str) and not item.isascii():
            raise ValueError('non-ASCII envelope string; use a UTF-8 artifact')
        if isinstance(item, dict) and any(not key.isascii() for key in item):
            raise ValueError('non-ASCII envelope key')


def assert_dag(rows, key, deps):
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError('duplicate DAG identity')
    visited = set()
    active = set()
    depths = {}

    def visit(identity):
        if identity not in indexed:
            raise ValueError('unknown DAG dependency: ' + identity)
        if identity in active:
            raise ValueError('DAG cycle')
        if identity in visited:
            return depths[identity]
        active.add(identity)
        depth = 1 + max((visit(dep) for dep in indexed[identity][deps]), default=0)
        active.remove(identity)
        visited.add(identity)
        depths[identity] = depth
        return depth

    for identity in indexed:
        visit(identity)
    return indexed, depths


def check_plan(plan):
    nodes, depths = assert_dag(plan['nodes'], 'node_id', 'depends_on')
    if max(depths.values()) > plan['max_depth']:
        raise ValueError('plan depth exceeds its admitted maximum')

    def ancestors(identity):
        answer = set()
        for dep in nodes[identity]['depends_on']:
            answer.add(dep)
            answer.update(ancestors(dep))
        return answer

    for node in nodes.values():
        slots = [out['output_slot'] for out in node['outputs']]
        if len(slots) != len(set(slots)):
            raise ValueError('duplicate output slot')
        for input_value in node['inputs']:
            if 'producer_node' not in input_value:
                continue
            producer = input_value['producer_node']
            if producer not in ancestors(node['node_id']):
                raise ValueError('future output must belong to a declared prerequisite')
            candidates = {out['output_slot']: out['schema_digest']
                          for out in nodes[producer]['outputs']}
            if candidates.get(input_value['output_slot']) != input_value['required_schema']:
                raise ValueError('unavailable output slot or mismatched schema')


def execute():
    from jsonschema import Draft202012Validator, validators
    from referencing import Registry, Resource

    # Draft JSON Schema regards 1.0 as an integer by mathematical equality.
    # Gabriel additionally requires an integer JSON token; bool is distinct.
    strict_integer = Draft202012Validator.TYPE_CHECKER.redefine(
        'integer', lambda checker, value: type(value) is int)
    Validator = validators.extend(Draft202012Validator, type_checker=strict_integer)
    schemas = {f.name: read(f) for f in sorted((CONTRACTS / 'schemas').glob('*.json'))}
    registry = Registry()
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema['$id'], Resource.from_contents(schema))
        for item in walk(schema):
            if isinstance(item, dict) and item.get('type') == 'object':
                assert item.get('additionalProperties') is False, (name, 'open object')
            if isinstance(item, dict) and '$ref' in item:
                target = item['$ref'].split('#')[0]
                assert target in schemas or target in ('',), (name, target)

    def validate(value, schema_name):
        ascii_envelope(value)
        Validator(schemas[schema_name], registry=registry).validate(value)

    manifest = read(CONTRACTS / 'examples-manifest.json')
    examples = {}
    artifact_ids = set()
    for row in manifest['examples']:
        path = CONTRACTS / row['path']
        schema_name = Path(row['schema']).name
        value = read(path)
        validate(value, schema_name)
        examples[path.stem] = value
        if schema_name == 'plan.schema.json':
            check_plan(value)
        for part in walk(value):
            if isinstance(part, dict) and set(part) == {'sha256', 'bytes', 'media_type'}:
                blob = CONTRACTS / 'examples/objects' / (part['sha256'] + '.blob')
                data = blob.read_bytes()
                assert len(data) == part['bytes'], blob
                assert hashlib.sha256(data).hexdigest() == part['sha256'], blob
                artifact_ids.add(part['sha256'])

    assert len(examples) == len(manifest['examples']), 'duplicate example names'
    object_paths = {p.stem for p in (CONTRACTS / 'examples/objects').glob('*.blob')}
    assert artifact_ids == object_paths, 'unreferenced or unavailable example blob'

    def load_artifact(part):
        return read(CONTRACTS / 'examples/objects' / (part['sha256'] + '.blob'))

    def check_domain_pack(pack):
        ports = pack['ports']
        names = {'compile', 'observe', 'evaluate', 'propose', 'execute', 'read_back'}
        assert set(ports) == names
        assert {p['capability_id'] for p in ports.values()} <= set(pack['capability_requirements'])
        assert {f['case_kind'] for f in pack['fixtures']} == {'valid', 'invalid', 'out_of_scope'}
        for field in ('evaluation_profiles', 'transformation_profiles'):
            ids = [p['profile_id'] for p in pack[field]]
            assert len(ids) == len(set(ids)), 'duplicate domain profile id'
        ids = [f['fixture_id'] for f in pack['fixtures']]
        assert len(ids) == len(set(ids)), 'duplicate domain fixture id'
        for port in ports.values():
            for field in ('input_schema_ref', 'output_schema_ref'):
                Draft202012Validator.check_schema(load_artifact(port[field]))
        # The example descriptors are declared synthetic, not runnable handlers.
        if pack['manifest_kind'] == 'synthetic_fixture':
            for port in ports.values():
                assert load_artifact(port['implementation_ref'])['status'] == 'NOT_IMPLEMENTED'
        for fixture in pack['fixtures']:
            port = ports[fixture['port']]
            inp = load_artifact(fixture['input_ref'])
            output = load_artifact(fixture['expected_ref'])
            in_validator = Validator(load_artifact(port['input_schema_ref']), registry=registry)
            Validator(load_artifact(port['output_schema_ref']), registry=registry).validate(output)
            if fixture['case_kind'] == 'invalid':
                assert not in_validator.is_valid(inp), 'invalid fixture unexpectedly matches input schema'
            else:
                in_validator.validate(inp)
            expected = {'valid': 'supported', 'invalid': 'invalid', 'out_of_scope': 'out_of_scope'}
            assert output['applicability'] == expected[fixture['case_kind']]
        # Fixture expected outcomes are checked for representation only. No
        # domain handler is invoked, and no semantic oracle is proven here.

    check_domain_pack(examples['domain-pack'])
    assert any(not (CONTRACTS / 'examples/objects' / (h + '.blob')).read_bytes().isascii()
               for h in artifact_ids), 'missing positive UTF-8 byte-preservation example'

    # These are fixture relationships, not a simulation of an implemented owner.
    command, event = examples['command'], examples['event']
    intent, result = examples['intent'], examples['result']
    task, run, grant = examples['task'], examples['run'], examples['grant']
    task_ref_path = CONTRACTS / 'examples/objects' / (run['task_spec_ref']['sha256'] + '.blob')
    pinned_task = read(task_ref_path)
    validate(pinned_task, 'task.schema.json')
    assert pinned_task == task
    assert command['command_id'] == event['command_id']
    assert command['expected_revision'] + 1 == event['run_revision']
    assert command['payload_ref'] == event['payload_ref']
    payload_path = CONTRACTS / 'examples/objects' / (command['payload_ref']['sha256'] + '.blob')
    payload = read(payload_path)
    validate(payload, 'result.schema.json')
    assert payload == result
    for key in ('attempt_id', 'intent_id', 'lease_id', 'fencing_token', 'run_id'):
        assert intent[key] == result[key], key
        assert intent[key] == examples['dispatch-marker'][key], key
    for value in (intent, command, event, examples['assessment'], examples['plan'], run):
        assert value['task_id'] == task['task_id']
        assert value['run_id'] == run['run_id']
    for key in ('task_id', 'workspace_id', 'principal_id', 'grant_id', 'policy_digest'):
        assert task[key] == grant[key]
    assert intent['capability_id'] in grant['tool_ids']
    assert intent['target_id'] in grant['resource_ids']
    assert intent['effect_class'] in grant['effect_classes']
    assert run['budget'] == task['budget_ceiling'] == grant['budget_ceiling']
    producer = next(n for n in examples['plan']['nodes']
                    if n['node_id'] == intent['step_id'])
    declared_outputs = {o['output_slot']: o['schema_digest'] for o in producer['outputs']}
    actual_outputs = {o['output_slot']: o['schema_digest'] for o in result['outputs']}
    assert len(actual_outputs) == len(result['outputs']), 'duplicate result output slot'
    assert actual_outputs == declared_outputs, 'completed fixture result must bind declared slots'
    request, observation = examples['model-request'], examples['observation']
    assert request['observation_ids'] == [observation['observation_id']]
    assert observation['availability_sequence'] <= request['issue_frontier']
    assert request['evidence_refs'] == [observation['content_ref']]
    known_checks = {check['check_id'] for check in task['checks']}
    for plan_name in ('plan', 'plan-future-output'):
        for node in examples[plan_name]['nodes']:
            assert set(node['check_ids']) <= known_checks
            assert node['capability_id'] in grant['tool_ids']

    requirements = read(CONTRACTS / 'requirements.json')['requirements']
    acceptance = read(CONTRACTS / 'acceptance-cases.json')['cases']
    package_spec = read(CONTRACTS / 'work-packages.json')
    packages = package_spec['packages']
    reqids = [row['id'] for row in requirements]
    atids = [row['id'] for row in acceptance]
    wpids = [row['id'] for row in packages]
    assert reqids == ['R%02d' % i for i in range(1, 13)]
    assert atids == ['AT%02d' % i for i in range(1, 26)]
    assert wpids == ['WP%02d' % i for i in range(1, 13)]
    _, _ = assert_dag(packages, 'id', 'depends_on')
    for index, package in enumerate(packages):
        assert set(package['depends_on']) <= set(wpids[:index]), package['id']
        assert set(package['requirement_ids']) <= set(reqids)
        assert set(package['acceptance_ids']) <= set(atids)
        assert package['status'] == 'NOT_STARTED'
        for deps in package.get('extension_prerequisites', {}).values():
            assert set(deps) <= set(wpids)
    package_map = {p['id']: p for p in packages}
    for scope in package_spec['release_scopes'].values():
        selected = set(scope['required_packages'])
        assert selected <= set(wpids)
        assert all(set(package_map[pid]['depends_on']) <= selected for pid in selected)
        assert set(scope['required_acceptance_ids']) <= set(atids)
        assigned = {a for pid in selected for a in package_map[pid]['acceptance_ids']}
        assert set(scope['required_acceptance_ids']) <= assigned
    assert not {'AT23', 'AT25'} & set(package_spec['release_scopes']['G1']['required_acceptance_ids'])
    assert not {'WP09', 'WP10'} & set(package_spec['release_scopes']['G1']['required_packages'])
    for case in acceptance:
        assert set(case['requirement_ids']) <= set(reqids)
        assert case['execution_status'] == 'NOT_EXECUTED'
        assert len(case['required_evidence']) >= 3
    assert {r for a in acceptance for r in a['requirement_ids']} == set(reqids)
    assert {a for p in packages for a in p['acceptance_ids']} == set(atids)
    assert {r for p in packages for r in p['requirement_ids']} == set(reqids)

    negative = []

    def reject(name, fn):
        try:
            fn()
        except Exception as exc:
            negative.append({'id': name, 'rejected': True, 'exception': type(exc).__name__})
        else:
            raise AssertionError('negative control unexpectedly accepted: ' + name)

    for name, field, value in [('unknown_field', 'arbitrary', 'x'),
                               ('bool_counter', 'expected_revision', True),
                               ('float_counter', 'expected_revision', 7.0),
                               ('oversized_integer', 'expected_revision', MAX_SAFE + 1),
                               ('negative_counter', 'expected_revision', -1),
                               ('unicode_identifier', 'task_id', 't\u00e4sk'),
                               ('unknown_operation', 'op', 'execute_unrestricted')]:
        bad = copy.deepcopy(command)
        bad[field] = value
        reject(name, lambda value=bad: validate(value, 'command.schema.json'))
    bad = copy.deepcopy(examples['artifact']); bad['sha256'] = 'A' * 64
    reject('uppercase_artifact_digest', lambda: validate(bad, 'artifact-ref.schema.json'))
    for name, raw in [('duplicate_key', '{"a":1,"a":2}'),
                       ('floating_json_token', '{"n":1.0}'),
                       ('nonfinite_token', '{"n":NaN}')]:
        reject(name, lambda raw=raw: strict_loads(raw))
    for name, value in [('cycle', 'step-review'), ('missing_dependency', 'absent-step')]:
        bad_plan = copy.deepcopy(examples['plan-future-output'])
        bad_plan['nodes'][0]['depends_on'] = [value]
        reject(name, lambda value=bad_plan: check_plan(value))
    bad_plan = copy.deepcopy(examples['plan-future-output'])
    bad_plan['nodes'][1]['inputs'][0]['required_schema'] = 'b' * 64
    reject('future_output_schema_mismatch', lambda: check_plan(bad_plan))
    bad_plan = copy.deepcopy(examples['plan-future-output'])
    bad_plan['nodes'][1]['depends_on'] = []
    reject('future_output_without_dependency', lambda: check_plan(bad_plan))
    bad_run = copy.deepcopy(run);bad_run['state'] = 'paused'
    reject('paused_is_flag_not_state', lambda: validate(bad_run, 'run.schema.json'))
    for name, mutate in [
        ('domain_pack_missing_port', lambda p: p['ports'].pop('read_back')),
        ('domain_pack_unknown_port', lambda p: p['ports'].update({'free_shell': p['ports']['execute']})),
        ('domain_pack_unknown_manifest_kind', lambda p: p.update({'manifest_kind': 'trusted_by_name'})),
        ('domain_pack_untyped_handler', lambda p: p['ports']['execute'].update({'executable_path': '/bin/sh'})),
        ('domain_pack_missing_fixture_class', lambda p: p.update({'fixtures': p['fixtures'][:2]})),
        ('domain_pack_unlisted_capability', lambda p: p.update({'capability_requirements': ['fixture.unrelated']})),
    ]:
        bad_pack = copy.deepcopy(examples['domain-pack'])
        mutate(bad_pack)
        def validate_pack(value=bad_pack):
            validate(value, 'domain-pack.schema.json')
            check_domain_pack(value)
        reject(name, validate_pack)
    bad_task = copy.deepcopy(task);bad_task['run_revision'] = 1
    reject('task_has_no_execution_revision', lambda: validate(bad_task, 'task.schema.json'))

    return {'status': 'PASSED', 'specification_status': 'PROPOSED',
            'scope': 'Draft 2020-12 schema validity, strict envelope examples, local byte references, selected static cross-links, DAG/trace coverage and negative representation controls only.',
            'runtime_acceptance_tests_executed': 0,
            'runtime_acceptance_cases_remain': 'AT01..AT25 NOT_EXECUTED',
            'jsonschema_version': importlib.metadata.version('jsonschema'),
            'schemas_checked': len(schemas), 'positive_examples_checked': len(examples),
            'distinct_artifact_blobs_checked': len(artifact_ids),
            'domain_pack_ports_checked': len(examples['domain-pack']['ports']),
            'domain_fixture_representations_checked': len(examples['domain-pack']['fixtures']),
            'requirements': reqids, 'work_packages': wpids, 'acceptance_case_designs': atids,
            'negative_controls': negative,
            'representation_controls_rejected': len(negative),
            'reference_resolution': 'local registry; no network retrieval',
            'limitations': ['No agent owner, effect executor or policy service is implemented by this validation.',
                            'Static fixtures are not a complete valid event history or authenticated identities.',
                            'Schema validity does not establish transactionality, containment, authorization, temporal truth or task success.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence/spec_validation.json')
    args = parser.parse_args()
    try:
        report = execute()
        exit_status = 0
    except Exception as exc:
        report = {'status': 'FAILED', 'error_type': type(exc).__name__, 'error': str(exc),
                  'runtime_acceptance_tests_executed': 0}
        exit_status = 1
    report['executed_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['python'] = platform.python_version()
    report['inputs'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(CONTRACTS.rglob('*')) if p.is_file()}
    report['validator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('inputs', 'negative_controls')},
                     sort_keys=True, indent=2))
    return exit_status


if __name__ == '__main__':
    sys.exit(main())
