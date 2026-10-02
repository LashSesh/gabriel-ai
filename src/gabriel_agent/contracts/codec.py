"""Exact JSON codec for ``gabriel.*/1`` envelopes.

ASCII strings, no duplicate keys, no native floats, integers inside
``[-(2**53-1), 2**53-1]``, sorted keys and compact separators. Booleans are
distinct from integers. Arbitrary UTF-8 or binary content lives in referenced
artifact bytes. Canonical bytes give identity, not authenticity.
"""
from __future__ import annotations

import hashlib
import json
import re

MAX_INT = 2 ** 53 - 1
MAX_DEPTH = 64
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+/-]+(?:;[ -~]+)?\Z")


class CodecError(ValueError):
    """Raised for any value outside the exact envelope domain."""


def _check(value, depth=0, allow_utf8=False):
    if depth > MAX_DEPTH:
        raise CodecError("envelope nesting exceeds %d" % MAX_DEPTH)
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is int:
        if not -MAX_INT <= value <= MAX_INT:
            raise CodecError("integer outside exact interchange domain")
        return
    if kind is str:
        if not allow_utf8 and not value.isascii():
            raise CodecError("envelope strings must be ASCII; store UTF-8 in an artifact")
        return
    if kind is list:
        for item in value:
            _check(item, depth + 1, allow_utf8)
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str or not key.isascii():
                raise CodecError("object keys must be ASCII strings")
            _check(item, depth + 1, allow_utf8)
        return
    raise CodecError("unsupported envelope value type: " + kind.__name__)


def canonical(value) -> bytes:
    """Deterministic ASCII bytes. Never normalizes types silently."""
    try:
        _check(value)
    except RecursionError as exc:  # pragma: no cover - defensive
        raise CodecError("cyclic or excessively nested value") from exc
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CodecError("duplicate JSON object key: " + key)
        result[key] = value
    return result


def _bad_number(text):
    raise CodecError("floating point or non-finite JSON token: " + text)


def loads(raw, *, ascii_only=True):
    """Parse exact JSON from bytes or str, rejecting duplicate keys and floats.

    With ``ascii_only=False`` arbitrary UTF-8 strings are accepted (provider
    output, domain records that carry text); integers, duplicate keys, floats
    and nesting are still checked. Such values are not envelope values and
    must be stored as UTF-8 artifacts, never canonicalized as envelopes.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            text = bytes(raw).decode("ascii" if ascii_only else "utf8")
        except UnicodeDecodeError as exc:
            raise CodecError("envelope bytes must be ASCII" if ascii_only else "bytes are not valid UTF-8") from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise CodecError("expected bytes or str")
    try:
        value = json.loads(text, object_pairs_hook=_pairs,
                           parse_float=_bad_number, parse_constant=_bad_number)
    except (json.JSONDecodeError, RecursionError, TypeError, OverflowError) as exc:
        raise CodecError("invalid exact JSON: " + str(exc)) from exc
    _check(value, allow_utf8=not ascii_only)
    return value


def dumps_utf8(value) -> bytes:
    """Deterministic UTF-8 JSON for records that legitimately carry text."""
    _check(value, allow_utf8=True)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(value) -> str:
    """SHA-256 of canonical bytes: an integrity identifier, not a signature."""
    return sha256_hex(canonical(value))


def artifact_ref(raw: bytes, media_type: str = "application/octet-stream") -> dict:
    if type(raw) is not bytes:
        raise CodecError("artifact bytes must be bytes")
    if type(media_type) is not str or not MEDIA_TYPE.fullmatch(media_type) or len(media_type) > 128:
        raise CodecError("invalid media type")
    return {"sha256": sha256_hex(raw), "bytes": len(raw), "media_type": media_type}


def is_identifier(value) -> bool:
    return type(value) is str and IDENTIFIER.fullmatch(value) is not None


def is_digest(value) -> bool:
    return type(value) is str and DIGEST.fullmatch(value) is not None


def require_identifier(value, name="identifier"):
    if not is_identifier(value):
        raise CodecError(name + " must match [A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    return value


def require_digest(value, name="digest"):
    if not is_digest(value):
        raise CodecError(name + " must be 64 lowercase hexadecimal characters")
    return value


def require_uint(value, name="integer"):
    if type(value) is not int or not 0 <= value <= MAX_INT:
        raise CodecError(name + " must be a nonnegative safe integer")
    return value


def require_bool(value, name="boolean"):
    if type(value) is not bool:
        raise CodecError(name + " must be a Boolean")
    return value


def require_ref(value, name="artifact_ref"):
    if type(value) is not dict or set(value) != {"sha256", "bytes", "media_type"}:
        raise CodecError(name + " must have exactly sha256, bytes and media_type")
    require_digest(value["sha256"], name + ".sha256")
    require_uint(value["bytes"], name + ".bytes")
    if (type(value["media_type"]) is not str or len(value["media_type"]) > 128
            or not MEDIA_TYPE.fullmatch(value["media_type"])):
        raise CodecError(name + ".media_type is invalid")
    return value
