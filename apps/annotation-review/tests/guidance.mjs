import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import ts from 'typescript';
function load(filename,annotation){
 const mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));
 const original=mod.require.bind(mod);if(annotation)mod.require=id=>id==='./annotation'?annotation:original(id);
 mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true,target:ts.ScriptTarget.ES2022}}).outputText,filename);
 return mod.exports;
}
const annotation=load(path.resolve('lib/annotation.ts'));
const {authored,exactMatches,missingRoles,kinds,roleLabels,stateLabels}=load(path.resolve('lib/guidance.ts'),annotation);
const prefix=String.fromCodePoint(0x1d4ab)+' Please test.';
const source={current_message:prefix+'\nSignature\nPlease test.',subject:'Please test.',authored_ranges:[{start:0,end:Array.from(prefix).length}]};
const matches=exactMatches(source,'current_message','Please test.');
assert.equal(matches.length,1);assert.equal(matches[0].start,2);assert.equal(matches[0].end,14);
assert.equal(exactMatches(source,'current_message','test.\nSignature').length,0);
assert.equal(exactMatches(source,'current_message','').length,0);
assert.equal(exactMatches(source,'subject','Please test.').length,1);
assert.equal(authored(source,2,14),true);assert.equal(authored(source,2,15),false);
assert.deepEqual(missingRoles({event_span_links:[{event_id:'e',role:'EVENT_ANCHOR'}]},{id:'e',kind:'ACTION'}),['ACTION']);
assert.deepEqual(missingRoles({event_span_links:[{event_id:'e',role:'EVENT_ANCHOR'},{event_id:'e',role:'STATUS'}]},{id:'e',kind:'STATUS'}),[]);
for(const [kind,states] of Object.entries(annotation.eventStates)){assert.ok(kinds[kind]);for(const state of states)assert.ok(stateLabels[state]);for(const role of annotation.rules.required_event_roles[kind])assert.ok(roleLabels[role]);}
console.log(JSON.stringify({guidance_checks:9,unicode_offsets:true,excluded_matches_filtered:true,required_roles_preserved:true,real_emails_read:0}));
