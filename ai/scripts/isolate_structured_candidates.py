"""Freeze candidate source boundaries after global identity/quote exclusions.

Outputs contain no accepted annotations and do not authorize model training.
The independent source reservation precedes new annotation/prompt selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'ai'))
from src.datasets.global_leakage import LeakageIndex


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding='utf-8') as stream:return [json.loads(s) for s in stream if s.strip()]


def rid(row):return 'enron:'+row['source_id']


def select_isolated(index, train_rows, reserved_rows, historical_rows, eval_count):
    historical=[rid(r) for r in historical_rows];reserved=[rid(r) for r in reserved_rows]
    bad_reserved=index.training_exclusions(reserved,historical)
    seen_groups=set();selected=[]
    for row in reserved_rows:
        record_id=rid(row)
        if record_id in bad_reserved:continue
        group=index.records[record_id]['leakage_group_id']
        if group not in seen_groups:
            seen_groups.add(group);selected.append(row)
    if len(selected)<eval_count:
        raise ValueError(f'Only {len(selected)} independent eligible reservation components; target {eval_count}')
    selected=selected[:eval_count]
    rejected_train=index.training_exclusions([rid(r) for r in train_rows],historical+reserved)
    retained=[r for r in train_rows if rid(r) not in rejected_train]
    assignments={r:'HISTORICAL_EXPOSED' for r in historical}
    assignments.update({rid(r):'EVAL_RESERVED' for r in selected})
    assignments.update({rid(r):'TRAIN_SCREEN' for r in retained})
    conflicts=index.partition_conflicts(assignments)
    if conflicts:raise ValueError('Final proposed source partitions conflict in global index')
    return selected,retained,bad_reserved,rejected_train,assignments,len(seen_groups)


def write(path,records):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        for row in records:stream.write(json.dumps(row,ensure_ascii=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reservation-dir',type=Path,default=ROOT/'ai/data/experiments/structured_v2_candidates_20261002_v2')
    parser.add_argument('--index',type=Path,default=ROOT/'ai/data/processed/structured_v2_expanded_leakage_index.json')
    parser.add_argument('--evaluation-count',type=int,default=600)
    parser.add_argument('--output-name',default='isolated',help='New immutable boundary version directory')
    args=parser.parse_args()
    if args.evaluation_count<1:raise ValueError('Positive evaluation reservation required')
    folder=args.reservation_dir.resolve();data_root=(ROOT/'ai/data').resolve()
    if data_root not in folder.parents:raise ValueError('Source packets must remain private under ai/data')
    manifest_path=folder/'reservation_manifest.json';manifest=json.loads(manifest_path.read_text())
    if manifest['status']!='reserved_candidates_pending_global_audit_and_reviews':raise ValueError('Invalid/superseded reservation')
    payload=json.loads(args.index.read_text());index=LeakageIndex(payload['records'],payload['links'],payload['policy'])
    index_sources={s['file_sha256'] for s in payload['source_files']}
    descriptors=[('reserved_candidates','reserved_fresh_candidates.jsonl'),
                 ('train_screen_candidates','train_screen_candidates.jsonl'),
                 ('historical_exposure_source_views','historical_exposure_source_views.jsonl')]
    for key,name in descriptors:
        digest=sha(folder/name)
        if digest!=manifest[key]['sha256'] or digest not in index_sources:
            raise ValueError(f'{key}: reservation/global index source snapshot mismatch')
    reserved=rows(folder/descriptors[0][1]);train=rows(folder/descriptors[1][1]);history=rows(folder/descriptors[2][1])
    selected,retained,bad_reserved,bad_train,assignments,eligible_groups=select_isolated(index,train,reserved,history,args.evaluation_count)
    auxiliary=[r for r,entry in index.records.items() if entry['dataset']!='enron']
    auxiliary_exclusions=index.training_exclusions(auxiliary,[rid(r) for r in selected])
    if not args.output_name or Path(args.output_name).name!=args.output_name or args.output_name in ('.','..'):
        raise ValueError('Output name must be one directory segment')
    output=folder/args.output_name;output.mkdir(exist_ok=False)
    eval_path=output/'evaluation_candidates.jsonl';train_path=output/'train_screen_candidates.jsonl'
    write(eval_path,selected);write(train_path,retained)
    boundary={'version':'2-alpha','status':'source_boundary_frozen_annotations_pending','index_sha256':sha(args.index),
              'index_path':args.index.resolve().relative_to(ROOT).as_posix(),'reservation_manifest_sha256':sha(manifest_path),
              'partitions':assignments,'protected_ids':sorted(set([rid(r) for r in history+reserved])),
              'protected_source_ids':sorted({r['source_id'] for r in history+reserved}),
              'evaluation_candidates_sha256':sha(eval_path),'train_screen_candidates_sha256':sha(train_path),
              'training_export_permitted':False,'accepted_structured_annotations':0,
              'policy':'All protected candidate components, including unused reservation sources, are excluded from TRAIN. Evaluation labels require blind A/B reviews and third adjudication before any model claim. This is a source boundary, not final test truth.'}
    (output/'boundary_manifest.json').write_text(json.dumps(boundary,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    from collections import Counter
    report={'index_sha256':boundary['index_sha256'],'indexed_records':len(index.records),
            'historical_exposure_sources':len(history),'original_reserved_candidates':len(reserved),
            'reservation_sources_excluded_by_historical_overlap':len(bad_reserved),'eligible_unique_reservation_components':eligible_groups,
            'evaluation_source_candidates_reserved':len(selected),'evaluation_annotation_status':'pending independent A/B + third adjudication',
            'screen_candidates_before_overlap_check':len(train),'screen_candidates_excluded':len(bad_train),
            'screen_candidates_retained':len(retained),'training_exclusion_reasons':dict(Counter(bad_train.values())),
            'auxiliary_training_exclusions_by_dataset':dict(Counter(index.records[r]['dataset'] for r in auxiliary_exclusions)),
            'training_performed':False,'accepted_structured_annotations':0,'human_gold_labels':0,
            'primitive_support':'unknown until independent source-grounded annotation',
            'prevalence_challenge_policy':'600 source-random reserved candidates; do not secretly enrich or tune this set. Any enriched challenge corpus needs separately reserved sources and its own sampling policy.',
            'all_reserved_sources_protected':True,'cross_partition_component_conflicts':0}
    (ROOT/'ai/reports/structured_candidate_isolation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
