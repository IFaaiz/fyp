import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import ts from 'typescript';

const root = path.resolve('.');
const legacyPath = path.join(root, 'lib/annotation.ts');
const legacyJs = ts.transpileModule(fs.readFileSync(legacyPath, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, resolveJsonModule: true, target: ts.ScriptTarget.ES2022 },
}).outputText;
const legacyModule = new Module(legacyPath);
legacyModule.filename = legacyPath;
legacyModule.paths = Module._nodeModulePaths(path.dirname(legacyPath));
legacyModule._compile(legacyJs, legacyPath);

const filename = path.join(root, 'lib/direct-annotation-v1.ts');
const js = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, resolveJsonModule: true, target: ts.ScriptTarget.ES2022 },
}).outputText;
const mod = new Module(filename);
mod.filename = filename;
mod.paths = Module._nodeModulePaths(path.dirname(filename));
const originalRequire = mod.require.bind(mod);
mod.require = (request) => request === './annotation' ? legacyModule.exports : originalRequire(request);
mod._compile(js, filename);
const { blankDirect, cp, stampDirectDraft, stampDirectSubmission, validateDirect, directVersion, directLabels, spanTypes } = mod.exports;

const source = {
  source_id: 'real-email-1', subject: 'Project report due Friday',
  current_message: 'Please send the revised report by Friday.',
  authored_ranges: [{ start: 0, end: Array.from('Please send the revised report by Friday.').length }],
  data_origin: 'PUBLIC_CORPUS',
};
const cpIndexOf = (haystack, needle) => {
  const body = cp(haystack), search = cp(needle);
  for (let index = 0; index <= body.length - search.length; index++) {
    if (search.every((point, offset) => body[index + offset] === point)) return index;
  }
  return -1;
};
const at = (field, text, type, id) => {
  const offset = cpIndexOf(source[field], text);
  assert.notEqual(offset, -1, `fixture text ${text}`);
  return { id, field, start: offset, end: offset + cp(text).length, text, type };
};
const evidence = at('current_message', 'Please send', 'EVIDENCE', 'trigger');
const scopeEvidence = at('subject', 'Project', 'EVIDENCE', 'scope');
const document = at('current_message', 'revised report', 'REQUESTED_DOCUMENT', 'doc');
const date = at('current_message', 'Friday', 'DEADLINE_DATE', 'date');
const base = () => ({
  schema_version: directVersion,
  record_id: source.source_id,
  current_source_id: source.source_id,
  scope: { value: 'PROJECT', reason: '', evidence_span_ids: ['scope'] },
  labels: ['REPORT_REQUEST', 'DEADLINE'],
  spans: [structuredClone(scopeEvidence), structuredClone(evidence), structuredClone(document), structuredClone(date)],
  label_support: [
    { label: 'REPORT_REQUEST', evidence_span_ids: ['trigger'], field_span_ids: ['doc'], applies_to: '', follow_up_target: null, review_reason: '' },
    { label: 'DEADLINE', evidence_span_ids: ['trigger'], field_span_ids: ['date'], applies_to: 'revised report', follow_up_target: null, review_reason: '' },
  ],
  needs_review: false,
  review_reasons: [],
  provenance: {
    data_origin: 'PUBLIC_CORPUS', source_reference: source.source_id, synthetic_case_id: null,
    annotation_tier: 'UNSET', annotation_mode: 'UNANNOTATED', annotator_id: null, annotated_at: null,
    blind_prelabels_shown: null, human_review: null, ai_assistance: null,
  },
});

let checks = 0;
const valid = (record, expected = true) => {
  const errors = validateDirect(record, source);
  assert.equal(errors.length === 0, expected, errors.join('; '));
  checks++;
};
valid(base());

function oneLabelRecord(label, message, triggerText, fieldSpans = [], { appliesTo = '', followUpTarget = null } = {}) {
  const localSource = {
    ...source,
    source_id: `label-${label.toLowerCase()}`,
    current_message: message,
    authored_ranges: [{ start: 0, end: cp(message).length }],
  };
  const addSpan = (id, field, text, type) => {
    const start = cpIndexOf(localSource[field], text);
    assert.notEqual(start, -1, `fixture text ${text}`);
    return { id, field, start, end: start + cp(text).length, text, type };
  };
  const spans = [
    addSpan('scope', 'subject', 'Project', 'EVIDENCE'),
    addSpan('trigger', 'current_message', triggerText, 'EVIDENCE'),
    ...fieldSpans.map(([id, text, type]) => addSpan(id, 'current_message', text, type)),
  ];
  return {
    source: localSource,
    annotation: {
      schema_version: directVersion, record_id: localSource.source_id, current_source_id: localSource.source_id,
      scope: { value: 'PROJECT', reason: '', evidence_span_ids: ['scope'] }, labels: [label], spans,
      label_support: [{ label, evidence_span_ids: ['trigger'], field_span_ids: fieldSpans.map(([id]) => id), applies_to: appliesTo, follow_up_target: followUpTarget, review_reason: '' }],
      needs_review: false, review_reasons: [],
      provenance: {
        data_origin: 'PUBLIC_CORPUS', source_reference: localSource.source_id, synthetic_case_id: null,
        annotation_tier: 'UNSET', annotation_mode: 'UNANNOTATED', annotator_id: null, annotated_at: null,
        blind_prelabels_shown: null, human_review: null, ai_assistance: null,
      },
    },
  };
}

const labelCases = [
  oneLabelRecord('MEETING', "Let's meet on Monday.", 'meet'),
  oneLabelRecord('DEADLINE', 'Please send the draft by Friday.', 'by Friday', [['due', 'Friday', 'DEADLINE_DATE']], { appliesTo: 'send the draft' }),
  oneLabelRecord('REPORT_REQUEST', 'Please send the revised report by Friday.', 'send the revised report', [['doc', 'revised report', 'REQUESTED_DOCUMENT']]),
  oneLabelRecord('DEPARTMENTAL_INPUT', 'Finance should send the figures.', 'Finance should send the figures', [['department', 'Finance', 'DEPARTMENT'], ['input', 'figures', 'INPUT']]),
  oneLabelRecord('ACTION_REQUEST', 'Please test the system.', 'test the system', [['action', 'test the system', 'ACTION_ITEM']]),
  oneLabelRecord('FOLLOW_UP', 'Reminder: please send the report.', 'Reminder', [], { followUpTarget: 'DOCUMENT_REQUEST' }),
  oneLabelRecord('APPROVAL', 'Please approve the revised project plan.', 'approve', [['target', 'revised project plan', 'APPROVAL_TARGET']]),
  oneLabelRecord('GENERAL_UPDATE', 'Testing is now complete.', 'Testing is now complete'),
];
for (const { source: labelSource, annotation } of labelCases) {
  assert.deepEqual(validateDirect(annotation, labelSource), [], `${annotation.labels[0]} should validate`);
  assert.deepEqual(annotation.labels, [annotation.label_support[0].label], 'validation preserves direct labels without adding co-occurrences');
  checks += 2;
}
const requiredFieldCases = [
  ['DEADLINE', 'due'], ['REPORT_REQUEST', 'doc'],
  ['DEPARTMENTAL_INPUT', 'department'], ['DEPARTMENTAL_INPUT', 'input'],
  ['ACTION_REQUEST', 'action'], ['APPROVAL', 'target'],
];
for (const [label, fieldId] of requiredFieldCases) {
  const { source: labelSource, annotation } = structuredClone(labelCases.find((item) => item.annotation.labels[0] === label));
  annotation.label_support[0].field_span_ids = annotation.label_support[0].field_span_ids.filter((id) => id !== fieldId);
  annotation.spans = annotation.spans.filter((span) => span.id !== fieldId);
  assert.ok(validateDirect(annotation, labelSource).length > 0, `${label} missing ${fieldId} must be explained`);
  annotation.label_support[0].review_reason = `The ${fieldId} is unavailable.`;
  annotation.needs_review = true;
  annotation.review_reasons = [`${label} needs adjudication.`];
  assert.deepEqual(validateDirect(annotation, labelSource), [], `${label} waiver with review should validate`);
  checks += 2;
}
const deadlineWithoutTarget = structuredClone(labelCases.find((item) => item.annotation.labels[0] === 'DEADLINE'));
deadlineWithoutTarget.annotation.label_support[0].applies_to = '';
assert.ok(validateDirect(deadlineWithoutTarget.annotation, deadlineWithoutTarget.source).length > 0);
deadlineWithoutTarget.annotation.label_support[0].review_reason = 'What is due is unclear.';
deadlineWithoutTarget.annotation.needs_review = true;
deadlineWithoutTarget.annotation.review_reasons = ['Deadline target needs adjudication.'];
assert.deepEqual(validateDirect(deadlineWithoutTarget.annotation, deadlineWithoutTarget.source), []);
checks += 2;

const rejects = (change) => { const record = base(); change(record); valid(record, false); };
rejects((record) => { record.scope.value = 'NON_PROJECT'; record.labels = ['NON_PROJECT']; });
rejects((record) => { record.labels = ['DEADLINE']; });
rejects((record) => { record.label_support[1].applies_to = '  '; });
rejects((record) => { record.label_support[0].field_span_ids = ['date']; });
rejects((record) => { record.label_support[1].evidence_span_ids = ['scope']; });
rejects((record) => { record.spans[0].start += 1; });
rejects((record) => { record.spans.push({ ...record.spans[0], id: 'orphan' }); });
rejects((record) => { record.current_source_id = 'prior-email'; });
rejects((record) => { record.spans.find((span) => span.id === 'trigger').field = 'subject'; });
rejects((record) => { record.derived_label_version = 'fyp-derived-labels-1.1'; });

const uncertain = {
  ...base(), scope: { value: 'UNCERTAIN', reason: 'The message mixes project and routine work.', evidence_span_ids: ['scope'] },
  labels: [], spans: [structuredClone(scopeEvidence)], label_support: [], needs_review: true,
  review_reasons: ['Scope needs adjudication.'],
};
valid(uncertain);
uncertain.labels = ['GENERAL_UPDATE'];
valid(uncertain, false);
checks++;
uncertain.labels = [];

const nonProject = {
  ...base(), scope: { value: 'NON_PROJECT', reason: '', evidence_span_ids: ['scope'] }, labels: ['NON_PROJECT'],
  spans: [structuredClone(scopeEvidence)], label_support: [],
};
valid(nonProject);
nonProject.scope.evidence_span_ids = [];
nonProject.spans = [];
valid(nonProject);
const inverseNonProject = base();
inverseNonProject.labels = ['NON_PROJECT', 'MEETING'];
inverseNonProject.label_support = [];
valid(inverseNonProject, false);
checks++;

uncertain.scope.evidence_span_ids = [];
uncertain.spans = [];
valid(uncertain);

const waived = base();
waived.label_support[0].field_span_ids = [];
waived.label_support[0].review_reason = 'The referenced attachment is missing from this message.';
waived.spans = waived.spans.filter((span) => span.id !== 'doc');
waived.needs_review = true;
waived.review_reasons = ['Requested document cannot be identified from available text.'];
valid(waived);

const unclearFollowUp = base();
unclearFollowUp.labels = ['FOLLOW_UP'];
unclearFollowUp.spans = [structuredClone(scopeEvidence), structuredClone(evidence)];
unclearFollowUp.label_support = [{ label: 'FOLLOW_UP', evidence_span_ids: ['trigger'], field_span_ids: [], applies_to: '', follow_up_target: 'UNCLEAR', review_reason: 'The previous expectation is not available.' }];
unclearFollowUp.needs_review = true;
unclearFollowUp.review_reasons = ['Prior thread expectation needs adjudication.'];
valid(unclearFollowUp);

const stampedDraft = stampDirectDraft({ ...base(), derived_label_version: 'forged', provenance: { annotation_tier: 'GOLD' } }, source);
assert.equal(validateDirect(stampedDraft, source).length, 0);
assert.equal(stampedDraft.provenance.annotation_tier, 'UNSET');
assert.equal(stampedDraft.provenance.annotation_mode, 'UNANNOTATED');
assert.equal('derived_label_version' in stampedDraft, false);
checks += 4;

const submitted = stampDirectSubmission(base(), source, 'annotator-1', '2026-10-06T00:00:00.000Z');
assert.equal(validateDirect(submitted, source).length, 0);
assert.equal(submitted.provenance.annotation_mode, 'BLIND_HUMAN');
assert.equal(submitted.provenance.annotator_id, 'annotator-1');
assert.equal(submitted.provenance.blind_prelabels_shown, false);
assert.equal(submitted.provenance.annotation_tier, 'UNSET');
assert.equal('derived_label_version' in submitted, false);
checks += 6;

const syntheticSource = { ...source, source_id: 'synthetic-1', data_origin: 'SYNTHETIC', synthetic_case_id: 'case-1' };
const synthetic = stampDirectSubmission({ ...base(), record_id: syntheticSource.source_id, current_source_id: syntheticSource.source_id }, syntheticSource, 'annotator-1', '2026-10-06T00:00:00.000Z');
assert.equal(synthetic.provenance.annotation_tier, 'SYNTHETIC');
assert.equal(validateDirect(synthetic, syntheticSource).length, 0);
const forgedGold = structuredClone(synthetic);
Object.assign(forgedGold.provenance, { annotation_tier: 'GOLD', human_review: { reviewer_id: 'reviewer', reviewed_at: '2026-10-06T00:00:00Z', decision: 'accepted' } });
assert.ok(validateDirect(forgedGold, syntheticSource).length > 0);
checks += 3;

const shiftedSource = {
  ...source, current_message: '📧 Please send the revised report by Friday.',
  authored_ranges: [{ start: 0, end: cp('📧 Please send the revised report by Friday.').length }],
};
const unicodeRecord = base();
unicodeRecord.spans = unicodeRecord.spans.map((span) => span.field === 'current_message'
  ? { ...span, start: cpIndexOf(shiftedSource.current_message, span.text), end: cpIndexOf(shiftedSource.current_message, span.text) + cp(span.text).length }
  : span);
assert.equal(validateDirect(unicodeRecord, shiftedSource).length, 0);
const quotedOnly = structuredClone(unicodeRecord);
quotedOnly.spans.find((span) => span.id === 'trigger').start = cpIndexOf(shiftedSource.current_message, 'Please send');
quotedOnly.spans.find((span) => span.id === 'trigger').end = quotedOnly.spans.find((span) => span.id === 'trigger').start + cp('Please send').length;
shiftedSource.authored_ranges = [{ start: 0, end: 2 }];
assert.ok(validateDirect(quotedOnly, shiftedSource).length > 0);
checks += 2;

assert.equal(directLabels.length, 9);
assert.equal(spanTypes.length, 14);
assert.equal(blankDirect(source).schema_version, directVersion);
checks += 3;
console.log(JSON.stringify({ schema_version: directVersion, labels: directLabels, checks }));
