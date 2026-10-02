"""Independent final metric check and paired bootstrap after TEST evaluation."""
from __future__ import annotations
import sys,json
from pathlib import Path
import numpy as np
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.models.optimization_benchmark import DATA,LABEL_ORDER,SEED,read_jsonl,decode,targets
from src.models.transfer_diagnostic import sha256_file

def main():
 from sklearn.metrics import precision_recall_fscore_support,accuracy_score,hamming_loss
 selection_path=AI/'annotation/optimization_final_selection.json';selection=json.loads(selection_path.read_text(encoding='utf-8'))
 result=json.loads((AI/'reports/optimization_final_test.json').read_text(encoding='utf-8'))
 assert result['selection_sha256']==sha256_file(selection_path)
 rows=read_jsonl(DATA/'test.jsonl');y=targets(rows);predictions={};verified=[]
 for spec in selection['candidates']:
  measured=next(r for r in result['results'] if r['run_id']==spec['run_id'])
  path=DATA/'final_test'/(spec['run_id']+'.npy');assert sha256_file(path)==measured['prediction_sha256']
  p=np.load(path);labs=decode(p,spec['thresholds'],spec['mode'],spec.get('fallback',False));hat=np.array([[int(l in ls) for l in LABEL_ORDER] for ls in labs]);predictions[spec['run_id']]=hat
  m=measured['test_metrics']
  for average in ['micro','macro']:
   pr,re,f,_=precision_recall_fscore_support(y,hat,average=average,zero_division=0)
   for key,val in [(average+'_precision',pr),(average+'_recall',re),(average+'_f1',f)]:assert abs(m[key]-val)<1e-12,(key,m[key],val)
  assert abs(m['exact_set_accuracy']-accuracy_score(y,hat))<1e-12
  assert abs(m['hamming_loss']-hamming_loss(y,hat))<1e-12
  pr,re,f,support=precision_recall_fscore_support(y,hat,average=None,zero_division=0)
  for j,l in enumerate(LABEL_ORDER):
   row=m['per_label'][l]
   for key,val in [('precision',pr[j]),('recall',re[j]),('f1',f[j]),('support',support[j]),('predicted',hat[:,j].sum())]:assert abs(row[key]-val)<1e-12,(l,key,row[key],val)
  verified.append(spec['run_id'])
 primary=selection['primary_run_id'];reference=selection['reference_run_id'];rng=np.random.default_rng(SEED)
 def f1(indices,hat):
  actual=y[indices];guess=hat[indices];tp=(actual*guess).sum(axis=0);fp=((1-actual)*guess).sum(axis=0);fn=(actual*(1-guess)).sum(axis=0)
  denom=2*tp+fp+fn;macro=np.divide(2*tp,denom,out=np.zeros(9,dtype=float),where=denom>0).mean();micro=2*tp.sum()/denom.sum() if denom.sum() else 0.
  return np.array([micro,macro])
 bootstrap=[]
 for _ in range(2000):
  indices=rng.integers(0,len(rows),len(rows));bootstrap.append(f1(indices,predictions[primary])-f1(indices,predictions[reference]))
 boot=np.array(bootstrap);interval=np.quantile(boot,[.025,.975],axis=0)
 report={'verified_with_independent_sklearn_metrics':verified,'test_records':len(rows),'test_group_count':len({r['snapshot_provenance']['leakage_group_id'] for r in rows}),'per_label_precision_recall_f1_support_predicted_verified':True,'primary_dev_selected_run_id':primary,'reference_run_id':reference,'paired_bootstrap':{'resamples':2000,'seed':SEED,'unit':'record; all102 TEST rows have distinct frozen thread/leakage components','fixed_9_label_macro_with_absent_resampled_support_zero_f1':True,'delta_micro_f1_95_percentile_interval':interval[:,0].tolist(),'delta_macro_f1_95_percentile_interval':interval[:,1].tolist(),'limitation':'small AI-silver TEST and1-3 rare positives; this bootstrap does not measure human accuracy or annotation bias'},'no_test_based_model_changes':True}
 (AI/'reports/optimization_final_verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
