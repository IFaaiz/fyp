"""Finite DEV-only blending and specialists with frozen TRAIN OOF thresholds."""
from __future__ import annotations
import sys,json,time,itertools,argparse
from pathlib import Path
import numpy as np
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.models.optimization_benchmark import DATA,SEED,LABEL_ORDER,benchmark_hash,load_partition,oof_thresholds,score_probabilities
from src.models.optimization_runtime import marginal_probabilities,resolve
from src.models.transfer_diagnostic import sha256_file

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--components',required=True);args=parser.parse_args()
 specs=json.loads(Path(args.components).read_text(encoding='utf-8'));assert 2<=len(specs)<=4
 report=AI/'reports/optimization_ensemble.json'
 if report.exists():raise SystemExit('Ensemble already measured; refusing overwrite')
 train,dev=load_partition('train'),load_partition('dev');y=[r['labels'] for r in train];yd=[r['labels'] for r in dev]
 arrays=[]
 for spec in specs:
  assert spec['benchmark_sha256']==benchmark_hash()
  oo=np.load(resolve(spec['train_oof_probabilities_path']));dv=np.load(resolve(spec['dev_probabilities_path']))
  assert oo.shape==(len(train),9) and dv.shape==(len(dev),9)
  arrays.append((marginal_probabilities(oo,spec['mode']),marginal_probabilities(dv,spec['mode'])))
 out=DATA/'ensemble';out.mkdir(exist_ok=True);modeldir=AI/'data/models/optimization/ensemble';modeldir.mkdir(parents=True,exist_ok=True)
 runs=[];matrices={};started=time.perf_counter()
 def measure(id,oo,dv,config,mode='flat'):
  run_started=time.perf_counter()
  t,details=oof_thresholds(y,oo,mode=mode);metrics=score_probabilities(yd,dv,t,mode=mode)
  run={'run_id':id,'kind':'ensemble','model':'probability blend' if config['method']=='blend' else 'cross-family per-label specialists','features':'component marginal probabilities; conditional hierarchy functions multiplied by PROJECT probability before blending','training_records':len(train),'dev_records':len(dev),'seed':SEED,'hyperparameters':config,'loss':'component binary losses; no ensemble parameter gradients','class_weighting':'component-specific','threshold_method':'binary F1 from TRAIN grouped OOF; weights/config selected on DEV','thresholds':t,'threshold_details':details,'mode':'flat','fallback':False,'dev_metrics':metrics,'benchmark_sha256':benchmark_hash(),'training_seconds':time.perf_counter()-started,'inference_seconds_per_record':None,'model_size_bytes':None}
  run['mode']=mode;run['training_seconds']=time.perf_counter()-run_started
  if mode=='scope_gated':run['features']+='; scope-first output gate; function heads retain original training populations and marginal scores'
  runs.append(run);matrices[id]=(oo,dv)
 # Fixed finite quarter-step simplex; no expansion based on DEV outcomes.
 for weights in itertools.product(range(5),repeat=len(specs)):
  if sum(weights)!=4 or sum(w>0 for w in weights)<2:continue
  ws=[w/4 for w in weights];id='ensemble_blend_'+'_'.join(map(str,weights))
  oo=sum(w*a[0] for w,a in zip(ws,arrays));dv=sum(w*a[1] for w,a in zip(ws,arrays))
  config={'method':'blend','weights':ws,'component_run_ids':[s['run_id'] for s in specs]}
  measure(id,oo,dv,config)
  measure(id+'_scope_gate',oo,dv,config,mode='scope_gated')
 # Choose each label from the same finite family pool using DEV binary F1;
 # every component's threshold comes exclusively from TRAIN OOF.
 component_metrics=[]
 for oo,dv in arrays:
  t,_=oof_thresholds(y,oo);component_metrics.append(score_probabilities(yd,dv,t))
 sources=[]
 for label in LABEL_ORDER:
  sources.append(max(range(len(specs)),key=lambda k:(component_metrics[k]['per_label'][label]['f1'],component_metrics[k]['per_label'][label]['precision'],-k)))
 oo=np.column_stack([arrays[k][0][:,j] for j,k in enumerate(sources)]);dv=np.column_stack([arrays[k][1][:,j] for j,k in enumerate(sources)])
 config={'method':'specialists','label_sources':sources,'component_run_ids':[s['run_id'] for s in specs]}
 measure('ensemble_label_specialists',oo,dv,config)
 measure('ensemble_label_specialists_scope_gate',oo,dv,config,mode='scope_gated')
 finalists=[max((r for r in runs if r['hyperparameters']['method']=='blend'),key=lambda r:(r['dev_metrics']['macro_f1'],r['dev_metrics']['micro_f1'])),max((r for r in runs if r['hyperparameters']['method']=='specialists'),key=lambda r:(r['dev_metrics']['macro_f1'],r['dev_metrics']['micro_f1']))]
 for run in finalists:
  id=run['run_id'];config=run['hyperparameters']
  used=[k for k,w in enumerate(config['weights']) if w>0] if config['method']=='blend' else sorted(set(config['label_sources']))
  active=[specs[k] for k in used]
  bundle={**config,'components':active,'benchmark_sha256':benchmark_hash()}
  if config['method']=='blend':bundle['weights']=[config['weights'][k] for k in used]
  else:bundle['label_sources']=[used.index(k) for k in config['label_sources']]
  path=modeldir/(id+'.json');path.write_text(json.dumps(bundle,indent=2)+'\n',encoding='utf-8',newline='\n')
  oo,dv=matrices[id];np.save(out/(id+'_oof.npy'),oo);np.save(out/(id+'_dev.npy'),dv)
  run.update({'model_path':str(path),'model_sha256':sha256_file(path),'train_oof_probabilities_path':str(out/(id+'_oof.npy')),'dev_probabilities_path':str(out/(id+'_dev.npy')),'model_size_bytes':path.stat().st_size+sum(s['model_size_bytes'] for s in active),'inference_seconds_per_record':sum(s.get('inference_seconds_per_record') or 0 for s in active)})
 result={'metric_provenance':'AI-SILVER DIAGNOSTIC PERFORMANCE; zero human/gold labels','benchmark_sha256':benchmark_hash(),'finite_blend_grid':'quarter-step simplex, >=2 nonzero component weights; each evaluated with flat exclusivity and scope-first gate; gate functions use original marginal scores and PROJECT TRAIN OOF threshold calibration','development_selection_warning':'label specialists and weights selected on 104 DEV records; rare DEV supports 1-3, potentially high selection variance','runs':runs,'final_candidates':finalists,'test_access':False}
 report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps([{'run_id':r['run_id'],'dev_micro':r['dev_metrics']['micro_f1'],'dev_macro':r['dev_metrics']['macro_f1']} for r in finalists],indent=2))

if __name__=='__main__':main()
