"""Check closed experiment bytes without running training or evaluation."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def verify(path: Path, require_local: bool = False):
    config=json.loads(path.read_text(encoding='utf-8'))
    checked=[];missing=[];changed=[];format_only=[]
    for experiment in config['experiments']:
        for item in experiment['files']:
            target=(ROOT/item['path']).resolve()
            if not target.is_relative_to(ROOT): raise ValueError('Closed artifact path escapes workspace')
            if not target.exists():
                if item.get('local_only') and not require_local: missing.append(item['path']);continue
                changed.append({'path':item['path'],'reason':'missing'});continue
            h=hashlib.sha256()
            with target.open('rb') as source:
                for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
            if h.hexdigest()==item['sha256']:checked.append(item['path'])
            elif item.get('canonical_lf_sha256') and hashlib.sha256(target.read_bytes().replace(b'\r\n',b'\n')).hexdigest()==item['canonical_lf_sha256']:
                checked.append(item['path']);format_only.append(item['path'])
            else:changed.append({'path':item['path'],'reason':'SHA256 changed'})
    return {'checked_files':len(checked),'missing_optional_local_files':missing,'changed_files':changed,
            'closed_files_intact':not changed,'format_only_lf_crlf_variants':format_only,
            'training_or_inference_performed':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=ROOT/'ai/config/closed_experiments.json')
    parser.add_argument('--require-local',action='store_true');args=parser.parse_args()
    result=verify(args.config,args.require_local);print(json.dumps(result,indent=2))
    if not result['closed_files_intact']:raise SystemExit(1)


if __name__=='__main__':main()
