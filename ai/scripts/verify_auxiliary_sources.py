"""Independently compare prepared auxiliary text and offsets with acquired bytes.

Only checksums, counts and IDs are exported. This is a fidelity check, not a
semantic source-label review and does not satisfy the personal review gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_rows(path: Path):
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def verify_airspace():
    archive_path = ROOT / 'ai/data/raw/airspace/Airspace_wargaming_1.0.zip'
    prepared_path = ROOT / 'ai/data/processed/airspace.jsonl'
    rows = load_rows(prepared_path)
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None, 'Airspace archive CRC failed')
        members = {m.filename for m in archive.infolist() if m.filename.endswith('.eml')}
        seen = set()
        for row in rows:
            name = row['source_provenance']['archive_member']
            require(name in members and name not in seen, 'Missing/duplicate source member')
            seen.add(name)
            message = BytesParser(policy=policy.default).parsebytes(archive.read(name))
            require(not message.is_multipart(), 'Independent audit needs explicit multipart handling')
            require(message.get_content() == row['body'], 'Decoded source body differs')
            require(str(message.get('Subject') or '') == row['subject'], 'Source subject differs')
            labels = [str(x).strip() for x in message.get_all('X-RADAR-Label', [])]
            require(labels == row['source_labels'], 'Original label inventory differs')
            require(str(message.get('X-RADAR-Replyto')) == row['reply_to_message_id_raw'], 'Reply field differs')
            require(str(message.get('X-RADAR-Thread')) == row['source_thread_id'], 'Raw thread field differs')
            for field, value in [('body', row['body']), ('subject', row['subject'])]:
                span = row['source_text_offsets'][field]
                require(row['source_text'][span['start']:span['end']] == value, 'Bad field offsets')
            require('labels' not in row, 'FYP labels must not be emitted')
        require(seen == members, 'Unparsed source message')
    return {'dataset_id':'airspace', 'records':len(rows), 'archive_sha256':sha(archive_path.read_bytes()),
            'processed_sha256':sha(prepared_path.read_bytes()), 'all_source_views_and_offsets_equal':True,
            'semantic_source_audit_report':'ai/reports/auxiliary_source_audits.json'}


def verify_radar():
    archive_path = ROOT / 'ai/data/raw/radar_action/action-item-dataset.tgz'
    prepared_path = ROOT / 'ai/data/processed/radar_action.jsonl'
    rows = load_rows(prepared_path)
    with tarfile.open(archive_path, 'r:gz') as archive:
        source_files = {Path(m.name).name: m for m in archive.getmembers()
                        if m.isfile() and Path(m.name).name.startswith('msg-')
                        and Path(m.name).name.endswith('.txt')}
        require(len(source_files) == len(rows), 'Unparsed or duplicate RADAR source message')
        source_members = {Path(m.name).name:m for m in archive.getmembers() if m.isfile()}
        judgments = {}
        for line in archive.extractfile(source_members['judgments.txt']).read().decode('utf-8').splitlines():
            if not line.strip():continue
            name,label,*coordinates=line.split()
            pairs=[(int(coordinates[i]),int(coordinates[i+1])) for i in range(0,len(coordinates),2)]
            require(name not in judgments, 'Duplicate source judgment')
            judgments[name]=(label,pairs)
        annotation_pairs={}
        for line in archive.extractfile(source_members['MsgAnnotationFilenamePairs.txt']).read().decode('utf-8').splitlines():
            if not line.strip():continue
            name,annotation_name=line.split('\t')
            require(name not in annotation_pairs,'Duplicate source annotation pairing')
            annotation_pairs[name]=annotation_name
        spans = 0
        for row in rows:
            raw = archive.extractfile(source_files[row['source_message_id']]).read()
            require(raw.decode('utf-8') == row['text'], 'Full-file source text differs')
            label,pairs=judgments[row['source_message_id']]
            require(row['action_item_source_label']==label,'Source presence judgment differs')
            require([(s['start'],s['length']) for s in row['action_item_spans']]==pairs,'Source action coordinates differ')
            ann_name=annotation_pairs[row['source_message_id']]
            released=[]
            for line in archive.extractfile(source_members[ann_name]).read().decode('utf-8').splitlines():
                if not line.strip():continue
                start,length,*fields=line.split('\t')
                released.append((int(start),int(length),fields[-1],fields))
            prepared=[(s['start'],s['length'],s['source_type'],s['source_fields']) for s in row['annotations']]
            require(prepared==released,'Original supplementary annotation coordinates/type/fields differ')
            for span in row['action_item_spans'] + row['annotations']:
                require(0 <= span['start'] < span['end'] <= len(row['text']), 'Out-of-bounds span')
                require(row['text'][span['start']:span['end']] == span['text'], 'Span text differs')
                spans += 1
            require(row['fyp_label_mapping'] is None, 'FYP mapping must remain absent')
            require(row['action_item_present'] == bool(row['action_item_spans']), 'Presence and spans disagree')
    return {'dataset_id':'radar_action','records':len(rows),'validated_source_slices':spans,
            'archive_sha256':sha(archive_path.read_bytes()),'processed_sha256':sha(prepared_path.read_bytes()),
            'all_source_views_and_offsets_equal':True}


def verify_parakweet():
    raw_root=ROOT/'ai/data/raw/parakweet/055f62857b3214c1682a0b18a2c5fc2c9f0c00e6'
    prepared_path=ROOT/'ai/data/processed/parakweet.jsonl'
    rows=load_rows(prepared_path)
    originals={p.name:p.read_bytes().decode('utf-8').splitlines() for p in raw_root.glob('*.txt')}
    seen=set()
    for row in rows:
        key=(row['source_file'],row['source_row_number'])
        require(key not in seen,'Duplicate source row');seen.add(key)
        label,text=originals[key[0]][key[1]-1].split('\t',1)
        require(row['text']==text and row['source_label']==label,'Source sentence/label differs')
        require(row['fragment'] is True and row['overlap_identity_complete'] is False,'Fragment provenance changed')
        require(row['fyp_labels']==[] and row['normalized_auxiliary_act'] is None,'FYP act/label invented')
    require(sum(len(lines) for lines in originals.values())==len(rows),'Source row count differs')
    return {'dataset_id':'parakweet','records':len(rows),'all_source_views_and_labels_equal':True,
            'processed_sha256':sha(prepared_path.read_bytes()),
            'semantic_source_audit_report':'ai/reports/auxiliary_source_audits.json'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'ai/reports/auxiliary_source_fidelity.json')
    args = parser.parse_args()
    payload = {'method':'independent raw-byte comparison; no text exported',
               'human_gold_claimed':False,'sources':[verify_airspace(),verify_radar(),verify_parakweet()]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(payload))


if __name__ == '__main__':
    main()
