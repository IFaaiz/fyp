"""Reproduce the audited AI-silver diagnostic freeze; never creates gold labels."""
from __future__ import annotations
import hashlib,json,sys
from collections import Counter,defaultdict
from pathlib import Path
AI=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(AI))
from src.models.silver_classifier import LABEL_ORDER,extract_authored_prefix
from src.models.transfer_diagnostic import validate_snapshot,load_shared_partitions,sha256_file
from train_silver_classifier import grouped_train_validation_split
ROOT=AI.parent
P=AI/'data/experiments/tonight_20261002'
def read(p):return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
def write(p,rows):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows),encoding='utf-8')
def main():
 original=read(P/'original_silver_snapshot.jsonl');byid={r['email_id']:r for r in original}
 audit={};proposals={}
 for name in ['audit_priority_decisions.jsonl','audit_other_positive_decisions.jsonl','audit_other_positive_tail_decisions.jsonl']:
  for r in read(P/name):
   if r['email_id'] in proposals:raise ValueError('overlapping auditor work')
   proposals[r['email_id']]=r;audit[r['email_id']]=r
 assert len(proposals)==353,'all positive rows must be audited'
 root={}
 for name in ['audit_negative_50_decisions.jsonl','root_calendar_adjudication.jsonl','root_rare_adjudication.jsonl','root_proposal_adjudication.jsonl','root_tail_adjudication.jsonl']:
  for r in read(P/name):root[r['email_id']]=r;audit[r['email_id']]=r
 for id,r in proposals.items():
  if r['verdict']!='confirmed' and id not in root:raise ValueError('unadjudicated auditor proposal '+id)
 for id,r in audit.items():
  assert r['source_sha256']==byid[id]['snapshot_provenance']['source_sha256']
  assert set(r['existing_labels'])==set(byid[id]['labels'])
  assert r['verdict'] in ['confirmed','corrected','exclude_uncertain']
  if r['verdict']=='exclude_uncertain':assert not r['auditor_labels']
  else:assert r['auditor_labels'] and set(r['auditor_labels'])<=set(LABEL_ORDER)
 # Conservatively keep repeated templates and near-copies together as well as canonical groups/threads.
 parent={id:id for id in byid}
 def find(x):
  while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
  return x
 def union(x,y):parent[find(y)]=find(x)
 seen={}
 for r in original:
  for key in [('group',r['snapshot_provenance']['leakage_group_id']),('thread',r['source_dataset'],r['thread_id'])]:
   if key in seen:union(r['email_id'],seen[key])
   else:seen[key]=r['email_id']
 pairs=json.loads((P/'near_duplicate_candidates.json').read_text(encoding='utf-8'))
 for pair in pairs:union(pair['left'],pair['right'])
 members=defaultdict(list)
 for id in byid:members[find(id)].append(id)
 groups={id:'tonight-lg-'+hashlib.sha256('|'.join(sorted(ids)).encode()).hexdigest()[:16] for ids in members.values() for id in ids}
 overrides={'method':'Supervisor-reviewed word unigram/bigram cosine >=0.90, normalized body >=120 characters; conservative template overgrouping prevents wording leakage. Canonical group/thread components are also unioned.','pairs':pairs,'group_mapping':groups}
 (AI/'annotation/tonight_leakage_overrides.json').write_text(json.dumps(overrides,indent=2)+'\n',encoding='utf-8')
 corrected=[];manifest=[];excluded=[]
 for old in original:
  id=old['email_id'];decision=audit.get(id)
  if decision and decision['verdict']=='exclude_uncertain':excluded.append(id);continue
  r=json.loads(json.dumps(old));r['labels']=[l for l in LABEL_ORDER if l in (decision['auditor_labels'] if decision else old['labels'])]
  r['authored_message']=extract_authored_prefix(r['current_message'])
  prov=r['snapshot_provenance'];prov['labels']=r['labels'];prov['leakage_group_id']=groups[id];prov['authored_message_sha256']=hashlib.sha256(r['authored_message'].encode()).hexdigest()
  corrected.append(r);manifest.append(dict(prov))
 validate_snapshot(corrected,manifest)
 snapshot=P/'corrected_silver_snapshot.jsonl';mp=AI/'annotation/training_silver_v2_manifest.jsonl'
 write(snapshot,corrected);write(mp,manifest)
 gp={(r['source_dataset'],r['email_id']):groups[r['email_id']] for r in corrected}
 outer,outerinfo=grouped_train_validation_split(corrected,gp,seed=20261002)
 inner,innerinfo=grouped_train_validation_split(outer['train'],gp,seed=20261003)
 partitions={'fit':inner['train'],'tuning':inner['validation'],'validation':outer['validation']}
 split={'seed':20261002,'inner_seed':20261003,'snapshot_sha256':sha256_file(snapshot),'snapshot_manifest_sha256':sha256_file(mp),'metric_provenance':'AI-silver diagnostic metrics','partitions':{k:[{f:(r['snapshot_provenance'][f] if f=='leakage_group_id' else r[f]) for f in ['email_id','source_dataset','thread_id','leakage_group_id']} for r in v] for k,v in partitions.items()},'outer_split_checks':outerinfo,'inner_split_checks':innerinfo}
 _,splitinfo=load_shared_partitions(corrected,split,snapshot_sha256=sha256_file(snapshot),silver_manifest_sha256=sha256_file(mp))
 sp=AI/'data/splits/tonight_silver_v2_shared_split.json';sp.parent.mkdir(parents=True,exist_ok=True);sp.write_text(json.dumps(split,indent=2)+'\n',encoding='utf-8')
 (AI/'annotation/tonight_silver_v2_shared_split.json').write_text(json.dumps(split,indent=2)+'\n',encoding='utf-8')
 decisions=[];full=[]
 for id,d in sorted(audit.items()):
  item={**d,'reviewer':d.get('reviewer','luna_xhigh_semantic_audit')};decisions.append(item);full.append({**item,'subject':byid[id]['subject'],'current_authored_message':extract_authored_prefix(byid[id]['current_message'])})
 write(AI/'annotation/tonight_semantic_audit_decisions.jsonl',decisions);write(P/'semantic_audit_fulltext.jsonl',full)
 before=Counter(l for r in original for l in r['labels']);after=Counter(l for r in corrected for l in r['labels']);removed=Counter();added=Counter()
 for id,d in audit.items():removed.update(set(byid[id]['labels'])-set(d['auditor_labels']));added.update(set(d['auditor_labels'])-set(byid[id]['labels']))
 report={'metric_provenance':'AI-silver diagnostic metrics','source_commit':'7c6096700582ef8db9da5780fee3bc28149c6e9b','original':len(original),'audited':len(audit),'positive_audited':len(proposals),'negative_sample':50,'targeted_calendar_audited':12,'verdict_counts':dict(Counter(r['verdict'] for r in audit.values())),'corrected_silver_v2':len(corrected),'unaudited_negative_retained':len(original)-len(audit),'excluded_ids':excluded,'training_ready':False,'diagnostic_override':'User explicitly requests actual prototype results below the historical 1000 AI-silver readiness gate; no human or gold quality claim.','label_support':{l:{'support_before':before[l],'removed':removed[l],'added':added[l],'support_after':after[l]} for l in LABEL_ORDER},'snapshot_manifest_sha256':sha256_file(mp),'snapshot_sha256':sha256_file(snapshot),'split_sha256':sha256_file(sp),'split':splitinfo,'known_risks':['AI agreement and supervisor adjudication are not human ground truth.','Only deterministic 50 NON_PROJECT plus targeted calendar negatives reviewed; other negatives retain earlier AI labels.','All records come from historical Enron mail, not modern Outlook project workflows.','All rare labels have low support; diagnostic metrics cannot establish production quality.','Conservative template grouping reduces effective independent sample size.']}
 (AI/'reports/tonight_semantic_audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
