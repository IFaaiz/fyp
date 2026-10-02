"""Create a text-free corpus index and reject partitions that overlap it."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.datasets.global_leakage import build_global_index, identity_from_row
from src.datasets.registry import validate_registry


def file_sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--registry',type=Path,default=AI/'config/dataset_registry.json')
    parser.add_argument('--source',action='append',required=True,help='registry dataset_id=JSONL path')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--assignments',type=Path,help='Existing assignment manifest bound to the exact output index SHA256')
    args=parser.parse_args();registry=json.loads(args.registry.read_text(encoding='utf-8'))
    errors=validate_registry(registry)
    if errors:raise ValueError('; '.join(errors))
    sources={d['dataset_id']:d for d in registry['datasets']};rows=[];provenance=[]
    for descriptor in args.source:
        name,separator,value=descriptor.partition('=')
        if not separator or name not in sources:raise ValueError('Source must name a registered dataset')
        path=Path(value);count=0
        with path.open(encoding='utf-8-sig') as f:
            for line in f:
                if line.strip():rows.append(identity_from_row(json.loads(line),name,sources[name]['overlap_family']));count+=1
        provenance.append({'dataset_id':name,'file_sha256':file_sha(path),'records':count})
    index=build_global_index(rows);payload=index.export();payload['source_files']=provenance
    encoded=(json.dumps(payload,indent=2,sort_keys=True)+'\n').encode('utf-8')
    output_sha=hashlib.sha256(encoded).hexdigest()
    if args.assignments:
        assignment=json.loads(args.assignments.read_text(encoding='utf-8'))
        if assignment.get('index_sha256')!=output_sha:raise ValueError('Assignments use a different index snapshot; re-audit complete component membership')
        conflicts=index.partition_conflicts(assignment['partitions'])
        if conflicts:raise ValueError('Cross-partition leakage: '+json.dumps(conflicts))
    # Source files and output must never alias; writing an index cannot replace emails.
    if args.output.resolve() in {Path(s.partition('=')[2]).resolve() for s in args.source}:
        raise ValueError('Index output cannot replace a source JSONL')
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(encoded)
    print(json.dumps({'records':len(rows),'components':len({r['leakage_group_id'] for r in index.records.values()}),
                      'links':len(index.links),'unresolved_identities':sum(not r['identity_complete'] for r in index.records.values()),
                      'index_sha256':output_sha,'source_files':provenance,'raw_text_exported':False}))


if __name__=='__main__':main()
