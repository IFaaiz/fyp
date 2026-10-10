import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import ts from 'typescript';

const root = path.resolve('.');
const timestamp = '2026-10-06T00:00:00.000Z';

function loadTs(relative, mocks = {}) {
  const filename = path.resolve(relative);
  const source = fs.readFileSync(filename, 'utf8');
  const js = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      esModuleInterop: true,
      resolveJsonModule: true,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const mod = new Module(filename);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const originalRequire = mod.require.bind(mod);
  mod.require = (request) => Object.hasOwn(mocks, request) ? mocks[request] : originalRequire(request);
  mod._compile(js, filename);
  return mod.exports;
}

const legacy = loadTs('lib/annotation.ts');
const direct = loadTs('lib/direct-annotation.ts', { './annotation': legacy });
const reviewFormat = loadTs('lib/review-format.ts', {
  './annotation': legacy,
  './direct-annotation': direct,
});

const source = {
  id: 'fixture-email-1',
  source_id: 'fixture-email-1',
  subject: 'Project report due Friday',
  body: 'Please send the revised report by Friday.',
  source_json: JSON.stringify({
    authored_ranges: [{ start: 0, end: Array.from('Please send the revised report by Friday.').length }],
    data_origin: 'PUBLIC_CORPUS',
  }),
  sha256: 'fixture-sha256',
  allocation: 'calibration_training',
  common_blind: 0,
  owner_slot: 0,
};
const publicSource = {
  source_id: source.source_id,
  subject: source.subject,
  current_message: source.body,
  authored_ranges: JSON.parse(source.source_json).authored_ranges,
  data_origin: 'PUBLIC_CORPUS',
};
const cp = direct.cp;
function span(field, text, type, id) {
  const points = cp(publicSource[field]);
  const start = points.join('').indexOf(text);
  assert.notEqual(start, -1, `fixture phrase ${text}`);
  return { id, field, start: cp(points.join('').slice(0, start)).length, end: cp(points.join('').slice(0, start)).length + cp(text).length, text, type };
}
function annotation() {
  const scopeEvidence = span('subject', 'Project', 'EVIDENCE', 'scope');
  const trigger = span('current_message', 'Please send', 'EVIDENCE', 'trigger');
  const document = span('current_message', 'revised report', 'REQUESTED_DOCUMENT', 'document');
  const date = span('current_message', 'Friday', 'DEADLINE_DATE', 'date');
  return {
    schema_version: direct.directVersion,
    record_id: source.source_id,
    current_source_id: source.source_id,
    scope: { value: 'PROJECT', reason: '', evidence_span_ids: ['scope'] },
    labels: ['REPORT_REQUEST', 'DEADLINE'],
    spans: [scopeEvidence, trigger, document, date],
    label_support: [
      { label: 'REPORT_REQUEST', evidence_span_ids: ['trigger'], field_span_ids: ['document'], applies_to: '', follow_up_target: null, review_reason: '' },
      { label: 'DEADLINE', evidence_span_ids: ['trigger'], field_span_ids: ['date'], applies_to: 'revised report', follow_up_target: null, review_reason: '' },
    ],
    needs_review: false,
    review_reasons: [],
    provenance: {},
  };
}

let checks = 0;
const preserve = {
  schema_version: 'fyp-structured-v1',
  derived_label_version: 'fyp-derived-labels-1.0',
  record_id: source.source_id,
  current_source_id: source.source_id,
  scope: { value: 'UNCERTAIN', evidence_span_ids: [], reason: '' },
  spans: [], events: [], event_span_links: [], event_relations: [],
  needs_review: false, review_reasons: [], provenance: {},
};
const preserved = reviewFormat.prepareReview(structuredClone(preserve), publicSource, preserve, 'draft', 'reviewer-0', timestamp).annotation;
assert.equal(preserved.schema_version, 'fyp-structured-v1');
assert.equal(preserved.derived_label_version, 'fyp-derived-labels-1.0');
assert.equal(preserved.provenance.annotation_mode, 'UNANNOTATED');
assert.equal('labels' in preserved, false);
checks += 4;
assert.throws(
  () => reviewFormat.prepareReview(annotation(), publicSource, preserve, 'draft', 'reviewer-0', timestamp),
  (error) => error.status === 409,
);
assert.throws(
  () => reviewFormat.prepareReview(preserve, publicSource, annotation(), 'draft', 'reviewer-0', timestamp),
  (error) => error.status === 409,
);
checks += 2;

const { setDirectScope } = loadTs('lib/direct-ui-state.ts');
const relevanceSpan = { id: 'relevance', field: 'current_message', start: 0, end: 7, text: 'Project', type: 'EVIDENCE' };
const initialScope = {
  scope: { value: 'UNCERTAIN', evidence_span_ids: ['relevance'] },
  labels: [], label_support: [], spans: [structuredClone(relevanceSpan)],
  needs_review: true, review_reasons: ['Project relevance has not been decided.'],
};
setDirectScope(initialScope, 'PROJECT');
assert.equal(initialScope.needs_review, false);
assert.deepEqual(initialScope.review_reasons, []);
const changedScope = {
  scope: { value: 'NON_PROJECT', evidence_span_ids: ['relevance'] },
  labels: ['NON_PROJECT'], label_support: [], spans: [structuredClone(relevanceSpan)],
  needs_review: false, review_reasons: [],
};
setDirectScope(changedScope, 'PROJECT');
assert.deepEqual(changedScope.labels, []);
assert.deepEqual(changedScope.spans.map((item) => item.id), ['relevance']);
const userNote = {
  scope: { value: 'PROJECT', evidence_span_ids: ['relevance'] },
  labels: ['REPORT_REQUEST'],
  label_support: [{ label: 'REPORT_REQUEST', evidence_span_ids: ['trigger'], field_span_ids: ['document'], review_reason: '' }],
  spans: [structuredClone(relevanceSpan), { id: 'trigger' }, { id: 'document' }],
  needs_review: true, review_reasons: ['Attachment identity needs adjudication.'],
};
setDirectScope(userNote, 'NON_PROJECT');
assert.deepEqual(userNote.labels, ['NON_PROJECT']);
assert.deepEqual(userNote.label_support, []);
assert.deepEqual(userNote.spans.map((item) => item.id), ['relevance']);
assert.deepEqual(userNote.review_reasons, ['Attachment identity needs adjudication.']);
assert.equal(userNote.needs_review, true);
setDirectScope(userNote, 'PROJECT');
assert.deepEqual(userNote.labels, []);
assert.deepEqual(userNote.review_reasons, ['Attachment identity needs adjudication.']);
assert.equal(userNote.needs_review, true);
checks += 13;

function reviewDatabase({ row = null, legacyRow = null, oldDirectRow = null, concurrentReads = false } = {}) {
  const state = { row: row && structuredClone(row), legacyRow: legacyRow && structuredClone(legacyRow), oldDirectRow: oldDirectRow && structuredClone(oldDirectRow), reads: 0, writeSql: [] };
  let releaseReads;
  const barrier = new Promise((resolve) => { releaseReads = resolve; });
  const db = {
    prepare(sql) {
      return {
        sql,
        values: [],
        bind(...values) { this.values = values; return this; },
        async first() {
          if (this.sql.includes('SELECT s.* FROM sources')) return this.values[0] === source.id ? { ...source } : null;
          if (this.sql.startsWith('SELECT revision,status,annotation_json FROM direct_label_reviews')) {
            const snapshot = state.row && structuredClone(state.row);
            if (concurrentReads) {
              state.reads++;
              if (state.reads === 2) releaseReads();
              await barrier;
            }
            return snapshot;
          }
          if (this.sql.startsWith('SELECT revision,status,annotation_json FROM direct_reviews')) return state.oldDirectRow && structuredClone(state.oldDirectRow);
          if (this.sql.startsWith('SELECT revision,status,annotation_json FROM reviews')) return state.legacyRow && structuredClone(state.legacyRow);
          throw new Error(`Unexpected first query: ${this.sql}`);
        },
      };
    },
    async batch(statements) {
      const write = statements[0];
      state.writeSql.push(write.sql);
      let changes = 0;
      if (write.sql.startsWith('UPDATE direct_label_reviews')) {
        const [annotationJson, status, revision, activeMs, updatedAt, submittedAt, sourceId, userId, oldRevision] = write.values;
        if (state.row?.source_id === sourceId && state.row?.user_id === userId && state.row.revision === oldRevision && state.row.status === 'draft') {
          Object.assign(state.row, { annotation_json: annotationJson, status, revision, active_ms: state.row.active_ms + activeMs, updated_at: updatedAt, submitted_at: submittedAt });
          changes = 1;
        }
      } else if (write.sql.startsWith('INSERT OR IGNORE INTO direct_label_reviews')) {
        const [sourceId, userId, annotationJson, status, revision, activeMs, createdAt, updatedAt, submittedAt] = write.values;
        if (!state.row) {
          state.row = { source_id: sourceId, user_id: userId, annotation_json: annotationJson, status, revision, active_ms: activeMs, created_at: createdAt, updated_at: updatedAt, submitted_at: submittedAt };
          changes = 1;
        }
      } else {
        throw new Error(`Unexpected write query: ${write.sql}`);
      }
      return [{ meta: { changes } }, { meta: { changes: 0 } }];
    },
  };
  return { db, state };
}

const reviewer = { userId: 'reviewer-0', email: 'reviewer0@example.test', displayName: 'Reviewer 0', slot: 0, isAdmin: false };
function loadReviewRoute(mockDb) {
  return loadTs('app/api/review/route.ts', {
    '../../../lib/database': {
      db: () => mockDb,
      reviewer: async () => reviewer,
      result: (body, status = 200) => Response.json(body, { status }),
      failed: (error) => Response.json({ error: error?.message || 'failed' }, { status: error?.status || 503 }),
      requireSameOrigin: () => {},
    },
    '../../../lib/review-format': reviewFormat,
    '../../../lib/round': { assignedSQL: 's.owner_slot=?' },
    '../../../lib/direct-annotation': direct,
  });
}
function postBody(record, revision, status = 'submitted') {
  return new Request('https://review.test/api/review', {
    method: 'POST',
    headers: { 'content-type': 'application/json', origin: 'https://review.test' },
    body: JSON.stringify({ source_id: source.id, annotation: record, revision, status, human_attestation: status === 'submitted', active_ms: 1200 }),
  });
}

const submittedStore = reviewDatabase({
  legacyRow: { source_id: source.id, user_id: reviewer.userId, annotation_json: JSON.stringify(preserve), status: 'draft', revision: 5, active_ms: 90 },
  oldDirectRow: { source_id: source.id, user_id: reviewer.userId, annotation_json: JSON.stringify({ schema_version: 'fyp-direct-label-v1', marker: 'preserve-v1-draft' }), status: 'draft', revision: 7, active_ms: 35 },
});
const reviewRoute = loadReviewRoute(submittedStore.db);
const firstSubmit = await reviewRoute.POST(postBody(annotation(), 0));
assert.equal(firstSubmit.status, 200);
assert.equal(submittedStore.state.row.status, 'submitted');
assert.equal(JSON.parse(submittedStore.state.row.annotation_json).schema_version, direct.directVersion);
assert.equal(submittedStore.state.legacyRow.revision, 5);
assert.equal(submittedStore.state.legacyRow.status, 'draft');
assert.equal(JSON.parse(submittedStore.state.oldDirectRow.annotation_json).marker, 'preserve-v1-draft');
assert.equal(submittedStore.state.oldDirectRow.revision, 7);
const frozenAttempt = await reviewRoute.POST(postBody(annotation(), 1));
assert.equal(frozenAttempt.status, 409);
assert.equal(submittedStore.state.row.revision, 1);
assert.equal(submittedStore.state.legacyRow.revision, 5);
checks += 9;

const staleV1Store = reviewDatabase({
  oldDirectRow: { source_id: source.id, user_id: reviewer.userId, annotation_json: JSON.stringify({ schema_version: 'fyp-direct-label-v1', marker: 'preserve-v1-draft' }), status: 'draft', revision: 7, active_ms: 35 },
});
const staleV1 = structuredClone(annotation());
staleV1.schema_version = 'fyp-direct-label-v1';
const staleV1Response = await loadReviewRoute(staleV1Store.db).POST(postBody(staleV1, 7, 'draft'));
assert.equal(staleV1Response.status, 409);
assert.equal(staleV1Store.state.row, null);
assert.equal(staleV1Store.state.oldDirectRow.revision, 7);
assert.equal(staleV1Store.state.writeSql.length, 0);
checks += 4;

const archivedV1Row = {
  source_id: source.id,
  user_id: reviewer.userId,
  annotation_json: JSON.stringify({ schema_version: 'fyp-direct-label-v1', marker: 'archived-v1' }),
  status: 'draft',
  revision: 7,
};
const emailQueries = [];
const emailDb = {
  prepare(sql) {
    return {
      sql,
      values: [],
      bind(...values) { this.values = values; return this; },
      async first() {
        emailQueries.push(this.sql);
        if (this.sql.includes('SELECT s.* FROM sources')) return { ...source };
        if (this.sql.includes('FROM direct_reviews')) return { ...archivedV1Row };
        if (this.sql.includes('FROM reviews')) return { status: 'draft' };
        throw new Error(`Unexpected email query: ${this.sql}`);
      },
    };
  },
};
const emailRoute = loadTs('app/api/email/route.ts', {
  '../../../lib/database': {
    db: () => emailDb,
    reviewer: async () => reviewer,
    result: (body, status = 200) => Response.json(body, { status }),
    failed: (error) => Response.json({ error: error?.message || 'failed' }, { status: error?.status || 503 }),
  },
  '../../../lib/round': { assignedSQL: 's.owner_slot=?' },
});
const archivedResponse = await emailRoute.GET(new Request(`https://review.test/api/email?id=${source.id}&format=direct-v1`));
assert.equal(archivedResponse.status, 200);
const archivedPayload = await archivedResponse.json();
assert.equal(archivedPayload.annotation.schema_version, 'fyp-direct-label-v1');
assert.equal(archivedPayload.annotation.marker, 'archived-v1');
assert.equal(archivedPayload.read_only, true);
assert.ok(emailQueries.some((query) => query.includes('FROM direct_reviews')));
assert.equal(emailQueries.some((query) => /\b(INSERT|UPDATE|DELETE)\b/i.test(query)), false);
checks += 6;

const concurrentStore = reviewDatabase({
  row: { source_id: source.id, user_id: reviewer.userId, annotation_json: JSON.stringify(direct.stampDirectDraft(annotation(), publicSource)), status: 'draft', revision: 0, active_ms: 0 },
  concurrentReads: true,
});
const concurrentRoute = loadReviewRoute(concurrentStore.db);
const concurrent = await Promise.all([
  concurrentRoute.POST(postBody(annotation(), 0, 'draft')),
  concurrentRoute.POST(postBody(annotation(), 0, 'draft')),
]);
assert.deepEqual(concurrent.map((response) => response.status).sort(), [200, 409]);
assert.equal(concurrentStore.state.row.revision, 1);
assert.equal(concurrentStore.state.writeSql.length, 2);
checks += 3;

const queueQueries = [];
const queueDb = {
  prepare(sql) {
    return {
      sql,
      values: [],
      bind(...values) { this.values = values; return this; },
      async all() {
        queueQueries.push(this.sql);
        return { results: [{ id: 'shared-first', round_member: 1 }, { id: 'assigned-later', round_member: 0 }] };
      },
    };
  },
};
const queueRoute = loadTs('app/api/queue/route.ts', {
  '../../../lib/database': {
    db: () => queueDb,
    reviewer: async () => reviewer,
    result: (body, status = 200) => Response.json(body, { status }),
    failed: (error) => Response.json({ error: error?.message || 'failed' }, { status: error?.status || 503 }),
  },
  '../../../lib/round': { assignedSQL: 's.owner_slot=?', roundAssignedSQL: 'EXISTS(SELECT 1 FROM calibration_round_sources cr WHERE cr.source_id=s.id)', prepareRound: async () => 30 },
});
const queueResponse = await queueRoute.GET(new Request('https://review.test/api/queue'));
assert.equal(queueResponse.status, 200);
assert.ok(queueQueries[0].includes('LEFT JOIN direct_label_reviews'));
assert.match(queueQueries[0], /ORDER BY round_member DESC,s\.position/);
assert.ok(!queueQueries[0].includes('LEFT JOIN direct_reviews'));
checks += 4;

const roundModule = loadTs('lib/round.ts');
let roundRows = 0;
let inserts = 0;
let insertedSql = '';
const roundDb = {
  prepare(sql) {
    return {
      sql,
      values: [],
      bind(...values) { this.values = values; return this; },
      async first() {
        if (this.sql.startsWith('SELECT COUNT(*) n FROM calibration_round_sources')) return { n: roundRows };
        if (this.sql.includes('SUM(common_blind=1)')) return { shared: 24, train: 8 };
        throw new Error(`Unexpected round query: ${this.sql}`);
      },
      async run() {
        inserts++;
        insertedSql = this.sql;
        assert.equal(this.values[0], roundModule.roundId);
        roundRows = 30;
        return { meta: { changes: 30 } };
      },
    };
  },
};
assert.equal(await roundModule.prepareRound(roundDb), 30);
assert.equal(await roundModule.prepareRound(roundDb), 30);
assert.equal(inserts, 1);
assert.match(insertedSql, /common_blind=1 OR id IN/);
assert.match(insertedSql, /allocation='calibration_training' AND common_blind=0 ORDER BY position LIMIT 6/);
assert.doesNotMatch(insertedSql, /labeler_human_holdout/);
assert.match(roundModule.roundAssignedSQL, /source_sha256=s\.sha256/);
checks += 7;

const adminEnv = { ADMIN_EMAIL: 'owner@example.test' };
const exportOwner = { email: 'owner@example.test' };
let exportMode = 'incomplete';
let exportQueries = [];
const exportDb = {
  prepare(sql) {
    return {
      sql,
      values: [],
      bind(...values) { this.values = values; return this; },
      async first() {
        exportQueries.push(this.sql);
        if (this.sql.includes('COUNT(*) n,SUM')) return { n: 25, invalid: 0 };
        throw new Error(`Unexpected export first query: ${this.sql}`);
      },
      async all() {
        exportQueries.push(this.sql);
        if (this.sql.includes('LEFT JOIN direct_label_reviews')) return { results: exportMode === 'incomplete'
          ? [{ user_id: 'u0', display_name: 'R0', slot: 0, submitted: 25 }, { user_id: 'u1', display_name: 'R1', slot: 1, submitted: 24 }, { user_id: 'u2', display_name: 'R2', slot: 2, submitted: 25 }]
          : [{ user_id: 'u0', display_name: 'R0', slot: 0, submitted: 25 }, { user_id: 'u1', display_name: 'R1', slot: 1, submitted: 25 }, { user_id: 'u2', display_name: 'R2', slot: 2, submitted: 24 }] };
        if (this.sql.includes('JOIN calibration_round_sources cr')) return { results: Array.from({ length: 25 }, (_, i) => ({
          source_id: `round-${i + 1}`, subject: `Synthetic source ${i + 1}`, current_message: 'Synthetic test only',
          source_json: '{"authored_ranges":[]}', allocation: i < 24 ? 'blind_agreement' : 'calibration_training',
          source_sha256: `hash-${i + 1}`, position: i + 1,
        })) };
        if (this.sql.includes('FROM direct_label_reviews WHERE status')) return { results: this.values.slice(1).flatMap((userId) => Array.from({ length: 25 }, (_, i) => ({ source_id: `round-${i + 1}`, user_id: userId, status: 'submitted', annotation_json: JSON.stringify({ schema_version: direct.directVersion }) }))) };
        throw new Error(`Unexpected export all query: ${this.sql}`);
      },
    };
  },
};
const exportRoute = loadTs('app/api/admin/export/route.ts', {
  'cloudflare:workers': { env: adminEnv },
  '../../../../lib/database': {
    db: () => exportDb,
    identity: async () => exportOwner,
    result: (body, status = 200) => Response.json(body, { status }),
    failed: (error) => Response.json({ error: error?.message || 'failed' }, { status: error?.status || 503 }),
  },
  '../../../../lib/round': { roundId: roundModule.roundId },
});
let exported = await exportRoute.GET();
assert.equal(exported.status, 409);
assert.ok(exportQueries.some((query) => query.includes('LEFT JOIN direct_label_reviews')));
assert.ok(!exportQueries.some((query) => query.includes('FROM direct_label_reviews WHERE status')));
exportMode = 'complete-first-two';
exportQueries = [];
exported = await exportRoute.GET();
assert.equal(exported.status, 200);
const exportPayload = await exported.json();
assert.equal(exportPayload.schema_version, 'fyp-calibration-export-v2');
assert.equal(exportPayload.sources.length, 25);
assert.deepEqual(exportPayload.reviewers.map((person) => person.slot), [0, 1]);
assert.equal(exportPayload.reviews.length, 50);
assert.ok(exportPayload.sources.every((item) => item.allocation !== 'labeler_human_holdout'));
assert.ok(exportQueries.some((query) => query.includes('cr.source_sha256=s.sha256')));
assert.ok(exportQueries.some((query) => query.includes('FROM direct_label_reviews WHERE status')));
checks += 10;

console.log(JSON.stringify({ suite: 'direct-api', checks, legacy_rows_read: 0, stored_human_responses_read: 0 }));
