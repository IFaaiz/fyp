"""Strict committee pseudo-silver screening; never use held-out labels."""
from __future__ import annotations
import sys,json,argparse,hashlib,re,time
from pathlib import Path
from collections import Counter
import numpy as np
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.models.optimization_benchmark import DATA,LABEL_ORDER,read_jsonl,decode,benchmark_hash
from src.models.optimization_runtime import predict_candidate
from src.models.silver_classifier import extract_authored_prefix
from src.models.transfer_diagnostic import sha256_file

def normalized(text):return ' '.join(re.findall(r'[a-z0-9]+',text.lower()))

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--components',type=Path,required=True);args=parser.parse_args()
 specs=json.loads(args.components.read_text(encoding='utf-8'));assert len(specs)==3
 assert {s['kind'] for s in specs}=={'lexical','embeddings','transformer'}
 if not any(s['dev_metrics']['macro_f1']>=.45 for s in specs):raise SystemExit('Strong initial DEV macro criterion .45 not met; pseudo expansion deferred')
 started=time.perf_counter();out=DATA/'pseudo';out.mkdir(exist_ok=True)
 report=AI/'reports/optimization_pseudo_screen.json'
 if report.exists():raise SystemExit('Pseudo screen already completed; refusing a new confidence search')
 source=AI/'data/interim/enron_candidates.jsonl';sidecar=AI/'data/interim/leakage_groups.jsonl'
 pool=read_jsonl(source)
 # Automated exclusion consults source identities/text, never held-out labels
 # or predictions. Protect every benchmark partition and all known audits.
 protected=read_jsonl(AI/'data/experiments/tonight_20261002/next_training_silver_snapshot.jsonl')
 protected_ids={r['email_id'] for r in protected};protected_threads={(r['source_dataset'],r['thread_id']) for r in protected}
 wanted={r['email_id'] for r in pool}|protected_ids;global_groups={}
 with sidecar.open(encoding='utf-8') as stream:
  for line in stream:
   r=json.loads(line)
   if r['email_id'] in wanted:global_groups[r['email_id']]=r['leakage_group_id']
 assert wanted<=set(global_groups),'global group coverage missing'
 protected_groups={global_groups[id] for id in protected_ids}
 audit_ids=set(protected_ids)
 for path in (AI/'annotation').glob('tonight*decisions*.jsonl'):
  audit_ids.update(r['email_id'] for r in read_jsonl(path) if 'email_id' in r)
 counts=Counter();filtered=[];seen=set();protected_normal={normalized(r['authored_message']) for r in protected}
 for r in pool:
  if r['email_id'] in audit_ids:counts['previously_audited_or_benchmark']+=1;continue
  if global_groups[r['email_id']] in protected_groups or (r['source_dataset'],r['thread_id']) in protected_threads:counts['protected_group_or_thread']+=1;continue
  if r.get('labels'):counts['already_labelled']+=1;continue
  r=dict(r);r['authored_message']=extract_authored_prefix(str(r.get('current_message') or ''))
  n=normalized(r['authored_message'])
  if len(n)<30:counts['too_short_or_empty']+=1;continue
  if n in protected_normal or n in seen:counts['exact_normalized_duplicate']+=1;continue
  seen.add(n);filtered.append(r)
 # Conservative word-unigram/bigram copy exclusion against all668 sources,
 # including DEV/TEST. This vocabulary is used only for duplicate filtering.
 from sklearn.feature_extraction.text import TfidfVectorizer
 vectorizer=TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True,dtype=np.float32)
 docs=[normalized(r['authored_message']) for r in protected]+[normalized(r['authored_message']) for r in filtered]
 matrix=vectorizer.fit_transform(docs);reference=matrix[:len(protected)];candidate=matrix[len(protected):]
 max_cosine=np.asarray((candidate@reference.T).max(axis=1).toarray()).reshape(-1)
 safe=[r for r,sim in zip(filtered,max_cosine) if sim<.85];counts['nearcopy_cosine_ge_085']=len(filtered)-len(safe)
 (out/'isolated_candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in safe),encoding='utf-8',newline='\n')
 predictions=[];probabilities=[]
 for spec in specs:
  p=predict_candidate(spec,safe);np.save(out/(spec['kind']+'_probabilities.npy'),p)
  probabilities.append(p);predictions.append(decode(p,spec['thresholds'],spec['mode'],spec.get('fallback',False)))
  print(f"Committee {spec['kind']} scored {len(safe)} isolated candidates",flush=True)
 accepted=[];support=Counter();rare={'REPORT_REQUEST','DEPARTMENTAL_INPUT','FOLLOW_UP','APPROVAL'}
 quotas={'NON_PROJECT':200,'GENERAL_UPDATE':200,'MEETING':150,'DEADLINE':100,'ACTION_REQUEST':150,**{l:50 for l in rare}}
 choices=[]
 for i,r in enumerate(safe):
  labs=predictions[0][i]
  if not labs or any(set(p[i])!=set(labs) for p in predictions[1:]):counts['committee_disagreement_or_empty']+=1;continue
  accepted_prob=True;min_score=1.
  for spec,p in zip(specs,probabilities):
   if labs==['NON_PROJECT']:
    strong=p[i,8]>=.90 and max(p[i,:8])<=.25;min_score=min(min_score,float(p[i,8]))
   else:
    strong=p[i,8]<=.20
    for label in labs:
     j=LABEL_ORDER.index(label);required=.85 if label in rare else .75
     strong=strong and p[i,j]>=max(required,float(spec['thresholds'][j])+.10);min_score=min(min_score,float(p[i,j]))
   accepted_prob=accepted_prob and strong
  if not accepted_prob:counts['insufficient_absolute_score_margin_or_scope']+=1;continue
  choices.append((min_score,r['email_id'],i,labs))
 for confidence,_,i,labs in sorted(choices,reverse=True):
  if len(accepted)>=1000:break
  if any(support[l]>=quotas[l] for l in labs):counts['label_quota_exceeded']+=1;continue
  r=dict(safe[i]);r['labels']=labs;r['pseudo_provenance']={'method':'three-model exact label-set agreement; strict absolute scores/margins; these scores are not guaranteed calibrated confidence','component_run_ids':[s['run_id'] for s in specs],'benchmark_sha256':benchmark_hash(),'source_sha256':hashlib.sha256((r['subject']+'\n'+r['current_message']).encode()).hexdigest(),'classification_status':'AI_PSEUDO_SILVER; no human labels','global_leakage_group_id':global_groups[r['email_id']]}
  accepted.append(r);support.update(labs)
 path=out/'strict_pseudo_candidates.jsonl';path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in accepted),encoding='utf-8',newline='\n')
 result={'metric_provenance':'AI/PSEUDO-SILVER; zero human/gold labels','benchmark_sha256':benchmark_hash(),'component_run_ids':[s['run_id'] for s in specs],'pool_records':len(pool),'isolated_scored_records':len(safe),'accepted_records':len(accepted),'accepted_label_support':dict(support),'label_caps':quotas,'exclusion_counts':dict(counts),'strict_project_score_floor':.75,'strict_rare_score_floor':.85,'NP_score_floor':.90,'nearcopy_max_cosine':.85,'protected_partitions':'allTRAIN/DEV/TEST groups, threads, exact/near copies excluded; labels/predictions not used for exclusion','test_predictions_inspected':False,'source_pool_sha256':sha256_file(source),'group_sidecar_sha256':sha256_file(sidecar),'pseudo_candidate_sha256':sha256_file(path),'elapsed_seconds':time.perf_counter()-started,'target_500_to_1000_met':len(accepted)>=500,'added_to_frozen_benchmark':False,'training_expansion_performed':False,'interpretation':'screened candidates only; no lowered score thresholds or relaxed quotas to manufacture500 rows; no automatic merge into audited silver'}
 report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
