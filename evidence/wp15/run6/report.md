# G1 matched evaluation report

Protocol `db5d1e78cff24c99` (frozen 2026-10-03T13:28:11.296872+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 10 tasks in 4 families, 80 runs.

Protocol 6: the associative memory layer (ADR-20); pre-declared in evidence/wp15/protocol6_declaration.md; history tasks run first in the same workspace for every Gabriel arm

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 20 | 14 | 0.70 | [0.18, 1.00] | 19 | 5 | 0.26 (n=19) | 1.00 | 2624 | 3.5 | 0 |
| simple_loop | 20 | 18 | 0.90 | [0.73, 1.00] | 18 | 0 | 0.00 (n=18) | 1.80 | 4957 | 4.3 | 0 |
| gabriel_reference_plan | 20 | 4 | 0.20 | [0.00, 0.67] | 4 | 0 | 0.00 (n=4) | 2.60 | 7602 | 11.1 | 16 |
| gabriel_associative | 20 | 7 | 0.35 | [0.00, 0.75] | 7 | 0 | 0.00 (n=7) | 2.35 | 6679 | 10.1 | 13 |

## Held-out families only (association-needed-held-out): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 4 | 4 | 1.00 | [1.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.00 | 2931 | 2.3 | 0 |
| simple_loop | 4 | 4 | 1.00 | [1.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.00 | 2930 | 1.9 | 0 |
| gabriel_reference_plan | 4 | 0 | 0.00 | [0.00, 0.00] | 0 | 0 | n/a (0 declared) | 3.00 | 9119 | 11.6 | 4 |
| gabriel_associative | 4 | 0 | 0.00 | [0.00, 0.00] | 0 | 0 | n/a (0 declared) | 3.25 | 9815 | 12.4 | 4 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 16 | 10 | 0.62 | [0.00, 1.00] | 15 | 5 | 0.33 (n=15) | 1.00 | 2548 | 3.8 | 0 |
| simple_loop | 16 | 14 | 0.88 | [0.67, 1.00] | 14 | 0 | 0.00 (n=14) | 2.00 | 5464 | 4.9 | 0 |
| gabriel_reference_plan | 16 | 4 | 0.25 | [0.00, 1.00] | 4 | 0 | 0.00 (n=4) | 2.50 | 7223 | 11.0 | 12 |
| gabriel_associative | 16 | 7 | 0.44 | [0.00, 1.00] | 7 | 0 | 0.00 (n=7) | 2.12 | 5895 | 9.6 | 9 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_reference_plan_minus_provider_only: success mean -0.50, CI95 by family [-1.00, +0.00], by task [-0.80, -0.20]; tokens +4978, requests +1.60; per task: da-archive -1.0, da-fee -1.0, da-garden -1.0, da-library -1.0, da-parking -1.0, dn-fee +0.0, dn-parking +0.0, du-archive +0.0, du-fee +0.0, du-parking +0.0
- gabriel_reference_plan_minus_simple_loop: success mean -0.70, CI95 by family [-1.00, -0.25], by task [-1.00, -0.40]; tokens +2645, requests +0.80; per task: da-archive -1.0, da-fee -1.0, da-garden -1.0, da-library -1.0, da-parking -1.0, dn-fee +0.0, dn-parking +0.0, du-archive +0.0, du-fee -1.0, du-parking -1.0
- gabriel_reference_plan_minus_gabriel_associative: success mean -0.15, CI95 by family [-0.41, +0.00], by task [-0.35, +0.00]; tokens +923, requests +0.25; per task: da-archive -0.5, da-fee -1.0, da-garden +0.0, da-library +0.0, da-parking +0.0, dn-fee +0.0, dn-parking +0.0, du-archive +0.0, du-fee +0.0, du-parking +0.0

## Retained failures and false completions

- da-archive / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems doc/summary.md: quote 'The statute states that records shall be retained for eleven' is not a verbatim span of any available source; required statement missing: schedule; required statement not cited from statute with 'the period named in the schedule', out of scope []; provider ['completed', 'completed', 'completed']
- da-archive / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-archive / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement not cited from agreement with 'as listed in the register'; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement not cited from agreement with 'as listed in the register'; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems doc/summary.md carries no citation; required statement missing: register; required statement not cited from agreement with 'as listed in the register', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems doc/summary.md: quote 'The agreement states that each plot is 40 square metres in s' is not a verbatim span of any available source; doc/summary.md: quote 'Plots are allocated according to a defined rule.' is not a verbatim span of any available source; required statement missing: register, out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: loan table; required statement not cited from bylaws with 'the terms of the loan table'; required statement missing: twenty-one days | 21 days, out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: loan table; required statement not cited from bylaws with 'the terms of the loan table'; required statement missing: twenty-one days | 21 days, out of scope []; provider ['completed', 'completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems doc/summary.md: quote 'The bylaws states that a member may borrow books for a perio' is not a verbatim span of any available source; doc/summary.md: quote 'The bylaws states that books must be returned within two wee' is not a verbatim span of any available source; required statement missing: loan table, out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems doc/summary.md: quote 'The bylaws state that members may borrow books from the libr' is not a verbatim span of any available source; doc/summary.md: quote 'Each member may keep a borrowed book for a period of twenty-' is not a verbatim span of any available source; doc/summary.md: quote 'After this period, the book must be returned or renewed acco' is not a verbatim span of any available source, out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems doc/summary.md: quote 'The handbook states that parking is allowed only in designat' is not a verbatim span of any available source; doc/summary.md: quote 'Certain spaces are reserved for handicapped parking and visi' is not a verbatim span of any available source; doc/summary.md: quote 'The time limit for parking in non-reserved spaces is two hou' is not a verbatim span of any available source, out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems doc/summary.md carries no citation; required statement missing: appendix; required statement not cited from handbook with 'according to the plan in the appendix', out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems doc/summary.md: quote 'parking is allowed only in designated spaces' is not a verbatim span of any available source; doc/summary.md: quote 'spaces are reserved for visitors and handicapped parking' is not a verbatim span of any available source; doc/summary.md: quote 'Parking in reserved spaces without authorization is prohibit' is not a verbatim span of any available source, out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems doc/summary.md: quote 'Parking is allowed only in designated areas and must comply ' is not a verbatim span of any available source; doc/summary.md: quote 'Reserved parking spaces are allocated for visitors, staff, a' is not a verbatim span of any available source; doc/summary.md: quote 'Parking in reserved spaces is limited to two hours to ensure' is not a verbatim span of any available source, out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: schedule; required statement not cited from statute with 'the period named in the schedule', out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: schedule; required statement not cited from statute with 'the period named in the schedule', out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: schedule; required statement not cited from statute with 'the period named in the schedule', out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: schedule; required statement not cited from statute with 'the period named in the schedule', out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed']
- du-archive / provider_only / rep 1: declared=False verified=False; provider status invalid_output; problems doc/summary.md carries no citation; required statement missing: schedule; required statement not cited from statute with 'the period named in the schedule', out of scope []; provider ['invalid_output']
- du-archive / simple_loop / rep 0: declared=False verified=False; budget exhausted without passing checks; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- du-archive / simple_loop / rep 1: declared=False verified=False; budget exhausted without passing checks; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- du-fee / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: annex; required statement not cited from charter with 'fixed in the annex', out of scope []; provider ['completed', 'completed', 'completed']
- du-fee / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: annex; required statement not cited from charter with 'fixed in the annex', out of scope []; provider ['completed', 'completed', 'completed']
- du-fee / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: annex; required statement not cited from charter with 'fixed in the annex', out of scope []; provider ['completed', 'completed', 'completed']
- du-fee / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: annex; required statement not cited from charter with 'fixed in the annex', out of scope []; provider ['completed', 'completed', 'completed']
- du-fee / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: 120, out of scope []; provider ['completed']
- du-fee / provider_only / rep 1: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: 120, out of scope []; provider ['completed']
- du-parking / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: appendix; required statement not cited from handbook with 'according to the plan in the appendix', out of scope []; provider ['completed', 'completed', 'completed']
- du-parking / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: appendix; required statement not cited from handbook with 'according to the plan in the appendix', out of scope []; provider ['completed', 'completed', 'completed']
- du-parking / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: appendix; required statement not cited from handbook with 'according to the plan in the appendix', out of scope []; provider ['completed', 'completed', 'completed']
- du-parking / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: appendix; required statement not cited from handbook with 'according to the plan in the appendix', out of scope []; provider ['completed', 'completed', 'completed']
- du-parking / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: twelve through thirty, out of scope []; provider ['completed']
- du-parking / provider_only / rep 1: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: twelve through thirty, out of scope []; provider ['completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
