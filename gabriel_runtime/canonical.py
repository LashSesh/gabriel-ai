"""Deliberately small, exact JSON domain used by the Gabriel owner.

Binary64 quantities belong in explicitly typed adapter encodings, not JSON
numbers. Canonicalization provides byte identity, not cryptographic authenticity.
"""
import hashlib
import json

MAX_INTEGER = 2**53 - 1
MAX_DEPTH = 64


def _check(value, depth=0):
    if depth > MAX_DEPTH:
        raise ValueError("JSON nesting exceeds 64")
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is int:
        if not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise ValueError("JSON integer exceeds exact interchange domain")
        return
    if kind is str:
        if not value.isascii():
            raise ValueError("JSON strings must be ASCII")
        return
    if kind is list:
        for item in value:
            _check(item, depth + 1)
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str or not key.isascii():
                raise ValueError("JSON object keys must be exact ASCII strings")
            _check(item, depth + 1)
        return
    raise ValueError("unsupported JSON value type: " + kind.__name__)


def canonical(value):
    """Return deterministic ASCII JSON; never silently normalize types."""
    try:
        _check(value)
    except RecursionError as exc:
        raise ValueError("cyclic or excessively nested JSON") from exc
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _bad_number(_):
    raise ValueError("floating point and nonfinite JSON numbers are forbidden")


def loads(text):
    """Parse exact JSON with duplicate-key, number and depth rejection."""
    if type(text) is not str:
        raise ValueError("JSON input must be an exact string")
    try:
        value = json.loads(text, object_pairs_hook=_object,
                           parse_float=_bad_number, parse_constant=_bad_number)
        canonical(value)
        return value
    except (RecursionError, TypeError, OverflowError) as exc:
        raise ValueError("invalid exact JSON") from exc


def digest(value):
    """SHA-256 of canonical ASCII JSON (integrity identifier, not signature)."""
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()
