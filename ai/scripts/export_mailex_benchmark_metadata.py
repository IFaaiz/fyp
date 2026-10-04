"""Export only aggregate metrics/configurations; prediction JSONL stays private."""
from __future__ import annotations
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai" / "src"))
from mailex_extraction.compact import inventory, read_rows


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run', action='append', required=True, help='Private compact experiment directory')
    p.add_argument('--output', default='ai/reports/mailex_extraction_results')
    a=p.parse_args()
    output=ROOT/a.output
    output.mkdir(parents=True, exist_ok=True)
    index=[]
    allowed=['config.json','selected_epoch.json','dev_metrics.json','dev_gold_type_metrics.json',
             'dev_gold_type_trigger_metrics.json','dev_gold_type_0.7_metrics.json',
             'dev_gold_type_trigger_0.7_metrics.json','calibration/calibration.json',
             *[f'calibration/dev_threshold_{t}.metrics.json' for t in (0.3,0.5,0.7,0.9)]]
    for run_name in a.run:
        run=ROOT/run_name
        if not run.is_dir(): raise ValueError(f'Run absent: {run_name}')
        dest=output/run.name
        dest.mkdir(exist_ok=True)
        files={}
        for name in allowed:
            src=run/name
            if src.is_file():
                # Only explicit source-free filenames are eligible. Never glob predictions.
                data=json.loads(src.read_text(encoding='utf-8'))
                target=dest/name.replace('/','_')
                target.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8',newline='\n')
                files[target.relative_to(ROOT).as_posix()]=hashlib.sha256(target.read_bytes()).hexdigest()
        index.append({'run':run.name,'weight_sha256':hashlib.sha256((run/'model.pt').read_bytes()).hexdigest(),
                      'weight_bytes':(run/'model.pt').stat().st_size,'public_metadata':files})
    (output/'compact_runs.json').write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8',newline='\n')
    train=read_rows(ROOT/'ai/data/experiments/mailex_extraction_v1/train_fyp_safe.jsonl')
    if any(r['split']!='train' for r in train): raise ValueError('Schema uses TRAIN only')
    types,roles=inventory(train)
    schema={'schema_version':1,'name':'MailEx native TRAIN ontology','event_types':types,'role_qualifier_keys':roles,
            'case_sensitive_roles':True,'span_offsets':'half-open Python character offsets',
            'arguments':'separate contiguous BIO runs attached to individual event instances',
            'triggers':'one or more native evidence segments, including discontinuous gold',
            'event_roles':{typ:sorted({(arg['role'],arg.get('qualifier') or '') for r in train for ev in r['events']
                                       if ev['event_type']==typ for arg in ev['arguments']}) for typ in types}}
    configdir=ROOT/'ai/config'
    (configdir/'mailex_native_extraction_schema.json').write_text(json.dumps(schema,indent=2)+'\n',encoding='utf-8',newline='\n')
    environment={name:version(name) for name in ('torch','transformers','numpy','scikit-learn','tokenizers','safetensors')}
    environment.update({'python':sys.version,'platform':'Windows development PC','cpu_threads':4,
                        'gliner_runtime':'isolated vendor directory; see GLiNER preflight/training report'})
    (configdir/'mailex_extraction_environment.json').write_text(json.dumps(environment,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'runs_exported':len(index),'private_predictions_exported':0,'event_types':len(types),'role_qualifier_keys':len(roles)}))


if __name__=='__main__': main()
