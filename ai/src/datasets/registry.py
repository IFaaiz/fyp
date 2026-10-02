"""Validate corpus provenance and enforce auxiliary-only training boundaries."""
from __future__ import annotations

import re
from typing import Any, Mapping

REQUIRED = {
    'dataset_name', 'dataset_id', 'version', 'official_source', 'download_url',
    'origin_corpus', 'overlap_family', 'license', 'redistribution_allowed',
    'raw_text_allowed_in_git', 'intended_component', 'original_labels',
    'mapping_policy', 'checksum', 'download_date', 'local_path', 'status',
}
ENRON_IDS = {'enron', 'mailex', 'parakweet', 'cerec', 'enron_meetings'}


def validate_registry(registry: Mapping[str, Any]) -> list[str]:
    errors = []
    if not isinstance(registry, Mapping):
        return ['registry must be an object']
    datasets = registry.get('datasets')
    if not isinstance(datasets, list):
        return ['datasets must be a list']
    seen = set()
    for index, row in enumerate(datasets):
        if not isinstance(row, dict):
            errors.append(f'datasets[{index}] must be an object'); continue
        name = row.get('dataset_id', str(index))
        if not isinstance(name, str) or not name.strip():
            errors.append(f'datasets[{index}]: dataset_id must be a nonempty string')
            continue
        for key in sorted(REQUIRED - row.keys()):errors.append(f'{name}: missing {key}')
        if name in seen:errors.append(f'{name}: duplicate dataset_id')
        seen.add(name)
        if row.get('raw_text_allowed_in_git') is not False:
            errors.append(f'{name}: raw source text must remain Git-ignored')
        if name in ENRON_IDS and row.get('overlap_family') != 'ENRON':
            errors.append(f'{name}: Enron-derived corpus must be family ENRON')
        policy = row.get('mapping_policy', {})
        if not isinstance(policy, dict) or policy.get('fyp_labels_generated') is not False:
            errors.append(f'{name}: source labels may not become FYP truth automatically')
        permission = row.get('redistribution_allowed')
        if permission is not None and type(permission) is not bool:
            errors.append(f'{name}: redistribution permission must be true/false/null')
        if type(row.get('training_permitted')) is not bool:
            errors.append(f'{name}: training permission must be an explicit boolean')
        if not isinstance(row.get('original_labels'), list):
            errors.append(f'{name}: original_labels must be an explicit inventory list')
        if row.get('status') == 'integrated_auxiliary':
            gates = row.get('quality_gates', {})
            if not isinstance(gates, Mapping):
                errors.append(f'{name}: integration quality_gates must be an object')
                gates = {}
            for key in ['official_source_verified', 'usage_terms_documented', 'reproducible_acquisition',
                        'deterministic_parser', 'counts_documented', 'schema_validated',
                        'offsets_validated_or_not_applicable', 'tests_passed', 'orchestrator_source_audit']:
                if gates.get(key) is not True:errors.append(f'{name}: integration gate not satisfied: {key}')
            checks = row.get('checksum')
            if (not isinstance(checks, Mapping) or checks.get('algorithm') != 'sha256'
                    or not isinstance(checks.get('files'), list) or not checks['files']):
                errors.append(f'{name}: integrated source needs acquired file checksums')
            else:
                for file_index, entry in enumerate(checks['files']):
                    if (not isinstance(entry, Mapping)
                            or not isinstance(entry.get('path'), str) or not entry['path'].strip()
                            or not isinstance(entry.get('sha256'), str)
                            or re.fullmatch(r'[0-9a-f]{64}', entry['sha256']) is None):
                        errors.append(f'{name}: invalid acquired file checksum at index {file_index}')
    return errors


def require_training_source(registry: Mapping[str, Any], dataset_id: str) -> Mapping[str, Any]:
    errors = validate_registry(registry)
    if errors:raise ValueError('; '.join(errors))
    record = next((r for r in registry['datasets'] if r['dataset_id'] == dataset_id), None)
    if record is None:raise ValueError(f'Unregistered training corpus: {dataset_id}')
    if record['status'] != 'integrated_auxiliary' or record.get('training_permitted') is not True:
        raise ValueError(f'{dataset_id}: source/quality/rights review has not authorized auxiliary training')
    return record
