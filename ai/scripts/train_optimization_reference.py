"""Replicate the original TF-IDF method on the new sealed benchmark."""
from __future__ import annotations
import sys,json,time
from pathlib import Path
import numpy as np
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.models.optimization_benchmark import load_partition,cv_splits,LABEL_ORDER,DATA,SEED,benchmark_hash,oof_thresholds,score_probabilities
from src.models.silver_classifier import TfidfOneVsRestLogisticRegression
from src.models.transfer_diagnostic import sha256_file

def predict(model_path,rows):
 model=TfidfOneVsRestLogisticRegression.load(model_path)
 return probabilities(model,rows)

def probabilities(model,rows):
 return np.array([[p[l] for l in LABEL_ORDER] for p in (model.predict_proba(r) for r in rows)])

def main():
 train,dev=load_partition('train'),load_partition('dev');out=DATA/'reference';out.mkdir(exist_ok=True)
 report=AI/'reports/optimization_reference.json'
 if report.exists():raise SystemExit('Reference already measured; refusing overwrite')
 started=time.perf_counter();oof=np.zeros((len(train),9))
 def fresh():return TfidfOneVsRestLogisticRegression(optimizer='sklearn',c=1,max_iter=1000,seed=SEED)
 for k,(fit,valid) in enumerate(cv_splits(train)):
  model=fresh().fit([train[i] for i in fit])
  oof[valid]=probabilities(model,[train[i] for i in valid])
  print(f'Reference OOF fold {k+1}/5 complete',flush=True)
 thresholds,details=oof_thresholds([r['labels'] for r in train],oof)
 model=fresh().fit(train);seconds=time.perf_counter()-started
 path=AI/'data/models/optimization/reference/model.json';model.save(path)
 started=time.perf_counter();prob=probabilities(model,dev);latency=(time.perf_counter()-started)/len(dev)
 restored=predict(path,dev);assert np.allclose(prob,restored,atol=1e-12)
 np.save(out/'train_oof.npy',oof);np.save(out/'dev.npy',prob)
 common={'model':'original custom word+bigram TF-IDF OVR logistic regression','features':'separate subject/body token namespace; sublinear TF; smoothed IDF; L2 normalization','training_records':len(train),'dev_records':len(dev),'seed':SEED,'hyperparameters':{'C':1,'solver':'lbfgs','max_iter':1000,'tolerance':1e-5},'loss':'binary cross entropy with L2','class_weighting':'none','training_seconds_including_oof':seconds,'inference_seconds_per_record':latency,'model_size_bytes':path.stat().st_size,'model_path':str(path),'model_sha256':sha256_file(path),'mode':'flat','fallback':False,'dev_probabilities_path':str(out/'dev.npy'),'train_oof_probabilities_path':str(out/'train_oof.npy'),'benchmark_sha256':benchmark_hash()}
 runs=[]
 for name,t in [('fixed_05',[.5]*9),('train_oof',thresholds)]:
  runs.append({**common,'run_id':'reference_original_tfidf_'+name,'threshold_method':name,'thresholds':t,'threshold_details':details if name=='train_oof' else None,'dev_metrics':score_probabilities([r['labels'] for r in dev],prob,t)})
 report.write_text(json.dumps({'metric_provenance':'AI-SILVER DIAGNOSTIC PERFORMANCE; zero human labels','runs':runs,'final_candidates':[runs[1]],'reloaded_predictions_match':True},indent=2)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps({r['run_id']:{k:r['dev_metrics'][k] for k in ['micro_f1','macro_f1']} for r in runs}),flush=True)

if __name__=='__main__':main()
