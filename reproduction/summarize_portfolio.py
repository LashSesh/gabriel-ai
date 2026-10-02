"""Publication tables and figure from verified saved portfolio-study outputs.

No risk optimization, acquisition experiment, fitting, or protocol mutation is
performed here. Protocol inputs supply the scenario/probability specification.
"""
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction as F
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results'
FIG = ROOT / 'figures'
POLICIES = ('minimax', 'fixed', 'reverse', 'hypothesis_entropy', 'strict_minimax', 'strict_ec2', 'full_book')
LABELS = {'minimax': 'Minimax', 'fixed': 'Fixed', 'reverse': 'Reverse',
          'hypothesis_entropy': 'Hypothesis entropy', 'strict_minimax': 'Strict minimax',
          'strict_ec2': 'Strict EC2', 'full_book': 'Full book'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decimal(value, places=None):
    """Exact terminating input decimals, or explicit half-up display rounding."""
    value = F(value)
    denominator = value.denominator
    for prime in (2, 5):
        while denominator % prime == 0:
            denominator //= prime
    if places is None and denominator != 1:
        raise ValueError('requested exact decimal is nonterminating')
    result = Decimal(value.numerator) / Decimal(value.denominator)
    if places is not None:
        result = result.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = format(result, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def tex_number(value):
    return '$' + str(F(value)) + '$'


def write_table(name, lines):
    assert lines[0].startswith(r'\begin{tabular}') and lines[-1] == r'\end{tabular}'
    (OUT / name).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def plot(primary, industrial):
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8,
                         'pdf.fonttype': 42, 'ps.fonttype': 42,
                         'axes.titleweight': 'semibold', 'axes.labelcolor': '#26333B',
                         'text.color': '#26333B', 'xtick.color': '#59656E',
                         'ytick.color': '#26333B'})
    fig = plt.figure(figsize=(6.3, 3.85), facecolor='white')
    axes = [fig.add_axes((.215, .23, .32, .62)), fig.add_axes((.64, .23, .32, .62))]
    colors = ('#276B91', '#CE8B45')
    labels = ['Minimax', 'Fixed', 'Reverse', 'Entropy', 'Strict minimax*', r'Strict EC$^2$*', 'Full book']
    for panel, (ax, study, maximum, title, xlabel) in enumerate(zip(
            axes, (primary, industrial), (13.4, 6.8),
            ('a  Portfolio (n = 128)', 'b  Inspection (n = 16)'),
            ('Portfolio access-cost units', 'Inspection access-cost units'))):
        for row in range(0, len(POLICIES), 2):
            ax.axhspan(row - .45, row + .45, color='#F3F6F8', zorder=0)
        for row, policy in enumerate(POLICIES):
            values = (F(study['policies'][policy]['mean_cost']), F(study['policies'][policy]['worst_cost']))
            for offset, value, color in zip((-.17, .17), values, colors):
                y = row + offset
                ax.barh(y, float(value), height=.29, color=color, zorder=3)
                ax.text(float(value) + maximum * .017, y, decimal(value, 2),
                        va='center', ha='left', fontsize=7.1, color='#26333B')
        ax.set_ylim(len(POLICIES) - .5, -.5)
        ax.set_xlim(0, maximum)
        ax.set_yticks(range(len(POLICIES)), labels if panel == 0 else [''] * len(POLICIES))
        ax.tick_params(axis='y', length=0, pad=7)
        ax.tick_params(axis='x', labelsize=7, length=3, color='#A6B0B7')
        ax.set_xticks((0, 3, 6, 9, 12) if panel == 0 else (0, 2, 4, 6))
        ax.xaxis.grid(True, color='#E1E6EA', linewidth=.6, zorder=0)
        for side in ('left', 'right', 'top'):
            ax.spines[side].set_visible(False)
        ax.spines['bottom'].set_color('#A6B0B7')
        ax.spines['bottom'].set_linewidth(.6)
        ax.set_title(title, loc='left', pad=12, fontsize=9)
        ax.set_xlabel(xlabel, fontsize=7.5, labelpad=6)
    fig.legend(handles=[Patch(facecolor=colors[0], label='Mean'), Patch(facecolor=colors[1], label='Worst case')],
               loc='upper center', bbox_to_anchor=(.62, .985), ncol=2, frameon=False,
               handlelength=1.3, columnspacing=1.7, fontsize=8)
    fig.text(.215, .087, 'Means use uniform catalogue weights, not estimated operational frequencies.',
             fontsize=6.8, ha='left')
    fig.text(.215, .045, '*Stricter winner-label stopping. Cost scales are specified separately per adapter.',
             fontsize=6.8, ha='left')
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / 'portfolio_acquisition.pdf', metadata={
        'Title': 'Acquisition cost in two synthetic current-record models',
        'Subject': 'Verified finite-model results; no comparison with external platforms',
        'Creator': 'reproduction/summarize_portfolio.py'})
    fig.savefig(FIG / 'portfolio_acquisition.png', dpi=240)
    plt.close(fig)


def main():
    results_raw = (OUT / 'portfolio_results.json').read_bytes()
    verification_raw = (OUT / 'portfolio_verification.json').read_bytes()
    protocol_raw = (OUT / 'portfolio_protocol.json').read_bytes()
    results, verification, protocol = map(json.loads, (results_raw, verification_raw, protocol_raw))
    assert verification['passed'] is True
    assert verification['results_sha256'] == sha(results_raw)
    assert results['protocol_sha256'] == verification['protocol_sha256'] == sha(protocol_raw)
    studies = results['studies']
    assert [s['scope'] for s in studies] == ['portfolio-primary', 'portfolio-control-1',
                                            'portfolio-control-2', 'portfolio-control-3', 'industrial-inspection']
    primary, industrial = studies[0], studies[-1]
    summary = dict(schema='gabriel.portfolio-summary.v1',
                   scope='Synthetic finite current-record studies; uniformly weighted catalogue summaries',
                   protocol_sha256=sha(protocol_raw), results_sha256=sha(results_raw),
                   verification_sha256=sha(verification_raw),
                   counts=dict(portfolio_records=128, inspection_records=16, studies=len(studies),
                               policies_per_study=len(POLICIES), policy_case_paths=verification['replayed_policy_paths'],
                               passive_observations=verification['replayed_passive_observations'],
                               risk_witnesses=verification['robust_risk_witnesses_verified'],
                               scenarios=len(protocol['scenarios']), horizons=len(protocol['horizons']),
                               probability_models=len(protocol['probability_models'])),
                   comparison_notes=[
                       'Strict minimax and strict EC2 identify the first minimum-feasible-action label, a stronger stopping objective.',
                       'Full book acquires a minimum-cost fixed query set identifying every modeled semantic current book.',
                       'Exact minimax optimizes worst cost; ties are broken by query index, not expected cost.',
                       'Cost scales are adapter-specific constructed units, not measured time, money or latency.',
                       'No quantitative comparison with Aladdin or any external platform is performed.'], studies=[])
    csv_rows = []
    for study in studies:
        item = dict(scope=study['scope'], epsilon=study['catalogue']['epsilon'],
                    risk_limit=study['catalogue']['risk_limit'], records=len(study['catalogue']['rows']),
                    optimal_worst_cost=study['optimal_worst_cost'],
                    strict_optimal_worst_cost=study['strict_optimal_worst_cost'],
                    full_book_cost=study['full_book_cost'], policies={})
        for policy in POLICIES:
            data = study['policies'][policy]
            fields = dict(mean_cost=data['mean_cost'], worst_cost=data['worst_cost'],
                          mean_queries=data['mean_queries'], known=data['status_counts'].get('known', 0),
                          blocked=data['status_counts'].get('blocked', 0),
                          nuisance_queries=data['nuisance_queries'], wrong_decisions=data['wrong_decisions'],
                          stronger_strict_objective=policy.startswith('strict_'))
            item['policies'][policy] = fields
            csv_rows.append(dict(scope=study['scope'], epsilon=item['epsilon'], risk_limit=item['risk_limit'],
                                 records=item['records'], policy=policy, **fields))
        summary['studies'].append(item)
    (OUT / 'portfolio_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (OUT / 'portfolio_summary.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)

    lines = [r'\begin{tabular}{@{}lrrrr@{}}', r'\toprule',
             r'& \multicolumn{2}{c}{Portfolio ($n=128$)} & \multicolumn{2}{c}{Inspection ($n=16$)} \\',
             r'\cmidrule(lr){2-3}\cmidrule(lr){4-5}', r'Policy & Mean & Worst & Mean & Worst \\', r'\midrule']
    for policy in POLICIES:
        label = LABELS[policy].replace('EC2', r'EC$^2$')
        if policy.startswith('strict_'):
            label += r'$^{\dagger}$'
        values = [study['policies'][policy][measure] for study in (primary, industrial)
                  for measure in ('mean_cost', 'worst_cost')]
        lines.append(label + ' & ' + ' & '.join(tex_number(value) for value in values) + r' \\')
    lines.extend((r'\bottomrule', r'\end{tabular}'))
    write_table('portfolio_primary_table.tex', lines)

    lines = [r'\begin{tabular}{@{}rrrrrrrr@{}}', r'\toprule',
             r'& & & & \multicolumn{2}{c}{Minimax} & \multicolumn{2}{c}{Reverse} \\',
             r'\cmidrule(lr){5-6}\cmidrule(lr){7-8}',
             r'$\varepsilon$ & $K$ & Known & Blocked & Mean & Worst & Mean & Worst \\', r'\midrule']
    for study in studies[:-1]:
        counts = study['policies']['minimax']['status_counts']
        values = [study['catalogue']['epsilon'], study['catalogue']['risk_limit'],
                  counts.get('known', 0), counts.get('blocked', 0)]
        values += [study['policies'][policy][measure] for policy in ('minimax', 'reverse')
                   for measure in ('mean_cost', 'worst_cost')]
        lines.append(' & '.join(tex_number(value) for value in values) + r' \\')
    lines.extend((r'\bottomrule', r'\end{tabular}'))
    write_table('portfolio_controls_table.tex', lines)

    lines = [r'\begin{tabular}{@{}>{\scriptsize}l*{8}{>{\scriptsize}r}@{}}', r'\toprule',
             r'& \multicolumn{4}{c}{\scriptsize Near horizon} & \multicolumn{4}{c}{\scriptsize Far horizon} \\',
             r'\cmidrule(lr){2-5}\cmidrule(lr){6-9}',
             r'Scenario & $e$ & $d$ & $c$ & $\ell$ & $e$ & $d$ & $c$ & $\ell$ \\', r'\midrule']
    for scenario in protocol['scenarios']:
        label = scenario['name'].replace('_', ' ').capitalize()
        values = [decimal(value) for horizon in protocol['horizons'] for value in scenario[horizon]]
        lines.append(label + ' & ' + ' & '.join(values) + r' \\')
    lines.extend((r'\bottomrule', r'\end{tabular}'))
    write_table('portfolio_scenarios_table.tex', lines)

    lines = [r'\begin{tabular}{@{}lrrr@{}}', r'\toprule',
             r'Scenario & Calm-weighted & Credit-weighted & Rates-weighted \\', r'\midrule']
    for i, scenario in enumerate(protocol['scenarios']):
        values = [decimal(model['probabilities'][i]) for model in protocol['probability_models']]
        lines.append(scenario['name'].replace('_', ' ').capitalize() + ' & ' + ' & '.join(values) + r' \\')
    for model in protocol['probability_models']:
        assert sum(map(F, model['probabilities'])) == 1
    lines.extend((r'\midrule', r'Total & 1 & 1 & 1 \\', r'\bottomrule', r'\end{tabular}'))
    write_table('portfolio_probabilities_table.tex', lines)
    plot(primary, industrial)
    print(json.dumps(dict(passed=True, counts=summary['counts'], tables=4, figure_formats=['pdf', 'png'],
                          csv_rows=len(csv_rows))))


if __name__ == '__main__':
    main()
