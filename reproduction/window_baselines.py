"""Validated uniform and adaptive subdivision for harmonic window queries.

These baselines do not solve for harmonic stationary phases.  They share exact
stationary/global-amplitude shortcuts and the certificate module's Arb point
oracle.  All other exclusions follow from a complete interval cover with valid
first- and second-derivative bounds.  Counts include repeated precision attempts.
"""
from __future__ import annotations

from fractions import Fraction as F
import heapq
from math import isqrt

from gabriel_runtime.window_certificate import prepare_model, point_enclosure, exact_number


def sqrt_upper(value, bits=128):
    value = F(value)
    if value < 0:
        raise ValueError('nonnegative square required')
    numerator = value.numerator << (2 * bits)
    root = isqrt(numerator // value.denominator)
    if root * root * value.denominator < numerator:
        root += 1
    return F(root, 1 << bits)


def interval_upper(model, left, right, radius, k1, k2):
    h = right['time'] - left['time']
    u, v = left['upper'], right['upper']
    return min(u + k1*h, v + k1*h, (u+v+k1*h)/2,
               max(u, v)+k2*h*h/8, model.a+radius, F(1))


def certify_by_subdivision(snapshot, source, targets, start_bits, end_bits,
                           threshold_bits, *, method='adaptive',
                           precisions=(128, 256, 512), max_evaluations=256):
    if method not in ('adaptive', 'uniform'):
        raise ValueError('adaptive or uniform method required')
    if type(max_evaluations) is not int or max_evaluations < 2:
        raise ValueError('at least two point evaluations required')
    start, end, threshold = map(exact_number, (start_bits, end_bits, threshold_bits))
    if start > end:
        raise ValueError('ordered closed interval required')
    model = prepare_model(snapshot, source, targets)
    radius2 = model.b*model.b + model.c*model.c
    output = dict(schema='gabriel.window-subdivision-certificate.v1', method=method,
                  status='unknown', model_identity=model.input_sha256,
                  input=dict(start=str(start),end=str(end),threshold=str(threshold)),
                  coefficients=dict(a=str(model.a),b=str(model.b),c=str(model.c),omega=str(model.omega)),
                  point_evaluations=0, attempted_precisions=[], points=[], witness=None,
                  certificate=None, intervals=[], bounds=None,
                  caps=dict(max_evaluations=max_evaluations,precisions=list(precisions)))

    def point(time):
        answer = None
        for precision in precisions:
            if output['point_evaluations'] >= max_evaluations:
                break
            enclosure = point_enclosure(model, time, precision)
            lo, hi = F(enclosure['lower']), F(enclosure['upper'])
            if lo > hi:
                raise ValueError('invalid oracle enclosure')
            answer = dict(time=time, lower=lo, upper=hi)
            record = dict(time=str(time),precision=precision,lower=str(lo),upper=str(hi))
            output['points'].append(record)
            output['point_evaluations'] += 1
            output['attempted_precisions'].append(precision)
            if lo > threshold:
                output['status'] = 'reachable'
                output['witness'] = dict(record)
                output['certificate'] = dict(kind='point')
                break
            if hi-lo <= F(1, 1 << 96):
                break
        return answer

    # Exact shortcuts are available to every method.  A direct algebraic
    # witness is valid for stationary mass without a transcendental point call.
    stationary = model.omega == 0 or radius2 == 0
    if stationary:
        mass = model.a + model.b if model.omega == 0 else model.a
        output['status'] = 'reachable' if mass > threshold else 'excluded'
        output['certificate'] = dict(kind='stationary',mass=str(mass))
        if mass > threshold:
            output['witness'] = dict(time=str(start),lower=str(mass),upper=str(mass),precision=0)
        return output
    gap = threshold-model.a
    if gap >= 0 and gap*gap >= radius2:
        output['status'] = 'excluded'
        output['certificate'] = dict(kind='global_amplitude',gap=str(gap),amplitude_squared=str(radius2))
        return output
    left = point(start)
    if output['status'] == 'reachable':
        return output
    if start == end:
        if left is not None and left['upper'] <= threshold:
            output['status'] = 'excluded'
            output['certificate'] = dict(kind='point')
        return output
    right = point(end)
    if output['status'] == 'reachable':
        return output
    if left is None or right is None:
        return output

    # Prepare subdivision-only work after shared algebraic and endpoint exits.
    # The model already contains the canonical input identity; rehashing the
    # dense snapshot here would be redundant work absent from the analytic path.
    radius = sqrt_upper(radius2)
    k1, k2 = abs(model.omega)*radius, model.omega*model.omega*radius
    output['bounds'] = dict(radius_upper=str(radius),K1=str(k1),K2=str(k2))

    def record_interval(l, r):
        upper = interval_upper(model,l,r,radius,k1,k2)
        return dict(start=str(l['time']),end=str(r['time']),upper=str(upper))

    if method == 'uniform':
        points = [left]
        for i in range(1, max_evaluations-1):
            current = point(start+(end-start)*F(i,max_evaluations-1))
            if output['status'] == 'reachable':
                return output
            if current is None:
                return output
            points.append(current)
        points.append(right)
        output['intervals'] = [record_interval(l,r) for l,r in zip(points,points[1:])]
        if all(F(cell['upper']) <= threshold for cell in output['intervals']):
            output['status'] = 'excluded'
            output['certificate'] = dict(kind='interval_cover')
        return output

    pending, covered = [], []
    counter = 0
    def add_interval(l,r):
        nonlocal counter
        upper = interval_upper(model,l,r,radius,k1,k2)
        if upper <= threshold:
            covered.append(record_interval(l,r))
        else:
            counter += 1
            heapq.heappush(pending,(-upper,l['time'],counter,l,r))
    add_interval(left,right)
    while pending and output['point_evaluations'] < max_evaluations:
        _,_,_,l,r = heapq.heappop(pending)
        middle = point((l['time']+r['time'])/2)
        if output['status'] == 'reachable':
            return output
        if middle is None:
            add_interval(l,r)
            break
        add_interval(l,middle)
        add_interval(middle,r)
    output['intervals'] = sorted(covered + [record_interval(l,r) for _,_,_,l,r in pending],
                                 key=lambda cell:F(cell['start']))
    if not pending:
        output['status'] = 'excluded'
        output['certificate'] = dict(kind='interval_cover')
    return output
