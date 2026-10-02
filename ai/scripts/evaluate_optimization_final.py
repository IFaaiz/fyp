"""Root-only, one-pass TEST evaluation after immutable candidate selection."""
from __future__ import annotations
import sys,json,time,hashlib
from pathlib import Path
import numpy as np
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.models.optimization_benchmark import DATA,BENCHMARK,LABEL_ORDER,benchmark_hash,read_jsonl,score_probabilities,decode
from src.models.optimization_runtime import predict_candidate,resolve
from src.models.transfer_diagnostic import sha256_file,validate_snapshot

def artifact_files(path):
 path=resolve(path)
 files=[path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file())
 if not files:raise ValueError('empty or missing model bundle')
 mapping={(p.name if path.is_file() else p.relative_to(path).as_posix()):p for p in files}
 if path.is_dir() and (path/'bundle.json').is_file():
  metadata=json.loads((path/'bundle.json').read_text(encoding='utf-8'))
  encoders={spec['encoder_path'] for spec in metadata.get('feature_specs',{}).values() if spec.get('encoder_path')}
  if metadata.get('encoder_path'):encoders.add(metadata['encoder_path'])
  for encoder_path in sorted(encoders):
   external=(path/encoder_path).resolve()
   for p in sorted(external.rglob('*')):
    if p.is_file():mapping['encoder:'+encoder_path.replace('\\','/')+'/'+p.relative_to(external).as_posix()]=p
 return mapping

def artifact_hashes(path):return {name:sha256_file(p) for name,p in artifact_files(path).items()}

def candidate_files(spec):
 files=set(artifact_files(spec['model_path']).values())
 if spec['kind']=='ensemble':
  bundle=json.loads(resolve(spec['model_path']).read_text(encoding='utf-8'))
  for component in bundle['components']:files.update(candidate_files(component))
 return files

def main():
 selection=AI/'annotation/optimization_final_selection.json'
 locked=json.loads(selection.read_text(encoding='utf-8'))
 seal=json.loads((AI/'annotation/optimization_test_seal.json').read_text(encoding='utf-8'))
 report=AI/'reports/optimization_final_test.json';access=AI/'annotation/optimization_test_access.json'
 if report.exists() or access.exists():raise SystemExit('TEST evaluation already started/completed; refusing another evaluation')
 assert locked['benchmark_sha256']==benchmark_hash()==seal['benchmark_sha256_at_freeze']
 for relative,digest in locked['implementation_sha256'].items():assert sha256_file(AI.parent/relative)==digest,'prediction implementation changed after selection lock'
 candidates=locked['candidates'];assert 3<=len(candidates)<=5
 for spec in candidates:
  assert artifact_hashes(spec['model_path'])==spec['artifact_hashes']
  if spec['kind']=='ensemble':
   bundle=json.loads(resolve(spec['model_path']).read_text(encoding='utf-8'))
   for component in bundle['components']:assert artifact_hashes(component['model_path'])==component['artifact_hashes']
 test_path=DATA/'test.jsonl';assert sha256_file(test_path)==seal['test']['file_sha256']
 access.write_text(json.dumps({'selection_sha256':sha256_file(selection),'benchmark_sha256':benchmark_hash(),'test_sha256':sha256_file(test_path),'status':'one-pass evaluation started; no subsequent tuning allowed','candidate_ids':[s['run_id'] for s in candidates]},indent=2)+'\n',encoding='utf-8',newline='\n')
 rows=read_jsonl(test_path);validate_snapshot(rows,[r['snapshot_provenance'] for r in rows]);assert [r['email_id'] for r in rows]==seal['test']['email_ids']
 expected=[r['labels'] for r in rows];out=DATA/'final_test';out.mkdir(exist_ok=True);results=[]
 for spec in candidates:
  started=time.perf_counter();prob=predict_candidate(spec,rows);seconds=time.perf_counter()-started
  metrics=score_probabilities(expected,prob,spec['thresholds'],mode=spec['mode'],fallback=spec.get('fallback',False))
  np.save(out/(spec['run_id']+'.npy'),prob)
  predictions=decode(prob,spec['thresholds'],mode=spec['mode'],fallback=spec.get('fallback',False))
  result={'run_id':spec['run_id'],'kind':spec['kind'],'test_metrics':metrics,'inference_seconds_with_cold_model_load':seconds,'inference_seconds_per_record_with_cold_load':seconds/len(rows),'thresholds':spec['thresholds'],'mode':spec['mode'],'prediction_sha256':sha256_file(out/(spec['run_id']+'.npy'))}
  results.append(result)
  # Errors saved as text-free IDs/labels; actual source reading starts only
  # after all locked candidates have been evaluated and the report exists.
  errors=[{'email_id':r['email_id'],'expected_labels':r['labels'],'predicted_labels':p} for r,p in zip(rows,predictions) if set(r['labels'])!=set(p)]
  (out/(spec['run_id']+'_errors.json')).write_text(json.dumps(errors,indent=2)+'\n',encoding='utf-8')
  print(json.dumps({'run_id':spec['run_id'],'test_micro_f1':metrics['micro_f1'],'test_macro_f1':metrics['macro_f1'],'test_exact_set_accuracy':metrics['exact_set_accuracy']}),flush=True)
 result={'metric_provenance':'AI-SILVER DIAGNOSTIC PERFORMANCE; ZERO human classification labels','selection_sha256':sha256_file(selection),'benchmark_sha256':benchmark_hash(),'test_sha256':sha256_file(test_path),'test_records':len(rows),'evaluation_policy':'exactly one evaluation per prelocked candidate; no TEST-based retuning or label changes','dev_selected_primary_run_id':locked['primary_run_id'],'results':results}
 report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
 marker=json.loads(access.read_text(encoding='utf-8'));marker['status']='completed; no subsequent tuning allowed';marker['result_sha256']=sha256_file(report)
 access.write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8',newline='\n')

if __name__=='__main__':main()
