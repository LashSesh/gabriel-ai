"""Render the implemented shared runtime topology, without experimental values."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]


def main():
    fig, ax = plt.subplots(figsize=(9.4, 4.2))
    ax.set(xlim=(0, 10), ylim=(0, 4.3)); ax.axis('off')
    def box(x, y, w, h, label, color):
        ax.add_patch(FancyBboxPatch((x,y), w,h, boxstyle='round,pad=0.06',
                     linewidth=1, edgecolor='#34465b', facecolor=color))
        ax.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=9)
    def arrow(a, b, label=None):
        ax.annotate('',xy=b,xytext=a,arrowprops=dict(arrowstyle='->',lw=1.1,color='#34465b'))
        if label: ax.text((a[0]+b[0])/2,(a[1]+b[1])/2+.08,label,
                         ha='center',fontsize=8,color='#34465b')
    box(.2,3.35,2.1,.65,'Exact command\nID, contract, clock, head','#e8f0fa')
    box(3.25,3.35,3.5,.65,'Owner admission\nbinding, retry identity, budgets','#e8f0fa')
    box(7.7,3.35,2.1,.65,'Committed receipt\noriginal result on retry','#e8f0fa')
    box(.25,1.85,2.85,.8,'Finite observation adapter\ncompatible models + next query','#eaf4e6')
    box(6.9,1.85,2.85,.8,'Maturity-risk adapter\nissues, outcomes, feedback','#eaf4e6')
    box(3.7,1.75,2.6,1.0,'Atomic transaction\nstate + result + journal\nSQLite DELETE / EXTRA','#fff1d7')
    box(.8,.25,3.65,.65,'Profile-specific views\ncommitted domain state','#eef0f2')
    box(5.5,.25,3.65,.65,'Semantic replay + expected anchor\nrecompute, compare, verify frontier','#eef0f2')
    arrow((2.36,3.675),(3.19,3.675))
    arrow((5,3.29),(5,2.81))
    arrow((3.64,2.25),(3.16,2.25));arrow((6.36,2.25),(6.84,2.25))
    arrow((6.36,2.7),(8.75,3.29),'after commit')
    arrow((4.2,1.69),(2.6,.96));arrow((5.8,1.69),(7.3,.96))
    fig.tight_layout(pad=.4)
    fig.savefig(ROOT/'figures/runtime_architecture.pdf')
    fig.savefig(ROOT/'figures/runtime_architecture.png',dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    main()
