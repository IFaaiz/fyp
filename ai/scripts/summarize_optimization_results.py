"""Consolidate completed optimization artifacts; never train or predict on TEST."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

AI = Path(__file__).resolve().parents[1]
REPORTS = AI / 'reports'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first(record, *keys):
    return next((record[k] for k in keys if record.get(k) is not None), None)


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                     ['| ' + ' | '.join(str(v) for v in row) + ' |' for row in rows])


def fmt(value):
    return 'unmeasured' if value is None else f'{value:.4f}'


def main():
    families = {name: read(REPORTS / f'optimization_{name}.json')
                for name in ['reference', 'lexical', 'embeddings', 'transformer', 'ensemble']}
    selection = read(AI / 'annotation/optimization_final_selection.json')
    final = read(REPORTS / 'optimization_final_test.json')
    verification = read(REPORTS / 'optimization_final_verification.json')
    benchmark = read(AI / 'annotation/optimization_benchmark.json')
    pseudo = read(REPORTS / 'optimization_pseudo_screen.json')
    locked = {r['run_id']: r for r in selection['candidates']}
    tests = {r['run_id']: r for r in final['results']}
    entries = []

    def add(family, raw, stage='development', parent=None):
        rid = raw['run_id']
        metrics = first(raw, 'dev_metrics', 'dev', 'dev_metrics_fixed_0_5')
        if family == 'transformer' and stage == 'development':
            metrics = raw['dev_metrics_fixed_0_5']
        entry = {
            'registry_id': rid + ('__train_oof_final' if stage == 'train_oof_calibration' else ''),
            'run_id': rid, 'family': family, 'stage': stage, 'parent_run_id': parent,
            'model': raw.get('model'), 'features': raw.get('features'),
            'training_records': first(raw, 'training_records', 'train_records', 'train_oof_records'),
            'dev_records': raw.get('dev_records'), 'seed': raw.get('seed', 20261004),
            'hyperparameters': raw.get('hyperparameters'), 'loss': raw.get('loss'),
            'class_weighting': first(raw, 'class_weighting', 'class_weight', 'fit_only_weight_report'),
            'threshold_method': first(raw, 'threshold_method', 'threshold_source'),
            'thresholds': first(raw, 'thresholds', 'oof_thresholds', 'thresholds_train_oof_only'),
            'dev_metrics': metrics,
            'training_seconds': first(raw, 'training_seconds_including_oof', 'training_time_seconds',
                                      'training_seconds', 'training_seconds_dev_refit'),
            'training_time_definition': 'See source_record: includes OOF only when explicitly stated; no inferred total.',
            'inference_seconds_per_record': raw.get('inference_seconds_per_record'),
            'model_size_bytes': first(raw, 'model_size_bytes', 'model_package_size_bytes', 'package_size_bytes'),
            'size_or_latency_estimates_are_separate': True,
            'test_metrics': None, 'source_record': raw,
        }
        if entry['training_records'] is None:
            entry['training_records'] = (raw.get('hyperparameters') or {}).get('training_records')
        if parent is not None:
            source_parent = next(r for r in families[family]['runs'] if r['run_id'] == parent)
            entry['model'] = source_parent['model']
            entry['features'] = source_parent['features']
        if family == 'lexical':
            if entry['training_records'] is None:
                entry['training_records'] = families['lexical']['partitions']['train']
                entry['training_records_provenance'] = 'All-TRAIN screen fit verified in run_optimization_lexical.py; original entry omitted count.'
            entry['model_size_estimated_bytes'] = raw.get('model_size_estimated_bytes')
            if raw.get('inference_time_ms_per_record') is not None:
                entry['inference_seconds_per_record'] = raw['inference_time_ms_per_record'] / 1000
            if 'dependency' in rid and entry['training_seconds'] == 0:
                entry['training_seconds'] = None
                entry['training_time_definition'] = 'Dependency source report has a zero placeholder; total fit time was not measured.'
            entry['loss'] = ('component logistic/squared-hinge losses' if 'specialists' in rid else
                             'log loss' if 'logistic' in raw['model'] or 'dependency' in rid else 'squared hinge')
            entry['implementation_defaults'] = {
                'estimator_random_state': 42, 'word_min_df': 1, 'char_min_df': 2,
                'max_features_per_text_channel': 120000, 'subject_weight': 1.5,
                'sublinear_tf': True, 'LR_solver': 'liblinear', 'LR_max_iter': 1200,
                'SVC_max_iter': 3000, 'tol': 1e-4,
            }
        if family == 'embeddings':
            if 'class_weight' in (raw.get('hyperparameters') or {}) and raw['hyperparameters']['class_weight'] is None:
                entry['class_weighting'] = 'none'
            if rid == 'per_label_specialists':
                entry['class_weighting'] = 'Per selected source head; GENERAL_UPDATE cap3, others unweighted.'
            if entry['hyperparameters'] is None and 'method' in raw:
                entry['hyperparameters'] = {k: raw.get(k) for k in ['method', 'C', 'weighting', 'mode', 'feature']}
            if entry['training_seconds'] is None and raw.get('oof_cv_training_seconds') is not None and raw.get('full_train_seconds') is not None:
                entry['training_seconds'] = raw['oof_cv_training_seconds'] + raw['full_train_seconds']
                entry['training_time_definition'] = 'Measured OOF head fits plus all-TRAIN head fit; frozen encoder feature cache creation is separate.'
            entry['head_inference_ms_per_record'] = first(raw, 'head_inference_ms_per_record', 'dev_head_inference_ms_per_record', 'dev_inference_ms_per_record')
            entry['estimated_end_to_end_ms_per_record'] = raw.get('estimated_end_to_end_ms_per_record')
        if family == 'transformer' and stage == 'development':
            entry['inference_seconds_per_record'] = raw['inference_ms_per_record_dev'] / 1000
            entry['thresholds'] = [0.5] * 9
            entry['threshold_method'] = 'fixed 0.5 screen; exploratory DEV-tuned metrics retained separately in source_record'
        if rid in locked and not (family == 'transformer' and stage == 'development'):
            entry['frozen_candidate'] = locked[rid]
            entry['dev_metrics'] = locked[rid]['dev_metrics']
            entry['model_size_bytes'] = locked[rid]['model_size_bytes']
            entry['test_metrics'] = tests[rid]['test_metrics']
            entry['test_cold_load_seconds_per_record'] = tests[rid]['inference_seconds_per_record_with_cold_load']
            entry['normalization_notes'] = []
            if raw.get('model_size_bytes') is not None and raw['model_size_bytes'] != entry['model_size_bytes']:
                entry['normalization_notes'].append({
                    'field': 'model_size_bytes', 'historical_source_value': raw['model_size_bytes'],
                    'authoritative_frozen_value': entry['model_size_bytes'],
                    'reason': 'Before TEST, the lock recomputed the size by enumerating unique referenced inference files, including bundle/config/tokenizer/external encoder files. Historical source aggregates are retained verbatim, not used as the final size.',
                })
            if rid == selection['reference_run_id'] and metrics['scope_classification'] != entry['dev_metrics']['scope_classification']:
                entry['normalization_notes'].append({
                    'field': 'dev_metrics.scope_classification',
                    'reason': 'The historical reference scope metric counted two empty DEV outputs as NON_PROJECT. The standardized pre-TEST lock counts empty flat outputs as PROJECT (NON_PROJECT versus otherwise), matching every other final candidate. Decoded predictions and all nine-label/per-label metrics are unchanged.',
                })
        entries.append(entry)

    for family, data in families.items():
        for raw in data['runs']:
            add(family, raw)
    e = families['embeddings']
    for raw in e['additional_ablations']:
        add('embeddings', raw)
    add('embeddings', e['contrastive_fewshot']['run'])
    specialist = dict(e['per_label_specialists'])
    specialist.update(model='MiniLM per-label specialist heads', features=specialist['selected_heads'],
                      training_records=462, dev_records=104,
                      hyperparameters={'selected_heads': specialist['selected_heads']},
                      loss='component LR/MLP losses',
                      threshold_method='five-fold grouped TRAIN OOF per-label F1')
    add('embeddings', specialist)
    for raw in families['transformer']['final_candidates']:
        add('transformer', raw, 'train_oof_calibration', raw['run_id'])
    assert len(entries) == 293, len(entries)
    assert len({r['registry_id'] for r in entries}) == len(entries)
    assert sum(r['test_metrics'] is not None for r in entries) == 5
    counts = dict(Counter(r['family'] for r in entries))
    registry = {
        'metric_provenance': final['metric_provenance'], 'benchmark_sha256': final['benchmark_sha256'],
        'selection_sha256': final['selection_sha256'], 'entries': len(entries), 'family_counts': counts,
        'count_definition': 'DEV configurations and final OOF calibration stages, not independent experiments or individual CV fits; duplicate exports are not additional runs.',
        'missing_field_policy': 'null means unavailable in the source record; explicit estimates and component/cache timings remain in source_record. Final frozen candidates have exact referenced-file sizes and measured cold-load TEST throughput.',
        'source_files_sha256': {f'optimization_{k}.json': sha(REPORTS / f'optimization_{k}.json') for k in families},
        'runs': entries,
    }
    (REPORTS / 'optimization_experiment_registry.json').write_text(json.dumps(registry, indent=2) + '\n', encoding='utf-8', newline='\n')

    audits = [read(REPORTS / f'optimization_test_error_audit_{reviewer}.json') for reviewer in ['root', 'luna']]
    audit_rows = [r for d in audits for r in d['audits']]
    assert all(d['all_assigned_sources_read'] and not d['frozen_references_or_models_changed'] for d in audits)
    errors = read(AI / 'data/experiments/optimization_20261002/final_test/ensemble_blend_1_0_3_0_errors.json')
    # Validate complete disjoint audit coverage against the saved error artifact, not new inference.
    error_rows = errors if isinstance(errors, list) else errors['errors']
    assert {r['email_id'] for r in audit_rows} == {r['email_id'] for r in error_rows}
    assert len(audit_rows) == len({r['email_id'] for r in audit_rows}) == 46
    error_by_id = {r['email_id']: r for r in error_rows}
    for row in audit_rows:
        original = error_by_id[row['email_id']]
        for field in ['expected_labels', 'predicted_labels']:
            assert set(row[field]) == set(original[field]), (row['email_id'], field)
    category_counts = Counter(r['error_category'] for r in audit_rows)
    ambiguous = sum(bool(r['reference_ambiguity']) for r in audit_rows)

    names = ['Original TF-IDF reference', 'Lexical specialists', 'MiniLM specialists',
             'DistilBERT focal gamma=2', 'DEV-selected ensemble']
    specs = selection['candidates']
    main_rows = []
    for name, s in zip(names, specs):
        m = tests[s['run_id']]['test_metrics']; d = s['dev_metrics']
        main_rows.append([name, fmt(d['micro_f1']), fmt(d['macro_f1']), fmt(m['micro_f1']),
                          fmt(m['macro_f1']), fmt(m['exact_set_accuracy']), fmt(m['hamming_loss'])])
    primary = tests[selection['primary_run_id']]['test_metrics']
    reference = tests[selection['reference_run_id']]['test_metrics']
    parts = [r'''# AI-silver model optimization — 2 October 2026

**AI-SILVER DIAGNOSTIC PERFORMANCE. Zero human classification labels.**

## Result and decision

The requested large improvement did not materialize on the frozen TEST set. The DEV-selected ensemble reaches **0.6522 micro / 0.4117 macro F1**; the freshly trained original TF-IDF reference reaches **0.6982 / 0.4033 on the same TEST records**. The ensemble gains only 0.0084 macro F1 and loses 0.0460 micro F1. Neither achieves both micro >=0.70 and macro >=0.45–0.50. The ensemble remains the preselected diagnostic candidate; TEST has not been used to replace it, adjust thresholds, or change labels. Preserve the simpler reference as a reusable comparator.

There is a usable, frozen training benchmark and saved inference pipeline, but this is not a reliable project-function classifier yet. ACTION_REQUEST regression is serious: the ensemble recalls only **1 of 17** TEST actions, versus **10 of 17** for the reference. DEV gains from many configurations and per-label choices did not generalize.

## Data, splits, and isolation

The source is 668 eligible, real Enron emails with audited AI-silver classifications. Six ambiguous references excluded before this sprint remain excluded; the historical 674-row artifact is unchanged. There are no synthetic training rows and no new human labels. The new approximately 70/15/15 split contains TRAIN **462**, DEV **104**, TEST **102**, seed **20261004**; inner grouping seed **20261005**. Complete ID coverage, source-qualified threads, leakage groups, and known near-copy components were verified. The 41 eligible known near-copy pairs remain within partitions; another pair has an excluded endpoint. All 102 TEST rows have distinct thread/leakage components. Five TRAIN OOF folds contain 92/93/93/92/92 records and every label has a positive in each fold.

The previously inspected 138-row historical validation set is excluded from new TEST by IDs, threads and leakage components; 132 still-eligible members may be in TRAIN/DEV. All current models start fresh from base/pretrained checkpoints rather than old fine-tuned weights. This guards model-selection leakage within this sprint. The source population and AI reference labels were previously audited; this is not a newly collected independent population or human gold test.

Historical scores around 0.626 micro / 0.363 macro are context from a different split and cannot be treated as the fair baseline. The new original-model reference is the matched comparison above.
''']
    labels = list(primary['per_label'])
    parts.append(table(['Label', 'TRAIN', 'DEV', 'TEST'],
                       [[lab, specs[0]['threshold_details'][lab]['tuning_positive_support'],
                         specs[0]['dev_metrics']['per_label'][lab]['support'],
                         primary['per_label'][lab]['support']] for lab in labels]))
    parts.append(f'''\nFrozen benchmark SHA256: `{final['benchmark_sha256']}`. TEST source SHA256: `{final['test_sha256']}`. Selection SHA256: `{final['selection_sha256']}`.\n
The split builder reproduces the saved membership; training APIs refuse sealed TEST. Thresholds for final candidates maximize per-label binary F1 using grouped TRAIN OOF scores, with NON_PROJECT exclusivity applied at decode. Those OOF threshold-selection scores are diagnostic rather than an unbiased extra evaluation. DEV macro F1 is the primary candidate-selection metric; micro F1 is secondary. DEV is selection-biased after the extensive screen. Five materially different candidates were locked and committed at **50ddec49e48f715c1d90a717c74581a528ee11c8**, before any final TEST prediction/error inspection. The one-pass evaluation marker is completed and refuses another evaluation.\n
## Locked candidate results\n''')
    parts.append(table(['Candidate', 'DEV micro', 'DEV macro', 'TEST micro', 'TEST macro', 'TEST exact set', 'TEST Hamming loss'], main_rows))
    parts.append('\nFull TEST precision and recall (nine labels, zero division = 0):\n')
    parts.append(table(['Candidate', 'Micro P', 'Micro R', 'Macro P', 'Macro R', 'Project-function macro (8)', 'Specific-function macro (7)'],
                       [[n] + [fmt(tests[s['run_id']]['test_metrics'][k]) for k in ['micro_precision', 'micro_recall', 'macro_precision', 'macro_recall', 'project_function_macro_f1', 'specific_function_macro_f1']] for n,s in zip(names,specs)]))
    parts.append('\nEight-function macro excludes NON_PROJECT; seven-function macro also excludes GENERAL_UPDATE. All seven specific-function TEST supports are below 20; four rare labels have only 1–3 positives. Do not interpret a single rare-label success as stable accuracy.\n')
    best_rows = []
    for lab in labels:
        n, s = max(zip(names, specs), key=lambda pair: tests[pair[1]['run_id']]['test_metrics']['per_label'][lab]['f1'])
        p = tests[s['run_id']]['test_metrics']['per_label'][lab]
        best_rows.append([lab, n, fmt(p['f1']), p['support']])
    parts.append('### Highest observed per-label TEST F1\n\nThis is a descriptive comparison of the five locked candidates. These TEST winners were not assembled into a new model or used to change selection.\n')
    parts.append(table(['Label', 'Highest observed candidate', 'TEST F1', 'Support'], best_rows))
    for name, s in zip(names, specs):
        parts.append(f'### {name}: TEST per label\n')
        parts.append(table(['Label', 'Support', 'Predicted', 'Precision', 'Recall', 'F1'],
                           [[lab, p['support'], p['predicted'], fmt(p['precision']), fmt(p['recall']), fmt(p['f1'])] for lab,p in tests[s['run_id']]['test_metrics']['per_label'].items()]))
    ci = verification['paired_bootstrap']
    parts.append(f'''\n### Uncertainty\n
The paired 2,000-resample record bootstrap (seed {ci['seed']}, all 102 records in distinct groups) gives ensemble minus reference micro F1 95% interval **[{ci['delta_micro_f1_95_percentile_interval'][0]:.4f}, {ci['delta_micro_f1_95_percentile_interval'][1]:.4f}]**, and macro F1 **[{ci['delta_macro_f1_95_percentile_interval'][0]:.4f}, {ci['delta_macro_f1_95_percentile_interval'][1]:.4f}]**. Both include zero. Macro always includes all nine labels, with absent resampled support giving zero F1. These intervals reflect small-sample uncertainty against AI-silver references; they do not measure annotation bias or human accuracy.\n
## Scope versus function classification\n''')
    parts.append(table(['Candidate', 'Scope accuracy', 'Project P', 'Project R', 'Project F1', 'NON_PROJECT F1', 'Empty output'],
                       [[n] + [fmt(tests[s['run_id']]['test_metrics']['scope_classification'][k]) for k in ['accuracy', 'project_precision', 'project_recall', 'project_f1', 'non_project_f1']] + [tests[s['run_id']]['test_metrics']['no_label_predictions']] for n,s in zip(names,specs)]))
    parts.append(r'''
Scope is NON_PROJECT versus any other decoded output for flat models; an empty output counts as project for this scope calculation and is reported separately. A good scope score does not imply that the correct project function is predicted. DistilBERT's 0.8922 scope accuracy is a promising component for a future independently evaluated experiment; it did not beat TF-IDF in complete nine-label classification. It has not been combined with the ensemble after seeing TEST.

## Actual experiment registry and ablations

The [unified registry](optimization_experiment_registry.json) preserves every source run and its parameters, features, loss/weighting, thresholds, DEV per-label metrics, measured/estimated runtime and size fields. Null means unavailable, not zero; estimates remain explicitly separate. It contains **293 DEV configuration/calibration entries**: reference 2, lexical 177, embeddings 24, transformer 26 (23 screen configurations + 3 final OOF calibration stages), ensemble 64. Exports and five fold fits are not counted as additional configurations. Only the five prelocked final stages have TEST metrics.

Normalized final fields are authoritative from the pre-TEST lock; embedded source records remain historical. Two reconciliations are explicitly annotated: the primary ensemble size was recomputed as 103,884,465 bytes by unique dependency enumeration versus the earlier 103,876,521-byte aggregate; the original reference DEV scope metric was standardized to count its two empty outputs as PROJECT rather than NON_PROJECT. Its decoded labels and all nine-label/per-label metrics are unchanged. These standardizations occurred before TEST, not as post-TEST optimization.

### Lexical features, class weights, text view, hierarchy, dependency

The 177 lexical entries comprise 126 flat configurations (nine word/character/composite profiles × seven C values × LR/SVC), 42 hierarchy configurations, seven matched text/domain/weight/acceptance ablations, one per-label specialist and one dependency model. C=1/C=4 anchors and shortlisted configurations use TRAIN OOF thresholds; other screening stages retain their explicit threshold method in the registry. SVC Platt calibration is trained on TRAIN cross-fit scores when there are at least 15 positives and negatives; tiny-support heads use an uncalibrated sigmoid. The hierarchy uses a TRAIN scope gate and project-only conditional function heads.

Matched OOF examples (DEV micro / macro): word unigram LR C1 **0.599 / 0.286**, C4 **0.635 / 0.310**; character 3–6 LR C1 **0.648 / 0.318**, C4 **0.637 / 0.375**. Word 1–3 + character 4–6 LR gives **0.623 / 0.277** at C1 and **0.614 / 0.273** at C4. The composite did not outperform character LR on macro. Best lexical hierarchy reached approximately **0.645 / 0.341**; scope could improve without function macro improving.

At the matched character SVC C8 ablation, subject+body+domain gives **0.634 / 0.333**, subject-only **0.589 / 0.251**, body-only **0.696 / 0.392**, no-domain **0.594 / 0.359**. Square-root capped class weights at 3/5/8 each give **0.622 / 0.328**. The acceptance-rule subset gives **0.602 / 0.346**; the C1 dependency candidate macro is about **0.363**. The acceptance subset has 435 TRAIN records (390 third-audit exact agreement plus 45 spot-audit exact agreement); the remaining 27 are direct supervisor corrections. There is no numeric confidence and no basis to call supervisor-corrected examples lower quality. This is an agreement-provenance ablation, not verified confidence-weighting.

The lexical specialist reaches **0.747 / 0.449 DEV**, but **0.603 / 0.309 TEST**. Its per-label DEV choices overfit this small sample.

### Embeddings, head choices, text length and contrastive adaptation

Official MiniLM-L6-v2 (384 dimensions, max length 256) and MPNet-base-v2 (768 dimensions, max length 384) use masked mean token pooling and L2 normalization, with fresh official base weights. See the [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). Frozen embedding heads compare LR, small MLP, SVM, weights, subject/body views and flat/hierarchical prediction. The tables below use TRAIN OOF thresholds throughout. Scores and embedding timings in source records distinguish cached head inference from encoder-inclusive inference.
''')
    embed_runs = e['runs'] + e['additional_ablations'] + [e['contrastive_fewshot']['run'], specialist]
    parts.append(table(['Embedding configuration', 'DEV micro', 'DEV macro'],
                       [[r['run_id'], fmt(r['dev_metrics']['micro_f1']), fmt(r['dev_metrics']['macro_f1'])] for r in embed_runs]))
    parts.append(r'''
Head-tail tokenization was corrected to avoid duplicating short messages and features were regenerated before selection. Two-chunk mean pooling did not improve over the MiniLM flat C1 baseline. The contrastive experiment is SetFit-style rather than a claim of the stock SetFit implementation: one epoch of Jaccard-weighted in-batch positive pairs, temperature 0.07, batch 16, LR 2e-5, followed by LR heads. Encoder training is repeated from the base checkpoint within each of five TRAIN OOF folds, then all TRAIN; no DEV encoder gradients. It took 14.77 seconds including OOF and did not beat the selected specialist DEV macro. See [SetFit concepts](https://huggingface.co/docs/setfit/conceptual_guides/setfit).

### DistilBERT: frozen/partial/full tuning, loss, length and curriculum

All 23 configurations start fresh from the same official DistilBERT base checkpoint (revision `12040accade4e8a0f71eabdb258fecc2e7e948be`). Compare head-only, last block, last two blocks and full encoder at 1e-5/2e-5/3e-5; then square-root weighting, raw inverse frequency capped at 3/5/8, focal gamma 1/2, balanced batches, head-tail, two chunks and hierarchy. Uncapped extreme rare-label weights were avoided. Epochs are selected using DEV macro at fixed 0.5, minimum three epochs, maximum eight, patience two.

The following screen results use **fixed 0.5** thresholds; these are not final TEST thresholds. Exploratory DEV-tuned metrics are preserved in the registry and are not used as final cutoffs.
''')
    parts.append(table(['Transformer screen configuration', 'DEV micro at .5', 'DEV macro at .5'],
                       [[r['run_id'], fmt(r['dev_metrics_fixed_0_5']['micro_f1']), fmt(r['dev_metrics_fixed_0_5']['macro_f1'])] for r in families['transformer']['runs']]))
    parts.append('\nFinal shortlisted configurations were refit within all five TRAIN OOF folds at their DEV-selected epoch counts; thresholds were then selected only from those OOF scores:\n')
    parts.append(table(['Transformer final OOF stage', 'Epochs', 'DEV micro', 'DEV macro'],
                       [[r['run_id'], r['selected_epoch'], fmt(r['dev_metrics']['micro_f1']), fmt(r['dev_metrics']['macro_f1'])] for r in families['transformer']['final_candidates']]))
    parts.append(r'''
The focal gamma=2 exploratory DEV-tuned macro around 0.634 shrinks to **0.428** with actual TRAIN OOF cutoffs; it is not evidence of a final 0.634 classifier. Full cap=5 falls from exploratory DEV-tuned macro around 0.576 to **0.389 OOF-calibrated DEV**. Its first-two-epochs exact-agreement curriculum yields fixed-threshold macro **0.3666**, below the matched all-TRAIN cap=5 **0.4047**. This curriculum tests agreement provenance rather than numeric confidence. Long-input variants and hierarchy did not justify selection. Deep tuning helped scope; it did not produce a substantial complete-classification gain.

### Ensemble and why DEV looked better

Four components (lexical specialists, flat MiniLM LR, MiniLM specialists, focal DistilBERT) were screened on a finite quarter-step simplex. There were 31 mixtures with at least two nonzero weights, each decoded flat and with a scope gate, plus two cross-family specialists: 64 entries. Conditional hierarchy scores are converted to marginal function scores before mixing. The scope-gated mixture thresholds function scores on true project TRAIN OOF rows; it does not claim to retrain every component head on project-only records. Best scope-gated DEV macro is about 0.463; the selected flat blend is higher.

The primary is **0.25 lexical specialists + 0.75 MiniLM specialists**, with the other component weights zero. It reaches DEV micro **0.7455**, macro **0.5053**. Nine per-label specialist choices and mixture selection on only 104 DEV examples, including 1–3 rare examples, create substantial selection variance. This is consistent with the observed TEST decline, not proof of a single isolated cause.

## Selected architecture, thresholds and saved artifacts

The lexical specialist heads by label are: MEETING composite word1–3+char4–6 SVC C0.5; DEADLINE char3–6 LR C4; REPORT_REQUEST word-unigram LR C0.1; DEPARTMENTAL_INPUT char3–6 LR C4; ACTION_REQUEST word-unigram LR C4; FOLLOW_UP/APPROVAL word-unigram LR C0.1; GENERAL_UPDATE word-unigram SVC C1; NON_PROJECT word1–2 SVC C4. All selected lexical heads use subject/body and domain features. Word/character channels have separate subject/body TF-IDF, sublinear TF, Unicode accent stripping, lowercase, L2 normalization, minimum document frequency 1 for words / 2 for character word-boundary ngrams, up to 120,000 features per channel, and subject channel weight 1.5. LR uses liblinear/max_iter1200; LinearSVC uses dual=auto/max_iter3000; tolerance 1e-4 and estimator seed 42. Domain features count date/time, numeric and URL cues, length, questions, reply/forward markers and meeting/deadline/document/request/approval/follow-up/department terminology; they are inputs to learned heads, not hardcoded labels. Calibration settings and hashes are in the lock and registry.

The MiniLM specialist heads are LR C1 for MEETING/DEADLINE/FOLLOW_UP, LR C0.1 for REPORT_REQUEST, body-only LR C1 for DEPARTMENTAL_INPUT, subject-only LR C1 for APPROVAL, cap3 LR C4 for GENERAL_UPDATE, MLP64 for ACTION_REQUEST/NON_PROJECT. Frozen 384-dimensional encoder weights are shared once per bundle. The flat blend enforces NON_PROJECT exclusivity using the common decoder; otherwise multiple project functions can co-occur. There is no forced best-label fallback, so output may be empty.
''')
    parts.append(table(['Label', 'Primary TRAIN OOF threshold'], [[lab, f'{v:.10f}'] for lab,v in zip(labels, locked[selection['primary_run_id']]['thresholds'])]))
    parts.append('\nAll final cutoffs, including the comparator cutoffs, are preserved below in the fixed label order above:\n')
    parts.append(table(['Candidate', 'Threshold vector'], [[n, ', '.join(f'{v:.6f}' for v in s['thresholds'])] for n,s in zip(names,specs)]))
    parts.append('\nExact bytes sum unique referenced inference files, including external encoders; shared dependencies are counted once. Timing is measured TEST batch time divided by 102, including cold model load/tokenization/inference, on this local machine. It is not an interactive single-email latency promise.\n')
    parts.append(table(['Candidate', 'Exact bytes', 'Decimal MB', 'Cold batch seconds/record'],
                       [[n, s['model_size_bytes'], f"{s['model_size_bytes']/1e6:.2f}", fmt(tests[s['run_id']]['inference_seconds_per_record_with_cold_load'])] for n,s in zip(names,specs)]))
    parts.append(r'''
Environment: Python 3.12.14, Torch 2.11.0+cu128, Transformers 4.57.6, sklearn 1.9.1, NumPy 2.5.3, SciPy 1.18.1; RTX 5070 with CUDA. Official encoders are loaded through AutoModel; sentence-transformers is not required. Model bundles, encoder weights, vocabulary and full emails remain local under ignored `ai/data/**`; code, manifests, hashes and text-free reports are versioned. A fresh clone needs the documented local data/checkpoints and generated bundles; model weights are not hosted in Git.

## Strict automatic annotation expansion

The separate 8,000-row unlabelled pool produced **6,777 isolated eligible scored records**. Exclusions: 246 previously audited/benchmark sources, 444 too short, 46 matching groups/threads, 466 exact duplicates, 21 cosine >=0.85 near copies. Membership/group exclusions use the verified global-group sidecar, and near-copy comparison excludes all 668 benchmark sources without using their TEST predictions for selection.

The predeclared three-model committee required exact nonempty label-set agreement. NON_PROJECT required score >=0.90 and maximum function score <=0.25; project examples required NON_PROJECT <=0.20 and positive scores >=0.75 and threshold+0.10, with rare positives >=0.85. Label caps were fixed. **Zero records were accepted**: 3,155 disagreement/empty, 3,622 insufficient scores/margins. Screening took 204.028 seconds. No gates were relaxed and no pseudo labels were added. The 500–1,000 expansion goal was not reached.

Low, partly uncalibrated absolute scores and unstable rare heads make this committee unsuitable for unattended expansion. Zero accepted does not establish that the pool contains zero usable project emails. Another independently source-read AI annotation batch is more defensible than treating these rejected scores as certainty.

## Post-selection source error analysis
''')
    parts.append(f'All **46 exact-set errors** of the primary were read from full subjects/current authored messages after all five locked TEST evaluations. Supervisor read 24, covering all 15 errors involving rare-label differences; GPT-6 Luna xhigh read the disjoint remaining 22. Audit files preserve frozen expected/predicted labels and source hashes; no reference or model was changed. **{ambiguous}** source/reference-boundary cases were flagged as ambiguous. These flags are analysis, not relabeling or a revised accuracy estimate.\n')
    parts.append(table(['Observed error category (one primary category/email)', 'Count'], sorted(category_counts.items())))
    parts.append('\nRepresentative paraphrased causes (raw email text is not published):\n')
    chosen = [audits[0]['audits'][i] for i in [1,3,7,12,18]] + [audits[1]['audits'][0]]
    for row in chosen:
        parts.append(f"- `{row['email_id']}`: {row['paraphrased_cause']} Expected `{', '.join(row['expected_labels'])}`; predicted `{', '.join(row['predicted_labels'])}`.")
    parts.append(r'''
Across the source reads, task requests are confused with departmental input/follow-up/status, dated events with deliverable deadlines, and generic business/training content with genuine project activity. Some short operational replies require clear project anchors which subject/current-message inputs do not always supply. The action head loses obvious work requests as well as short coordination requests. Rare-label threshold selection on seven or eight TRAIN positives cannot solve these boundary problems by itself.

## Verification and running the saved prototype

The 126-test suite passed before the final lock, including TEST-access, hierarchy semantics, group isolation and decoding guards. The supervisor reloaded all five saved candidates on all 104 DEV records: decoded labels and metrics matched exactly, maximum score discrepancy <=1.5e-8. Inference implementation/model hashes were locked before TEST. Independent sklearn verification recomputed every TEST micro/macro precision/recall/F1, exact set/Hamming metric and per-label support/predicted count. The source audit covers every primary error exactly once. No post-TEST model or threshold changes were made.

Run from the repository root, with JSONL rows containing `email_id`, `subject` and `body` (or `current_message`/`authored_message`):

```powershell
ai\.venv\Scripts\python.exe ai\scripts\predict_optimization_classifier.py --input emails.jsonl --output predictions.jsonl
```

The default remains the frozen DEV-selected ensemble. Output includes labels, all nine scores, run ID and diagnostic-use provenance. It refuses the sealed TEST file. Scores are not calibrated confidence. Full weights are available in this workspace; the selection JSON describes their dependency hashes.
''')
    smoke_path = REPORTS / 'optimization_inference_smoke.json'
    if smoke_path.exists():
        smoke = read(smoke_path)
        parts.append(f"The saved-model CLI smoke ran on **{smoke['records']} synthetic interface-only example**, validating output ID/run ID/nine finite scores/label schema. Its output labels were `{', '.join(smoke['output_labels'])}`. This proves the saved inference path runs, not classification accuracy; the synthetic row was never added to training or evaluation.\n")
    else:
        raise RuntimeError('Saved-model smoke verification is required before publishing this report')
    parts.append(r'''
## What is usable and what should happen next

Usable now: the frozen 668-row benchmark with source provenance and isolated splits; the 462-row training partition; 293 recorded configurations/calibration stages; five saved reloadable model candidates; one-pass TEST evidence; the JSONL inference CLI; and a complete source-read error audit. This is a reproducible AI-only training prototype, not evidence of deployment readiness.

The next justified work is additional independently source-read AI annotation of real project emails, concentrating on action requests and rare REPORT_REQUEST/FOLLOW_UP/APPROVAL/DEPARTMENTAL_INPUT, with explicit boundary examples for task versus status/follow-up and project scope. Double-review new sources before acceptance and retain disagreements rather than using agreement as calibrated confidence. Strengthen quantity and diversity before expanding model size. Human validation remains deferred at the user's request; any future claim of human accuracy would need an independent human-reviewed set.

This TEST set is now inspected and must not be used for another optimization cycle. Reserve a fresh independent test before another DEV-driven sprint; retain the present results as the closed experiment. Transformer scope and the stronger reference action head are hypotheses for that future study, not a justification to tune this completed TEST. No additional DAPT, extraction, thread model or dashboard changes were introduced.

### Evidence files

- [Frozen benchmark and membership](../annotation/optimization_benchmark.json), [personal split verification](optimization_benchmark_verification.json).
- [Pre-TEST selection](../annotation/optimization_final_selection.json), [DEV reload proof](optimization_dev_preflight.json), [completed one-pass access marker](../annotation/optimization_test_access.json).
- [Full final TEST metrics](optimization_final_test.json), [independent verification and intervals](optimization_final_verification.json).
- [All-run registry](optimization_experiment_registry.json); original [lexical](optimization_lexical.json), [embeddings](optimization_embeddings.json), [transformer](optimization_transformer.json), [ensemble](optimization_ensemble.json), [reference](optimization_reference.json) reports.
- [Strict pseudo-label screen](optimization_pseudo_screen.json), [supervisor source audit](optimization_test_error_audit_root.json), [Luna xhigh source audit](optimization_test_error_audit_luna.json), [CLI smoke](optimization_inference_smoke.json).
''')
    (REPORTS / 'ai_silver_model_optimization.md').write_text('\n\n'.join(parts).rstrip() + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'registry_entries': len(entries), 'families': counts, 'source_errors_audited': len(audit_rows),
                      'report': str(REPORTS / 'ai_silver_model_optimization.md')}))


if __name__ == '__main__':
    main()
