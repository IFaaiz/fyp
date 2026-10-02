"""Root DEV preflight and immutable selection lock before any TEST inference."""
from __future__ import annotations
import sys,json,time
from pathlib import Path
import numpy as np
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI));sys.path.insert(0,str(AI/'scripts'))
from src.models.optimization_benchmark import DATA,BENCHMARK,load_partition,benchmark_hash,score_probabilities,decode
from src.models.optimization_runtime import predict_candidate,resolve
from src.models.transfer_diagnostic import sha256_file
from evaluate_optimization_final import artifact_hashes,candidate_files

def key(spec):return spec['dev_metrics']['macro_f1'],spec['dev_metrics']['micro_f1']
def main():
 path=AI/'annotation/optimization_final_selection.json'
 if path.exists():raise SystemExit('Selection already locked; refusing overwrite')
 pool=json.loads((DATA/'normalized/all_candidates.json').read_text(encoding='utf-8'))
 ensemble=json.loads((AI/'reports/optimization_ensemble.json').read_text(encoding='utf-8'))
 selected=[next(s for s in pool if s['kind']=='reference')]
 for kind in ['lexical','embeddings','transformer']:selected.append(max((s for s in pool if s['kind']==kind),key=key))
 selected.append(max(ensemble['final_candidates'],key=key))
 # Hash every ensemble dependency before freezing the enclosing JSON bundle.
 for spec in selected:
  if spec['kind']=='ensemble':
   bundlepath=resolve(spec['model_path']);bundle=json.loads(bundlepath.read_text(encoding='utf-8'))
   for component in bundle['components']:component['artifact_hashes']=artifact_hashes(component['model_path'])
   bundlepath.write_text(json.dumps(bundle,indent=2)+'\n',encoding='utf-8',newline='\n')
   spec['model_sha256']=sha256_file(bundlepath)
 dev=load_partition('dev');expected=[r['labels'] for r in dev];preflight=[]
 for spec in selected:
  hashes=artifact_hashes(spec['model_path']);started=time.perf_counter();actual=predict_candidate(spec,dev);seconds=time.perf_counter()-started
  saved=np.load(resolve(spec['dev_probabilities_path']));error=float(np.max(np.abs(saved-actual)))
  assert np.allclose(actual,saved,atol=1e-5,rtol=1e-5),(spec['run_id'],error)
  assert decode(actual,spec['thresholds'],spec['mode'],spec.get('fallback',False))==decode(saved,spec['thresholds'],spec['mode'],spec.get('fallback',False)),'reload changes DEV label sets'
  metrics=score_probabilities(expected,actual,spec['thresholds'],spec['mode'],spec.get('fallback',False))
  for m in ['macro_f1','micro_f1','exact_set_accuracy','hamming_loss']:assert abs(metrics[m]-spec['dev_metrics'][m])<1e-12,(spec['run_id'],m)
  assert hashes==artifact_hashes(spec['model_path']),'bundle mutated during preflight'
  spec['artifact_hashes']=hashes;spec['dev_metrics']=metrics
  spec['model_size_bytes']=sum(p.stat().st_size for p in candidate_files(spec));spec['size_definition']='unique referenced model/head/config/tokenizer/bundle files; shared encoder counted once'
  spec['dev_reload_seconds_with_cold_model_load']=seconds;spec['dev_reload_seconds_per_record_with_cold_load']=seconds/len(dev)
  preflight.append({'run_id':spec['run_id'],'max_probability_reload_error':error,'decoded_DEV_labels_exactly_match':True,'DEV_metrics_personally_recomputed':True,'cold_load_inference_seconds_per_record':seconds/len(dev)})
  print(json.dumps(preflight[-1]),flush=True)
 primary=max(selected,key=key)
 implementations=['ai/src/models/'+name for name in ['optimization_runtime.py','optimization_benchmark.py','optimization_lexical.py','optimization_embeddings.py','optimization_transformer.py','silver_classifier.py','transfer_diagnostic.py']]+['ai/src/datasets/cleaning.py','ai/src/datasets/schemas.py']
 locked={'metric_provenance':'AI-SILVER DIAGNOSTIC PERFORMANCE; ZERO human classification labels','status':'Final selection locked before any TEST predictions/error inspection','benchmark_sha256':benchmark_hash(),'test_seal_sha256':sha256_file(AI/'annotation/optimization_test_seal.json'),'selection_criterion':'highest DEV macro F1, micro F1 secondary; original reference plus one best candidate per lexical/frozen-transfer/transformer family and one finite-grid ensemble; five materially different systems','primary_run_id':primary['run_id'],'reference_run_id':selected[0]['run_id'],'candidates':selected,'root_dev_preflight':preflight,'implementation_sha256':{p:sha256_file(AI.parent/p) for p in implementations},'threshold_source':'TRAIN grouped OOF only; no final DEV threshold tuning','test_predictions_or_errors_inspected':False,'no_training_on_dev_or_test':True,'future_test_rule':'evaluate each frozen candidate exactly once; preserve membership, labels, thresholds, weights, and selection after TEST'}
 path.write_text(json.dumps(locked,indent=2)+'\n',encoding='utf-8',newline='\n')
 (AI/'reports/optimization_dev_preflight.json').write_text(json.dumps({'benchmark_sha256':benchmark_hash(),'primary_run_id':primary['run_id'],'candidates':preflight,'selection_sha256':sha256_file(path)},indent=2)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps({'locked':True,'primary':primary['run_id'],'selection_sha256':sha256_file(path),'TEST_evaluated':False}),flush=True)

if __name__=='__main__':main()
