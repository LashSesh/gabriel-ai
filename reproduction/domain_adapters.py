"""Two synthetic finite models for the SAME observation planner.

These are controlled mechanism examples, not estimates of real-world coverage.
Transport specializes only the conservative carrier mechanism of the supplied
T4W specification. It is not a reimplementation of its absent reference core.
"""
from fractions import Fraction as F
from itertools import product, permutations
import numpy as np
from finite_observation import Catalogue


def transport_records():
    records = []
    for p, a, b in product((F(1,4), F(3,4)), (F(0), F(1,4), F(1,2)),
                          (F(0), F(1,4), F(1,2))):
        r = [p, 1-p, F(0)]
        history, substeps = [tuple(r)], []
        for t in range(4):
            for (i,j), rate in zip(((0,1),(1,2)), (a,b)):
                before = tuple(r)
                delta = rate * (r[i]-r[j])
                r[i] -= delta; r[j] += delta
                substeps.append((before, tuple(r), rate, i, j))
            history.append(tuple(r))
        rows = tuple(str(x) for state in history[:4] for x in state)
        records.append(dict(id=f'p={p};a={a};b={b}', observations=rows,
                            label=int(r[2] >= F(1,4)),
                            inputs=np.array([[float(2*x-1) for x in v] for v in history]),
                            exact_history=history, substeps=substeps))
    return records, tuple(f'r[{t},{i}]' for t in range(4) for i in range(3))


def event_records():
    records = []
    for events in permutations('ABCD'):
        row = tuple(str(events.index(e)+1) for e in 'ABCD')
        u = np.array([[1.0 if e == x else -1.0 for x in 'ABCD'] for e in events])
        records.append(dict(id=''.join(events), observations=row,
                            label=int(events.index('A') < events.index('B')), inputs=u))
    return records, tuple('time['+e+']' for e in 'ABCD')


def build_catalogue(domain, records, queries, nuisance, labels):
    rows, targets, physical = [], [], []
    for h, tag, alias in product(range(len(records)), range(nuisance), range(2)):
        rows.append(records[h]['observations'] + (str(tag),))
        targets.append(int(labels[h])); physical.append(h)
    c = Catalogue(f'{domain};tag_values={nuisance};aliases=2;target={tuple(labels)}',
                  queries+('metadata_tag',), (1,)*(len(queries)+1), tuple(rows), tuple(targets))
    return c, physical
