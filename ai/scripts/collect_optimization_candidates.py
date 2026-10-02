"""Normalize completed family finalists for the root-owned selection process."""
from __future__ import annotations
import sys,json
from pathlib import Path
import numpy as np
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.models.optimization_benchmark import DATA,LABEL_ORDER,benchmark_hash,load_partition,score_probabilities
from src.models.optimization_runtime import resolve

def write_json(path,data):path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8',newline='\n')
def metric_key(r):return (r['dev_metrics']['macro_f1'],r['dev_metrics']['micro_f1'])

def main():
 train,dev=load_partition('train'),load_partition('dev');out=DATA/'normalized';out.mkdir(exist_ok=True);candidates=[]
 reference=json.loads((AI/'reports/optimization_reference.json').read_text(encoding='utf-8'))['final_candidates'][0]
 candidates.append({**reference,'kind':'reference'})
 def add(spec,oo,dv):
  assert oo.shape==(len(train),9) and dv.shape==(len(dev),9)
  assert spec['benchmark_sha256']==benchmark_hash()
  actual=score_probabilities([r['labels'] for r in dev],dv,spec['thresholds'],spec['mode'],spec.get('fallback',False))
  for metric in ['micro_f1','macro_f1']:assert abs(actual[metric]-spec['dev_metrics'][metric])<1e-10,(spec['run_id'],metric)
  spec['dev_metrics']=actual
  np.save(out/(spec['run_id']+'_oof.npy'),oo);np.save(out/(spec['run_id']+'_dev.npy'),dv)
  spec['train_oof_probabilities_path']=str(out/(spec['run_id']+'_oof.npy'));spec['dev_probabilities_path']=str(out/(spec['run_id']+'_dev.npy'))
  candidates.append(spec)
 lexical_path=AI/'reports/optimization_lexical.json'
 if lexical_path.exists():
  r=json.loads(lexical_path.read_text(encoding='utf-8'));oof=np.load(AI/r['artifacts']['train_oof_probabilities']);dv=np.load(AI/r['artifacts']['dev_probabilities'])
  for run in r['runs']:
   if not run.get('model_artifact') or run['run_id'] not in oof.files:continue
   if run['run_id'].startswith('legacy_'):continue
   spec={**run,'kind':'lexical','model_path':str(AI/run['model_artifact']),'mode':run['task'],'fallback':False,'thresholds':[run['thresholds'][l] for l in LABEL_ORDER],'dev_metrics':run['dev'],'benchmark_sha256':r['benchmark_sha256'],'model_size_bytes':run['model_size_bytes'],'inference_seconds_per_record':(run.get('inference_time_ms_per_record') or 0)/1000}
   add(spec,oof[run['run_id']],dv[run['run_id']])
 ep=AI/'reports/optimization_embeddings.json'
 if ep.exists():
  r=json.loads(ep.read_text(encoding='utf-8'))
  if r.get('final_candidates'):
   for spec in r['final_candidates']:
    spec={**spec,'kind':'embeddings','benchmark_sha256':benchmark_hash()}
    add(spec,np.load(resolve(spec['train_oof_probabilities_path'])),np.load(resolve(spec['dev_probabilities_path'])))
  else:collect_legacy_embeddings(r,train,dev,add)
 tp=AI/'reports/optimization_transformer.json'
 if tp.exists():
  r=json.loads(tp.read_text(encoding='utf-8'))
  # Transformer agent publishes fully refitted OOF candidates here.
  for candidate in r.get('final_candidates',[]):
   spec=dict(candidate);spec.update({'kind':'transformer','benchmark_sha256':benchmark_hash()})
   add(spec,np.load(resolve(spec['train_oof_probabilities_path'])),np.load(resolve(spec['dev_probabilities_path'])))
 write_json(out/'all_candidates.json',candidates)
 print(json.dumps([{'run_id':s['run_id'],'kind':s['kind'],'dev_micro':s['dev_metrics']['micro_f1'],'dev_macro':s['dev_metrics']['macro_f1'],'mode':s['mode']} for s in candidates],indent=2))

def collect_legacy_embeddings(r,train,dev,add):
  dv=json.loads(Path(r['dev_probability_artifact']).read_text());oo=json.loads(Path(r['train_oof_probability_artifact']).read_text())
  assert dv['row_ids']==[x['email_id'] for x in dev] and oo['row_ids']==[x['email_id'] for x in train]
  for bundle in r['bundles']:
   b=json.loads(Path(bundle['bundle_path'],'bundle.json').read_text());name=bundle['bundle_name']
   if name=='per_label_specialists':
    selected=r['per_label_specialists'];heads=selected['selected_heads'];dp=np.column_stack([np.array(dv['probabilities'][h['selected_run_id']])[:,h['label_index']] for h in heads]);op=np.column_stack([np.array(oo['probabilities'][h['selected_run_id']])[:,h['label_index']] for h in heads]);run={**selected,'model':'frozen sentence encoder per-label specialist heads','features':heads,'training_records':len(train),'dev_records':len(dev),'seed':r['runtime'].get('seed',20261004),'loss':'component logloss/squared hinge','class_weighting':'per-label choices','hyperparameters':{'selected_heads':heads}}
   else:
    eligible=[run for run in r['runs'] if run['mode']==b['prediction_mode'] and run['oof_thresholds']==b['thresholds_train_oof_only']]
    if not eligible:continue
    run=max(eligible,key=metric_key);dp=np.array(dv['probabilities'][run['run_id']]);op=np.array(oo['probabilities'][run['run_id']])
   spec={**run,'kind':'embeddings','model_path':bundle['bundle_path'],'mode':b['prediction_mode'],'fallback':b.get('fallback',False),'threshold_method':'TRAIN grouped OOF binary F1','thresholds':[b['thresholds_train_oof_only'][l] for l in LABEL_ORDER],'dev_metrics':b['dev_metrics'],'benchmark_sha256':b['benchmark_sha256'],'model_size_bytes':bundle['package_size_bytes'],'inference_seconds_per_record':(run.get('estimated_end_to_end_ms_per_record') or 0)/1000}
   add(spec,op,dp)
if __name__=='__main__':main()
