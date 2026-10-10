import schemaFile from './direct-schema-v1.json';
import { stampBlindHumanSubmission, stampUnannotatedDraft } from './annotation';

export const directSchema: any = schemaFile;
export const directVersion = 'fyp-direct-label-v1';
export const directLabels: string[] = [
  'MEETING', 'DEADLINE', 'REPORT_REQUEST', 'DEPARTMENTAL_INPUT',
  'ACTION_REQUEST', 'FOLLOW_UP', 'APPROVAL', 'GENERAL_UPDATE', 'NON_PROJECT',
];
export const projectLabels: string[] = directLabels.filter((label) => label !== 'NON_PROJECT');
export const spanTypes: string[] = [
  'EVIDENCE', 'MEETING_DATE', 'MEETING_TIME', 'DEADLINE_DATE', 'DEADLINE_TIME',
  'ACTION_ITEM', 'RESPONSIBLE_PARTY', 'DEPARTMENT', 'REQUESTED_DOCUMENT',
  'PARTICIPANT', 'AGENDA', 'PROJECT', 'INPUT', 'APPROVAL_TARGET',
];

const requiredFieldTypes: Record<string, string[]> = {
  MEETING: [],
  DEADLINE: ['DEADLINE_DATE|DEADLINE_TIME'],
  REPORT_REQUEST: ['REQUESTED_DOCUMENT'],
  DEPARTMENTAL_INPUT: ['DEPARTMENT', 'INPUT'],
  ACTION_REQUEST: ['ACTION_ITEM'],
  FOLLOW_UP: [],
  APPROVAL: ['APPROVAL_TARGET'],
  GENERAL_UPDATE: [],
};

const allowedFieldTypes: Record<string, string[]> = {
  MEETING: ['MEETING_DATE', 'MEETING_TIME', 'PARTICIPANT', 'AGENDA', 'PROJECT'],
  DEADLINE: ['DEADLINE_DATE', 'DEADLINE_TIME', 'ACTION_ITEM', 'REQUESTED_DOCUMENT', 'RESPONSIBLE_PARTY', 'PROJECT'],
  REPORT_REQUEST: ['REQUESTED_DOCUMENT', 'RESPONSIBLE_PARTY', 'PROJECT'],
  DEPARTMENTAL_INPUT: ['DEPARTMENT', 'INPUT', 'RESPONSIBLE_PARTY', 'PROJECT'],
  ACTION_REQUEST: ['ACTION_ITEM', 'RESPONSIBLE_PARTY', 'PROJECT'],
  FOLLOW_UP: spanTypes.filter((type) => type !== 'EVIDENCE'),
  APPROVAL: ['APPROVAL_TARGET', 'RESPONSIBLE_PARTY', 'PROJECT'],
  GENERAL_UPDATE: ['ACTION_ITEM', 'RESPONSIBLE_PARTY', 'DEPARTMENT', 'REQUESTED_DOCUMENT', 'INPUT', 'APPROVAL_TARGET', 'PROJECT'],
};

const followUpTargets = ['TASK', 'DOCUMENT_REQUEST', 'APPROVAL', 'DEPARTMENT_INPUT', 'MEETING_ACTION', 'UNCLEAR'];

export const cp = (value: string) => Array.from(value);

export function blankDirect(source: any) {
  const draft: any = {
    schema_version: directVersion,
    record_id: source.source_id,
    current_source_id: source.source_id,
    scope: { value: 'UNCERTAIN', reason: '', evidence_span_ids: [] },
    labels: [],
    spans: [],
    label_support: [],
    needs_review: true,
    review_reasons: ['Project relevance has not been decided.'],
    provenance: {
      data_origin: source.data_origin || 'UNKNOWN',
      source_reference: ['REAL_EMAIL', 'PUBLIC_CORPUS'].includes(source.data_origin) ? source.source_id : null,
      synthetic_case_id: null,
      annotation_tier: 'UNSET',
      annotation_mode: 'UNANNOTATED',
      annotator_id: null,
      annotated_at: null,
      blind_prelabels_shown: null,
      human_review: null,
      ai_assistance: null,
    },
  };
  return stampDirectDraft(draft, source);
}

function resolveRef(root: any, ref: string): any {
  return ref.replace(/^#\//, '').split('/').reduce((value, key) => value?.[key], root);
}

function structural(value: any, rule: any, path = '$'): string[] {
  if (rule === true) return [];
  if (rule === false || !rule || typeof rule !== 'object') return [path + ' is forbidden'];
  const errors: string[] = [];
  if (rule.$ref) errors.push(...structural(value, resolveRef(directSchema, rule.$ref), path));
  if ('const' in rule && JSON.stringify(value) !== JSON.stringify(rule.const)) errors.push(path + ' has an invalid value');
  if (rule.enum && !rule.enum.some((item: any) => JSON.stringify(item) === JSON.stringify(value))) errors.push(path + ' has an invalid choice');
  if (rule.type) {
    const types = Array.isArray(rule.type) ? rule.type : [rule.type];
    const matches = types.some((type: string) => type === 'null' ? value === null
      : type === 'array' ? Array.isArray(value)
        : type === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value)
          : type === 'integer' ? Number.isInteger(value)
            : typeof value === type);
    if (!matches) return [...errors, path + ' has an invalid type'];
  }
  if (typeof value === 'string') {
    if (rule.minLength !== undefined && cp(value).length < rule.minLength) errors.push(path + ' is required');
    if (rule.format === 'date-time' && !/^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value)) errors.push(path + ' needs an ISO timestamp');
  }
  if (typeof value === 'number' && rule.minimum !== undefined && value < rule.minimum) errors.push(path + ' is below the minimum');
  if (Array.isArray(value)) {
    if (rule.minItems !== undefined && value.length < rule.minItems) errors.push(path + ' needs evidence');
    if (rule.uniqueItems && new Set(value.map((item: any) => JSON.stringify(item))).size !== value.length) errors.push(path + ' contains duplicates');
    if (rule.items) value.forEach((item, index) => errors.push(...structural(item, rule.items, `${path}[${index}]`)));
  }
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    for (const key of rule.required || []) if (!(key in value)) errors.push(path + '.' + key + ' is required');
    for (const [key, item] of Object.entries(value)) {
      if (rule.properties?.[key]) errors.push(...structural(item, rule.properties[key], path + '.' + key));
      else if (rule.additionalProperties === false) errors.push(path + '.' + key + ' is not allowed');
    }
  }
  if (rule.allOf) for (const child of rule.allOf) errors.push(...structural(value, child, path));
  if (rule.oneOf && rule.oneOf.filter((child: any) => structural(value, child, path).length === 0).length !== 1) errors.push(path + ' does not match exactly one allowed record');
  if (rule.anyOf && !rule.anyOf.some((child: any) => structural(value, child, path).length === 0)) errors.push(path + ' does not match an allowed value');
  if (rule.not && structural(value, rule.not, path).length === 0) errors.push(path + ' has a forbidden combination');
  if (rule.if) {
    const branch = structural(value, rule.if, path).length === 0 ? rule.then : rule.else;
    if (branch) errors.push(...structural(value, branch, path));
  }
  return errors;
}

function validAuthoredRange(start: number, end: number, source: any, bodyLength: number): boolean {
  if (!Array.isArray(source.authored_ranges)) return false;
  let covered = false;
  for (const range of source.authored_ranges) {
    if (!range || !Number.isInteger(range.start) || !Number.isInteger(range.end)
      || range.start < 0 || range.end < range.start || range.end > bodyLength) return false;
    if (range.start <= start && end <= range.end) covered = true;
  }
  return covered;
}

function provenanceErrors(provenance: any, source: any): string[] {
  const errors: string[] = [];
  const origin = source.data_origin || 'UNKNOWN';
  const expectedReference = ['REAL_EMAIL', 'PUBLIC_CORPUS'].includes(origin) ? source.source_id : null;
  const expectedSyntheticId = origin === 'SYNTHETIC' ? (source.synthetic_case_id || source.source_id) : null;
  if (provenance.data_origin !== origin) errors.push('Provenance origin must match the source.');
  if (provenance.source_reference !== expectedReference) errors.push('Provenance source reference must be server-stamped from the source.');
  if (provenance.synthetic_case_id !== expectedSyntheticId) errors.push('Synthetic case ID must match the source provenance.');
  if (origin === 'SYNTHETIC') {
    if (provenance.annotation_tier !== 'SYNTHETIC') errors.push('Synthetic examples must keep SYNTHETIC provenance.');
    if (!provenance.synthetic_case_id) errors.push('Synthetic examples need a case ID.');
  }
  if (provenance.annotation_tier === 'GOLD') {
    if (!['REAL_EMAIL', 'PUBLIC_CORPUS'].includes(origin)) errors.push('GOLD requires a real or public message.');
    if (!['BLIND_HUMAN', 'AI_ASSISTED_HUMAN'].includes(provenance.annotation_mode)) errors.push('GOLD requires human annotation.');
    if (!String(provenance.annotator_id || '').trim() || !provenance.annotated_at) errors.push('GOLD needs annotator identity and annotation time.');
    if (!provenance.human_review) errors.push('GOLD needs a separate human review.');
    else if (!String(provenance.human_review.reviewer_id || '').trim() || !provenance.human_review.reviewed_at) errors.push('GOLD review needs reviewer identity and time.');
    else if (provenance.human_review.decision === 'rejected') errors.push('A rejected annotation cannot be GOLD.');
    else if (provenance.human_review.reviewer_id === provenance.annotator_id) errors.push('GOLD review must be completed by a different person.');
  }
  if (provenance.annotation_mode === 'BLIND_HUMAN') {
    if (!String(provenance.annotator_id || '').trim() || !provenance.annotated_at) errors.push('Blind human annotation needs annotator identity and time.');
    if (provenance.blind_prelabels_shown !== false) errors.push('Blind human annotation must record that no prelabels were shown.');
    if (provenance.ai_assistance !== null) errors.push('Blind human annotation cannot include AI assistance.');
  } else if (provenance.annotation_mode === 'AI_ASSISTED_HUMAN') {
    if (!String(provenance.annotator_id || '').trim() || !provenance.annotated_at) errors.push('AI-assisted annotation needs annotator identity and time.');
    if (provenance.blind_prelabels_shown !== true) errors.push('AI-assisted annotation must record that prelabels were shown.');
    if (!provenance.ai_assistance || !['accepted', 'modified', 'rejected'].includes(provenance.ai_assistance.human_disposition)) errors.push('AI-assisted annotation needs model details and the human decision.');
  } else if (provenance.annotation_mode === 'AI_ONLY') {
    if (!['SILVER', 'SYNTHETIC'].includes(provenance.annotation_tier)) errors.push('AI-only annotation must stay SILVER or SYNTHETIC.');
    if (!provenance.ai_assistance) errors.push('AI-only annotation needs model and run details.');
    if (provenance.human_review !== null || provenance.annotator_id !== null || provenance.annotated_at !== null || provenance.blind_prelabels_shown !== null) errors.push('AI-only annotation cannot claim human review or presentation.');
  } else if (provenance.annotation_mode === 'RULE_BASED') {
    if (provenance.annotation_tier !== 'SILVER') errors.push('Rule-based annotations must stay SILVER.');
    if (provenance.ai_assistance !== null) errors.push('Rule-based annotations cannot claim model assistance.');
  } else if (provenance.annotation_mode === 'UNANNOTATED') {
    if (provenance.annotation_tier !== 'UNSET' || provenance.annotator_id !== null || provenance.annotated_at !== null) errors.push('Unannotated records must stay UNSET and have no annotator or annotation time.');
    if (provenance.human_review !== null || provenance.ai_assistance !== null || provenance.blind_prelabels_shown !== null) errors.push('Unannotated records cannot claim human review, AI help or blind work.');
  } else if (provenance.annotation_mode === 'SYNTHETIC_GENERATION'
    && (origin !== 'SYNTHETIC' || provenance.annotation_tier !== 'SYNTHETIC')) errors.push('Synthetic generation must remain SYNTHETIC.');
  return errors;
}

export function validateDirect(annotation: any, source: any): string[] {
  const errors = structural(annotation, directSchema).slice(0, 20);
  if (errors.length) return errors;
  const fail = (message: string) => errors.push(message);
  if (!source || annotation.current_source_id !== source.source_id || annotation.record_id !== source.source_id) fail('Wrong current email.');

  const spans = new Map<string, any>();
  const ids = new Set<string>();
  const coordinates = new Set<string>();
  const usedSpanIds = new Set<string>();
  for (const span of annotation.spans) {
    if (ids.has(span.id)) fail('Span IDs must be unique.');
    ids.add(span.id);
    spans.set(span.id, span);
    const fieldText = source?.[span.field];
    const points = typeof fieldText === 'string' ? cp(fieldText) : [];
    if (typeof fieldText !== 'string' || span.end <= span.start || span.end > points.length || points.slice(span.start, span.end).join('') !== span.text) {
      fail(`Evidence ${span.id} must exactly match its source using Unicode code-point offsets.`);
    }
    if (span.field === 'current_message' && !validAuthoredRange(span.start, span.end, source, points.length)) {
      fail(`Evidence ${span.id} must be inside current authored text.`);
    }
    const key = JSON.stringify([span.field, span.type, span.start, span.end]);
    if (coordinates.has(key)) fail('Share an existing span instead of duplicating its source coordinates.');
    coordinates.add(key);
  }

  const readSpanIds = (spanIds: string[], allowedTypes: string[] | null, path: string) => {
    for (const id of spanIds) {
      const span = spans.get(id);
      if (!span) {
        fail(`${path} refers to an unknown span.`);
        continue;
      }
      usedSpanIds.add(id);
      if (allowedTypes && !allowedTypes.includes(span.type)) fail(`${path} references a span type that does not support this label.`);
    }
  };
  readSpanIds(annotation.scope.evidence_span_ids, ['EVIDENCE'], 'scope.evidence_span_ids');
  if (annotation.scope.value === 'UNCERTAIN') {
    if (!annotation.scope.reason.trim()) fail('Uncertain scope needs a reason.');
    if (!annotation.needs_review || !annotation.review_reasons.length) fail('Uncertain scope needs review and a review reason.');
    if (annotation.labels.length || annotation.label_support.length) fail('Uncertain scope cannot have labels or label support.');
    if (annotation.spans.some((span: any) => span.type !== 'EVIDENCE')) fail('Uncertain scope can contain only scope EVIDENCE spans.');
  } else if (annotation.scope.value === 'NON_PROJECT') {
    if (JSON.stringify(annotation.labels) !== JSON.stringify(['NON_PROJECT'])) fail('NON_PROJECT must be the only label.');
    if (annotation.label_support.length) fail('NON_PROJECT cannot have project label support.');
    if (annotation.spans.some((span: any) => span.type !== 'EVIDENCE')) fail('NON_PROJECT can contain only scope EVIDENCE spans.');
    if (annotation.spans.some((span: any) => !annotation.scope.evidence_span_ids.includes(span.id))) fail('NON_PROJECT cannot contain orphan evidence spans.');
  }

  const labelSet = new Set<string>();
  for (const label of annotation.labels) {
    if (labelSet.has(label)) fail('Labels must be unique.');
    labelSet.add(label);
  }
  const supportByLabel = new Map<string, any>();
  const supportAllowedIds = new Set<string>();
  for (const support of annotation.label_support) {
    if (supportByLabel.has(support.label)) fail('Each selected label must have exactly one support row.');
    supportByLabel.set(support.label, support);
    const definition = allowedFieldTypes[support.label] || [];
    readSpanIds(support.evidence_span_ids, ['EVIDENCE'], `${support.label} evidence_span_ids`);
    readSpanIds(support.field_span_ids, definition, `${support.label} field_span_ids`);
    for (const id of support.field_span_ids) supportAllowedIds.add(id);
    if (!support.evidence_span_ids.some((id: string) => {
      const span = spans.get(id);
      return span?.type === 'EVIDENCE' && span.field === 'current_message';
    })) fail(`${support.label} needs a current_message EVIDENCE trigger.`);
    if (support.label !== 'FOLLOW_UP' && support.follow_up_target !== null) fail('Only FOLLOW_UP may set follow_up_target.');
    if (support.label === 'FOLLOW_UP' && !followUpTargets.includes(support.follow_up_target)) fail('FOLLOW_UP needs a valid follow-up target.');
    if (support.label === 'FOLLOW_UP' && support.follow_up_target === 'UNCLEAR' && !support.review_reason.trim()) fail('UNCLEAR follow-up needs a review reason.');
    const required = requiredFieldTypes[support.label] || [];
    const actualTypes = new Set(support.field_span_ids.map((id: string) => spans.get(id)?.type).filter(Boolean));
    const missing = required.filter((group) => group.includes('|')
      ? !group.split('|').some((type) => actualTypes.has(type))
      : !actualTypes.has(group));
    if (support.label === 'DEADLINE' && !support.applies_to.trim()) missing.push('applies_to');
    if (missing.length && !support.review_reason.trim()) fail(`${support.label} is missing ${missing.join(', ')}; explain the waiver in review_reason.`);
    if (missing.length && support.review_reason.trim() && (!annotation.needs_review || !annotation.review_reasons.length)) {
      fail(`${support.label} field waiver needs needs_review and a global review reason.`);
    }
    if (support.review_reason.trim() && (!annotation.needs_review || !annotation.review_reasons.length)) fail(`${support.label} review_reason needs global review.`);
  }
  for (const label of annotation.labels) {
    if (label === 'NON_PROJECT') continue;
    if (!supportByLabel.has(label)) fail(`Selected label ${label} needs one label_support row.`);
  }
  if (annotation.scope.value !== 'NON_PROJECT' && labelSet.has('NON_PROJECT')) fail('NON_PROJECT requires NON_PROJECT scope and is exclusive.');
  for (const label of supportByLabel.keys()) if (!labelSet.has(label)) fail(`Label support ${label} is not selected.`);
  if (annotation.scope.value === 'PROJECT' && annotation.labels.length === 0
    && (!annotation.needs_review || !annotation.review_reasons.length)) fail('A PROJECT record with no selected labels needs review and a reason.');
  for (const span of annotation.spans) if (!usedSpanIds.has(span.id)) fail(`Span ${span.id} is orphaned.`);

  if (annotation.needs_review && !annotation.review_reasons.length) fail('Needs review requires at least one review reason.');
  if (!annotation.needs_review && annotation.review_reasons.length) fail('Clear review reasons or select Needs review.');
  if (annotation.provenance.annotation_tier === 'GOLD'
    && (annotation.provenance.annotation_mode === 'AI_ONLY' || annotation.provenance.data_origin === 'SYNTHETIC')) fail('AI-only or synthetic annotations cannot be GOLD.');
  if (annotation.provenance.annotation_tier === 'GOLD'
    && (annotation.needs_review || annotation.scope.value === 'UNCERTAIN')) fail('Unresolved or needs-review annotations cannot be GOLD.');
  for (const message of provenanceErrors(annotation.provenance, source || {})) fail(message);
  return [...new Set(errors)].slice(0, 20);
}

function stampDirect(input: any, source: any, mode: 'draft' | 'submission', annotatorId?: string, annotatedAt?: string) {
  const stamp = mode === 'draft'
    ? stampUnannotatedDraft(input, source)
    : stampBlindHumanSubmission(input, source, annotatorId || '', annotatedAt || '');
  delete stamp.derived_label_version;
  return stamp;
}

export function stampDirectDraft(input: any, source: any) {
  return stampDirect(input, source, 'draft');
}

export function stampDirectSubmission(input: any, source: any, annotatorId: string, annotatedAt: string) {
  return stampDirect(input, source, 'submission', annotatorId, annotatedAt);
}
