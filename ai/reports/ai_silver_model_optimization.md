# AI-silver model optimization — 2 October 2026

**AI-SILVER DIAGNOSTIC PERFORMANCE. Zero human classification labels.**

## Result and decision

The requested large improvement did not materialize on the frozen TEST set. The DEV-selected ensemble reaches **0.6522 micro / 0.4117 macro F1**; the freshly trained original TF-IDF reference reaches **0.6982 / 0.4033 on the same TEST records**. The ensemble gains only 0.0084 macro F1 and loses 0.0460 micro F1. Neither achieves both micro >=0.70 and macro >=0.45–0.50. The ensemble remains the preselected diagnostic candidate; TEST has not been used to replace it, adjust thresholds, or change labels. Preserve the simpler reference as a reusable comparator.

There is a usable, frozen training benchmark and saved inference pipeline, but this is not a reliable project-function classifier yet. ACTION_REQUEST regression is serious: the ensemble recalls only **1 of 17** TEST actions, versus **10 of 17** for the reference. DEV gains from many configurations and per-label choices did not generalize.

## Data, splits, and isolation

The source is 668 eligible, real Enron emails with audited AI-silver classifications. Six ambiguous references excluded before this sprint remain excluded; the historical 674-row artifact is unchanged. There are no synthetic training rows and no new human labels. The new approximately 70/15/15 split contains TRAIN **462**, DEV **104**, TEST **102**, seed **20261004**; inner grouping seed **20261005**. Complete ID coverage, source-qualified threads, leakage groups, and known near-copy components were verified. The 41 eligible known near-copy pairs remain within partitions; another pair has an excluded endpoint. All 102 TEST rows have distinct thread/leakage components. Five TRAIN OOF folds contain 92/93/93/92/92 records and every label has a positive in each fold.

The previously inspected 138-row historical validation set is excluded from new TEST by IDs, threads and leakage components; 132 still-eligible members may be in TRAIN/DEV. All current models start fresh from base/pretrained checkpoints rather than old fine-tuned weights. This guards model-selection leakage within this sprint. The source population and AI reference labels were previously audited; this is not a newly collected independent population or human gold test.

Historical scores around 0.626 micro / 0.363 macro are context from a different split and cannot be treated as the fair baseline. The new original-model reference is the matched comparison above.


| Label | TRAIN | DEV | TEST |
| --- | --- | --- | --- |
| MEETING | 61 | 13 | 17 |
| DEADLINE | 33 | 13 | 10 |
| REPORT_REQUEST | 7 | 1 | 1 |
| DEPARTMENTAL_INPUT | 11 | 3 | 3 |
| ACTION_REQUEST | 69 | 19 | 17 |
| FOLLOW_UP | 7 | 2 | 1 |
| APPROVAL | 8 | 2 | 3 |
| GENERAL_UPDATE | 141 | 31 | 36 |
| NON_PROJECT | 244 | 59 | 54 |


Frozen benchmark SHA256: `5e2da2d089e3aaddd7cbe57bf569af00bcafdbe7ddac8f28b4bc7274e3bc202b`. TEST source SHA256: `0edfaf0b9c590b54fcceee57729258558310e8715665aa2d91d2c05b22bd2fa4`. Selection SHA256: `ef6f86fa7b60fbf0d9ff7069d56de4c6df058ada4e444a995888dbb793e4c2c9`.

The split builder reproduces the saved membership; training APIs refuse sealed TEST. Thresholds for final candidates maximize per-label binary F1 using grouped TRAIN OOF scores, with NON_PROJECT exclusivity applied at decode. Those OOF threshold-selection scores are diagnostic rather than an unbiased extra evaluation. DEV macro F1 is the primary candidate-selection metric; micro F1 is secondary. DEV is selection-biased after the extensive screen. Five materially different candidates were locked and committed at **50ddec49e48f715c1d90a717c74581a528ee11c8**, before any final TEST prediction/error inspection. The one-pass evaluation marker is completed and refuses another evaluation.

## Locked candidate results


| Candidate | DEV micro | DEV macro | TEST micro | TEST macro | TEST exact set | TEST Hamming loss |
| --- | --- | --- | --- | --- | --- | --- |
| Original TF-IDF reference | 0.7080 | 0.3887 | 0.6982 | 0.4033 | 0.5784 | 0.0904 |
| Lexical specialists | 0.7474 | 0.4490 | 0.6028 | 0.3092 | 0.5294 | 0.1220 |
| MiniLM specialists | 0.6082 | 0.4950 | 0.5278 | 0.3983 | 0.4510 | 0.1852 |
| DistilBERT focal gamma=2 | 0.6728 | 0.4284 | 0.6383 | 0.4001 | 0.5392 | 0.1296 |
| DEV-selected ensemble | 0.7455 | 0.5053 | 0.6522 | 0.4117 | 0.5490 | 0.1046 |


Full TEST precision and recall (nine labels, zero division = 0):


| Candidate | Micro P | Micro R | Macro P | Macro R | Project-function macro (8) | Specific-function macro (7) |
| --- | --- | --- | --- | --- | --- | --- |
| Original TF-IDF reference | 0.7218 | 0.6761 | 0.4980 | 0.3731 | 0.3517 | 0.2924 |
| Lexical specialists | 0.6071 | 0.5986 | 0.3367 | 0.3878 | 0.2458 | 0.1937 |
| MiniLM specialists | 0.4358 | 0.6690 | 0.3589 | 0.6285 | 0.3467 | 0.2996 |
| DistilBERT focal gamma=2 | 0.5615 | 0.7394 | 0.3758 | 0.6251 | 0.3380 | 0.2774 |
| DEV-selected ensemble | 0.6716 | 0.6338 | 0.4274 | 0.5004 | 0.3566 | 0.3037 |


Eight-function macro excludes NON_PROJECT; seven-function macro also excludes GENERAL_UPDATE. All seven specific-function TEST supports are below 20; four rare labels have only 1–3 positives. Do not interpret a single rare-label success as stable accuracy.


### Highest observed per-label TEST F1

This is a descriptive comparison of the five locked candidates. These TEST winners were not assembled into a new model or used to change selection.


| Label | Highest observed candidate | TEST F1 | Support |
| --- | --- | --- | --- |
| MEETING | DistilBERT focal gamma=2 | 0.7000 | 17 |
| DEADLINE | Original TF-IDF reference | 0.5263 | 10 |
| REPORT_REQUEST | DistilBERT focal gamma=2 | 0.0645 | 1 |
| DEPARTMENTAL_INPUT | Original TF-IDF reference | 0.5000 | 3 |
| ACTION_REQUEST | Original TF-IDF reference | 0.5405 | 17 |
| FOLLOW_UP | MiniLM specialists | 0.5000 | 1 |
| APPROVAL | DEV-selected ensemble | 0.4000 | 3 |
| GENERAL_UPDATE | Original TF-IDF reference | 0.7667 | 36 |
| NON_PROJECT | DistilBERT focal gamma=2 | 0.8972 | 54 |

### Original TF-IDF reference: TEST per label


| Label | Support | Predicted | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
| MEETING | 17 | 8 | 0.7500 | 0.3529 | 0.4800 |
| DEADLINE | 10 | 9 | 0.5556 | 0.5000 | 0.5263 |
| REPORT_REQUEST | 1 | 0 | 0.0000 | 0.0000 | 0.0000 |
| DEPARTMENTAL_INPUT | 3 | 1 | 1.0000 | 0.3333 | 0.5000 |
| ACTION_REQUEST | 17 | 20 | 0.5000 | 0.5882 | 0.5405 |
| FOLLOW_UP | 1 | 0 | 0.0000 | 0.0000 | 0.0000 |
| APPROVAL | 3 | 0 | 0.0000 | 0.0000 | 0.0000 |
| GENERAL_UPDATE | 36 | 24 | 0.9583 | 0.6389 | 0.7667 |
| NON_PROJECT | 54 | 71 | 0.7183 | 0.9444 | 0.8160 |

### Lexical specialists: TEST per label


| Label | Support | Predicted | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
| MEETING | 17 | 10 | 0.7000 | 0.4118 | 0.5185 |
| DEADLINE | 10 | 6 | 0.3333 | 0.2000 | 0.2500 |
| REPORT_REQUEST | 1 | 0 | 0.0000 | 0.0000 | 0.0000 |
| DEPARTMENTAL_INPUT | 3 | 3 | 0.0000 | 0.0000 | 0.0000 |
| ACTION_REQUEST | 17 | 21 | 0.3810 | 0.4706 | 0.4211 |
| FOLLOW_UP | 1 | 11 | 0.0909 | 1.0000 | 0.1667 |
| APPROVAL | 3 | 0 | 0.0000 | 0.0000 | 0.0000 |
| GENERAL_UPDATE | 36 | 23 | 0.7826 | 0.5000 | 0.6102 |
| NON_PROJECT | 54 | 66 | 0.7424 | 0.9074 | 0.8167 |

### MiniLM specialists: TEST per label


| Label | Support | Predicted | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
| MEETING | 17 | 12 | 0.5833 | 0.4118 | 0.4828 |
| DEADLINE | 10 | 15 | 0.2667 | 0.4000 | 0.3200 |
| REPORT_REQUEST | 1 | 45 | 0.0222 | 1.0000 | 0.0435 |
| DEPARTMENTAL_INPUT | 3 | 1 | 0.0000 | 0.0000 | 0.0000 |
| ACTION_REQUEST | 17 | 45 | 0.2667 | 0.7059 | 0.3871 |
| FOLLOW_UP | 1 | 3 | 0.3333 | 1.0000 | 0.5000 |
| APPROVAL | 3 | 8 | 0.2500 | 0.6667 | 0.3636 |
| GENERAL_UPDATE | 36 | 32 | 0.7188 | 0.6389 | 0.6765 |
| NON_PROJECT | 54 | 57 | 0.7895 | 0.8333 | 0.8108 |

### DistilBERT focal gamma=2: TEST per label


| Label | Support | Predicted | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
| MEETING | 17 | 23 | 0.6087 | 0.8235 | 0.7000 |
| DEADLINE | 10 | 13 | 0.4615 | 0.6000 | 0.5217 |
| REPORT_REQUEST | 1 | 30 | 0.0333 | 1.0000 | 0.0645 |
| DEPARTMENTAL_INPUT | 3 | 2 | 0.0000 | 0.0000 | 0.0000 |
| ACTION_REQUEST | 17 | 28 | 0.3929 | 0.6471 | 0.4889 |
| FOLLOW_UP | 1 | 11 | 0.0909 | 1.0000 | 0.1667 |
| APPROVAL | 3 | 0 | 0.0000 | 0.0000 | 0.0000 |
| GENERAL_UPDATE | 36 | 27 | 0.8889 | 0.6667 | 0.7619 |
| NON_PROJECT | 54 | 53 | 0.9057 | 0.8889 | 0.8972 |

### DEV-selected ensemble: TEST per label


| Label | Support | Predicted | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
| MEETING | 17 | 11 | 0.7273 | 0.4706 | 0.5714 |
| DEADLINE | 10 | 9 | 0.4444 | 0.4000 | 0.4211 |
| REPORT_REQUEST | 1 | 0 | 0.0000 | 0.0000 | 0.0000 |
| DEPARTMENTAL_INPUT | 3 | 7 | 0.2857 | 0.6667 | 0.4000 |
| ACTION_REQUEST | 17 | 7 | 0.1429 | 0.0588 | 0.0833 |
| FOLLOW_UP | 1 | 7 | 0.1429 | 1.0000 | 0.2500 |
| APPROVAL | 3 | 2 | 0.5000 | 0.3333 | 0.4000 |
| GENERAL_UPDATE | 36 | 30 | 0.8000 | 0.6667 | 0.7273 |
| NON_PROJECT | 54 | 61 | 0.8033 | 0.9074 | 0.8522 |


### Uncertainty

The paired 2,000-resample record bootstrap (seed 20261004, all 102 records in distinct groups) gives ensemble minus reference micro F1 95% interval **[-0.1197, 0.0247]**, and macro F1 **[-0.0989, 0.1230]**. Both include zero. Macro always includes all nine labels, with absent resampled support giving zero F1. These intervals reflect small-sample uncertainty against AI-silver references; they do not measure annotation bias or human accuracy.

## Scope versus function classification


| Candidate | Scope accuracy | Project P | Project R | Project F1 | NON_PROJECT F1 | Empty output |
| --- | --- | --- | --- | --- | --- | --- |
| Original TF-IDF reference | 0.7745 | 0.9032 | 0.5833 | 0.7089 | 0.8160 | 1 |
| Lexical specialists | 0.7843 | 0.8611 | 0.6458 | 0.7381 | 0.8167 | 0 |
| MiniLM specialists | 0.7941 | 0.8000 | 0.7500 | 0.7742 | 0.8108 | 0 |
| DistilBERT focal gamma=2 | 0.8922 | 0.8776 | 0.8958 | 0.8866 | 0.8972 | 2 |
| DEV-selected ensemble | 0.8333 | 0.8780 | 0.7500 | 0.8090 | 0.8522 | 2 |


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


| Embedding configuration | DEV micro | DEV macro |
| --- | --- | --- |
| minilm_flat_lr_c0.1_none | 0.4649 | 0.3732 |
| minilm_flat_lr_c0.1_sqrt | 0.5804 | 0.3572 |
| minilm_flat_lr_c0.1_cap3 | 0.5053 | 0.3711 |
| minilm_flat_lr_c1_none | 0.6070 | 0.4234 |
| minilm_flat_lr_c1_sqrt | 0.6644 | 0.3666 |
| minilm_flat_lr_c1_cap3 | 0.6327 | 0.3516 |
| minilm_flat_lr_c1_cap5 | 0.6121 | 0.3240 |
| minilm_flat_lr_c1_cap8 | 0.5874 | 0.3155 |
| minilm_flat_lr_c4_none | 0.6595 | 0.3392 |
| minilm_flat_lr_c4_sqrt | 0.6380 | 0.3176 |
| minilm_flat_lr_c4_cap3 | 0.6713 | 0.3690 |
| minilm_flat_svm_c1 | 0.6429 | 0.3109 |
| minilm_flat_mlp64 | 0.4860 | 0.1914 |
| minilm_hier_lr_c0.1 | 0.4712 | 0.3803 |
| minilm_hier_lr_c1 | 0.5723 | 0.3735 |
| minilm_hier_lr_c4 | 0.6205 | 0.3358 |
| minilm_flat_body_lr_c1 | 0.6299 | 0.4076 |
| minilm_flat_subject_lr_c1 | 0.4497 | 0.2499 |
| minilm_flat_subject_twice_lr_c1 | 0.6019 | 0.4081 |
| mpnet_flat_lr_c1 | 0.6454 | 0.2965 |
| minilm_subject_body_head_tail_lr_c1 | 0.5848 | 0.3869 |
| minilm_subject_body_two_chunks_lr_c1 | 0.6238 | 0.4213 |
| minilm_supervised_contrastive_1epoch | 0.6275 | 0.4180 |
| per_label_specialists | 0.6082 | 0.4950 |


Head-tail tokenization was corrected to avoid duplicating short messages and features were regenerated before selection. Two-chunk mean pooling did not improve over the MiniLM flat C1 baseline. The contrastive experiment is SetFit-style rather than a claim of the stock SetFit implementation: one epoch of Jaccard-weighted in-batch positive pairs, temperature 0.07, batch 16, LR 2e-5, followed by LR heads. Encoder training is repeated from the base checkpoint within each of five TRAIN OOF folds, then all TRAIN; no DEV encoder gradients. It took 14.77 seconds including OOF and did not beat the selected specialist DEV macro. See [SetFit concepts](https://huggingface.co/docs/setfit/conceptual_guides/setfit).

### DistilBERT: frozen/partial/full tuning, loss, length and curriculum

All 23 configurations start fresh from the same official DistilBERT base checkpoint (revision `12040accade4e8a0f71eabdb258fecc2e7e948be`). Compare head-only, last block, last two blocks and full encoder at 1e-5/2e-5/3e-5; then square-root weighting, raw inverse frequency capped at 3/5/8, focal gamma 1/2, balanced batches, head-tail, two chunks and hierarchy. Uncapped extreme rare-label weights were avoided. Epochs are selected using DEV macro at fixed 0.5, minimum three epochs, maximum eight, patience two.

The following screen results use **fixed 0.5** thresholds; these are not final TEST thresholds. Exploratory DEV-tuned metrics are preserved in the registry and are not used as final cutoffs.


| Transformer screen configuration | DEV micro at .5 | DEV macro at .5 |
| --- | --- | --- |
| head_only_lr1e-05_unweighted_head512 | 0.4952 | 0.0917 |
| head_only_lr2e-05_unweighted_head512 | 0.5116 | 0.0933 |
| head_only_lr3e-05_unweighted_head512 | 0.4724 | 0.0908 |
| last_block_lr1e-05_unweighted_head512 | 0.5022 | 0.0895 |
| last_block_lr2e-05_unweighted_head512 | 0.6694 | 0.2544 |
| last_block_lr3e-05_unweighted_head512 | 0.7131 | 0.2856 |
| last_2_blocks_lr1e-05_unweighted_head512 | 0.6777 | 0.2146 |
| last_2_blocks_lr2e-05_unweighted_head512 | 0.7429 | 0.2912 |
| last_2_blocks_lr3e-05_unweighted_head512 | 0.7402 | 0.3242 |
| full_encoder_lr1e-05_unweighted_head512 | 0.6311 | 0.2100 |
| full_encoder_lr2e-05_unweighted_head512 | 0.6975 | 0.3092 |
| full_encoder_lr3e-05_unweighted_head512 | 0.7154 | 0.3404 |
| full_encoder_lr3e-05_sqrt_head512 | 0.7099 | 0.3601 |
| full_encoder_lr3e-05_capped3.0_head512 | 0.7752 | 0.3889 |
| full_encoder_lr3e-05_capped5.0_head512 | 0.7865 | 0.4047 |
| full_encoder_lr3e-05_capped8.0_head512 | 0.6826 | 0.3417 |
| full_encoder_lr3e-05_focal1.0_head512 | 0.7360 | 0.3524 |
| full_encoder_lr3e-05_focal2.0_head512 | 0.7597 | 0.3691 |
| full_encoder_lr3e-05_balanced_batch_head512 | 0.7360 | 0.3620 |
| full_encoder_lr3e-05_none_headtail | 0.6850 | 0.3243 |
| full_encoder_lr3e-05_none_twochunk | 0.6140 | 0.1742 |
| full_encoder_lr3e-05_hierarchical_head512 | 0.7063 | 0.2765 |
| full_encoder_lr3e-05_capped5.0_head512_exact_agreement_curriculum | 0.7260 | 0.3666 |


Final shortlisted configurations were refit within all five TRAIN OOF folds at their DEV-selected epoch counts; thresholds were then selected only from those OOF scores:


| Transformer final OOF stage | Epochs | DEV micro | DEV macro |
| --- | --- | --- | --- |
| full_encoder_lr3e-05_capped5.0_head512 | 8 | 0.7241 | 0.3887 |
| full_encoder_lr3e-05_focal2.0_head512 | 7 | 0.6728 | 0.4284 |
| full_encoder_lr3e-05_hierarchical_head512 | 7 | 0.6377 | 0.2666 |


The focal gamma=2 exploratory DEV-tuned macro around 0.634 shrinks to **0.428** with actual TRAIN OOF cutoffs; it is not evidence of a final 0.634 classifier. Full cap=5 falls from exploratory DEV-tuned macro around 0.576 to **0.389 OOF-calibrated DEV**. Its first-two-epochs exact-agreement curriculum yields fixed-threshold macro **0.3666**, below the matched all-TRAIN cap=5 **0.4047**. This curriculum tests agreement provenance rather than numeric confidence. Long-input variants and hierarchy did not justify selection. Deep tuning helped scope; it did not produce a substantial complete-classification gain.

### Ensemble and why DEV looked better

Four components (lexical specialists, flat MiniLM LR, MiniLM specialists, focal DistilBERT) were screened on a finite quarter-step simplex. There were 31 mixtures with at least two nonzero weights, each decoded flat and with a scope gate, plus two cross-family specialists: 64 entries. Conditional hierarchy scores are converted to marginal function scores before mixing. The scope-gated mixture thresholds function scores on true project TRAIN OOF rows; it does not claim to retrain every component head on project-only records. Best scope-gated DEV macro is about 0.463; the selected flat blend is higher.

The primary is **0.25 lexical specialists + 0.75 MiniLM specialists**, with the other component weights zero. It reaches DEV micro **0.7455**, macro **0.5053**. Nine per-label specialist choices and mixture selection on only 104 DEV examples, including 1–3 rare examples, create substantial selection variance. This is consistent with the observed TEST decline, not proof of a single isolated cause.

## Selected architecture, thresholds and saved artifacts

The lexical specialist heads by label are: MEETING composite word1–3+char4–6 SVC C0.5; DEADLINE char3–6 LR C4; REPORT_REQUEST word-unigram LR C0.1; DEPARTMENTAL_INPUT char3–6 LR C4; ACTION_REQUEST word-unigram LR C4; FOLLOW_UP/APPROVAL word-unigram LR C0.1; GENERAL_UPDATE word-unigram SVC C1; NON_PROJECT word1–2 SVC C4. All selected lexical heads use subject/body and domain features. Word/character channels have separate subject/body TF-IDF, sublinear TF, Unicode accent stripping, lowercase, L2 normalization, minimum document frequency 1 for words / 2 for character word-boundary ngrams, up to 120,000 features per channel, and subject channel weight 1.5. LR uses liblinear/max_iter1200; LinearSVC uses dual=auto/max_iter3000; tolerance 1e-4 and estimator seed 42. Domain features count date/time, numeric and URL cues, length, questions, reply/forward markers and meeting/deadline/document/request/approval/follow-up/department terminology; they are inputs to learned heads, not hardcoded labels. Calibration settings and hashes are in the lock and registry.

The MiniLM specialist heads are LR C1 for MEETING/DEADLINE/FOLLOW_UP, LR C0.1 for REPORT_REQUEST, body-only LR C1 for DEPARTMENTAL_INPUT, subject-only LR C1 for APPROVAL, cap3 LR C4 for GENERAL_UPDATE, MLP64 for ACTION_REQUEST/NON_PROJECT. Frozen 384-dimensional encoder weights are shared once per bundle. The flat blend enforces NON_PROJECT exclusivity using the common decoder; otherwise multiple project functions can co-occur. There is no forced best-label fallback, so output may be empty.


| Label | Primary TRAIN OOF threshold |
| --- | --- |
| MEETING | 0.1916438602 |
| DEADLINE | 0.0942020642 |
| REPORT_REQUEST | 0.0307272331 |
| DEPARTMENTAL_INPUT | 0.0336561105 |
| ACTION_REQUEST | 0.3661601839 |
| FOLLOW_UP | 0.0278504023 |
| APPROVAL | 0.0332409505 |
| GENERAL_UPDATE | 0.4485610485 |
| NON_PROJECT | 0.5016504665 |


All final cutoffs, including the comparator cutoffs, are preserved below in the fixed label order above:


| Candidate | Threshold vector |
| --- | --- |
| Original TF-IDF reference | 0.145671, 0.080674, 0.016910, 0.028713, 0.153617, 0.018908, 0.025902, 0.340675, 0.489032 |
| Lexical specialists | 0.212807, 0.062063, 0.074917, 0.021146, 0.085323, 0.060705, 0.075751, 0.380186, 0.410044 |
| MiniLM specialists | 0.203040, 0.092175, 0.013477, 0.044946, 0.349210, 0.019279, 0.019812, 0.503970, 0.501770 |
| DistilBERT focal gamma=2 | 0.292191, 0.364551, 0.142948, 0.292797, 0.299003, 0.173568, 0.363760, 0.550000, 0.450934 |
| DEV-selected ensemble | 0.191644, 0.094202, 0.030727, 0.033656, 0.366160, 0.027850, 0.033241, 0.448561, 0.501650 |


Exact bytes sum unique referenced inference files, including external encoders; shared dependencies are counted once. Timing is measured TEST batch time divided by 102, including cold model load/tokenization/inference, on this local machine. It is not an interactive single-email latency promise.


| Candidate | Exact bytes | Decimal MB | Cold batch seconds/record |
| --- | --- | --- | --- |
| Original TF-IDF reference | 21752605 | 21.75 | 0.0036 |
| Lexical specialists | 11716945 | 11.72 | 0.0196 |
| MiniLM specialists | 92150378 | 92.15 | 0.0521 |
| DistilBERT focal gamma=2 | 268804303 | 268.80 | 0.0070 |
| DEV-selected ensemble | 103884465 | 103.88 | 0.0234 |


Environment: Python 3.12.14, Torch 2.11.0+cu128, Transformers 4.57.6, sklearn 1.9.1, NumPy 2.5.3, SciPy 1.18.1; RTX 5070 with CUDA. Official encoders are loaded through AutoModel; sentence-transformers is not required. Model bundles, encoder weights, vocabulary and full emails remain local under ignored `ai/data/**`; code, manifests, hashes and text-free reports are versioned. A fresh clone needs the documented local data/checkpoints and generated bundles; model weights are not hosted in Git.

## Strict automatic annotation expansion

The separate 8,000-row unlabelled pool produced **6,777 isolated eligible scored records**. Exclusions: 246 previously audited/benchmark sources, 444 too short, 46 matching groups/threads, 466 exact duplicates, 21 cosine >=0.85 near copies. Membership/group exclusions use the verified global-group sidecar, and near-copy comparison excludes all 668 benchmark sources without using their TEST predictions for selection.

The predeclared three-model committee required exact nonempty label-set agreement. NON_PROJECT required score >=0.90 and maximum function score <=0.25; project examples required NON_PROJECT <=0.20 and positive scores >=0.75 and threshold+0.10, with rare positives >=0.85. Label caps were fixed. **Zero records were accepted**: 3,155 disagreement/empty, 3,622 insufficient scores/margins. Screening took 204.028 seconds. No gates were relaxed and no pseudo labels were added. The 500–1,000 expansion goal was not reached.

Low, partly uncalibrated absolute scores and unstable rare heads make this committee unsuitable for unattended expansion. Zero accepted does not establish that the pool contains zero usable project emails. Another independently source-read AI annotation batch is more defensible than treating these rejected scores as certainty.

## Post-selection source error analysis


All **46 exact-set errors** of the primary were read from full subjects/current authored messages after all five locked TEST evaluations. Supervisor read 24, covering all 15 errors involving rare-label differences; GPT-6 Luna xhigh read the disjoint remaining 22. Audit files preserve frozen expected/predicted labels and source hashes; no reference or model was changed. **13** source/reference-boundary cases were flagged as ambiguous. These flags are analysis, not relabeling or a revised accuracy estimate.


| Observed error category (one primary category/email) | Count |
| --- | --- |
| meeting_deadline_confusion | 1 |
| missed_action_and_spurious_deadline | 1 |
| missed_action_and_spurious_meeting | 1 |
| missed_action_request | 3 |
| missed_approval | 1 |
| missed_coordination_task_and_department_input | 1 |
| missed_deadline | 1 |
| missed_deadline_and_status | 1 |
| missed_deadline_spurious_follow_up | 1 |
| missed_document_and_action_request | 1 |
| missed_general_update | 2 |
| missed_meeting_and_spurious_action | 1 |
| missed_meeting_and_spurious_deadline | 1 |
| missed_multiple_project_functions | 1 |
| scope_false_negative | 11 |
| scope_false_negative_mixed_content | 1 |
| scope_false_positive | 5 |
| spurious_action_and_update_on_meeting | 1 |
| spurious_deadline_and_action_on_status | 1 |
| spurious_follow_up | 1 |
| spurious_follow_up_and_update | 1 |
| spurious_request_on_status | 2 |
| subject_driven_spurious_approval | 1 |
| task_vs_department_and_time_confusion | 1 |
| task_vs_department_confusion | 3 |
| task_vs_follow_up_confusion | 1 |


Representative paraphrased causes (raw email text is not published):


- `enron-2e2db154d7bc44289f6aa356`: Explicit project form review and separate memorandum finalization/delivery were missed despite correct due-date and status predictions. Expected `DEADLINE, REPORT_REQUEST, ACTION_REQUEST, GENERAL_UPDATE`; predicted `DEADLINE, GENERAL_UPDATE`.

- `enron-3bd556e0f745d49140c20420`: Named project task owners and work assignments were replaced with a departmental-input label; department mentions alone are insufficient. Expected `MEETING, ACTION_REQUEST, GENERAL_UPDATE`; predicted `MEETING, DEPARTMENTAL_INPUT, GENERAL_UPDATE`.

- `enron-897371da1298eb56d8154c4a`: Software testing update includes an individual confirmation request; model substituted departmental input from surrounding feedback/team language. Expected `ACTION_REQUEST, GENERAL_UPDATE`; predicted `DEPARTMENTAL_INPUT, GENERAL_UPDATE`.

- `enron-f06f913be9773fae2f003fa6`: An explicit latest delivery day was missed; a progress message was incorrectly treated as an outstanding-request follow-up. Expected `DEADLINE, GENERAL_UPDATE`; predicted `FOLLOW_UP, GENERAL_UPDATE`.

- `enron-0d963bd9982588504b5610bd`: Commercial training promotion uses project vocabulary and event dates, which should not establish participation in an active project. Expected `NON_PROJECT`; predicted `MEETING, GENERAL_UPDATE`.

- `enron-5375a0ad61ba69a337462376`: The current message reports a named project financing decision and continued risk monitoring; the model treated this project-specific status as unrelated political or commercial discussion. Expected `GENERAL_UPDATE`; predicted `NON_PROJECT`.


Across the source reads, task requests are confused with departmental input/follow-up/status, dated events with deliverable deadlines, and generic business/training content with genuine project activity. Some short operational replies require clear project anchors which subject/current-message inputs do not always supply. The action head loses obvious work requests as well as short coordination requests. Rare-label threshold selection on seven or eight TRAIN positives cannot solve these boundary problems by itself.

## Verification and running the saved prototype

The 126-test suite passed before the final lock, including TEST-access, hierarchy semantics, group isolation and decoding guards. The supervisor reloaded all five saved candidates on all 104 DEV records: decoded labels and metrics matched exactly, maximum score discrepancy <=1.5e-8. Inference implementation/model hashes were locked before TEST. Independent sklearn verification recomputed every TEST micro/macro precision/recall/F1, exact set/Hamming metric and per-label support/predicted count. The source audit covers every primary error exactly once. No post-TEST model or threshold changes were made.

Run from the repository root, with JSONL rows containing `email_id`, `subject` and `body` (or `current_message`/`authored_message`):

```powershell
ai\.venv\Scripts\python.exe ai\scripts\predict_optimization_classifier.py --input emails.jsonl --output predictions.jsonl
```

The default remains the frozen DEV-selected ensemble. Output includes labels, all nine scores, run ID and diagnostic-use provenance. It refuses the sealed TEST file. Scores are not calibrated confidence. Full weights are available in this workspace; the selection JSON describes their dependency hashes.


The saved-model CLI smoke ran on **1 synthetic interface-only example**, validating output ID/run ID/nine finite scores/label schema. Its output labels were `ACTION_REQUEST, FOLLOW_UP, GENERAL_UPDATE`. This proves the saved inference path runs, not classification accuracy; the synthetic row was never added to training or evaluation.



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
