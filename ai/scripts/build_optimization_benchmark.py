"""Freeze new668-record benchmark before any sprint model development."""
from __future__ import annotations
import sys,json,hashlib
from pathlib import Path
from collections import Counter
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI));sys.path.insert(0,str(AI/'scripts'))
from src.models.optimization_benchmark import DATA,BENCHMARK,SEED,LABEL_ORDER,read_jsonl,balanced_folds,group_components
from src.models.transfer_diagnostic import validate_snapshot,sha256_file
from train_silver_classifier import grouped_train_validation_split

def main():
 if BENCHMARK.exists():raise SystemExit('Benchmark already frozen; refusing membership overwrite')
 source=AI/'data/experiments/tonight_20261002/next_training_silver_snapshot.jsonl';mp=AI/'annotation/tonight_next_training_manifest.jsonl'
 rows=read_jsonl(source);validate_snapshot(rows,read_jsonl(mp));assert len(rows)==668
 old=json.loads((AI/'annotation/tonight_silver_v2_shared_split.json').read_text(encoding='utf-8'))
 old_ids={m['email_id'] for m in old['partitions']['validation']};old_groups={m['leakage_group_id'] for m in old['partitions']['validation']};old_threads={(m['source_dataset'],m['thread_id']) for m in old['partitions']['validation']}
 candidates=[r for r in rows if r['email_id'] not in old_ids and r['snapshot_provenance']['leakage_group_id'] not in old_groups and (r['source_dataset'],r['thread_id']) not in old_threads]
 groups={(r['source_dataset'],r['email_id']):r['snapshot_provenance']['leakage_group_id'] for r in rows}
 outer,_=grouped_train_validation_split(candidates,groups,validation_ratio=(.15*len(rows))/len(candidates),seed=SEED)
 test=outer['validation'];test_ids={r['email_id'] for r in test};remaining=[r for r in rows if r['email_id'] not in test_ids]
 inner,_=grouped_train_validation_split(remaining,groups,validation_ratio=(.15*len(rows))/len(remaining),seed=SEED+1)
 parts={'train':inner['train'],'dev':inner['validation'],'test':test}
 owner_ids={};owner_groups={};owner_threads={}
 for name,rs in parts.items():
  for r in rs:
   for key,owner in [(r['email_id'],owner_ids),(r['snapshot_provenance']['leakage_group_id'],owner_groups),((r['source_dataset'],r['thread_id']),owner_threads)]:
    if key in owner and owner[key]!=name:raise ValueError('leakage boundary split')
    owner[key]=name
 assert set(owner_ids)=={r['email_id'] for r in rows};assert not test_ids&old_ids
 DATA.mkdir(parents=True,exist_ok=True)
 metadata={}
 for name,rs in parts.items():
  rs.sort(key=lambda r:(r['source_dataset'],r['email_id']));path=DATA/(name+'.jsonl');path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rs),encoding='utf-8',newline='\n')
  metadata[name]={'records':len(rs),'email_ids':[r['email_id'] for r in rs],'leakage_groups':len({r['snapshot_provenance']['leakage_group_id'] for r in rs}),'source_qualified_threads':len({(r['source_dataset'],r['thread_id']) for r in rs}),'label_support':{l:sum(l in r['labels'] for r in rs) for l in LABEL_ORDER},'file_sha256':sha256_file(path),'membership_sha256':hashlib.sha256('|'.join(sorted(r['email_id'] for r in rs)).encode()).hexdigest()}
 folds=balanced_folds(parts['train'])
 assert sorted(i for f in folds for i in f)==list(range(len(parts['train'])))
 fold_owner={}
 for k,fold in enumerate(folds):
  for i in fold:
   r=parts['train'][i];g=r['snapshot_provenance']['leakage_group_id'];assert g not in fold_owner or fold_owner[g]==k;fold_owner[g]=k
 meta={'status':'test_frozen_before_experiment','seed':SEED,'inner_seed':SEED+1,'source_commit':'5d0b5aa279926fd0db8d0f86ec89d8a9350661c6','source_manifest_sha256':sha256_file(mp),'source_snapshot_sha256':sha256_file(source),'metric_provenance':'AI-SILVER DIAGNOSTIC PERFORMANCE; zero human/gold labels','partitions':metadata,'test_design':'New frozen test selected from eligible records outside previously inspected138-validation ID/thread/leakage components, using predeclared seeded multilabel group-aware approximation. No performance-based membership choices. All remaining668 included inTRAIN/DEV/TEST.','historical_limit':'These records were semantically audited and may have participated in earlier training. New benchmark is untouched by this sprint model development, not a new independent source population. All sprint models initialize fresh pretrained/base weights.','train_cv_validation_ids':[[parts['train'][i]['email_id'] for i in f] for f in folds],'train_cv_label_support':[{l:sum(l in parts['train'][i]['labels'] for i in f) for l in LABEL_ORDER} for f in folds],'test_label_or_prediction_access_before_final_selection':False,'selection_primary_metric':'DEV macro F1; micro F1 secondary','test_final_evaluation_limit':'3-5 locked materially different candidates; one evaluation each; no subsequent tuning'}
 meta['train_cv_record_counts']=[len(f) for f in folds]
 BENCHMARK.write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8',newline='\n')
 seal={'status':'TEST frozen; never change membership after model development','benchmark_sha256_at_freeze':sha256_file(BENCHMARK),'test':metadata['test'],'seed':SEED,'selection_policy':meta['test_final_evaluation_limit']}
 (AI/'annotation/optimization_test_seal.json').write_text(json.dumps(seal,indent=2)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps({'counts':{k:v['records'] for k,v in metadata.items()},'supports':{k:v['label_support'] for k,v in metadata.items()},'CV':meta['train_cv_label_support'],'benchmark_sha256':sha256_file(BENCHMARK)},indent=2))
if __name__=='__main__':main()
