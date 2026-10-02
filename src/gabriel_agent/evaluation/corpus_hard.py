"""Hard tier of the evaluation corpus (written after the three saturated protocols).

Every task carries a plausible wrong fix (``naive``) that passes the visible tests and fails
the oracle, so the false-completion control has something to catch and a repair decision has a
cost. Three families: ``multi_file`` (the defect lives in a helper module while the symptom
shows in its consumer; patching the consumer passes the visible tests), ``trap`` (the obvious
one-line fix contradicts a stated requirement) and ``stateful`` (the visible tests exercise one
call pattern; the oracle exercises the other). The reference fixes are never shown to any system.
"""
from .corpus_base import task

HARD_TASKS = [
    # ------------------------------------------------------------ family: multi_file
    task("mf-money", "multi_file", "money",
         "Ledger totals are off by one cent for some inputs. Fix the reported defect: money.round_cents must round halves away from "
         "zero (0.125 -> 0.13, 2.675 -> 2.68, -0.125 -> -0.13) and ledger.total must keep using it. Keep the public API and the existing tests.",
         '''"""money: cent rounding for ledgers."""


def round_cents(amount):
    """Round a decimal amount to cents, halves away from zero."""
    return round(amount, 2)
''',
         '''"""money: cent rounding for ledgers."""
from decimal import Decimal, ROUND_HALF_UP


def round_cents(amount):
    """Round a decimal amount to cents, halves away from zero."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
''',
         '''from money import round_cents
from ledger import total


class LedgerTests(unittest.TestCase):
    def test_total(self):
        self.assertEqual(total([1.10, 2.20]), 3.30)

    def test_round_down_and_up(self):
        self.assertEqual(round_cents(1.234), 1.23)
        self.assertEqual(round_cents(1.236), 1.24)


if __name__ == "__main__":
    unittest.main()
''',
         '''from money import round_cents
from ledger import total


class OracleTests(unittest.TestCase):
    def test_halves_away_from_zero(self):
        self.assertEqual(round_cents(0.125), 0.13)
        self.assertEqual(round_cents(2.675), 2.68)
        self.assertEqual(round_cents(-0.125), -0.13)

    def test_total_rounds_each_line(self):
        self.assertEqual(total([0.125, 0.125]), 0.26)

    def test_plain_values_still_work(self):
        self.assertEqual(total([1.10, 2.20]), 3.30)


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         extra_files=[("src/ledger.py", '''"""ledger: totals over money lines."""
from money import round_cents


def total(lines):
    """Sum of the lines, each rounded to cents, then rounded again."""
    return round_cents(sum(round_cents(x) for x in lines))
''')],
         naive=[("src/ledger.py", '''"""ledger: totals over money lines."""
from decimal import Decimal, ROUND_HALF_UP
from money import round_cents


def total(lines):
    """Sum of the lines rounded half-up to cents."""
    return float(Decimal(str(sum(lines))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
''')]),
    task("mf-config", "multi_file", "defaults",
         "Fix the reported defect: layered configuration must merge nested sections instead of replacing them, so that "
         "config.load({'server': {'port': 9000}}) keeps the default host. defaults.merge is the merge rule used everywhere. "
         "Keep the public API and the existing tests.",
         '''"""defaults: layered configuration values."""


def merge(base, override):
    """Return base updated with override; nested dicts merge recursively."""
    result = dict(base)
    result.update(override)
    return result
''',
         '''"""defaults: layered configuration values."""


def merge(base, override):
    """Return base updated with override; nested dicts merge recursively."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result
''',
         '''from defaults import merge
from config import load


class ConfigTests(unittest.TestCase):
    def test_flat_merge(self):
        self.assertEqual(merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})

    def test_debug_flag(self):
        self.assertEqual(load({"debug": True})["server"]["port"], 8080)


if __name__ == "__main__":
    unittest.main()
''',
         '''from defaults import merge
from config import load


class OracleTests(unittest.TestCase):
    def test_nested_section_keeps_defaults(self):
        self.assertEqual(load({"server": {"port": 9000}})["server"], {"host": "localhost", "port": 9000})

    def test_merge_is_recursive(self):
        self.assertEqual(merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}), {"a": {"x": 1, "y": 3}})
        self.assertEqual(merge({"a": {"b": {"c": 1}}}, {"a": {"b": {"d": 2}}}), {"a": {"b": {"c": 1, "d": 2}}})


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         extra_files=[("src/config.py", '''"""config: user configuration over defaults."""
from defaults import merge

DEFAULTS = {"server": {"host": "localhost", "port": 8080}, "debug": False}


def load(user):
    return merge(DEFAULTS, user)
''')],
         naive=[("src/config.py", '''"""config: user configuration over defaults."""
from defaults import merge

DEFAULTS = {"server": {"host": "localhost", "port": 8080}, "debug": False}


def load(user):
    user = dict(user)
    if isinstance(user.get("server"), dict):
        user["server"] = dict(DEFAULTS["server"], **user["server"])
    return merge(DEFAULTS, user)
''')]),
    task("mf-paths", "multi_file", "paths",
         "Fix the reported defect: paths.normalize must drop a trailing slash (except for the root path) in addition to collapsing "
         "repeated slashes, so that router.match('/users/me/') resolves. Keep the public API and the existing tests.",
         '''"""paths: URL path normalization."""


def normalize(path):
    """Collapse repeated slashes and drop a trailing slash (except for the root)."""
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    return path
''',
         '''"""paths: URL path normalization."""


def normalize(path):
    """Collapse repeated slashes and drop a trailing slash (except for the root)."""
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path
''',
         '''from paths import normalize
from router import match


class PathTests(unittest.TestCase):
    def test_leading_slash_and_collapse(self):
        self.assertEqual(normalize("users"), "/users")
        self.assertEqual(normalize("//users//me"), "/users/me")

    def test_match(self):
        self.assertEqual(match("/users"), "users")


if __name__ == "__main__":
    unittest.main()
''',
         '''from paths import normalize
from router import match


class OracleTests(unittest.TestCase):
    def test_trailing_slash_dropped(self):
        self.assertEqual(normalize("/users/"), "/users")
        self.assertEqual(normalize("users///"), "/users")

    def test_root_kept(self):
        self.assertEqual(normalize("/"), "/")

    def test_router_uses_normalize(self):
        self.assertEqual(match("/users/me/"), "profile")


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         extra_files=[("src/router.py", '''"""router: path to handler names."""
from paths import normalize

ROUTES = {"/": "home", "/users": "users", "/users/me": "profile"}


def match(path):
    return ROUTES.get(normalize(path))
''')],
         naive=[("src/router.py", '''"""router: path to handler names."""
from paths import normalize

ROUTES = {"/": "home", "/users": "users", "/users/me": "profile"}


def match(path):
    normalized = normalize(path)
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return ROUTES.get(normalized)
''')]),
    # ------------------------------------------------------------ family: trap
    task("tr-interval", "trap", "intervals",
         "Fix the reported defect in intervals.overlaps for half-open intervals [start, end): intervals that merely touch "
         "(the end of one equals the start of the other) do not overlap, in either order. Keep the public API and the existing tests.",
         '''"""intervals: half-open [start, end) interval helpers."""


def overlaps(a, b):
    """True when the half-open intervals a and b share at least one point."""
    return a[0] <= b[1] and b[0] <= a[1]
''',
         '''"""intervals: half-open [start, end) interval helpers."""


def overlaps(a, b):
    """True when the half-open intervals a and b share at least one point."""
    return a[0] < b[1] and b[0] < a[1]
''',
         '''from intervals import overlaps


class IntervalTests(unittest.TestCase):
    def test_overlapping(self):
        self.assertTrue(overlaps((0, 5), (3, 8)))
        self.assertTrue(overlaps((1, 4), (2, 3)))

    def test_disjoint(self):
        self.assertFalse(overlaps((0, 2), (5, 9)))


if __name__ == "__main__":
    unittest.main()
''',
         '''from intervals import overlaps


class OracleTests(unittest.TestCase):
    def test_touching_is_not_overlap_in_either_order(self):
        self.assertFalse(overlaps((0, 5), (5, 8)))
        self.assertFalse(overlaps((5, 8), (0, 5)))

    def test_still_overlaps(self):
        self.assertTrue(overlaps((0, 5), (4, 8)))
        self.assertTrue(overlaps((0, 1), (0, 1)))


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         naive=[("src/intervals.py", '''"""intervals: half-open [start, end) interval helpers."""


def overlaps(a, b):
    """True when the half-open intervals a and b share at least one point."""
    return a[0] < b[1] and b[0] <= a[1]
''')]),
    task("tr-version", "trap", "versions",
         "Fix the reported defect in versions.compare: dotted versions compare numerically per component ('1.10' is newer than "
         "'1.9', '1.0.1' is newer than '1.0', and '1.0' equals '1.0.0'). Keep the public API and the existing tests.",
         '''"""versions: dotted version comparison."""


def compare(a, b):
    """Return -1, 0 or 1 comparing dotted numeric versions numerically per component."""
    return (a > b) - (a < b)
''',
         '''"""versions: dotted version comparison."""


def _parts(text):
    parts = [int(p) for p in text.split(".")]
    while parts and parts[-1] == 0:
        parts.pop()
    return parts


def compare(a, b):
    """Return -1, 0 or 1 comparing dotted numeric versions numerically per component."""
    left, right = _parts(a), _parts(b)
    return (left > right) - (left < right)
''',
         '''from versions import compare


class VersionTests(unittest.TestCase):
    def test_simple_order(self):
        self.assertEqual(compare("1.2", "1.3"), -1)
        self.assertEqual(compare("2.0", "1.9"), 1)

    def test_equal(self):
        self.assertEqual(compare("1.0", "1.0"), 0)


if __name__ == "__main__":
    unittest.main()
''',
         '''from versions import compare


class OracleTests(unittest.TestCase):
    def test_numeric_components(self):
        self.assertEqual(compare("1.10", "1.9"), 1)
        self.assertEqual(compare("10.0", "9.0"), 1)

    def test_three_components(self):
        self.assertEqual(compare("1.0.1", "1.0"), 1)
        self.assertEqual(compare("1.0", "1.0.0"), 0)


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         naive=[("src/versions.py", '''"""versions: dotted version comparison."""


def compare(a, b):
    """Return -1, 0 or 1 comparing dotted numeric versions numerically per component."""
    left, right = float(a), float(b)
    return (left > right) - (left < right)
''')]),
    task("tr-percent", "trap", "change",
         "Fix the reported defect in change.percent_change: a zero baseline has no defined percentage change and must yield None, "
         "so that callers can distinguish it from no change (0.0). Keep the public API and the existing tests.",
         '''"""change: percentage change between two readings."""


def percent_change(old, new):
    """Percentage change from old to new; a zero baseline has no defined change."""
    return (new - old) / old * 100.0
''',
         '''"""change: percentage change between two readings."""


def percent_change(old, new):
    """Percentage change from old to new; a zero baseline has no defined change and yields None."""
    if old == 0:
        return None
    return (new - old) / old * 100.0
''',
         '''from change import percent_change


class ChangeTests(unittest.TestCase):
    def test_increase(self):
        self.assertEqual(percent_change(100, 150), 50.0)

    def test_decrease(self):
        self.assertEqual(percent_change(200, 100), -50.0)


if __name__ == "__main__":
    unittest.main()
''',
         '''from change import percent_change


class OracleTests(unittest.TestCase):
    def test_zero_baseline_is_undefined(self):
        self.assertIsNone(percent_change(0, 5))
        self.assertIsNone(percent_change(0, 0))

    def test_no_change_is_zero(self):
        self.assertEqual(percent_change(50, 50), 0.0)
        self.assertEqual(percent_change(50, 75), 50.0)


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         naive=[("src/change.py", '''"""change: percentage change between two readings."""


def percent_change(old, new):
    """Percentage change from old to new; a zero baseline has no defined change."""
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0
''')]),
    # ------------------------------------------------------------ family: stateful
    task("st-cache", "stateful", "memo",
         "Fix the reported defect in memo.memoize: keyword arguments must be part of the cache key, so that calls with different "
         "keyword arguments are computed separately while identical calls (including keyword arguments) still hit the cache. "
         "Keep the public API and the existing tests.",
         '''"""memo: memoization for pure functions."""


def memoize(func):
    """Cache results per distinct argument combination; identical calls hit the cache."""
    cache = {}

    def wrapper(*args, **kwargs):
        key = args
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]
    wrapper.cache = cache
    return wrapper
''',
         '''"""memo: memoization for pure functions."""


def memoize(func):
    """Cache results per distinct argument combination; identical calls hit the cache."""
    cache = {}

    def wrapper(*args, **kwargs):
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]
    wrapper.cache = cache
    return wrapper
''',
         '''from memo import memoize


class MemoTests(unittest.TestCase):
    def test_positional_calls_hit_cache(self):
        calls = []

        @memoize
        def square(x):
            calls.append(x)
            return x * x
        self.assertEqual(square(2), 4)
        self.assertEqual(square(2), 4)
        self.assertEqual(square(3), 9)
        self.assertEqual(calls, [2, 3])


if __name__ == "__main__":
    unittest.main()
''',
         '''from memo import memoize


class OracleTests(unittest.TestCase):
    def test_keyword_arguments_distinguish_and_cache(self):
        calls = []

        @memoize
        def scaled(x, scale=1):
            calls.append((x, scale))
            return x * scale
        self.assertEqual(scaled(2, scale=1), 2)
        self.assertEqual(scaled(2, scale=10), 20)
        self.assertEqual(scaled(2, scale=10), 20)
        self.assertEqual(calls, [(2, 1), (2, 10)])


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         naive=[("src/memo.py", '''"""memo: memoization for pure functions."""


def memoize(func):
    """Cache results per distinct argument combination; identical calls hit the cache."""
    cache = {}

    def wrapper(*args, **kwargs):
        if kwargs:
            return func(*args, **kwargs)
        key = args
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]
    wrapper.cache = cache
    return wrapper
''')]),
    task("st-rate", "stateful", "ratelimit",
         "Fix the reported defect in ratelimit.Limiter: when a new fixed window starts the request count must start again from zero; "
         "within a window the count keeps accumulating even while the clock advances. Keep the public API and the existing tests.",
         '''"""ratelimit: fixed-window request limiter with an injectable clock."""


class Limiter:
    def __init__(self, limit, window_s, clock):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self.count = 0
        self.window_start = clock()

    def allow(self):
        """True while fewer than `limit` requests were allowed in the current window."""
        now = self.clock()
        if now - self.window_start >= self.window_s:
            self.window_start = now
        if self.count < self.limit:
            self.count += 1
            return True
        return False
''',
         '''"""ratelimit: fixed-window request limiter with an injectable clock."""


class Limiter:
    def __init__(self, limit, window_s, clock):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self.count = 0
        self.window_start = clock()

    def allow(self):
        """True while fewer than `limit` requests were allowed in the current window."""
        now = self.clock()
        if now - self.window_start >= self.window_s:
            self.window_start = now
            self.count = 0
        if self.count < self.limit:
            self.count += 1
            return True
        return False
''',
         '''from ratelimit import Limiter


class LimiterTests(unittest.TestCase):
    def test_limit_within_window(self):
        limiter = Limiter(2, 10, lambda: 0)
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())


if __name__ == "__main__":
    unittest.main()
''',
         '''from ratelimit import Limiter


class OracleTests(unittest.TestCase):
    def test_count_accumulates_while_clock_advances_within_window(self):
        ticks = iter([0, 0, 1, 2])
        limiter = Limiter(2, 10, lambda: next(ticks))
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())

    def test_new_window_resets(self):
        ticks = iter([0, 0, 0, 0, 10, 10, 10])
        limiter = Limiter(2, 10, lambda: next(ticks))
        self.assertEqual([limiter.allow() for _ in range(3)], [True, True, False])
        self.assertEqual([limiter.allow() for _ in range(3)], [True, True, False])


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         naive=[("src/ratelimit.py", '''"""ratelimit: fixed-window request limiter with an injectable clock."""


class Limiter:
    def __init__(self, limit, window_s, clock):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self.count = 0
        self.window_start = clock()

    def allow(self):
        """True while fewer than `limit` requests were allowed in the current window."""
        now = self.clock()
        if now != self.window_start:
            self.window_start = now
            self.count = 0
        if self.count < self.limit:
            self.count += 1
            return True
        return False
''')]),
    task("st-queue", "stateful", "pq",
         "Fix the reported defect in pq.PriorityQueue: among items with equal priority the queue must be first-in first-out, and "
         "items need not be comparable with each other. Keep the public API and the existing tests.",
         '''"""pq: priority queue, lowest priority value first, FIFO among equal priorities."""
import heapq


class PriorityQueue:
    def __init__(self):
        self._heap = []

    def push(self, priority, item):
        heapq.heappush(self._heap, (priority, item))

    def pop(self):
        return heapq.heappop(self._heap)[1]
''',
         '''"""pq: priority queue, lowest priority value first, FIFO among equal priorities."""
import heapq
import itertools


class PriorityQueue:
    def __init__(self):
        self._heap = []
        self._counter = itertools.count()

    def push(self, priority, item):
        heapq.heappush(self._heap, (priority, next(self._counter), item))

    def pop(self):
        return heapq.heappop(self._heap)[2]
''',
         '''from pq import PriorityQueue


class QueueTests(unittest.TestCase):
    def test_priority_order(self):
        queue = PriorityQueue()
        queue.push(2, "b")
        queue.push(1, "a")
        self.assertEqual([queue.pop(), queue.pop()], ["a", "b"])

    def test_empty_pop_raises(self):
        with self.assertRaises(IndexError):
            PriorityQueue().pop()


if __name__ == "__main__":
    unittest.main()
''',
         '''from pq import PriorityQueue


class OracleTests(unittest.TestCase):
    def test_fifo_among_equal_priorities(self):
        queue = PriorityQueue()
        queue.push(1, "z")
        queue.push(1, "a")
        self.assertEqual([queue.pop(), queue.pop()], ["z", "a"])

    def test_items_need_not_be_comparable(self):
        queue = PriorityQueue()
        queue.push(1, {"id": 2})
        queue.push(1, {"id": 1})
        self.assertEqual(queue.pop(), {"id": 2})


if __name__ == "__main__":
    unittest.main()
''',
         tier="hard",
         naive=[("src/pq.py", '''"""pq: priority queue, lowest priority value first, FIFO among equal priorities."""
import heapq


class PriorityQueue:
    def __init__(self):
        self._heap = []

    def push(self, priority, item):
        heapq.heappush(self._heap, (priority, repr(item), item))

    def pop(self):
        return heapq.heappop(self._heap)[2]
''')]),
]
