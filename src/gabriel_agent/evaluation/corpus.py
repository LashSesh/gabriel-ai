"""Held-out repository-repair corpus for the G1 evaluation.

Nine small Python repositories in three task families. Each carries a seeded
defect, visible tests that pass on the defective code, a reference fix and an
independent oracle (never placed in the repository) that fails on the defect
and passes on the fix. ``soundness_check`` executes these properties with the
interpreter; the corpus is frozen by digest before any evaluation run.

The reference fixes are not shown to any system under evaluation.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts.codec import canonical


@dataclass(frozen=True)
class EvalTask:
    task_id: str
    family: str
    module: str
    goal: str
    buggy: str
    fixed: str
    visible_tests: str
    oracle: str
    allowed_paths: tuple = ("src/",)

    def files(self) -> dict:
        return {"src/%s.py" % self.module: self.buggy, "tests/test_%s.py" % self.module: self.visible_tests,
                "README.md": "# %s\n\nSmall library used in the Gabriel evaluation corpus.\n" % self.module}

    def digest(self) -> str:
        return hashlib.sha256(canonical({"task_id": self.task_id, "family": self.family, "module": self.module, "goal": self.goal,
                                         "buggy": self.buggy, "visible_tests": self.visible_tests, "oracle": self.oracle,
                                         "allowed_paths": list(self.allowed_paths)})).hexdigest()


_VISIBLE_HEADER = '''import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
'''
_ORACLE_HEADER = '''import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
'''


def _task(task_id, family, module, goal, buggy, fixed, visible, oracle):
    return EvalTask(task_id, family, module, goal, buggy, fixed, _VISIBLE_HEADER + visible, _ORACLE_HEADER + oracle)


TASKS = [
    # ------------------------------------------------------------ family: text_parsing
    _task("tp-kvparse", "text_parsing", "kvparse",
          "Fix the kvparse parser bug: parse_pairs must return an empty dict for empty input and ignore blank items. "
          "Do not change the public API; keep the existing tests passing.",
          '''"""kvparse: parse comma-separated key=value pairs."""


def parse_pairs(text):
    """Return a dict of key -> value for ``"a=1,b=2"``."""
    result = {}
    for item in text.split(","):
        key, _, value = item.partition("=")
        result[key.strip()] = value.strip()
    return result
''',
          '''"""kvparse: parse comma-separated key=value pairs."""


def parse_pairs(text):
    """Return a dict of key -> value for ``"a=1,b=2"``; blank items are skipped."""
    result = {}
    for item in text.split(","):
        if not item.strip():
            continue
        key, _, value = item.partition("=")
        result[key.strip()] = value.strip()
    return result
''',
          '''from kvparse import parse_pairs


class ParsePairsTests(unittest.TestCase):
    def test_basic_pairs(self):
        self.assertEqual(parse_pairs("a=1,b=2"), {"a": "1", "b": "2"})

    def test_whitespace(self):
        self.assertEqual(parse_pairs(" a = 1 , b=2"), {"a": "1", "b": "2"})


if __name__ == "__main__":
    unittest.main()
''',
          '''from kvparse import parse_pairs


class OracleTests(unittest.TestCase):
    def test_empty_string_is_empty_dict(self):
        self.assertEqual(parse_pairs(""), {})

    def test_trailing_comma_is_ignored(self):
        self.assertEqual(parse_pairs("a=1,"), {"a": "1"})

    def test_basic_still_works(self):
        self.assertEqual(parse_pairs("a=1,b=2"), {"a": "1", "b": "2"})


if __name__ == "__main__":
    unittest.main()
'''),
    _task("tp-csvfields", "text_parsing", "csvfields",
          "Fix the reported defect in csvfields.split_fields: a doubled double-quote inside a quoted field must be unescaped "
          "to a single double-quote character, and a quoted field may contain commas. Keep the public API and the existing tests.",
          '''"""csvfields: split one CSV line into fields (RFC 4180 subset)."""


def split_fields(line):
    fields, current, quoted = [], [], False
    i = 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == '"':
                quoted = False
            else:
                current.append(ch)
        elif ch == '"':
            quoted = True
        elif ch == ",":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    fields.append("".join(current))
    return fields
''',
          '''"""csvfields: split one CSV line into fields (RFC 4180 subset)."""


def split_fields(line):
    fields, current, quoted = [], [], False
    i = 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    current.append('"')
                    i += 1
                else:
                    quoted = False
            else:
                current.append(ch)
        elif ch == '"':
            quoted = True
        elif ch == ",":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    fields.append("".join(current))
    return fields
''',
          '''from csvfields import split_fields


class SplitFieldsTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(split_fields("a,b,c"), ["a", "b", "c"])

    def test_quoted_comma(self):
        self.assertEqual(split_fields('"x,y",z'), ["x,y", "z"])


if __name__ == "__main__":
    unittest.main()
''',
          '''from csvfields import split_fields


class OracleTests(unittest.TestCase):
    def test_doubled_quote_is_unescaped(self):
        self.assertEqual(split_fields('"say ""hi""",b'), ['say "hi"', "b"])

    def test_empty_fields(self):
        self.assertEqual(split_fields("a,,c,"), ["a", "", "c", ""])

    def test_quoted_comma_still_works(self):
        self.assertEqual(split_fields('"x,y",z'), ["x,y", "z"])


if __name__ == "__main__":
    unittest.main()
'''),
    _task("tp-querystring", "text_parsing", "querystring",
          "Fix the reported defect in querystring.parse_qs: a plus sign in a value must decode to a space, and a key without "
          "an equals sign must map to an empty string. Keep percent-decoding, the public API and the existing tests.",
          '''"""querystring: parse application/x-www-form-urlencoded strings."""
from urllib.parse import unquote


def parse_qs(text):
    result = {}
    if not text:
        return result
    for part in text.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[unquote(key)] = unquote(value)
    return result
''',
          '''"""querystring: parse application/x-www-form-urlencoded strings."""
from urllib.parse import unquote


def parse_qs(text):
    result = {}
    if not text:
        return result
    for part in text.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        result[unquote(key.replace("+", " "))] = unquote(value.replace("+", " "))
    return result
''',
          '''from querystring import parse_qs


class ParseQsTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_qs("a=1&b=2"), {"a": "1", "b": "2"})

    def test_percent_decoding(self):
        self.assertEqual(parse_qs("q=a%20b"), {"q": "a b"})


if __name__ == "__main__":
    unittest.main()
''',
          '''from querystring import parse_qs


class OracleTests(unittest.TestCase):
    def test_plus_is_space(self):
        self.assertEqual(parse_qs("q=a+b"), {"q": "a b"})

    def test_key_without_value(self):
        self.assertEqual(parse_qs("flag&a=1"), {"flag": "", "a": "1"})

    def test_percent_still_works(self):
        self.assertEqual(parse_qs("q=a%20b&x=%41"), {"q": "a b", "x": "A"})


if __name__ == "__main__":
    unittest.main()
'''),
    # ------------------------------------------------------------ family: numeric_logic
    _task("nl-median", "numeric_logic", "stats",
          "Fix the reported defect in stats.median: for an even number of values the median must be the arithmetic mean of "
          "the two middle values of the sorted data (as a float). Keep the public API and the existing tests.",
          '''"""stats: tiny descriptive statistics."""


def median(values):
    data = sorted(values)
    if not data:
        raise ValueError("median of empty data")
    return data[len(data) // 2]


def mean(values):
    values = list(values)
    if not values:
        raise ValueError("mean of empty data")
    return sum(values) / len(values)
''',
          '''"""stats: tiny descriptive statistics."""


def median(values):
    data = sorted(values)
    if not data:
        raise ValueError("median of empty data")
    middle = len(data) // 2
    if len(data) % 2 == 1:
        return data[middle]
    return (data[middle - 1] + data[middle]) / 2


def mean(values):
    values = list(values)
    if not values:
        raise ValueError("mean of empty data")
    return sum(values) / len(values)
''',
          '''from stats import median, mean


class StatsTests(unittest.TestCase):
    def test_odd_median(self):
        self.assertEqual(median([3, 1, 2]), 2)

    def test_mean(self):
        self.assertEqual(mean([1, 2, 3, 4]), 2.5)


if __name__ == "__main__":
    unittest.main()
''',
          '''from stats import median


class OracleTests(unittest.TestCase):
    def test_even_median_is_mean_of_middle(self):
        self.assertEqual(median([4, 1, 3, 2]), 2.5)

    def test_two_values(self):
        self.assertEqual(median([10, 20]), 15.0)

    def test_odd_still_works(self):
        self.assertEqual(median([9, 7, 8]), 8)


if __name__ == "__main__":
    unittest.main()
'''),
    _task("nl-roman", "numeric_logic", "roman",
          "Fix the reported defect in roman.to_int: subtractive notation (IV, IX, XL, XC, CD, CM) must be handled, so that "
          "'IV' is 4 and 'MCMXCIV' is 1994. Keep the public API and the existing tests.",
          '''"""roman: Roman numeral conversion."""
VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def to_int(text):
    total = 0
    for ch in text:
        total += VALUES[ch]
    return total
''',
          '''"""roman: Roman numeral conversion."""
VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def to_int(text):
    total = 0
    for index, ch in enumerate(text):
        value = VALUES[ch]
        if index + 1 < len(text) and VALUES[text[index + 1]] > value:
            total -= value
        else:
            total += value
    return total
''',
          '''from roman import to_int


class RomanTests(unittest.TestCase):
    def test_additive(self):
        self.assertEqual(to_int("III"), 3)
        self.assertEqual(to_int("LVIII"), 58)

    def test_single(self):
        self.assertEqual(to_int("M"), 1000)


if __name__ == "__main__":
    unittest.main()
''',
          '''from roman import to_int


class OracleTests(unittest.TestCase):
    def test_subtractive(self):
        self.assertEqual(to_int("IV"), 4)
        self.assertEqual(to_int("IX"), 9)

    def test_mixed(self):
        self.assertEqual(to_int("MCMXCIV"), 1994)

    def test_additive_still_works(self):
        self.assertEqual(to_int("LVIII"), 58)


if __name__ == "__main__":
    unittest.main()
'''),
    _task("nl-leapyear", "numeric_logic", "calendarx",
          "Fix the reported defect in calendarx.is_leap: years divisible by 100 are not leap years unless they are also "
          "divisible by 400 (1900 is not a leap year, 2000 is). days_in_month must follow. Keep the public API and the existing tests.",
          '''"""calendarx: Gregorian calendar helpers."""


def is_leap(year):
    return year % 4 == 0


def days_in_month(year, month):
    if month == 2:
        return 29 if is_leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31
''',
          '''"""calendarx: Gregorian calendar helpers."""


def is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year, month):
    if month == 2:
        return 29 if is_leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31
''',
          '''from calendarx import is_leap, days_in_month


class CalendarTests(unittest.TestCase):
    def test_common_years(self):
        self.assertTrue(is_leap(2024))
        self.assertFalse(is_leap(2023))

    def test_days(self):
        self.assertEqual(days_in_month(2024, 2), 29)
        self.assertEqual(days_in_month(2023, 4), 30)


if __name__ == "__main__":
    unittest.main()
''',
          '''from calendarx import is_leap, days_in_month


class OracleTests(unittest.TestCase):
    def test_century_rule(self):
        self.assertFalse(is_leap(1900))
        self.assertTrue(is_leap(2000))

    def test_february_1900(self):
        self.assertEqual(days_in_month(1900, 2), 28)

    def test_ordinary_leap_still_works(self):
        self.assertTrue(is_leap(2024))


if __name__ == "__main__":
    unittest.main()
'''),
    # ------------------------------------------------------------ family: collections
    _task("co-dedupe", "collections", "seqtools",
          "Fix the reported defect in seqtools.dedupe: duplicates must be removed while preserving the order of first "
          "occurrence. Keep the public API and the existing tests.",
          '''"""seqtools: sequence helpers."""


def dedupe(items):
    return list(set(items))
''',
          '''"""seqtools: sequence helpers."""


def dedupe(items):
    seen, result = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
''',
          '''from seqtools import dedupe


class DedupeTests(unittest.TestCase):
    def test_no_duplicates_remain(self):
        self.assertEqual(sorted(dedupe([3, 1, 3, 2, 1])), [1, 2, 3])

    def test_empty(self):
        self.assertEqual(dedupe([]), [])


if __name__ == "__main__":
    unittest.main()
''',
          '''from seqtools import dedupe


class OracleTests(unittest.TestCase):
    def test_order_of_first_occurrence(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])

    def test_strings(self):
        self.assertEqual(dedupe(["b", "a", "b", "c"]), ["b", "a", "c"])

    def test_single(self):
        self.assertEqual(dedupe([7]), [7])


if __name__ == "__main__":
    unittest.main()
'''),
    _task("co-slugify", "collections", "slug",
          "Fix the reported defect in slug.slugify: runs of non-alphanumeric characters must collapse into a single hyphen "
          "and the result must not start or end with a hyphen. Keep the public API and the existing tests.",
          '''"""slug: URL slugs."""
import re


def slugify(text):
    return re.sub(r"[^a-z0-9]", "-", text.lower())
''',
          '''"""slug: URL slugs."""
import re


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
''',
          '''from slug import slugify


class SlugifyTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_lowercase(self):
        self.assertEqual(slugify("ABC"), "abc")


if __name__ == "__main__":
    unittest.main()
''',
          '''from slug import slugify


class OracleTests(unittest.TestCase):
    def test_collapses_runs(self):
        self.assertEqual(slugify("Hello   World!"), "hello-world")

    def test_strips_edges(self):
        self.assertEqual(slugify(" --x-- "), "x")

    def test_simple_still_works(self):
        self.assertEqual(slugify("Hello World"), "hello-world")


if __name__ == "__main__":
    unittest.main()
'''),
    _task("co-chunk", "collections", "chunking",
          "Fix the reported defect in chunking.chunk: the final partial chunk must be kept when the length is not a multiple "
          "of the chunk size, and a size larger than the input yields one chunk. Keep the public API and the existing tests.",
          '''"""chunking: split sequences into fixed-size chunks."""


def chunk(items, size):
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i:i + size] for i in range(0, len(items) - size + 1, size)]
''',
          '''"""chunking: split sequences into fixed-size chunks."""


def chunk(items, size):
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i:i + size] for i in range(0, len(items), size)]
''',
          '''from chunking import chunk


class ChunkTests(unittest.TestCase):
    def test_exact_multiple(self):
        self.assertEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_invalid_size(self):
        with self.assertRaises(ValueError):
            chunk([1], 0)


if __name__ == "__main__":
    unittest.main()
''',
          '''from chunking import chunk


class OracleTests(unittest.TestCase):
    def test_partial_last_chunk(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_size_larger_than_input(self):
        self.assertEqual(chunk([1, 2], 5), [[1, 2]])

    def test_empty(self):
        self.assertEqual(chunk([], 3), [])


if __name__ == "__main__":
    unittest.main()
'''),
    # ------------------------------------------------------------ family: validation (added after the first frozen run; held out there)
    _task("vl-email", "validation", "emailcheck",
          "Fix the reported defect in emailcheck.is_valid_email: the domain part must contain a dot with at least one character "
          "before and after it, so 'a@b' is invalid while 'a@b.co' is valid. Keep the public API and the existing tests.",
          '''"""emailcheck: minimal e-mail address validation."""


def is_valid_email(text):
    if text.count("@") != 1:
        return False
    local, domain = text.split("@")
    return bool(local) and bool(domain) and " " not in text
''',
          '''"""emailcheck: minimal e-mail address validation."""


def is_valid_email(text):
    if text.count("@") != 1:
        return False
    local, domain = text.split("@")
    if not local or not domain or " " in text:
        return False
    head, dot, tail = domain.rpartition(".")
    return dot == "." and bool(head) and bool(tail)
''',
          '''from emailcheck import is_valid_email


class EmailTests(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_valid_email("user@example.com"))

    def test_invalid(self):
        self.assertFalse(is_valid_email("no-at-sign"))
        self.assertFalse(is_valid_email("two@@example.com"))


if __name__ == "__main__":
    unittest.main()
''',
          '''from emailcheck import is_valid_email


class OracleTests(unittest.TestCase):
    def test_domain_needs_dot(self):
        self.assertFalse(is_valid_email("a@b"))
        self.assertFalse(is_valid_email("a@b."))
        self.assertFalse(is_valid_email("a@.b"))

    def test_dotted_domain_is_valid(self):
        self.assertTrue(is_valid_email("a@b.co"))

    def test_basic_still_works(self):
        self.assertTrue(is_valid_email("user@example.com"))
        self.assertFalse(is_valid_email("no-at-sign"))


if __name__ == "__main__":
    unittest.main()
'''),
    _task("vl-isbn10", "validation", "isbn",
          "Fix the reported defect in isbn.is_valid_isbn10: the check digit may be the letter X (value 10) in the last position, "
          "so '0-306-40615-2' and '0-8044-2957-X' are both valid. Keep the public API and the existing tests.",
          '''"""isbn: ISBN-10 validation."""


def is_valid_isbn10(text):
    digits = [ch for ch in text if ch != "-"]
    if len(digits) != 10 or not all(ch.isdigit() for ch in digits):
        return False
    total = sum((10 - index) * int(ch) for index, ch in enumerate(digits))
    return total % 11 == 0
''',
          '''"""isbn: ISBN-10 validation."""


def is_valid_isbn10(text):
    digits = [ch for ch in text if ch != "-"]
    if len(digits) != 10 or not all(ch.isdigit() for ch in digits[:9]):
        return False
    last = digits[9]
    if last not in "0123456789Xx":
        return False
    values = [int(ch) for ch in digits[:9]] + [10 if last in "Xx" else int(last)]
    total = sum((10 - index) * value for index, value in enumerate(values))
    return total % 11 == 0
''',
          '''from isbn import is_valid_isbn10


class IsbnTests(unittest.TestCase):
    def test_valid_numeric(self):
        self.assertTrue(is_valid_isbn10("0-306-40615-2"))

    def test_invalid(self):
        self.assertFalse(is_valid_isbn10("0-306-40615-3"))
        self.assertFalse(is_valid_isbn10("12345"))


if __name__ == "__main__":
    unittest.main()
''',
          '''from isbn import is_valid_isbn10


class OracleTests(unittest.TestCase):
    def test_x_check_digit(self):
        self.assertTrue(is_valid_isbn10("0-8044-2957-X"))

    def test_x_only_in_last_position(self):
        self.assertFalse(is_valid_isbn10("0-X044-2957-1"))

    def test_numeric_still_works(self):
        self.assertTrue(is_valid_isbn10("0-306-40615-2"))
        self.assertFalse(is_valid_isbn10("0-306-40615-3"))


if __name__ == "__main__":
    unittest.main()
'''),
    _task("vl-luhn", "validation", "luhn",
          "Fix the reported defect in luhn.is_valid: the Luhn algorithm doubles every second digit counting from the rightmost "
          "digit (the check digit is never doubled), so the 16-digit number '4539 1488 0343 6467' must be valid and "
          "'4539 1488 0343 6468' invalid. Keep the public API and the existing tests.",
          '''"""luhn: Luhn checksum validation for identification numbers."""


def is_valid(text):
    digits = [int(ch) for ch in text if ch.isdigit()]
    if len(digits) < 2:
        return False
    total = 0
    for index, digit in enumerate(digits):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
''',
          '''"""luhn: Luhn checksum validation for identification numbers."""


def is_valid(text):
    digits = [int(ch) for ch in text if ch.isdigit()]
    if len(digits) < 2:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
''',
          '''from luhn import is_valid


class LuhnTests(unittest.TestCase):
    def test_odd_length_valid(self):
        self.assertTrue(is_valid("79927398713"))

    def test_too_short(self):
        self.assertFalse(is_valid("7"))


if __name__ == "__main__":
    unittest.main()
''',
          '''from luhn import is_valid


class OracleTests(unittest.TestCase):
    def test_even_length_valid(self):
        self.assertTrue(is_valid("4539 1488 0343 6467"))

    def test_even_length_invalid(self):
        self.assertFalse(is_valid("4539 1488 0343 6468"))

    def test_odd_length_still_works(self):
        self.assertTrue(is_valid("79927398713"))
        self.assertFalse(is_valid("79927398710"))


if __name__ == "__main__":
    unittest.main()
'''),
]


def tasks() -> list:
    return list(TASKS)


def families() -> dict:
    result = {}
    for task in TASKS:
        result.setdefault(task.family, []).append(task.task_id)
    return result


def corpus_digest() -> str:
    return hashlib.sha256(canonical([t.digest() for t in TASKS])).hexdigest()


_GIT_ENV = dict(GIT_AUTHOR_NAME="corpus", GIT_AUTHOR_EMAIL="corpus@invalid", GIT_COMMITTER_NAME="corpus",
                GIT_COMMITTER_EMAIL="corpus@invalid", GIT_CONFIG_NOSYSTEM="1")


def materialize(task: EvalTask, repo: Path) -> str:
    """Write the defective repository and commit it; returns the base commit."""
    repo = Path(repo)
    for rel, content in task.files().items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    env = dict(os.environ, **_GIT_ENV)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "seed %s" % task.task_id], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def write_oracle(task: EvalTask, directory: Path) -> Path:
    path = Path(directory) / ("oracle_%s.py" % task.module)
    path.write_text(task.oracle)
    return path


def visible_argv(task: EvalTask) -> list:
    return ["python3", "-m", "unittest", "discover", "-s", "tests"]


def oracle_argv(task: EvalTask) -> list:
    return ["python3", "-m", "unittest", "oracle_%s" % task.module]


def task_spec(task: EvalTask, repo: Path, base_commit: str, oracle_path: Path, provider: dict, budget: dict, **over) -> dict:
    spec = {"goal": task.goal, "repository": str(repo), "base_commit": base_commit, "allowed_paths": list(task.allowed_paths),
            "checks": [{"check_id": "unit", "kind": "software/test_passed", "argv": visible_argv(task), "timeout_ms": 60000,
                        "role": "baseline_and_acceptance"},
                       {"check_id": "oracle", "kind": "software/test_passed", "argv": oracle_argv(task), "timeout_ms": 60000,
                        "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle_%s.py" % task.module, "source": str(oracle_path)}]}],
            "provider": provider, "budget": budget}
    spec.update(over)
    return spec


def _run(argv, cwd, timeout=120):
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
    return proc.returncode


def soundness_check(task: EvalTask, python: str = "python3") -> dict:
    """Execute the corpus invariants: visible tests pass on the defect, the oracle fails on the
    defect, and both pass on the reference fix. Runs in temporary directories only."""
    results = {}
    with tempfile.TemporaryDirectory(prefix="gabriel-corpus-") as directory:
        root = Path(directory)
        for variant, source in (("buggy", task.buggy), ("fixed", task.fixed)):
            repo = root / variant
            for rel, content in task.files().items():
                path = repo / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            (repo / "src" / (task.module + ".py")).write_text(source)
            write_oracle(task, repo)
            visible = _run([python] + visible_argv(task)[1:], repo)
            oracle = _run([python] + oracle_argv(task)[1:], repo)
            results[variant] = {"visible_exit": visible, "oracle_exit": oracle}
    sound = (results["buggy"]["visible_exit"] == 0 and results["buggy"]["oracle_exit"] != 0
             and results["fixed"]["visible_exit"] == 0 and results["fixed"]["oracle_exit"] == 0)
    return {"task_id": task.task_id, "family": task.family, "sound": sound, "results": results, "digest": task.digest()}


def check_all(python: str = sys.executable) -> dict:
    report = [soundness_check(task, python) for task in TASKS]
    return {"corpus_digest": corpus_digest(), "tasks": report, "all_sound": all(r["sound"] for r in report),
            "families": families()}
