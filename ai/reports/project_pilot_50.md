# Separate project-email annotation pilot

The initial 250-record Enron seed contains many generic business messages and social or promotional mail. Its first 50 records are not a suitable project-management evaluation sample. This pilot is a separately screened, unlabelled 50-record sample for two independent reviewers. It does not replace the initial seed or its saved reviewer decisions.

## Selection and provenance

- Source: `ai/data/interim/enron_candidates.jsonl` (Enron); SHA-256 is recorded in the generated manifest.
- Selection list: `ai/annotation/project_pilot_50_ids.json`, in fixed review order.
- Composition: 40 provisional project-work candidates covering planning, meetings, assignments, document requests, delivery dates, status, and risks; 10 clear out-of-scope controls covering consumer promotions and leisure content.
- The screening assessed candidate relevance only. All records retain empty labels and spans and `unlabelled` annotation status. Neither expected classes nor gold labels are embedded in the seed.
- Selected IDs do not overlap the original 250-record seed. The builder verifies source records, unique IDs, complete candidate-pool threads, manifest order, and unchanged existing seed content. Reviewer outputs are separate.

Run `ai/.venv/Scripts/python.exe ai/scripts/build_project_pilot.py` from the repository root, or start the annotator with `--pilot project` to build or verify the seed automatically. The generated seed and reviewer files are ignored by Git. See `ai/annotation/simple_annotator/README.md` for the reviewer command.

## Interpretation

This is a pilot for reviewing the annotation workflow and whether project-management labels are recognizable. Enron mail differs from university or workplace Outlook project mail. Human review of this sample cannot establish target-domain model performance. Use authorized, de-identified project emails for that evaluation when available. Keep reviewers independent and reconcile disagreements only after both complete the same batch.
