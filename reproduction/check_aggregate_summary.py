"""Deterministic synthetic checks of the common-date summary mechanism."""
import json
from pathlib import Path
import numpy as np

from summarize_aggregate_risk import (bootstrap_from_starts, circle_block_starts,
    jensen_components, score, shared_bootstrap)


def main():
    # Exhaust explicit block concatenations rather than calling the constructor.
    x=np.column_stack((np.arange(7.), 2*np.arange(7.)+3))
    starts=np.asarray([[6,3,1],[0,5,2],[4,4,4]],dtype=np.int32)
    found=bootstrap_from_starts(x,starts,3)
    expected=[]
    for row in starts:
        selected=[]
        for start in row:
            for offset in range(3):
                selected.append(x[(int(start)+offset)%7])
        expected.append(np.mean(selected[:7],axis=0))
    np.testing.assert_allclose(found,expected,rtol=0,atol=0)
    # Exact linear dependence is preserved by common-date resampling.
    np.testing.assert_allclose(found[:,1],2*found[:,0]+3,rtol=0,atol=2e-15)
    a=circle_block_starts(7,3,9,123)
    assert np.array_equal(a,circle_block_starts(7,3,9,123))
    assert a.shape==(9,3) and a.min()>=0 and a.max()<7
    # A constant score difference is invariant under all blocks and contracts.
    differences=np.empty((70,8,2));differences[:,:,0]=-.125;differences[:,:,1]=-.25
    summary,arrays=shared_bootstrap(differences,['a','b'],lengths=(20,60),replicates=17,seed=987)
    assert summary['conjunctive_gate_passed']
    for length in (20,60):
        np.testing.assert_array_equal(arrays[f'bootstrap_means_{length}'],
                                      np.tile([-.125,-.25],(17,1)))
    differences[:,:,1]=.0625
    rejected,_=shared_bootstrap(differences,['a','b'],lengths=(20,60),replicates=17,seed=987)
    assert not rejected['conjunctive_gate_passed']
    # The Jensen split vanishes at simplex vertices and for duplicated experts.
    q=np.asarray([[1.,2.],[2.,3.],[1.,4.]])
    e=np.asarray([[2.,3.],[3.,4.],[2.,5.]])
    y=np.asarray([1.5,5.,0.])
    w=np.tile([1.,0.],(3,1))
    vertex,_=jensen_components(q,e,w,y,score(q[:,0],e[:,0],y))
    assert abs(vertex['mean_total_gap'])<1e-15
    w[:]=.5
    bb=np.sum(w/e,axis=1); qq=np.sum(w*q/e,axis=1)/bb;ee=1/bb
    diverse,_=jensen_components(q,e,w,y,score(qq,ee,y))
    assert diverse['mean_log_gap']>0 and diverse['mean_hinge_gap']>0
    duplicate_q=np.repeat(q[:,:1],2,axis=1);duplicate_e=np.repeat(e[:,:1],2,axis=1)
    duplicated,_=jensen_components(duplicate_q,duplicate_e,w,y,
                                    score(q[:,0],e[:,0],y))
    assert abs(duplicated['mean_total_gap'])<1e-15
    invalids=[lambda:circle_block_starts(7,8),
              lambda:circle_block_starts(7,0),
              lambda:circle_block_starts(True,1),
              lambda:shared_bootstrap(np.zeros((7,8,2)),['a','a'],lengths=(3,),replicates=2),
              lambda:bootstrap_from_starts(np.zeros((7,2)),np.array([[7,0,0]]),3)]
    rejections=0
    for callback in invalids:
        try:callback()
        except ValueError:rejections+=1
    assert rejections==len(invalids)
    result=dict(status='passed',nature='Deterministic synthetic mechanism checks; no market outcomes read',
        explicit_block_cases=len(starts),constant_comparator_bootstrap_cases=4,
        conjunctive_positive_and_negative_cases=2,jensen_vertex_duplicate_and_diverse_cases=3,
        invalid_input_rejections=rejections)
    target=Path(__file__).resolve().parents[1]/'results/aggregate_summary_checks.json'
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
