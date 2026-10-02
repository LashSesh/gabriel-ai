# AT23: one core across three domain adapters

Backend `linux_namespace`, provider `gpt-4.1-mini` (openai_compat), catalog digest `ff1616bea15411ef`, replay `passed` with 0 external calls, memory chain `passed` (8 entries).

| domain | pack | state | requests | tokens | model revisions | eligible assessments |
|---|---|---|---|---|---|---|
| software | software-repair 0.1.0 | succeeded | 2 | 1922 | gpt-4.1-mini-2025-04-14 | base-commit=passed, baseline:unit=passed, checks-intact=passed, no-secrets=passed, oracle=passed, output-valid=passed, scope=passed, unit=passed |
| document | document-amendment 0.1.0 | succeeded | 2 | 1681 | gpt-4.1-mini-2025-04-14 | base-commit=passed, checks-intact=passed, citations=passed, claims=passed, no-secrets=passed, output-valid=passed, scope=passed |
| numerical | numerical-transform 0.1.0 | succeeded | 2 | 1481 | gpt-4.1-mini-2025-04-14 | base-commit=passed, checks-intact=passed, no-secrets=passed, output-valid=passed, reference=passed, scope=passed |

## Controls (scripted invalid and out-of-scope inputs; no repair cycles)

| domain | variant | state | failed mandatory checks |
|---|---|---|---|
| software | wrong_then_weaken | failed | oracle |
| document | fabricated | failed | citations |
| document | wrong_source | failed | claims |
| document | out_of_scope | failed | - |
| numerical | dimension_mismatch | failed | reference |
| numerical | unknown_operation | failed | - |
| numerical | out_of_scope_path | failed | - |

## AT16: direct versus hosted analytical worker

- worker build `2f88464762b61973`; hosted backend `linux_namespace`, exit 0; direct and hosted output bytes equal: **True**
- scope controls: dimension_mismatch=out_of_scope, unknown_unit=invalid_input, unknown_operation=invalid_input, graph_too_large=out_of_scope, wrong_input_kind=out_of_scope
- collision control: legacy padded signatures equal True, retained signatures differ True, cache keys differ True

