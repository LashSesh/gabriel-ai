"""Plot current-state response to one retained synthetic source correction."""
from pathlib import Path
import hashlib
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'results/stream_demo.json'
data=json.loads(source.read_text())['summary']
snapshots=data['snapshots']
before=np.array([float.fromhex(x) for x in snapshots['before_correction']['learner']['lane_weights_hex'][0]])
after=np.array([float.fromhex(x) for x in snapshots['after_correction']['learner']['lane_weights_hex'][0]])
assert data['published_prefix_unchanged_after_correction']
labels=['Raw HS','Slow FHS','FHS 25%','FHS 50%','FHS 75%','Fast FHS','Severity\n125','Severity\n500']
fig,ax=plt.subplots(figsize=(7.2,2.7),layout='constrained')
x=np.arange(8);w=.36
ax.bar(x-w/2,before,w,label='Before correction',color='#4b6c8d')
ax.bar(x+w/2,after,w,label='After correction',color='#ce8b46')
ax.set_xticks(x,labels,fontsize=8);ax.set_ylabel('Current mixture weight',fontsize=9)
ax.tick_params(axis='y',labelsize=8);ax.set_ylim(0,max(before.max(),after.max())*1.24)
ax.spines[['top','right']].set_visible(False);ax.set_axisbelow(True);ax.grid(axis='y',alpha=.2)
ax.legend(loc='upper left',ncol=2,fontsize=8,frameon=False)
for ext in ['pdf','png']:fig.savefig(ROOT/f'figures/stream_correction.{ext}',dpi=180)
plt.close(fig)
(ROOT/'results/stream_figure_data.json').write_text(json.dumps({'kind':'synthetic current-state correction example','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'expert_labels':labels,'before':before.tolist(),'after':after.tolist(),'unchanged_issued_count':snapshots['before_correction']['issued_count'],'correction_index':data['fixture']['corrected_index']},indent=2)+'\n')
