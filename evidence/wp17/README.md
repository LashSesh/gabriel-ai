# Protocol 10 evidence: the channel route on the numerical pack (ADR-24)

| File | Content |
|------|---------|
| `protocol10_declaration.md` | The question, the mechanism under test, the corpus families, the pilot rule, protocols 10a and 10b, the pre-declared criterion and consequence; written before any run with the provider, with the amendment recorded after the first pilot and before 10a was frozen |
| `pilot10.frozen.json`, `pilot10-run/` | First pilot (six runs, the seen decision topics): confirmed the prerequisite family, exposed the construction defect of the undeclared family; retained, not counted |
| `pilot10b.frozen.json`, `pilot10b-run/` | Second pilot (three runs) after the recorded amendment; retained, not counted |
| `protocol10a-train.frozen.json`, `run10a-train/` | Training run: 18 runs of the rule-based production configuration on the six seen tasks; `decision_analysis.json` lists every unit's retained decisions beside its provider statuses |
| `policies10/` | `scripts/policy_route.py train`: samples, training manifest, metrics (validation folds, resubstitution), the candidate readouts bound to the numerical layout |
| `protocol10b-eval.frozen.json`, `run10b-eval/` | Evaluation run: the frozen candidate against the rule on all nineteen numerical tasks, two repetitions, the two held-out families never executed before |
| `promotion10/promotion.json` | `scripts/policy_route.py promote`: the declared criterion on the held-out families, the held-out decision loss, the memory service's promotion decision |

Every run directory holds `protocol.json`, `results.json`, `report.json`, `report.md`, one unit
directory per (task, system, repetition) with the retained workspace, and `final_diffs/` with
the exact tree the verification judged (`scripts/eval_final_diffs.py`). Materialized
repositories, worktrees, object stores and principal secrets are not committed.
