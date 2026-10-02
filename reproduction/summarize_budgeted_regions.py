"""Generate compact publication tables from independently verified results."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results'


def number(value, mark=False):
    return '$' + str(Fraction(value)) + (r'^{\dagger}' if mark else '') + '$'


def write_table(name, lines):
    assert lines[0].startswith(r'\begin{tabular}') and lines[-1] == r'\end{tabular}'
    (OUT / name).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    raw = (OUT / 'budgeted_portfolio_results.json').read_bytes()
    data = json.loads(raw)
    verification = json.loads((OUT / 'budgeted_region_verification.json').read_text())
    checks = json.loads((OUT / 'budgeted_region_checks.json').read_text())
    assert verification['passed'] is True and checks['passed'] is True
    assert verification['results_sha256'] == hashlib.sha256(raw).hexdigest()
    studies = data['studies']
    assert len(studies) == 5
    labels = ('Portfolio $(2,25)$', 'Portfolio $(0,25)$', 'Portfolio $(6,25)$',
              'Portfolio $(2,15)$', 'Inspection')
    policies = ('old_minimax', 'reverse', 'local_lex', 'global_lex')
    lines = [r'\begin{tabular}{@{}l*{8}{@{\hspace{7pt}}r}@{}}', r'\toprule',
             r'& \multicolumn{2}{c}{Minimax} & \multicolumn{2}{c}{Reverse} & \multicolumn{2}{c}{Local} & \multicolumn{2}{c}{Budget} \\',
             r'\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-9}',
             r'Model $(\epsilon,K)$ & Mean & Worst & Mean & Worst & Mean & Worst & Mean & Worst \\',
             r'\midrule']
    for label, study in zip(labels, studies):
        record = study['budgets'][0]
        assert record['budget'] == study['root_worst_cost']
        values = []
        for policy in policies:
            result = record['policies'][policy]
            values.append(number(result['mean_cost']))
            values.append(number(result['worst_cost'], mark=not result['budget_feasible']))
        lines.append(label + ' & ' + ' & '.join(values) + r' \\')
    lines.extend((r'\bottomrule', r'\end{tabular}'))
    write_table('budgeted_primary_table.tex', lines)

    control = studies[3]
    assert control['scope'] == 'portfolio-control-3'
    assert (control['catalogue']['epsilon'], control['catalogue']['risk_limit']) == ('2', '15')
    lines = [r'\begin{tabular}{@{}rrr@{}}', r'\toprule',
             r'Allowed budget & Optimal mean & Achieved worst \\', r'\midrule']
    for record in control['budgets']:
        result = record['policies']['global_lex']
        assert result['budget_feasible'] and result['mean_cost'] == record['optimal_expected_cost']
        lines.append(' & '.join(number(v) for v in (record['budget'], result['mean_cost'], result['worst_cost'])) + r' \\')
    lines.extend((r'\bottomrule', r'\end{tabular}'))
    write_table('budgeted_frontier_table.tex', lines)
    print(json.dumps(dict(passed=True, tables=2, primary_rows=5, frontier_rows=3,
                          result_sha256=hashlib.sha256(raw).hexdigest())))


if __name__ == '__main__':
    main()
