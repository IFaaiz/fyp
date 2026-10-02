"""Shared frozen development benchmark. Test access belongs to the final evaluator."""
from __future__ import annotations
import hashlib,json,random
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
from .silver_classifier import LABEL_ORDER
from .transfer_diagnostic import validate_snapshot,sha256_file,full_diagnostic_metrics,exclusive_predictions,tune_thresholds,record_text
AI=Path(__file__).resolve().parents[2]
DATA=AI/'data/experiments/optimization_20261002'
BENCHMARK=AI/'annotation/optimization_benchmark.json'
SEED=20261004
PROJECT_LABELS=LABEL_ORDER[:-1]
def read_jsonl(path):return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]
def load_partition(name):
 if name not in ('train','dev'):raise ValueError('TEST is sealed; only root final evaluator may load it after selection lock')
 meta=json.loads(BENCHMARK.read_text(encoding='utf-8'));path=DATA/(name+'.jsonl')
 if sha256_file(path)!=meta['partitions'][name]['file_sha256']:raise ValueError('benchmark partition drift')
 rows=read_jsonl(path);validate_snapshot(rows,[r['snapshot_provenance'] for r in rows])
 if [r['email_id'] for r in rows]!=meta['partitions'][name]['email_ids']:raise ValueError('benchmark ID drift')
 return rows

def group_components(rows):
 parent=list(range(len(rows)))
 def find(x):
  while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
  return x
 def union(x,y):parent[find(y)]=find(x)
 seen={}
 for i,r in enumerate(rows):
  for key in [('thread',r['source_dataset'],r['thread_id']),('group',r['snapshot_provenance']['leakage_group_id'])]:
   if key in seen:union(i,seen[key])
   else:seen[key]=i
 out=defaultdict(list)
 for i in range(len(rows)):out[find(i)].append(i)
 return list(out.values())

def balanced_folds(rows,n=5,seed=SEED):
 comps=group_components(rows);support=Counter(l for r in rows for l in r['labels']);rng=random.Random(seed)
 profiles=[(ids,Counter(l for i in ids for l in rows[i]['labels'])) for ids in comps];rng.shuffle(profiles)
 profiles.sort(key=lambda pair:sum(v/max(support[l],1) for l,v in pair[1].items()),reverse=True)
 sizes=[0]*n;counts=[Counter() for _ in range(n)];folds=[[] for _ in range(n)]
 for ids,ls in profiles:
  def cost(k):
   size_cost=((sizes[k]+len(ids)-len(rows)/n)/max(len(rows)/n,1))**2-((sizes[k]-len(rows)/n)/max(len(rows)/n,1))**2
   label_cost=sum(((counts[k][l]+ls[l]-support[l]/n)/max(support[l]/n,1))**2-((counts[k][l]-support[l]/n)/max(support[l]/n,1))**2 for l in LABEL_ORDER)
   return label_cost+size_cost
  k=min(range(n),key=lambda k:(cost(k),sizes[k],k));folds[k].extend(ids);sizes[k]+=len(ids);counts[k].update(ls)
 return [sorted(f) for f in folds]

def cv_splits(rows):
 meta=json.loads(BENCHMARK.read_text(encoding='utf-8'));ids=[r['email_id'] for r in rows]
 if ids!=meta['partitions']['train']['email_ids']:raise ValueError('OOF requires exact frozen TRAIN rows/order')
 lookup={id:i for i,id in enumerate(ids)};all_indices=set(range(len(rows)))
 return [(np.array(sorted(all_indices-set(lookup[id] for id in fold)),dtype=int),np.array([lookup[id] for id in fold],dtype=int)) for fold in meta['train_cv_validation_ids']]

def targets(rows):return np.array([[int(l in r['labels']) for l in LABEL_ORDER] for r in rows],dtype=np.int64)
def texts(rows,view='subject_body'):
 if view=='body':return [r['authored_message'] for r in rows]
 if view=='subject':return [r['subject'] for r in rows]
 if view=='subject_twice':return [f"[SUBJECT] {r['subject']} {r['subject']}\n[BODY] {r['authored_message']}" for r in rows]
 if view!='subject_body':raise ValueError('unknown text view')
 return [record_text(r) for r in rows]

def decode(probabilities,thresholds=None,mode='flat',fallback=False):
 p=np.asarray(probabilities,dtype=float);t=np.full(9,.5) if thresholds is None else np.asarray(thresholds,dtype=float)
 if p.ndim!=2 or p.shape[1]!=9 or t.shape!=(9,) or not np.isfinite(p).all():raise ValueError('finite Nx9 probabilities and9thresholds required')
 if mode=='flat':return exclusive_predictions(p.tolist(),t.tolist())
 if mode not in ('hierarchical','scope_gated'):raise ValueError('unknown prediction mode')
 out=[]
 for row in p:
  if row[8]>=t[8]:out.append(['NON_PROJECT']);continue
  labs=[l for j,l in enumerate(PROJECT_LABELS) if row[j]>=t[j]]
  if not labs and fallback:labs=[PROJECT_LABELS[int(np.argmax(row[:8]))]]
  out.append(labs)
 return out

def score_probabilities(expected_labels,probabilities,thresholds=None,mode='flat',fallback=False):
 predicted=decode(probabilities,thresholds,mode,fallback)
 metrics=full_diagnostic_metrics(expected_labels,predicted)
 from sklearn.metrics import accuracy_score,precision_recall_fscore_support
 true_scope=np.array(['NON_PROJECT' not in labs for labs in expected_labels],dtype=int)
 if mode in ('hierarchical','scope_gated'):
  scope_threshold=.5 if thresholds is None else thresholds[8]
  pred_scope=(np.asarray(probabilities)[:,8]<scope_threshold).astype(int)
 else:pred_scope=np.array(['NON_PROJECT' not in labs for labs in predicted],dtype=int)
 precision,recall,f1,support=precision_recall_fscore_support(true_scope,pred_scope,labels=[0,1],zero_division=0)
 metrics['scope_classification']={'definition':'binary scope gate for hierarchy/scope_gated; NON_PROJECT versus otherwise decoded output for flat','accuracy':float(accuracy_score(true_scope,pred_scope)),'project_precision':float(precision[1]),'project_recall':float(recall[1]),'project_f1':float(f1[1]),'non_project_f1':float(f1[0]),'unassigned_records':sum(not labs for labs in predicted)}
 metrics['project_function_macro_f1']=sum(metrics['per_label'][l]['f1'] for l in PROJECT_LABELS)/8
 metrics['specific_function_macro_f1']=sum(metrics['per_label'][l]['f1'] for l in PROJECT_LABELS if l!='GENERAL_UPDATE')/7
 return metrics

def oof_thresholds(expected_labels,probabilities,mode='flat'):
 p=np.asarray(probabilities,dtype=float)
 if mode=='flat':return tune_thresholds(expected_labels,p.tolist())
 if mode not in ('hierarchical','scope_gated'):raise ValueError('unknown threshold mode')
 project=np.array(['NON_PROJECT' not in labels for labels in expected_labels]);t,details=tune_thresholds([expected_labels[i] for i in range(len(project)) if project[i]],p[project].tolist())
 # Scope calibration uses every TRAIN OOF record; function calibration uses PROJECT TRAIN OOF only.
 scope_expected=[['NON_PROJECT'] if not flag else ['GENERAL_UPDATE'] for flag in project]
 st,sd=tune_thresholds(scope_expected,p.tolist());t[8]=st[8];details['NON_PROJECT']=sd['NON_PROJECT'];return t,details

def benchmark_hash():return sha256_file(BENCHMARK)
