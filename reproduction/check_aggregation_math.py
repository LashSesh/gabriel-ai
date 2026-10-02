"""Independent algebra/reference checks for convex joint-risk aggregation.

Fraction arithmetic verifies every rational identity and reference proximal map.
Decimal(80) evaluates logarithms; this is high-precision numerical verification,
not directed-rounding certification. This file imports no production algorithm.
"""
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path
import json
import random

ROOT = Path(__file__).resolve().parents[1]
BETA = F(1, 40)


def decimal(value):
    return Decimal(value.numerator) / Decimal(value.denominator)


def dot(x, y):
    return sum(a*b for a,b in zip(x,y))


def simplex_projection(v):
    """Exact Euclidean projection of rational vectors to a probability simplex."""
    ordered = sorted(v, reverse=True)
    cumulative = F(0)
    threshold = None
    for j, item in enumerate(ordered, 1):
        cumulative += item
        candidate = (cumulative-1)/j
        if item > candidate:
            threshold = candidate
    result = [max(item-threshold, F(0)) for item in v]
    assert sum(result) == 1 and min(result) >= 0
    return result


def score(a,b,y):
    return -decimal(b).ln()+decimal(a+max(y*b-a,F(0))/BETA-1)


def main():
    rng = random.Random(2026092615)
    totals = dict(jensen_cases=0, strict_cases=0, equality_cases=0,
                  unit_rescalings=0, subgradient_inequalities=0,
                  proximal_reference_pairs=0, constant_expert_cases=0,
                  pooling_coordinate_equivalence_cases=0)
    largest_identity_error = Decimal(0)
    tolerance = Decimal('1e-70')
    with localcontext() as ctx:
        ctx.prec = 80
        for dimension in [2,3,5,8]:
            for index in range(160):
                q = [F(rng.randint(1,12), rng.randint(1,5)) for _ in range(dimension)]
                e = [value+F(rng.randint(0,15),rng.randint(1,5)) for value in q]
                if index % 4 == 0:
                    e = [max(e)]*dimension
                masses = [rng.randint(0,9) for _ in range(dimension)]
                masses[index % dimension] += 1
                w = [F(value,sum(masses)) for value in masses]
                a, b = [qi/ei for qi,ei in zip(q,e)], [1/ei for ei in e]
                ab, bb = dot(w,a), dot(w,b)
                Q, E = ab/bb, 1/bb
                assert 0 < Q <= E
                assert min(q) <= Q <= max(q) and min(e) <= E <= max(e)
                arithmetic_weights = [wi*bi/bb for wi,bi in zip(w,b)]
                assert dot(arithmetic_weights,q) == Q and dot(arithmetic_weights,e) == E
                arithmetic_Q, arithmetic_E = dot(w,q), dot(w,e)
                transformed_weights = [wi*ei/arithmetic_E for wi,ei in zip(w,e)]
                assert 1/dot(transformed_weights,b) == arithmetic_E
                assert dot(transformed_weights,a)/dot(transformed_weights,b) == arithmetic_Q
                totals['pooling_coordinate_equivalence_cases'] += 1
                # Explicitly include aggregate kinks and values on both sides.
                y = Q if index % 7 == 0 else F(rng.randint(-10,35),rng.randint(1,5))
                d = [y*bi-ai for ai,bi in zip(a,b)]
                hinge_gap = (dot(w,[abs(di) for di in d])-abs(dot(w,d)))/(2*BETA)
                assert hinge_gap >= 0
                direct_hinge = (dot(w,[max(di,F(0)) for di in d])-max(dot(w,d),F(0)))/BETA
                assert direct_hinge == hinge_gap
                gap = dot([decimal(wi) for wi in w], [score(ai,bi,y) for ai,bi in zip(a,b)])-score(ab,bb,y)
                exact_form = decimal(bb).ln()-sum(decimal(wi)*decimal(bi).ln() for wi,bi in zip(w,b))+decimal(hinge_gap)
                error = abs(gap-exact_form)
                largest_identity_error = max(error,largest_identity_error)
                assert error < tolerance and gap >= -tolerance
                active = [i for i,wi in enumerate(w) if wi > 0]
                strict = len({b[i] for i in active}) > 1 or (any(d[i]>0 for i in active) and any(d[i]<0 for i in active))
                assert gap > tolerance if strict else abs(gap) < tolerance
                totals['jensen_cases'] += 1
                totals['strict_cases' if strict else 'equality_cases'] += 1
                for scale in [F(1,1000),F(7,3),F(1000)]:
                    scaled_b = [bi/scale for bi in b]
                    assert dot(w,a)/dot(w,scaled_b) == scale*Q
                    assert 1/dot(w,scaled_b) == scale*E
                    unit_error = abs(score(ab,bb/scale,y*scale)-score(ab,bb,y)-decimal(scale).ln())
                    assert unit_error < tolerance
                    totals['unit_rescalings'] += 1
                # The exact rational subgradient vector, including all three
                # legal hinge choices when the aggregate forecast equals y.
                zvalues = [F(0),F(1,2),F(1)] if y*bb==ab else [F(y*bb>ab)]
                for z in zvalues:
                    g = [-bi/bb+ai+z*di/BETA for ai,bi,di in zip(a,b,d)]
                    centered = [gi-sum(g)/dimension for gi in g]
                    for vertex in range(dimension):
                        u = [F(i==vertex) for i in range(dimension)]
                        delta = [ui-wi for ui,wi in zip(u,w)]
                        assert dot(g,delta) == dot(centered,delta)
                        residual = score(dot(u,a),dot(u,b),y)-score(ab,bb,y)-decimal(dot(g,delta))
                        assert residual >= -tolerance
                        totals['subgradient_inequalities'] += 1
                # A frozen constant-expert problem is exactly a ridge objective
                # plus a score constant. Its proximal map has an exact rational
                # solution for arbitrary rational external points z.
                rho, tau = F(1,100), F(37,5)
                center = [F(1,dimension)]*dimension
                z1 = [F(rng.randint(-15,25),11) for _ in range(dimension)]
                z2 = [F(rng.randint(-15,25),11) for _ in range(dimension)]
                c = 1/(1+tau*rho)
                prox = lambda z: simplex_projection([(zi+tau*rho*ui)*c for zi,ui in zip(z,center)])
                p1,p2 = prox(z1),prox(z2)
                norm2 = lambda v: dot(v,v)
                assert norm2([x-y for x,y in zip(p1,p2)]) <= c*c*norm2([x-y for x,y in zip(z1,z2)])
                assert prox(center) == center
                # On the simplex itself there is no active projection; this
                # realizes the claimed contraction factor exactly.
                p = prox(w)
                assert norm2([x-y for x,y in zip(p,center)]) == c*c*norm2([x-y for x,y in zip(w,center)])
                totals['proximal_reference_pairs'] += 1
                totals['constant_expert_cases'] += 1
        # Forecast mixing can, but need not, beat the best constituent.
        a,b,w = [F(1,2),F(3,4)],[F(1,2),F(1,4)],[F(1,2),F(1,2)]
        aggregate = lambda y: score(dot(w,a),dot(w,b),y)
        assert aggregate(F(3,2)) < min(score(a[i],b[i],F(3,2)) for i in range(2))
        assert aggregate(F(0)) > min(score(a[i],b[i],F(0)) for i in range(2))
        result = dict(status='passed',seed=2026092615,decimal_precision=80,
                      tolerance=str(tolerance),counts=totals,
                      largest_jensen_identity_error=str(largest_identity_error),
                      arithmetic='Fractions for algebra and proximal reference; Decimal logarithms, no interval proof',
                      scope='Reference identities only; no empirical performance or full-system contraction claim')
    path = ROOT/'results/aggregation_math_checks.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
