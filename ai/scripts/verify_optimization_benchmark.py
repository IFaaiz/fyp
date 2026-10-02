"""Verify sealed membership and hashes without displaying TEST text or errors."""
from __future__ import annotations
import sys,json,hashlib
from pathlib import Path
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI));sys.path.insert(0,str(AI/'scripts'))
from src.models.optimization_benchmark import *
from src.models.transfer_diagnostic import validate_snapshot,sha256_file
from train_silver_classifier import grouped_train_validation_split

def main():
 meta=json.loads(BENCHMARK.read_text(encoding='utf-8'));seal=json.loads((AI/'annotation/optimization_test_seal.json').read_text(encoding='utf-8'))
 assert benchmark_hash()==seal['benchmark_sha256_at_freeze'];assert meta['partitions']['test']==seal['test']
 source=AI/'data/experiments/tonight_20261002/next_training_silver_snapshot.jsonl'
 manifest=AI/'annotation/tonight_next_training_manifest.jsonl'
 assert sha256_file(source)==meta['source_snapshot_sha256'];assert sha256_file(manifest)==meta['source_manifest_sha256']
 rows=read_jsonl(source);validate_snapshot(rows,read_jsonl(manifest));assert len(rows)==668
 owner={};threads={};groups={}
 for name,info in meta['partitions'].items():
  assert sha256_file(DATA/(name+'.jsonl'))==info['file_sha256']
  assert hashlib.sha256('|'.join(sorted(info['email_ids'])).encode()).hexdigest()==info['membership_sha256']
  for id in info['email_ids']:assert id not in owner;owner[id]=name
 assert set(owner)=={r['email_id'] for r in rows}
 for r in rows:
  part=owner[r['email_id']]
  for key,seen in [((r['source_dataset'],r['thread_id']),threads),(r['snapshot_provenance']['leakage_group_id'],groups)]:
   assert key not in seen or seen[key]==part;seen[key]=part
 old=json.loads((AI/'annotation/tonight_silver_v2_shared_split.json').read_text(encoding='utf-8'))['partitions']['validation']
 oldids={r['email_id'] for r in old};oldgroups={r['leakage_group_id'] for r in old};oldthreads={(r['source_dataset'],r['thread_id']) for r in old}
 candidates=[r for r in rows if r['email_id'] not in oldids and r['snapshot_provenance']['leakage_group_id'] not in oldgroups and (r['source_dataset'],r['thread_id']) not in oldthreads]
 groupmap={(r['source_dataset'],r['email_id']):r['snapshot_provenance']['leakage_group_id'] for r in rows}
 outer,_=grouped_train_validation_split(candidates,groupmap,validation_ratio=(.15*len(rows))/len(candidates),seed=SEED)
 assert {r['email_id'] for r in outer['validation']}==set(meta['partitions']['test']['email_ids'])
 remaining=[r for r in rows if owner[r['email_id']]!='test']
 inner,_=grouped_train_validation_split(remaining,groupmap,validation_ratio=(.15*len(rows))/len(remaining),seed=SEED+1)
 assert {r['email_id'] for r in inner['validation']}==set(meta['partitions']['dev']['email_ids'])
 pairs=json.loads((AI/'annotation/tonight_leakage_overrides.json').read_text(encoding='utf-8'))['pairs'];present=0
 for pair in pairs:
  if pair['left'] in owner and pair['right'] in owner:
   present+=1;assert owner[pair['left']]==owner[pair['right']]
 train=load_partition('train');folds=balanced_folds(train)
 assert [[train[i]['email_id'] for i in fold] for fold in folds]==meta['train_cv_validation_ids']
 assert [len(f) for f in folds]==meta['train_cv_record_counts']
 for fit,valid in cv_splits(train):
  owners={}
  for label,indices in [('fit',fit),('validation',valid)]:
   for i in indices:
    r=train[i]
    for key in [('thread',r['source_dataset'],r['thread_id']),('group',r['snapshot_provenance']['leakage_group_id'])]:
     assert key not in owners or owners[key]==label;owners[key]=label
 try:load_partition('test')
 except ValueError:pass
 else:raise AssertionError('development TEST guard missing')
 result={'verified':True,'benchmark_sha256':benchmark_hash(),'total_records':len(rows),'partition_counts':{k:v['records'] for k,v in meta['partitions'].items()},'known_nearcopy_pairs_checked':present,'all_known_pairs':len(pairs),'split_and_cv_reproduced':True,'test_text_or_errors_displayed':False,'development_test_guard_verified':True}
 (AI/'reports/optimization_benchmark_verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
