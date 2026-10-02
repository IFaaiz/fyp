"""Reserve unseen source candidates before V2 semantic retrieval or fitting.

This performs label-free sampling only. Outputs are PRIVATE candidates, not
annotations or an accepted evaluation set. Global overlap checks and independent
AI reviews must still approve them before training/evaluation use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENRON_ID = re.compile(r'^enron-[0-9a-f]{16,64}$')


def sha_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def collect_ids(value, output):
    if isinstance(value,str) and ENRON_ID.fullmatch(value):output.add(value)
    elif isinstance(value,dict):
        for key,item in value.items():collect_ids(key,output);collect_ids(item,output)
    elif isinstance(value,list):
        for item in value:collect_ids(item,output)


def exposed_ids(paths):
    found=set();manifest=[]
    for path in sorted(set(paths)):
        if not path.is_file():continue
        if path.suffix=='.jsonl':
            with path.open(encoding='utf-8-sig') as stream:
                for line in stream:
                    if line.strip():collect_ids(json.loads(line),found)
        elif path.suffix=='.json':collect_ids(json.loads(path.read_text(encoding='utf-8-sig')),found)
        else:continue
        manifest.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha_file(path)})
    return found,manifest


def sample_candidates(source, excluded, count, seed):
    rng=random.Random(seed);sample=[];seen_ids=set();eligible=0;scanned=0;excluded_rows=0;exposed_sources={}
    with source.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():continue
            row=json.loads(line);scanned+=1;sid=row.get('email_id')
            if not isinstance(sid,str) or not ENRON_ID.fullmatch(sid):
                raise ValueError('Expected canonical stable Enron IDs; no guessed identities')
            if sid in excluded:
                excluded_rows+=1
                exposed_sources[sid]={'source_id':sid,'email_id':sid,'source_dataset':'enron',
                                     'subject':row.get('subject',''),'current_message':row.get('current_message',''),
                                     'raw_body':row.get('raw_body',''),'thread_context':row.get('thread_context',[]),
                                     'thread_id':row.get('thread_id')}
                continue
            if sid in seen_ids:continue
            seen_ids.add(sid)
            text=row.get('authored_message',row.get('current_message',''))
            if not isinstance(text,str) or len(text.strip())<80:continue
            eligible+=1
            packet={'source_id':sid,'email_id':sid,'source_dataset':'enron','overlap_family':'ENRON',
                    'subject':row.get('subject',''),'current_message':text,'raw_body':row.get('raw_body',''),
                    'thread_context':row.get('thread_context',[]),'thread_id':row.get('thread_id'),
                    'source_thread_id':row.get('source_thread_id'), 'source_thread_verified':False,
                    'candidate_status':'unreviewed','fyp_labels':None,'structured_annotation':None}
            if len(sample)<count:sample.append(packet)
            else:
                position=rng.randrange(eligible)
                if position<count:sample[position]=packet
    if len(sample)<count:raise ValueError(f'Only {len(sample)} eligible unseen records; requested {count}')
    rng.shuffle(sample)
    return sample,{'source_rows_scanned':scanned,'eligible_unseen_rows':eligible,'excluded_exposed_rows':excluded_rows,
                   'historical_ids_missing_from_full_source':len(excluded-set(exposed_sources))},list(exposed_sources.values())


def write_rows(path, rows):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'ai/data/interim/enron_full.jsonl')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'ai/data/experiments/structured_v2_candidates_20261002')
    parser.add_argument('--train-screen-count',type=int,default=5000)
    parser.add_argument('--reserve-count',type=int,default=1200)
    parser.add_argument('--seed',type=int,default=20261002)
    args=parser.parse_args()
    if min(args.train_screen_count,args.reserve_count)<1:raise ValueError('Positive candidate counts required')
    output=args.output_dir.resolve();data_root=(ROOT/'ai/data').resolve()
    if data_root not in output.parents:raise ValueError('Private packets must remain under ignored ai/data')
    if output.exists():raise FileExistsError('Candidate reservation is immutable; use a separate explicitly versioned directory')
    annotation_paths=list((ROOT/'ai/annotation').glob('*.json'))+list((ROOT/'ai/annotation').glob('*.jsonl'))
    historical=list((ROOT/'ai/data/interim').glob('enron*candidates*.jsonl'))
    historical+=list((ROOT/'ai/data/interim').glob('enron*sample*.jsonl'))
    historical+=list((ROOT/'ai/data/interim').glob('enron*smoke*.jsonl'))
    historical+=list((ROOT/'ai/data/processed').glob('enron*.jsonl'))
    for directory in ['annotated','splits']:
        historical+=list((ROOT/'ai/data'/directory).rglob('*.jsonl'))
        historical+=list((ROOT/'ai/data'/directory).rglob('*.json'))
    for directory in (ROOT/'ai/data/experiments').iterdir():
        if directory.is_dir() and not directory.name.startswith('structured_v2'):
            historical+=list(directory.rglob('*.jsonl'))+list(directory.rglob('*.json'))
    excluded,exposure_manifest=exposed_ids(annotation_paths+historical)
    before=args.source.stat();source_sha=sha_file(args.source)
    sample,stats,historical_sources=sample_candidates(args.source,excluded,args.train_screen_count+args.reserve_count,args.seed)
    after=args.source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed during reservation')
    output.mkdir(parents=True)
    reserved=sample[:args.reserve_count];train=sample[args.reserve_count:]
    reserve_path=output/'reserved_fresh_candidates.jsonl';train_path=output/'train_screen_candidates.jsonl'
    write_rows(reserve_path,reserved);write_rows(train_path,train)
    historical_path=output/'historical_exposure_source_views.jsonl'
    write_rows(historical_path,sorted(historical_sources,key=lambda r:r['source_id']))
    manifest={'version':'2-alpha','seed':args.seed,'status':'reserved_candidates_pending_global_audit_and_reviews',
              'source_sha256':source_sha,'source_bytes':before.st_size,'previously_exposed_ids_excluded':len(excluded),
              'exposure_inventory':exposure_manifest,'source_scan':stats,
              'reserved_candidates':{'count':len(reserved),'sha256':sha_file(reserve_path)},
              'train_screen_candidates':{'count':len(train),'sha256':sha_file(train_path)},
              'historical_exposure_source_views':{'count':len(historical_sources),'sha256':sha_file(historical_path)},
              'annotations_accepted':0,'human_reviewed_labels':0,'models_trained':0,
              'policy':'Reserved candidates must not enter semantic TRAIN retrieval, prompt development, DEV selection or fitting. They are not an evaluation set until global isolation, double AI review and third adjudication pass. Split prevalence/challenge only under a predeclared source-selection policy.',
              'limitations':['Exclusion matches known historical source IDs; aliases, near copies and quoted copies require a shared global leakage snapshot','Future discovered exposure may invalidate reserved candidates','No primitive-positive support established by unlabelled sampling']}
    (output/'reservation_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    public={k:v for k,v in manifest.items() if k!='exposure_inventory'}
    (ROOT/'ai/reports/structured_candidate_reservation.json').write_text(json.dumps(public,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'source_scan':stats,'excluded_known_ids':len(excluded),'reserved':len(reserved),'train_screen':len(train),'accepted_annotations':0,'model_training_performed':False}))


if __name__=='__main__':main()
