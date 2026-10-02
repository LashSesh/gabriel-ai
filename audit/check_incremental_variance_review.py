"""Independent reviewer check of cached variance values versus frozen reference."""
import sys
import json
import hashlib
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gabriel_runtime.stream import StreamRiskAdapter
from gabriel_runtime.incremental import IncrementalStreamRiskAdapter

def main():
    reference=StreamRiskAdapter(); cached=IncrementalStreamRiskAdapter()
    seed=2026092609
    rng=np.random.default_rng(seed)
    checks=0
    lengths=(61,62,63,64,65,310,311,315,319,321,513,700,320,399)
    corrections=(0,1,59,60,61,312,698,699)
    for case in range(30):
        x=np.exp(np.cumsum(rng.normal(0,.03,700)))[:,None]
        for n in lengths:
            a,b=reference.ecb.fading_variances(x[:n])
            c,d=cached.ecb.fading_variances(x[:n])
            assert a.tobytes()==c.tobytes() and b.tobytes()==d.tobytes(),(case,n,'prefix')
            checks+=1
        for s in corrections:
            z=x.copy(); z[s]*=1.03125
            a,b=reference.ecb.fading_variances(z)
            c,d=cached.ecb.fading_variances(z)
            assert a.tobytes()==c.tobytes() and b.tobytes()==d.tobytes(),(case,s,'correction')
            checks+=1
    files=('gabriel_runtime/incremental.py','gabriel_runtime/stream.py','reproduction/ecb_risk.py')
    result={'status':'passed','variance_byte_equal_cases':checks,'seed':seed,
            'numpy_version':np.__version__,'prefix_lengths':list(lengths),
            'correction_indexes':list(corrections),'source_sha256':{
                name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}}
    out=Path(__file__).with_name('incremental_variance_review.json')
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
