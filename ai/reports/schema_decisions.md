# Annotation schema decisions — 24 September 2026

## Action-only project email

Decision: add **ACTION_REQUEST** as an eighth project classification label (nine labels including the exclusive NON_PROJECT filter). An email such as “Ali, please contact the vendor and confirm installation” is clearly in scope, yet none of the original seven project labels describes its purpose. Calling it GENERAL_UPDATE would make that label inconsistent; calling it NON_PROJECT or leaving a reviewed record empty would lose the distinction from unknown classification.

We evaluated three designs:

1. Add ACTION_REQUEST/TASK. This gives annotators a direct, searchable label and gives a future multi-label classifier a learnable target.
2. Keep seven labels and infer project relevance from ACTION_ITEM extraction. This makes classification depend on extraction quality and leaves action-only messages with an empty reviewed label list.
3. Add a separate project-relevance field. This is flexible but adds a second human decision and another prediction target to every record.

The first design is the smallest reliable extension. ACTION_REQUEST covers a concrete requested, directed, or assigned operational project task. A request solely to submit a formal document, supply departmental input, or give approval keeps its existing specific label; add ACTION_REQUEST when a distinct operational task is also requested. It may co-occur with DEADLINE or FOLLOW_UP. ACTION_ITEM is a text span and does not automatically imply ACTION_REQUEST. MailEx Request_Action events remain provisional extraction evidence, not automatic FYP classification labels.

## Deadline time

Decision: add **DEADLINE_TIME** as the eleventh extraction type. Due-time text is required for precise alerts and will be costly to recover after human annotation. It covers explicit expressions such as “5 PM”, “3 PM”, and “COB” without assuming a clock normalization. In “by Friday at 3 PM”, annotate “Friday” as DEADLINE_DATE and “3 PM” as DEADLINE_TIME. Date normalization and business-specific COB conversion remain downstream rule logic, with timezone/context review.

Both changes preserve the existing canonical JSONL fields and multi-label semantics. Existing MailEx and Enron records remain unlabelled for FYP classification. Annotation guidelines, machine-readable schema, fixtures, validator constants, and tests were updated before preparing the human seed.
