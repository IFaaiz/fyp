"""Create a source-free finalist manifest. Commit it before TEST inference."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ai'/'src'))
from mailex_extraction.metrics import validate_test_authorization


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def artifact_map(paths):
    result={}
    for value in paths:
        path=(ROOT/value).resolve()
        relative=path.relative_to(ROOT.resolve()).as_posix()
        if not path.is_file(): raise ValueError(f'Missing frozen artifact: {relative}')
        result[relative]=digest(path)
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--compact-checkpoint',required=True)
    p.add_argument('--compact-threshold',required=True,type=float)
    p.add_argument('--gliner-checkpoint')
    p.add_argument('--gliner-schema')
    p.add_argument('--gliner-threshold',type=float)
    p.add_argument('--output',default='ai/config/mailex_extraction_selection_lock.json')
    p.add_argument('--decision-note',required=True,help='DEV-only selection rationale, without source excerpts')
    a=p.parse_args()
    output=ROOT/a.output
    if output.exists(): raise ValueError('Selection manifest already exists; never overwrite a TEST lock')
    if not 0<a.compact_threshold<=1: raise ValueError('BIO threshold must be in (0,1]')
    checkpoint=(ROOT/a.compact_checkpoint).resolve()
    config=json.loads((checkpoint/'config.json').read_text(encoding='utf-8'))
    encoder=(ROOT/config['encoder']).resolve()
    schema=ROOT/'ai/config/mailex_native_extraction_schema.json'
    evaluator=artifact_map(['ai/src/mailex_extraction/metrics.py','ai/scripts/evaluate_mailex_extraction.py'])
    token_names=['config.json','tokenizer.json','tokenizer_config.json','vocab.txt',
                 'special_tokens_map.json','added_tokens.json','spm.model','sentencepiece.bpe.model']
    token_files=[encoder/name for name in token_names if (encoder/name).is_file()]
    code=['ai/src/mailex_extraction/__init__.py','ai/src/mailex_extraction/compact.py',
          'ai/scripts/predict_mailex_compact.py','ai/scripts/run_mailex_compact.py']
    preprocessing=['ai/src/datasets/mailex_native.py','ai/scripts/build_mailex_fyp_safe_views.py',
                   'ai/scripts/prepare_mailex_native.py','ai/config/mailex_extraction_environment.json',
                   checkpoint/'config.json',*token_files]
    finalists=[{'run_id':'compact_selected','architecture':'Shared DistilBERT categorical BIO triggers and event-conditioned argument BIO',
                'config':config,'thresholds':{'bio':a.compact_threshold},'inference_device':'cuda',
                'expected_output_path':'ai/data/experiments/mailex_extraction_v1/private_test/compact_selected_predictions.jsonl',
                'model_weights':artifact_map([checkpoint/'model.pt']), 'code':artifact_map(code),
                'preprocessing':artifact_map(preprocessing),'evaluator':evaluator,'schema':artifact_map([schema])}]
    if a.gliner_checkpoint:
        if not a.gliner_schema or a.gliner_threshold is None: p.error('GLiNER finalist needs its frozen TRAIN schema and threshold')
        directory=(ROOT/a.gliner_checkpoint).resolve()
        weights=[directory/name for name in ('model.safetensors','pytorch_model.bin','model.pt') if (directory/name).is_file()]
        if not weights: raise ValueError('GLiNER checkpoint has no supported model weight file')
        gliner_code=['ai/src/mailex_extraction/gliner_backend.py','ai/scripts/run_mailex_gliner.py',
                     'ai/scripts/predict_mailex_gliner.py',*sorted((ROOT/'ai/data/cache/mailex_gliner/vendor/gliner2').rglob('*.py'))]
        gliner_pre=[directory/name for name in token_names if (directory/name).is_file()]
        # AutoExtractor reloads the nested encoder configuration as well as
        # its outer config and tokenizer. All must be frozen with the weights.
        gliner_pre.extend(sorted((directory/'encoder_config').rglob('*.json')))
        finalists.append({'run_id':'gliner_small_selected','architecture':'GLiNER2.5 Small natural trigger-anchored native event records',
                         'config':{'checkpoint_directory':directory.relative_to(ROOT).as_posix(),
                                   'encoder_max_positions':512,'schema_prompt_budget_subwords':320,
                                   'record_merge':'identical full-record deduplication only; never union by anchor',
                                   'empty_body':'empty predictions; native gold retained'},
                         'thresholds':{'record':a.gliner_threshold},'inference_device':'cuda',
                         'expected_output_path':'ai/data/experiments/mailex_extraction_v1/private_test/gliner_small_selected_predictions.jsonl',
                         'model_weights':artifact_map(weights),'code':artifact_map(gliner_code),
                         'preprocessing':artifact_map(gliner_pre+['ai/config/mailex_extraction_environment.json']),
                         'evaluator':evaluator,'schema':artifact_map([a.gliner_schema])})
    gold=ROOT/'ai/data/experiments/mailex_extraction_v1/test_fyp_safe.jsonl'
    manifest={'schema_version':1,'status':'locked','split':'test','created_utc':datetime.now(timezone.utc).isoformat(),
              'dataset_variant':'mailex_native_fyp_safe_v1','gold_path':gold.relative_to(ROOT).as_posix(),
              'gold_sha256':digest(gold),'selection_rule':'DEV exact argument-role micro F1; TEST is not used for selection',
              'selection_note':a.decision_note,'finalists':finalists}
    validate_test_authorization(manifest)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'status':'manifest_created_not_yet_committed','path':output.relative_to(ROOT).as_posix(),
                      'sha256':digest(output),'finalists':[r['run_id'] for r in finalists]}))


if __name__=='__main__': main()
