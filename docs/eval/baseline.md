# Personal Child Context Agent — Evaluation Report

- Scenarios: **19/19 passed**
- Categories covered: **16**

## Metrics

| Metric | Score | Ratio | Goal |
| --- | --- | --- | --- |
| conflict_recall | 1.000 | 15/15 | ↑ higher |
| conflict_precision | 1.000 | 15/15 | ↑ higher |
| evidence_accuracy | 1.000 | 15/15 | ↑ higher |
| abstention_accuracy | 1.000 | 17/17 | ↑ higher |
| personalization_accuracy | 1.000 | 4/4 | ↑ higher |
| unsupported_inference_rate | 0.000 | 0/1 | ↓ lower |
| action_accuracy | 1.000 | 47/47 | ↑ higher |
| action_completion_accuracy | 1.000 | 9/9 | ↑ higher |
| document_processing_accuracy | 1.000 | 19/19 | ↑ higher |

## Coverage

- `action_tool_failure`: 1
- `clear_conflict`: 1
- `document_processing_failure`: 1
- `duplicate_action`: 1
- `false_positive`: 1
- `missing_personal_context`: 1
- `missing_school_information`: 2
- `no_conflict`: 1
- `pending_resolved`: 1
- `pending_unresolved`: 1
- `personalization`: 3
- `region_au`: 1
- `region_us`: 1
- `source_contradiction`: 1
- `stale_personal_context`: 1
- `unsupported_inference`: 1

## Scenarios

| Scenario | Category | Region | Overall | Fired rules | Pass |
| --- | --- | --- | --- | --- | --- |
| clear_conflict_medication | clear_conflict | - | CONFIRMED_RELEVANCE | medication_schedule_overlap | ✅ |
| no_conflict | no_conflict | - | NO_RELEVANT_MATCH_FOUND | - | ✅ |
| missing_personal_context | missing_personal_context | - | INFORMATION_MISSING | missing_personal_context | ✅ |
| missing_school_information | missing_school_information | - | INFORMATION_MISSING | allergen_ingredients_unconfirmed | ✅ |
| missing_event_time | missing_school_information | - | INFORMATION_MISSING | medication_overlap_undetermined | ✅ |
| stale_personal_context | stale_personal_context | - | CONFIRMED_RELEVANCE | medication_schedule_overlap, stale_personal_context | ✅ |
| source_contradiction | source_contradiction | - | CLARIFICATION_REQUIRED | source_contradiction | ✅ |
| false_positive_negated_allergen | false_positive | - | NO_RELEVANT_MATCH_FOUND | - | ✅ |
| unsupported_inference_asthma | unsupported_inference | - | NO_RELEVANT_MATCH_FOUND | - | ✅ |
| personalization_A_known_present | personalization | - | CONFIRMED_RELEVANCE | explicit_allergen_match | ✅ |
| personalization_B_explicitly_absent | personalization | - | NO_RELEVANT_MATCH_FOUND | - | ✅ |
| personalization_C_unknown | personalization | - | INFORMATION_MISSING | missing_allergen_info | ✅ |
| pending_resolved | pending_resolved | - | INFORMATION_MISSING | missing_allergen_info | ✅ |
| pending_unresolved | pending_unresolved | - | INFORMATION_MISSING | missing_allergen_info | ✅ |
| duplicate_action | duplicate_action | - | CONFIRMED_RELEVANCE | medication_schedule_overlap | ✅ |
| document_processing_failure | document_processing_failure | - | NO_RELEVANT_MATCH_FOUND | - | ✅ |
| action_tool_failure | action_tool_failure | - | CONFIRMED_RELEVANCE | medication_schedule_overlap | ✅ |
| us_field_trip_allergen | region_us | US | CONFIRMED_RELEVANCE | explicit_allergen_match | ✅ |
| au_excursion_trigger | region_au | AU | CONFIRMED_RELEVANCE | known_trigger_match | ✅ |

