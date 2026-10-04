# MailEx subject-plus-body ablation artifacts

This report records a source-free preparation audit for separate FYP-safe TRAIN and DEV views. The script did not open TEST rows or TEST raw threads. It reads each safe thread's raw-thread header only after the existing `_safe_raw_headers` helper verifies turn count and normalized body alignment.

## Paired view policy

Only threads with verified header alignment are included, so body-only and subject-plus-body files contain the same messages. An empty or absent subject remains an aligned row with no added prefix. The body text and native event/argument associations are preserved. Nonempty subject text is prepended as unlabeled tokens; body token and event span character/token offsets are shifted by the exact prefix lengths and validated against exact substrings.

The paired artifacts are an experimental view over the FYP-safe rows. They do not alter official MailEx splits or the original safe-view files. No message text, subject text, row IDs, or thread IDs are included here.

## Counts and hashes

| Split | Input safe messages | Input safe threads | Aligned threads | Paired messages | Nonempty subjects | Empty subjects | Alignment failures | Body file SHA-256 | Subject+body file SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| train | 2762 | 1061 | 1029 | 2683 | 2614 | 69 | 32 | `c092da25f82c3ccda87a442fa61adaef123834b7d8f862c9a15a1494f205ba98` | `f2a17663cfd3f9593b933623a7cb976ba24aa10f08ff6872b842fdc107ae6645` |
| dev | 361 | 131 | 128 | 352 | 340 | 12 | 3 | `d4508085efc66e24d06c020153d17c46523a848c2bd0200bf16a0c4ac5477438` | `de8da56c370bb1c2fb408faa6e115b7a3bef5ab7c706d2cf10f5add2a9987bcc` |

## Validation

| Split | Token offsets checked | Parsed span segments checked | Exact character shifts checked | Exact token-index shifts checked | Validation errors |
|---|---:|---:|---:|---:|---:|
| train | 331100 | 35694 | 176171 | 195565 | 0 |
| dev | 43592 | 5132 | 23501 | 27311 | 0 |

The manifest stores input and output file hashes and the aggregate alignment-reason counts. Hashes identify the exact private artifacts used; they do not reveal their contents.

## Paired compact baseline results

Both compact runs used seed 17, the same categorical BIO architecture, encoder learning rate `2e-5`, head learning rate `1e-3`, batch size 8, maximum 8 epochs, patience 2, and the same checkpoint selection metric. Each run trained and selected on its paired TRAIN/DEV membership. No TEST rows or protected examples were used.

| Input view | TRAIN messages | DEV messages | Best epoch at threshold 0.5 | DEV role-exact F1 at 0.5 | DEV event-record partial F1 at 0.5 | DEV event-record exact F1 at 0.5 | Checkpoint SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---|
| Body only | 2683 | 352 | 8 | 0.3175 | 0.4618 | 0.1661 | `8476cc54066e119f87fcd6979dc51d49aef562682e5a28c1810edd1038c25f66` |
| Subject plus body | 2683 | 352 | 8 | 0.3047 | 0.4509 | 0.1667 | `e4df8789118a002f05aad6cba460fe9117f45399e1a0c26f969587069904b61e` |

The same predeclared DEV threshold grid (`0.3`, `0.5`, `0.7`, `0.9`) selected `0.7` for both runs using role-exact micro F1:

| Input view | Role-exact F1 at 0.7 | Event-record partial F1 at 0.7 | Event-record exact F1 at 0.7 |
|---|---:|---:|---:|
| Body only | 0.3366 | 0.4901 | 0.1840 |
| Subject plus body | 0.3444 | 0.4898 | 0.1851 |

At the DEV-selected threshold, the subject view adds 0.0078 absolute role-exact F1, while event-record partial F1 is effectively unchanged (−0.0002). This is a single-seed DEV result, not evidence of a generalizable gain. The current main benchmark remains body-only; this experiment does not show that subject text hurts extraction.

Oracle diagnostics at the training run's fixed threshold `0.5`:

| Input view | Oracle mode | Role-exact F1 | Event-record partial F1 | Event-record exact F1 |
|---|---|---:|---:|---:|
| Body only | Gold type, zero trigger vector | 0.2255 | 0.4141 | 0.0840 |
| Body only | Gold type and gold trigger | 0.4957 | 0.7174 | 0.2333 |
| Subject plus body | Gold type, zero trigger vector | 0.2182 | 0.4172 | 0.0716 |
| Subject plus body | Gold type and gold trigger | 0.4827 | 0.6923 | 0.2210 |

The gold-type/zero-trigger diagnostic is represented during training by the 20% trigger-conditioning dropout, but it supplies no instance-specific trigger anchor and cannot distinguish same-type event instances by trigger. The gold-type-and-trigger diagnostic supplies that anchor and is the stronger trigger-and-type oracle. The paired run outputs, DEV predictions, oracle metrics, threshold-grid outputs, and calibration manifests remain in the ignored private experiment directory.

## Reproduction

Run from `ai/` with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_mailex_subject_ablation.py
```
