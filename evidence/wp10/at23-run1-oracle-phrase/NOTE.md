# AT23 run 1 (retained)

The first real-provider AT23 run failed the document task on the `claims` check although the
model's amendment was correct and both citations resolved (`document/valid.diff`): the
required-claims oracle demanded the literal phrase "30 days" and the model wrote "thirty (30)
days". This is an oracle phrasing defect, not a system defect. The oracle format was extended
to accept a list of phrasings for the same fact (the cited source span stays fixed) and the
run was repeated under `evidence/wp10/at23`. Software and numerical succeeded in this run as
well; the controls behaved identically.
