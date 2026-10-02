"""Exact-rational reference cases for the floating-point correction helper."""
from pathlib import Path
from fractions import Fraction as F
import json, random, math
from severity_correction import correct_discounted_score, severity_readout

ROOT = Path(__file__).resolve().parents[1]


def main():
    rng = random.Random(2026092606)
    max_error, checks = 0.0, 0
    for count in range(1,33):
        for repeat in range(32):
            lam = rng.choice([F(1,2),F(3,4),F(7,8)])
            initial = F(rng.randrange(1,20),3)+1
            scores = [F(rng.randrange(0,200),5)+1 for _ in range(count)]
            position = rng.randrange(count)
            new_score = F(rng.randrange(0,500),5)+1
            old = initial
            for x in scores:
                old = lam*old+(1-lam)*x
            altered = list(scores);altered[position] = new_score
            direct = initial
            for x in altered:
                direct = lam*direct+(1-lam)*x
            formula = old+(1-lam)*lam**(count-position-1)*(new_score-scores[position])
            assert formula == direct
            computed = correct_discounted_score(float(old),float(lam),count,position+1,
                                                float(scores[position]),float(new_score))
            error = abs(computed-float(direct));max_error = max(max_error,error)
            assert math.isclose(computed,float(direct),abs_tol=1e-12,rel_tol=1e-12)
            out = severity_readout(computed)
            assert math.isclose(out['ratio'],float(min(F(20),max(F(1),direct))),abs_tol=1e-12,rel_tol=1e-12)
            # Avoid demanding a rounded boundary flag when exact state equals cap.
            if abs(float(direct)-20)>1e-12:
                assert out['upper_cap_active'] == (direct>20)
            checks += 1
    rejected = 0
    invalid = [lambda: correct_discounted_score(1,0.9,0,1,1,2),
               lambda: correct_discounted_score(1,0.9,5,0,1,2),
               lambda: correct_discounted_score(1,0.9,5,6,1,2),
               lambda: correct_discounted_score(1,0.9,5,1.0,1,2),
               lambda: correct_discounted_score(1,1,5,1,1,2),
               lambda: correct_discounted_score(1,0,5,1,1,2),
               lambda: correct_discounted_score(float('nan'),0.9,5,1,1,2),
               lambda: correct_discounted_score(1,0.9,5,1,1,float('inf')),
               lambda: severity_readout(float('inf')),
               lambda: severity_readout(1,0.5)]
    for case in invalid:
        try:case()
        except ValueError:rejected += 1
        else:raise AssertionError('invalid input accepted')
    result={'schema':'gabriel.severity-correction-checks.v1','status':'pass',
            'seed':2026092606,'rational_reference_cases':checks,
            'max_absolute_binary64_error':max_error,'absolute_tolerance':1e-12,
            'relative_tolerance':1e-12,'invalid_input_rejections':rejected,
            'scope':'Finite reference checks of binary64 implementation; exact identity separately proven algebraically. No interval-rounding certificate.'}
    (ROOT/'results/severity_correction_checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
