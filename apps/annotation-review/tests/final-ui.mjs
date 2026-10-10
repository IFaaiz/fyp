import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import ts from 'typescript';

const root = path.resolve('.');

function loadTs(relative) {
  const filename = path.resolve(relative);
  const source = fs.readFileSync(filename, 'utf8');
  const js = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      esModuleInterop: true,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const mod = new Module(filename);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod._compile(js, filename);
  return mod.exports;
}

const { labelGuide, fieldNames, directGuide } = loadTs('lib/direct-guidance.ts');
const uiPath = path.resolve('app/direct-home.tsx');
const ui = fs.readFileSync(uiPath, 'utf8');
const labels = [
  'MEETING', 'DEADLINE', 'REPORT_REQUEST', 'DEPARTMENTAL_INPUT',
  'ACTION_REQUEST', 'FOLLOW_UP', 'APPROVAL', 'GENERAL_UPDATE',
];
const extractionTypes = [
  'MEETING_DATE', 'MEETING_TIME', 'DEADLINE_DATE', 'DEADLINE_TIME',
  'ACTION_ITEM', 'RESPONSIBLE_PARTY', 'DEPARTMENT', 'REQUESTED_DOCUMENT',
  'PARTICIPANT', 'AGENDA', 'PROJECT',
];

assert.deepEqual(Object.keys(labelGuide), labels);
assert.ok(Object.values(labelGuide).every((guide) => guide.required.length === 0));
assert.deepEqual(Object.keys(fieldNames), ['EVIDENCE', ...extractionTypes]);
assert.ok(directGuide.some(([, text]) => text.includes('EVIDENCE is auxiliary support, not a 12th extraction target.')));
assert.match(ui, /\['Relevance','FYP labels','Evidence','Submit'\]/);
assert.match(ui, /directLabels\.filter\(\(v:string\)=>v!=='NON_PROJECT'\)/);
assert.match(ui, /Words showing this label · Required support/);
assert.match(ui, /extractionSpanTypes\.filter\(\(kind:string\)=>!info\.fields\.includes\(kind\)\)/);
assert.match(ui, /Leave unstated details blank/);
assert.doesNotMatch(ui, /deriveLabels|derived_label_version|Derived FYP labels/);
assert.match(ui, /round_member\?'Shared first round · '/);
assert.match(ui, /q\.find\(\(x:any\)=>x\.status!=='submitted'\)/);
assert.match(ui, /Save draft/);
assert.match(ui, /Submit & next/);
assert.match(ui, /source\.archived_direct_available/);
assert.match(ui, /Download my archived draft/);

console.log(JSON.stringify({ suite: 'final-ui', steps: 4, direct_labels: labels.length, extraction_span_types: extractionTypes.length, support_types: ['EVIDENCE'], checks: 16 }));
