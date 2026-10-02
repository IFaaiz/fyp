"""Run the DEV-selected, frozen AI-silver diagnostic classifier on JSONL emails."""
from __future__ import annotations
import sys,json,argparse
from pathlib import Path
AI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(AI))
from src.models.optimization_benchmark import DATA,LABEL_ORDER,decode,read_jsonl
from src.models.optimization_runtime import predict_candidate
from src.models.silver_classifier import extract_authored_prefix

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--selection',type=Path,default=AI/'annotation/optimization_final_selection.json');args=parser.parse_args()
 if args.input.resolve()==(DATA/'test.jsonl').resolve():raise SystemExit('Use the one-pass final evaluator for sealed TEST, not the inference CLI')
 if args.output.resolve()==args.input.resolve():raise SystemExit('Input/output must differ')
 selection=json.loads(args.selection.read_text(encoding='utf-8'));spec=next(s for s in selection['candidates'] if s['run_id']==selection['primary_run_id'])
 rows=read_jsonl(args.input)
 for r in rows:
  r.setdefault('subject','')
  if not r.get('authored_message'):r['authored_message']=extract_authored_prefix(str(r.get('current_message') or r.get('body') or ''))
  r.setdefault('current_message',r['authored_message'])
  if not r['authored_message'].strip():raise ValueError('Each email needs nonempty body/current_message/authored_message')
 probabilities=predict_candidate(spec,rows);labels=decode(probabilities,spec['thresholds'],spec['mode'],spec.get('fallback',False))
 outputs=[{'email_id':r.get('email_id'),'labels':labs,'scores':dict(zip(LABEL_ORDER,map(float,p))),'score_semantics':spec.get('probability_semantics','positive label scores; calibration depends on component; output may use a scope-first gate'),'run_id':spec['run_id'],'intended_use':'AI-silver diagnostic prototype; zero human validation'} for r,p,labs in zip(rows,probabilities,labels)]
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(''.join(json.dumps(r)+'\n' for r in outputs),encoding='utf-8',newline='\n')
 print(json.dumps({'records':len(outputs),'run_id':spec['run_id'],'output':str(args.output)}))

if __name__=='__main__':main()
