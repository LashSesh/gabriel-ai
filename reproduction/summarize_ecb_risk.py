"""Summarize saved ECB forecasts; never fit a model or alter the protocol.

Run from any directory: python reproduction/summarize_ecb_risk.py
Inputs are the saved protocol, result metadata and prediction archive. Forecast
metrics are independently recomputed from that archive and checked against the
saved results before any derived outputs are written.
"""

from __future__ import annotations

import argparse
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np


MODELS = ("raw_hs", "fast_fhs", "slow_fhs", "multiscale_fhs", "selected_fhs")
MODEL_LABELS = {
    "raw_hs": "Raw HS",
    "fast_fhs": "Fast FHS",
    "slow_fhs": "Slow FHS",
    "multiscale_fhs": "Primary multiscale FHS",
    "selected_fhs": "Development-selected multiscale FHS",
}
ATOL = 1e-12


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archived_metrics(q, e, y, tail_probability):
    """Evaluate upper-loss FZ0 and identification residuals on saved forecasts."""
    if not all(np.isfinite(a).all() for a in (q, e, y)):
        raise ValueError("Nonfinite archived forecast or outcome")
    if np.any(e <= 0) or np.any(q > e + ATOL):
        raise ValueError("Archived FZ0 forecast violates e > 0 or q <= e")
    tail_term = np.maximum(y - q, 0) / tail_probability
    scores = np.log(e) + (q + tail_term) / e - 1
    breaches = y > q
    return {
        "n": len(y),
        "mean_fz0": float(scores.mean()),
        "exceedances": int(breaches.sum()),
        "exceedance_fraction": float(breaches.mean()),
        "mean_es_identification_residual": float((q + tail_term - e).mean()),
        "mean_var": float(q.mean()),
        "mean_es": float(e.mean()),
    }


def checked_rows(root: Path):
    folder = root / "results"
    protocol_path = folder / "ecb_risk_protocol.json"
    result_path = folder / "ecb_risk_results.json"
    prediction_path = folder / "ecb_risk_predictions.npz"
    protocol = json.loads(protocol_path.read_text())
    results = json.loads(result_path.read_text())
    if sha256(protocol_path) != results["protocol_sha256"]:
        raise ValueError("Saved protocol hash does not match the forecast results")
    if sha256(prediction_path) != results["predictions_sha256"]:
        raise ValueError("Prediction archive hash does not match the forecast results")
    if tuple(protocol["models"]) != MODELS:
        raise ValueError("Unexpected model order")
    tail_probability = float(1 - Fraction(protocol["alpha"]))
    rows = []
    with np.load(prediction_path, allow_pickle=False) as archive:
        dates = archive["dates"]
        for contract in results["contracts"]:
            currency, horizon = contract["currency"], contract["horizon"]
            key = f"{currency}_{horizon}"
            origins = archive[f"{key}_origins"]
            q_all = archive[f"{key}_candidate_var"]
            e_all = archive[f"{key}_candidate_es"]
            y_all = archive[f"{key}_realized"]
            start, end = protocol["test"]
            mask = (dates[origins] >= start) & (dates[origins + horizon] <= end)
            if int(mask.sum()) != contract["periods"]["test"]["n"]:
                raise ValueError(f"Test membership differs for {key}")
            for model, column in zip(MODELS, contract["candidate_columns"]):
                computed = archived_metrics(
                    q_all[mask, column], e_all[mask, column], y_all[mask],
                    tail_probability,
                )
                saved = contract["models"][model]["test"]
                for metric, value in computed.items():
                    if metric in ("n", "exceedances"):
                        matches = value == saved[metric]
                    else:
                        matches = np.isclose(value, saved[metric], rtol=ATOL, atol=ATOL)
                    if not matches:
                        raise ValueError(f"Archived metric mismatch: {key}/{model}/{metric}")
                rows.append({
                    "currency": currency,
                    "horizon_observed_intervals": horizon,
                    "model": model,
                    "model_label": MODEL_LABELS[model],
                    "selected_fast_weight": contract["selected_weight"],
                    "primary_fast_weight": protocol["primary_weight"],
                    "test_start": start,
                    "test_end": end,
                    **computed,
                    "exceedance_percent": 100 * computed["exceedance_fraction"],
                    "target_exceedance_percent": 100 * tail_probability,
                    "absolute_coverage_deviation_pp":
                        100 * abs(computed["exceedance_fraction"] - tail_probability),
                    "mean_fz0_gain_over_raw_hs":
                        contract["models"]["raw_hs"]["test"]["mean_fz0"]
                        - computed["mean_fz0"],
                })
    expected = len(protocol["currencies"]) * len(protocol["horizons_observed_intervals"]) * len(MODELS)
    if len(rows) != expected or len(rows) != 40:
        raise ValueError(f"Expected 40 contract/method rows, got {len(rows)}")
    sources = {
        "source_url": protocol["source"],
        "source_download_date": protocol["source_download_date"],
        "source_csv_sha256": results["source_csv_sha256"],
        "protocol_sha256": sha256(protocol_path),
        "results_sha256": sha256(result_path),
        "predictions_sha256": sha256(prediction_path),
        "forecast_source_sha256": results["source_sha256"],
        "summary_source_sha256": sha256(Path(__file__)),
        "bibliography_keys": ["ecb2026fx", "ecb2026reuse", "ecb2026copyright", "patton2019es"],
    }
    return protocol, rows, sources


def ranges(values):
    return {"min": float(min(values)), "max": float(max(values))}


def summarize(protocol, rows, sources):
    contracts = list(dict.fromkeys((r["currency"], r["horizon_observed_intervals"]) for r in rows))
    by_contract = {
        contract: {r["model"]: r for r in rows
                   if (r["currency"], r["horizon_observed_intervals"]) == contract}
        for contract in contracts
    }
    pairwise = {}
    for first in MODELS:
        pairwise[first] = {}
        for second in MODELS:
            diff = np.array([c[first]["mean_fz0"] - c[second]["mean_fz0"]
                             for c in by_contract.values()])
            pairwise[first][second] = {
                "lower_score": int(np.sum(diff < -ATOL)),
                "tie": int(np.sum(np.abs(diff) <= ATOL)),
                "higher_score": int(np.sum(diff > ATOL)),
            }
    method_summary = {}
    for model in MODELS:
        selected = [r for r in rows if r["model"] == model]
        method_summary[model] = {
            "label": MODEL_LABELS[model],
            "score_comparison_to_raw_hs": pairwise[model]["raw_hs"],
            "contract_mean_fz0_range": ranges([r["mean_fz0"] for r in selected]),
            "score_gain_over_raw_hs_range":
                ranges([r["mean_fz0_gain_over_raw_hs"] for r in selected]),
            "exceedance_percent_range": ranges([r["exceedance_percent"] for r in selected]),
            "absolute_coverage_deviation_pp_range":
                ranges([r["absolute_coverage_deviation_pp"] for r in selected]),
            "lowest_contract_score_including_ties": sum(
                c[model]["mean_fz0"] <= min(r["mean_fz0"] for r in c.values()) + ATOL
                for c in by_contract.values()
            ),
        }
    return {
        "schema": "gabriel.ecb-risk.summary.v1",
        "input_sources": sources,
        "test_period": protocol["test"],
        "alpha": protocol["alpha"],
        "target_exceedance_percent": 100 * float(1 - Fraction(protocol["alpha"])),
        "contract_count": len(contracts),
        "contract_model_rows": len(rows),
        "test_outcomes_across_contracts": sum(c["raw_hs"]["n"] for c in by_contract.values()),
        "test_forecast_pairs": sum(r["n"] for r in rows),
        "test_n_range": ranges([r["n"] for r in rows]),
        "selected_weights": {f"{cur}_h{h}": by_contract[cur, h]["raw_hs"]["selected_fast_weight"]
                             for cur, h in contracts},
        "methods": method_summary,
        "pairwise_contract_score_counts": pairwise,
        "verification": {
            "metrics_recomputed_from_prediction_archive": True,
            "archive_and_protocol_hashes_match_saved_results": True,
            "saved_metric_absolute_tolerance": ATOL,
            "saved_metric_relative_tolerance": ATOL,
            "all_test_forecasts_have_positive_es_and_var_not_above_es": True,
        },
        "interpretation": {
            "score_gain": "raw-HS mean FZ0 minus method mean FZ0; signed unscaled score difference, not a percentage",
            "win_count": "descriptive number of contracts with smaller mean score; no independence or significance claim",
            "coverage": "observed strict VaR exceedance fraction; target 1-alpha, not a statistical calibration certificate",
            "scope": "retrospective current-vintage reference-rate forecasting; no trading or ROI result",
        },
    }, by_contract


def write_tables(folder, by_contract):
    score_lines = [
        r"\begin{tabular}{lrrrrrrrr}",
        r"\toprule",
        r"Currency & $h$ & Raw HS & Fast & Slow & Primary & Selected & $w_{\rm sel}$ & $n$ \\",
        r"\midrule",
    ]
    coverage_lines = [
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        r"Currency & $h$ & Raw HS & Fast & Slow & Primary & Selected \\",
        r"\midrule",
    ]
    for (currency, horizon), models in by_contract.items():
        first = models["raw_hs"]
        scores = " & ".join(f"{models[m]['mean_fz0']:.4f}" for m in MODELS)
        coverage = " & ".join(f"{models[m]['exceedance_percent']:.2f}" for m in MODELS)
        score_lines.append(
            f"{currency} & {horizon} & {scores} & ${first['selected_fast_weight']}$ & {first['n']} " + r"\\"
        )
        coverage_lines.append(f"{currency} & {horizon} & {coverage} " + r"\\")
    score_lines += [r"\bottomrule", r"\end{tabular}"]
    coverage_lines += [r"\bottomrule", r"\end{tabular}"]
    (folder / "ecb_risk_table.tex").write_text("\n".join(score_lines) + "\n")
    (folder / "ecb_coverage_table.tex").write_text("\n".join(coverage_lines) + "\n")


def annotated_matrix(ax, values, labels, cmap, norm, fmt):
    rendered = ax.imshow(values, cmap=cmap, norm=norm, aspect="auto", interpolation="nearest")
    ax.set_xticks(range(len(labels)), labels=labels, fontsize=7)
    ax.tick_params(axis="both", length=0, pad=6)
    ax.set_xticks(np.arange(values.shape[1] + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(values.shape[0] + 1) - 0.5, minor=True)
    ax.grid(which="minor", color="white", linewidth=0.8)
    ax.tick_params(which="minor", bottom=False, left=False)
    for (i, j), value in np.ndenumerate(values):
        r, g, b, _ = cmap(norm(value))
        color = "white" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.49 else "#20242a"
        ax.text(j, i, format(value, fmt), ha="center", va="center", fontsize=7, color=color)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return rendered


def write_figure(folder, by_contract, target):
    gain = np.array([[m[k]["mean_fz0_gain_over_raw_hs"] for k in MODELS[1:]]
                     for m in by_contract.values()])
    coverage = np.array([[m[k]["exceedance_percent"] for k in MODELS]
                         for m in by_contract.values()])
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8,
        "pdf.fonttype": 42, "ps.fonttype": 42,
        "axes.titleweight": "normal", "savefig.facecolor": "white",
    })
    gain_cmap = LinearSegmentedColormap.from_list("orange_white_blue", ["#b97835", "#f7f7f7", "#3a7198"])
    coverage_cmap = LinearSegmentedColormap.from_list("blue_white_orange", ["#3a7198", "#f7f7f7", "#b97835"])
    span = max(0.05, float(np.ceil(np.max(np.abs(gain)) * 20) / 20))
    fig, axes = plt.subplots(1, 2, figsize=(160 / 25.4, 118 / 25.4), sharey=True,
                             gridspec_kw={"width_ratios": [4, 5]})
    fig.subplots_adjust(left=0.145, right=0.985, top=0.79, bottom=0.27, wspace=0.13)
    left = annotated_matrix(axes[0], gain, ["Fast", "Slow", "Primary\nmultiscale", "Selected\nmultiscale"],
                            gain_cmap, TwoSlopeNorm(vmin=-span, vcenter=0, vmax=span), "+.3f")
    right = annotated_matrix(axes[1], coverage, ["Raw HS", "Fast", "Slow", "Primary\nmultiscale", "Selected\nmultiscale"],
                             coverage_cmap, TwoSlopeNorm(vmin=0, vcenter=target, vmax=2 * target), ".2f")
    axes[0].set_yticks(range(len(by_contract)), labels=[f"{c}  h={h}" for c, h in by_contract], fontsize=8)
    axes[1].tick_params(labelleft=False)
    axes[0].set_title("(a) Mean FZ0 gain over raw HS\nPositive = lower mean score", loc="left", fontsize=8, pad=10)
    axes[1].set_title(f"(b) VaR breaches (%)\nNominal rate = {target:g}%", loc="left", fontsize=8, pad=10)
    for ax, im, ticks, label in (
        (axes[0], left, [-span, 0, span], "FZ0 difference (raw minus method)"),
        (axes[1], right, [0, target, 2 * target], "Observed exceedances (%)"),
    ):
        box = ax.get_position()
        cax = fig.add_axes([box.x0, 0.105, box.width, 0.025])
        bar = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=ticks)
        bar.ax.tick_params(labelsize=7, length=2)
        bar.set_label(label, fontsize=7, labelpad=3)
        bar.outline.set_linewidth(0.4)
    fig.text(0.145, 0.96, "ECB reference-rate losses: held-out 2020–2025", fontsize=10, ha="left", va="top")
    fig.text(0.145, 0.915, "Primary: fixed w=1/2. Selected: w chosen on 2010–2019.", fontsize=7.5, ha="left", va="top")
    fig.text(0.145, 0.022, "h counts observed rate intervals; overlapping h=5 outcomes. Descriptive comparisons.", fontsize=6.6, ha="left")
    fig.savefig(folder / "ecb_risk_forecasts.pdf", metadata={"Title": "ECB held-out risk forecasts", "Creator": "Gabriel reproduction/summarize_ecb_risk.py"})
    fig.savefig(folder / "ecb_risk_forecasts.png", dpi=220)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    protocol, rows, sources = checked_rows(root)
    summary, by_contract = summarize(protocol, rows, sources)
    results_dir = root / "results"
    figures_dir = root / "figures"
    figures_dir.mkdir(exist_ok=True)
    with (results_dir / "ecb_risk_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (results_dir / "ecb_risk_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    write_tables(results_dir, by_contract)
    write_figure(figures_dir, by_contract, summary["target_exceedance_percent"])
    print("Verified 40 saved contract/method summaries; wrote two tables, CSV, JSON, PDF and PNG.")
    for model, record in summary["methods"].items():
        print(model, record["score_comparison_to_raw_hs"],
              "gain range", record["score_gain_over_raw_hs_range"])


if __name__ == "__main__":
    main()
