"""Inference for frozen optimization candidates and probability ensembles."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from .optimization_benchmark import LABEL_ORDER,AI

def resolve(path):
 p=Path(path)
 return p if p.is_absolute() else AI.parent/p

def marginal_probabilities(p,mode):
 p=np.asarray(p,dtype=float).copy()
 if mode=='hierarchical':p[:,:8]*=1-p[:,8,None]
 elif mode not in ('flat','scope_gated'):raise ValueError('unknown component mode')
 return p

def predict_candidate(spec,rows):
 kind=spec['kind'];path=resolve(spec['model_path'])
 if kind=='reference':
  from .silver_classifier import TfidfOneVsRestLogisticRegression
  model=TfidfOneVsRestLogisticRegression.load(path)
  result=[[p[l] for l in LABEL_ORDER] for p in (model.predict_proba(r) for r in rows)]
 elif kind=='lexical':
  import joblib
  result=joblib.load(path).predict_proba(rows)
 elif kind=='embeddings':
  from .optimization_embeddings import predict
  result=predict(path,rows)
 elif kind=='transformer':
  from .optimization_transformer import predict
  result=predict(path,rows)
 elif kind=='ensemble':
  bundle=json.loads(path.read_text(encoding='utf-8'))
  components=[marginal_probabilities(predict_candidate(c,rows),c['mode']) for c in bundle['components']]
  if bundle['method']=='blend':result=sum(w*p for w,p in zip(bundle['weights'],components))
  elif bundle['method']=='specialists':result=np.column_stack([components[k][:,j] for j,k in enumerate(bundle['label_sources'])])
  else:raise ValueError('unknown ensemble method')
 else:raise ValueError('unknown model kind')
 result=np.asarray(result,dtype=float)
 if result.shape!=(len(rows),9) or not np.isfinite(result).all() or np.any((result<0)|(result>1)):raise ValueError('invalid Nx9 probability output')
 return result
