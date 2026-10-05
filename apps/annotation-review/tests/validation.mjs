import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import ts from 'typescript';
const filename=path.resolve('lib/annotation.ts');
const js=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true,resolveJsonModule:true,target:ts.ScriptTarget.ES2022}}).outputText;
const mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));mod._compile(js,filename);
const {validateAnnotation,cp}=mod.exports;
const fixtures=JSON.parse(fs.readFileSync('tests/synthetic-examples.json','utf8'));
let passed=0;
for(const f of fixtures){const source={...f.source,context_sources:f.context_sources||[],context_annotations:f.context_annotations||(f.context_sources||[]).map(x=>({current_source_id:x.source_id,events:x.events||[]}))};const errs=validateAnnotation(f.annotation,source);assert.deepEqual(errs,[],`${f.fixture_id}: ${errs.join('; ')}`);passed++;}
const f=fixtures.find(x=>x.annotation.events.length&&x.annotation.scope.value==='PROJECT'&&!x.annotation.needs_review);
const source={...f.source,context_sources:f.context_sources||[],context_annotations:f.context_annotations||(f.context_sources||[]).map(x=>({current_source_id:x.source_id,events:x.events||[]}))};
function rejects(mutation){const a=structuredClone(f.annotation);mutation(a);assert.ok(validateAnnotation(a,source).length);passed++;}
rejects(a=>a.scope.evidence_span_ids=[]);
rejects(a=>a.spans[0].start+=1);
rejects(a=>a.event_span_links=a.event_span_links.filter(x=>x.role!=='EVENT_ANCHOR'));
rejects(a=>{const id=a.event_span_links.find(x=>x.role==='EVENT_ANCHOR').span_id;a.spans.find(x=>x.id===id).field='subject';});
rejects(a=>a.spans.push({...a.spans[0],id:'duplicate'}));
rejects(a=>{a.scope.value='NON_PROJECT';});
rejects(a=>a.events[0].certainty='UNCERTAIN');
rejects(a=>a.provenance.annotation_tier='GOLD');
assert.equal(cp('🙂é').length,2);passed++;
const priorFixture=fixtures.find(x=>x.annotation.event_relations.some(r=>r.kind==='SUPERSEDES'&&r.target));
const priorSource={...priorFixture.source,context_sources:structuredClone(priorFixture.context_sources||[]),context_annotations:structuredClone(priorFixture.context_annotations||(priorFixture.context_sources||[]).map(x=>({current_source_id:x.source_id,events:x.events||[]})))};
const priorEvent=priorSource.context_annotations.find(x=>x.current_source_id===priorFixture.annotation.event_relations[0].target.source_id).events.find(x=>x.id===priorFixture.annotation.event_relations[0].target.event_id);priorEvent.kind='ACTION';assert.ok(validateAnnotation(priorFixture.annotation,priorSource).length);passed++;
const cleanPriorSource={...priorFixture.source,context_sources:priorFixture.context_sources||[],context_annotations:priorFixture.context_annotations||(priorFixture.context_sources||[]).map(x=>({current_source_id:x.source_id,events:x.events||[]}))};assert.deepEqual(validateAnnotation(priorFixture.annotation,cleanPriorSource),[]);const duplicateRelation=structuredClone(priorFixture.annotation);duplicateRelation.event_relations.push({...duplicateRelation.event_relations[0],id:'different-relation-id'});assert.ok(validateAnnotation(duplicateRelation,cleanPriorSource).length);passed++;
rejects(a=>{a.provenance={data_origin:'UNKNOWN',source_reference:null,synthetic_case_id:null,annotation_tier:'GOLD',annotation_mode:'BLIND_HUMAN',annotator_id:'synthetic-reviewer',annotated_at:'2026-10-01T00:00:00Z',blind_prelabels_shown:false,human_review:{reviewer_id:'synthetic-adjudicator',reviewed_at:'2026-10-01T01:00:00Z',decision:'accepted'},ai_assistance:null};});
rejects(a=>{a.provenance={data_origin:'PUBLIC_CORPUS',source_reference:source.source_id,synthetic_case_id:null,annotation_tier:'UNSET',annotation_mode:'RULE_BASED',annotator_id:null,annotated_at:null,blind_prelabels_shown:null,human_review:null,ai_assistance:null};});
console.log(JSON.stringify({synthetic_fixtures:fixtures.length,validation_checks:passed,real_emails_read:0}));


