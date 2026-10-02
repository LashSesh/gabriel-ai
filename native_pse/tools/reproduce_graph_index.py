"""Compile, regenerate, independently verify and fault-test the finite index.

Requires C++17 (g++ by default); does not build the optional Rust integration.
Run: python native_pse/tools/reproduce_graph_index.py --output /new/directory
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def require(condition,message):
    if not condition:raise RuntimeError(message)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--compiler',default='g++');args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);steps=[]
    def run(cmd,ok=True):
        r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True)
        steps.append({'command':list(map(str,cmd)),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
        require((r.returncode==0)==ok,json.dumps(steps[-1]))
        return r
    compiler=run([args.compiler,'--version']).stdout
    for name in ['build_graph_index','verify_graph_index']:
        run([args.compiler,'-std=c++17','-O3','-Wall','-Wextra','-Werror',ROOT/'tools'/(name+'.cpp'),'-o',out/name])
    with tempfile.TemporaryDirectory(prefix='gabriel-index-checks-') as d:
        temp=Path(d);data=temp/'data'
        generation=json.loads(run([out/'build_graph_index',data]).stdout)
        verification=json.loads(run([out/'verify_graph_index',data]).stdout)
        run([out/'build_graph_index',temp/'again'])
        names=['s7_classes.bin','s7_metadata.bin','s7_witnesses.bin']
        for name in names:
            require((data/name).read_bytes()==(temp/'again'/name).read_bytes(),
                    'Repeated generation differs: '+name)
            require((data/name).read_bytes()==(ROOT/'crates/pse-metatron/data'/name).read_bytes(),
                    'Delivered data differs: '+name)
        identity=sum(i<<(3*i) for i in range(7))
        faults=[('class-range',0,0,struct.pack('<H',65535)),
                ('wrong-class',0,2,struct.pack('<H',0)),
                ('witness-range',2,0,struct.pack('<I',0xffffffff)),
                ('nonbijection',2,0,struct.pack('<I',0)),
                ('wrong-representative',1,0,struct.pack('<I',1)),
                ('wrong-minimum',1,4,struct.pack('<I',1)),
                ('wrong-orbit',1,8,struct.pack('<I',2)),
                ('wrong-stabilizer',1,12,struct.pack('<I',5039)),
                ('witness-high-bit',2,0,struct.pack('<I',int.from_bytes((data/names[2]).read_bytes()[:4],'little')|(1<<21))),
                ('witness-digit-seven',2,0,struct.pack('<I',identity|7))]
        fault_results=[]
        def reject(case,label,reason=None):
            r=run([out/'verify_graph_index',case],False)
            actual=r.stderr.strip()
            require(reason is None or actual==reason,
                    'Unexpected rejection for '+label+': '+actual)
            fault_results.append({'case':label,'rejected':True,'reason':actual})
        for label,index,offset,value in faults:
            case=temp/label;shutil.copytree(data,case);f=case/names[index]
            b=bytearray(f.read_bytes());b[offset:offset+len(value)]=value;f.write_bytes(b)
            reject(case,label,'witness bijection' if label=='witness-digit-seven' else None)
        label='split-single-edge-orbit';case=temp/label;shutil.copytree(data,case)
        ids=bytearray((case/names[0]).read_bytes());meta=bytearray((case/names[1]).read_bytes())
        original_class=struct.unpack_from('<H',ids,2)[0];new_class=len(meta)//16
        require(original_class<new_class<=65535,'Single-edge class identifiers out of range')
        require(struct.unpack_from('<4I',meta,16*original_class)==(1,1<<20,21,240),
                'Unexpected original single-edge metadata')
        require(struct.unpack_from('<I',(case/names[2]).read_bytes(),4)[0]==identity,
                'Expected identity witness for the single-edge representative')
        struct.pack_into('<H',ids,2,new_class)
        struct.pack_into('<2I',meta,16*original_class+8,20,252)
        meta.extend(struct.pack('<4I',1,1,1,5040))
        (case/names[0]).write_bytes(ids);(case/names[1]).write_bytes(meta)
        reject(case,label,'generator closure')
        for index,name in enumerate(names):
            label='truncated-'+name;case=temp/label;shutil.copytree(data,case);f=case/name;f.write_bytes(f.read_bytes()[:-1])
            reject(case,label)
        case=temp/'valid-alternative';shutil.copytree(data,case);f=case/names[2];b=bytearray(f.read_bytes())
        b[:4]=struct.pack('<I',sum((6-i)<<(3*i) for i in range(7)));f.write_bytes(b)
        run([out/'verify_graph_index',case])
        report={'status':'passed','generator':generation,'independent_verification':verification,
            'invalid_certificates':fault_results,'valid_alternative_witness_accepted':True,
            'regenerated_files_byte_identical':True,'data_sha256':{n:sha(data/n) for n in names},
            'source_sha256':{p.name:sha(p) for p in [Path(__file__),ROOT/'tools/build_graph_index.cpp',ROOT/'tools/verify_graph_index.cpp']},
            'compiler':compiler,'steps':steps,'rust_integration':'Not compiled or executed by this script.'}
        (out/'verification_report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ['status','generator','independent_verification','regenerated_files_byte_identical']}))


if __name__=='__main__':main()
