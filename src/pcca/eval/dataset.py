"""Synthetic evaluation dataset (SOT-2744).

A hand-authored set of scenarios that exercises every safety-relevant behaviour of
the agent. Each :class:`Scenario` pairs synthetic inputs (a school document + a
child's Personal Context) with **ground-truth expectations** so the harness can
score the agent objectively.

Design choices:
  * **Deterministic ground truth.** The tools are deterministic, so every
    expectation here is exact (which Conflict-Tool rules must fire, which must NOT,
    what the agent should plan/do). This makes the metrics reproducible and lets the
    baseline double as a regression gate.
  * **Repository-representable vs. raw contexts.** Most scenarios run end-to-end
    through the flow (so Action metrics apply). A few — notably the inter-source
    contradiction — need two contexts of the *same* type for one child, which the
    repository keys collapse; those set ``raw_contexts=True`` and are scored at the
    Conflict-Tool level only (see the note in the harness).
  * **Coverage.** ``build_dataset`` covers the scenario catalogue named in SOT-2744:
    clear conflict / no conflict / missing personal context / missing school
    information / stale personal context / inter-document contradiction / false
    positive / unsupported inference / same document × different child (A/B/C
    personalization) / pending action + new information (resolved & unresolved) /
    duplicate action / document processing failure / action tool failure / US / AU.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pcca.models import ChildContext, ContextStatus

# A single fixed "now" so freshness checks are deterministic. Everything is authored
# relative to this instant (never the wall clock).
NOW = datetime(2026, 9, 1, 8, 0)


@dataclass(frozen=True)
class ContextSpec:
    """Declarative Personal Context, materialised into a :class:`ChildContext`.

    ``age_days`` sets ``last_confirmed_at = now - age_days`` (``None`` ⇒ never
    confirmed, i.e. always stale) so freshness scenarios are expressed simply.
    """

    context_type: str
    status: ContextStatus
    value: str | None = None
    age_days: int | None = 0

    def build(self, child_id: str, now: datetime) -> ChildContext:
        last = None if self.age_days is None else now - timedelta(days=self.age_days)
        return ChildContext(
            child_id=child_id,
            context_type=self.context_type,
            status=self.status,
            value=self.value,
            last_confirmed_at=last,
        )


@dataclass(frozen=True)
class Expectations:
    """Ground truth for one scenario."""

    # Overall Conflict-Tool classification name (e.g. "CONFIRMED_RELEVANCE") or None.
    overall_classification: str | None
    # Conflict-Tool rules that SHOULD fire (the positives for Recall/Precision).
    positive_rules: frozenset[str] = field(default_factory=frozenset)
    # Rules that must NOT fire — firing one is a false positive / unsupported inference.
    forbidden_rules: frozenset[str] = field(default_factory=frozenset)
    # Whether the agent should abstain (surface information_missing / clarification)
    # rather than assert safety. None ⇒ not scored for abstention.
    should_abstain: bool | None = None
    # Multiset of action *tools* the flow should plan ("calendar_event" / "reminder"
    # / "gmail_draft"). Only meaningful when the scenario runs through the flow.
    expected_action_tools: tuple[str, ...] = ()
    # Expected Document-Tool status ("parsed" | "processing_failed").
    detect_status: str = "parsed"


@dataclass(frozen=True)
class ReevalProbe:
    """Re-evaluation probe: add context(s), then re-evaluate open actions."""

    add_contexts: tuple[ContextSpec, ...]
    expect_transition: bool  # WAITING_FOR_INFORMATION -> READY_FOR_REVIEW


@dataclass(frozen=True)
class Scenario:
    """One synthetic evaluation case."""

    scenario_id: str
    category: str
    description: str
    document_id: str
    document_text: str
    contexts: tuple[ContextSpec, ...]
    expected: Expectations
    region: str | None = None
    source: str = "synthetic"
    # When True the contexts are NOT persistable one-per-type through the repository
    # (e.g. a genuine present/absent contradiction), so the scenario is scored at the
    # Conflict-Tool level only and the flow/action metrics are skipped.
    raw_contexts: bool = False
    # Personalization triad tag; variants sharing a group are compared against each
    # other (in particular: `unknown` must not be collapsed to `explicitly_absent`).
    personalization_group: str | None = None
    # Scenario is designed to tempt an ungrounded (medical) generalisation.
    unsupported_inference_case: bool = False
    # --- optional flow probes (Action Completion Accuracy) ---
    approve_all: bool = False       # approve every planned action; check completion
    executor_fails: bool = False    # approve with a failing executor; expect FAILED
    reprocess: bool = False         # reprocess the same document; expect dedup
    reeval: ReevalProbe | None = None

    @property
    def runs_flow(self) -> bool:
        """Repository-representable scenarios run end-to-end through the flow."""

        return not self.raw_contexts


# --- documents --------------------------------------------------------------------
# Authored to parse cleanly through the Document Tool's label extractor.

_AQUARIUM = """\
Event: Aquarium Field Trip
Date: 2026-09-18
Start: 09:00
End: 15:00
Transportation: chartered bus
"""

_ZOO_LUNCH = """\
Event: Zoo Field Trip
Date: 2026-09-18
Start: 09:00
End: 15:00
Food: Peanut butter sandwiches provided by the school.
"""

_COOKING = """\
Event: Cooking Class
Date: 2026-09-20
Start: 09:00
End: 11:00
Food: A hot lunch will be provided by the school.
"""

_LIBRARY = """\
Event: Library Visit
Date: 2026-10-01
Activity: Quiet reading in the school library.
"""

# Event + date only (no activity/food text), so the Conflict Tool does not treat it
# as a "food event" — used to isolate the inter-source contradiction rule.
_READING = """\
Event: Reading Hour
Date: 2026-10-01
"""

_SNACK_FREE = """\
Event: Snack Time
Food: We serve peanut-free cookies in a nut-free kitchen.
"""

_NATURE_WALK = """\
Event: Nature Walk
Activity: Visit to the petting zoo with rabbits and goats.
"""

_SPORTS_NO_TIME = """\
Event: Sports Day
Date: 2026-09-25
Transportation: walking
"""

_UNPARSEABLE = """\
Dear families, we hope you all have a wonderful and restful weekend ahead.
Warm regards, the school office.
"""

_US_FIELD_TRIP = """\
Event: Science Museum Field Trip
Date: 2026-09-22
Start: 09:30
End: 14:00
Food: Boxed lunch with peanut butter and jelly sandwiches.
"""

_AU_EXCURSION = """\
Event: Beach Excursion
Date: 2026-09-24
Start: 09:00
End: 13:00
Activity: Swimming session at the local pool beforehand.
Required items: sunsmart hat, sunscreen
"""


def build_dataset() -> list[Scenario]:
    """Return the full synthetic scenario set covering the SOT-2744 catalogue."""

    scenarios: list[Scenario] = []

    # 1. Clear conflict — scheduled medication overlaps the trip window.
    scenarios.append(
        Scenario(
            scenario_id="clear_conflict_medication",
            category="clear_conflict",
            description="Scheduled medication at 12:00 falls inside a 09:00–15:00 trip.",
            document_id="doc-aquarium",
            document_text=_AQUARIUM,
            contexts=(
                ContextSpec("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00"),
            ),
            expected=Expectations(
                overall_classification="CONFIRMED_RELEVANCE",
                positive_rules=frozenset({"medication_schedule_overlap"}),
                should_abstain=False,
                expected_action_tools=("calendar_event", "reminder"),
            ),
            approve_all=True,
            reprocess=True,
        )
    )

    # 2. No conflict — dated event, allergy explicitly absent, nothing relevant fires.
    scenarios.append(
        Scenario(
            scenario_id="no_conflict",
            category="no_conflict",
            description="Dated event; the child's allergy is explicitly absent — no risk found.",
            document_id="doc-library-dated",
            document_text="Event: Museum Visit\nDate: 2026-10-02\nStart: 10:00\nEnd: 12:00\n",
            contexts=(
                ContextSpec("food_allergy", ContextStatus.EXPLICITLY_ABSENT),
            ),
            expected=Expectations(
                overall_classification="NO_RELEVANT_MATCH_FOUND",
                positive_rules=frozenset(),
                should_abstain=False,
                # A dated event still yields a calendar action (planned, unapproved).
                expected_action_tools=("calendar_event",),
            ),
        )
    )

    # 3. Missing Personal Context — nothing recorded about the child.
    scenarios.append(
        Scenario(
            scenario_id="missing_personal_context",
            category="missing_personal_context",
            description="No Personal Context recorded — relevance cannot be assessed.",
            document_id="doc-library",
            document_text=_LIBRARY,
            contexts=(),
            expected=Expectations(
                overall_classification="INFORMATION_MISSING",
                positive_rules=frozenset({"missing_personal_context"}),
                should_abstain=True,
                # A dated notice still yields an (all-day) calendar action.
                expected_action_tools=("calendar_event", "gmail_draft"),
            ),
        )
    )

    # 4. Missing School Information — food event, known allergen not confirmed absent.
    scenarios.append(
        Scenario(
            scenario_id="missing_school_information",
            category="missing_school_information",
            description="Food event; child has an egg allergy but ingredients aren't stated.",
            document_id="doc-cooking",
            document_text=_COOKING,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.KNOWN_PRESENT, "egg"),
            ),
            expected=Expectations(
                overall_classification="INFORMATION_MISSING",
                positive_rules=frozenset({"allergen_ingredients_unconfirmed"}),
                should_abstain=True,
                expected_action_tools=("calendar_event", "gmail_draft"),
            ),
            approve_all=True,
        )
    )

    # 5. Missing event time — medication, but the document has no time window.
    scenarios.append(
        Scenario(
            scenario_id="missing_event_time",
            category="missing_school_information",
            description="Medication present but the document states no start/end time.",
            document_id="doc-sports-notime",
            document_text=_SPORTS_NO_TIME,
            contexts=(
                ContextSpec("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00"),
            ),
            expected=Expectations(
                overall_classification="INFORMATION_MISSING",
                positive_rules=frozenset({"medication_overlap_undetermined"}),
                should_abstain=True,
                # Date-only ⇒ an all-day calendar action; the undetermined med ⇒ draft.
                expected_action_tools=("calendar_event", "gmail_draft"),
            ),
        )
    )

    # 6. Stale Personal Context — a relied-upon medication is overdue for re-confirmation.
    scenarios.append(
        Scenario(
            scenario_id="stale_personal_context",
            category="stale_personal_context",
            description="Medication overlaps the trip but was last confirmed 200 days ago.",
            document_id="doc-aquarium-stale",
            document_text=_AQUARIUM,
            contexts=(
                ContextSpec(
                    "scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00", age_days=200
                ),
            ),
            expected=Expectations(
                overall_classification="CONFIRMED_RELEVANCE",
                positive_rules=frozenset(
                    {"medication_schedule_overlap", "stale_personal_context"}
                ),
                should_abstain=None,
                expected_action_tools=("calendar_event", "reminder", "reminder"),
            ),
        )
    )

    # 7. Inter-document contradiction — same context marked present AND explicitly absent.
    scenarios.append(
        Scenario(
            scenario_id="source_contradiction",
            category="source_contradiction",
            description="A food allergy is asserted both present and explicitly absent.",
            document_id="doc-reading-contra",
            document_text=_READING,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut"),
                ContextSpec("food_allergy", ContextStatus.EXPLICITLY_ABSENT),
            ),
            expected=Expectations(
                overall_classification="CLARIFICATION_REQUIRED",
                positive_rules=frozenset({"source_contradiction"}),
                should_abstain=True,
            ),
            raw_contexts=True,
        )
    )

    # 8. False positive inducer — a negated allergen must NOT flag.
    scenarios.append(
        Scenario(
            scenario_id="false_positive_negated_allergen",
            category="false_positive",
            description="Peanut-free snack; the known peanut allergy must not be flagged.",
            document_id="doc-snack-free",
            document_text=_SNACK_FREE,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut"),
            ),
            expected=Expectations(
                overall_classification="NO_RELEVANT_MATCH_FOUND",
                positive_rules=frozenset(),
                forbidden_rules=frozenset({"explicit_allergen_match"}),
                should_abstain=False,
                expected_action_tools=(),
            ),
        )
    )

    # 9. Unsupported inference inducer — asthma must NOT flag a petting zoo.
    scenarios.append(
        Scenario(
            scenario_id="unsupported_inference_asthma",
            category="unsupported_inference",
            description="Asthma + petting zoo; no explicit trigger, so nothing may be flagged.",
            document_id="doc-nature-walk",
            document_text=_NATURE_WALK,
            contexts=(
                ContextSpec("medical_condition", ContextStatus.KNOWN_PRESENT, "asthma"),
                # Allergy explicitly absent isolates the test to the ungrounded-trigger
                # question: asthma alone must never flag the petting zoo.
                ContextSpec("food_allergy", ContextStatus.EXPLICITLY_ABSENT),
            ),
            expected=Expectations(
                overall_classification="NO_RELEVANT_MATCH_FOUND",
                positive_rules=frozenset(),
                forbidden_rules=frozenset({"known_trigger_match"}),
                should_abstain=False,
                expected_action_tools=(),
            ),
            unsupported_inference_case=True,
        )
    )

    # 10. Personalization A/B/C — same food document, three different children.
    scenarios.extend(_personalization_triad())

    # 11. Pending action + new information (resolved).
    scenarios.append(
        Scenario(
            scenario_id="pending_resolved",
            category="pending_resolved",
            description="A missing-allergen enquiry resolves once the parent confirms no allergy.",
            document_id="doc-cooking-pending",
            document_text=_COOKING,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.UNKNOWN),
            ),
            expected=Expectations(
                overall_classification="INFORMATION_MISSING",
                positive_rules=frozenset({"missing_allergen_info"}),
                should_abstain=True,
                expected_action_tools=("calendar_event", "gmail_draft"),
            ),
            reeval=ReevalProbe(
                add_contexts=(ContextSpec("food_allergy", ContextStatus.EXPLICITLY_ABSENT),),
                expect_transition=True,
            ),
        )
    )

    # 12. Pending action + no new information (unresolved).
    scenarios.append(
        Scenario(
            scenario_id="pending_unresolved",
            category="pending_unresolved",
            description="Without new information the missing-allergen enquiry stays open.",
            document_id="doc-cooking-open",
            document_text=_COOKING,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.UNKNOWN),
            ),
            expected=Expectations(
                overall_classification="INFORMATION_MISSING",
                positive_rules=frozenset({"missing_allergen_info"}),
                should_abstain=True,
                expected_action_tools=("calendar_event", "gmail_draft"),
            ),
            reeval=ReevalProbe(add_contexts=(), expect_transition=False),
        )
    )

    # 13. Duplicate action inducer — reprocessing must not double-create.
    scenarios.append(
        Scenario(
            scenario_id="duplicate_action",
            category="duplicate_action",
            description="Reprocessing the same document must not create duplicate actions.",
            document_id="doc-aquarium-dup",
            document_text=_AQUARIUM,
            contexts=(
                ContextSpec("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00"),
            ),
            expected=Expectations(
                overall_classification="CONFIRMED_RELEVANCE",
                positive_rules=frozenset({"medication_schedule_overlap"}),
                should_abstain=False,
                expected_action_tools=("calendar_event", "reminder"),
            ),
            reprocess=True,
        )
    )

    # 14. Document processing failure — unparseable notice.
    scenarios.append(
        Scenario(
            scenario_id="document_processing_failure",
            category="document_processing_failure",
            description="A prose email with no recognisable fields fails to parse.",
            document_id="doc-unparseable",
            document_text=_UNPARSEABLE,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.EXPLICITLY_ABSENT),
            ),
            expected=Expectations(
                overall_classification="NO_RELEVANT_MATCH_FOUND",
                positive_rules=frozenset(),
                detect_status="processing_failed",
                expected_action_tools=(),
            ),
        )
    )

    # 15. Action tool failure — an approved action whose executor errors ⇒ FAILED.
    scenarios.append(
        Scenario(
            scenario_id="action_tool_failure",
            category="action_tool_failure",
            description="An approved calendar action fails at the executor and is marked FAILED.",
            document_id="doc-aquarium-fail",
            document_text=_AQUARIUM,
            contexts=(
                ContextSpec("scheduled_medication", ContextStatus.KNOWN_PRESENT, "12:00"),
            ),
            expected=Expectations(
                overall_classification="CONFIRMED_RELEVANCE",
                positive_rules=frozenset({"medication_schedule_overlap"}),
                should_abstain=False,
                expected_action_tools=("calendar_event", "reminder"),
            ),
            executor_fails=True,
        )
    )

    # 16. US scenario — a US field trip with an explicit peanut allergen match.
    scenarios.append(
        Scenario(
            scenario_id="us_field_trip_allergen",
            category="region_us",
            description="US museum trip; boxed peanut-butter lunch matches the child's allergy.",
            document_id="doc-us-trip",
            document_text=_US_FIELD_TRIP,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut"),
            ),
            expected=Expectations(
                overall_classification="CONFIRMED_RELEVANCE",
                positive_rules=frozenset({"explicit_allergen_match"}),
                should_abstain=False,
                expected_action_tools=("calendar_event", "reminder"),
            ),
            region="US",
        )
    )

    # 17. Australia scenario — an AU excursion; an explicit chlorine trigger fires.
    scenarios.append(
        Scenario(
            scenario_id="au_excursion_trigger",
            category="region_au",
            description="AU beach excursion with a pool session; explicit chlorine trigger fires.",
            document_id="doc-au-excursion",
            document_text=_AU_EXCURSION,
            contexts=(
                ContextSpec("known_trigger", ContextStatus.KNOWN_PRESENT, "pool"),
                # No food in scope for this excursion; absent allergy isolates the trigger.
                ContextSpec("food_allergy", ContextStatus.EXPLICITLY_ABSENT),
            ),
            expected=Expectations(
                overall_classification="CONFIRMED_RELEVANCE",
                positive_rules=frozenset({"known_trigger_match"}),
                should_abstain=False,
                expected_action_tools=("calendar_event", "reminder"),
            ),
            region="AU",
        )
    )

    return scenarios


def _personalization_triad() -> list[Scenario]:
    """Same food document, three children: known_present / explicitly_absent / unknown.

    The invariant under test: child C (`unknown`) must NOT be treated like child B
    (`explicitly_absent`). A ⇒ CONFIRMED, B ⇒ nothing relevant, C ⇒ INFORMATION_MISSING.
    """

    group = "personalization_allergen"
    doc = _ZOO_LUNCH  # food contains "peanut butter"

    return [
        Scenario(
            scenario_id="personalization_A_known_present",
            category="personalization",
            description="Child A: peanut allergy KNOWN_PRESENT ⇒ confirmed relevance.",
            document_id="doc-zoo-A",
            document_text=doc,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.KNOWN_PRESENT, "peanut"),
            ),
            expected=Expectations(
                overall_classification="CONFIRMED_RELEVANCE",
                positive_rules=frozenset({"explicit_allergen_match"}),
                should_abstain=False,
                expected_action_tools=("calendar_event", "reminder"),
            ),
            personalization_group=group,
        ),
        Scenario(
            scenario_id="personalization_B_explicitly_absent",
            category="personalization",
            description="Child B: allergy EXPLICITLY_ABSENT ⇒ no allergen concern.",
            document_id="doc-zoo-B",
            document_text=doc,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.EXPLICITLY_ABSENT),
            ),
            expected=Expectations(
                overall_classification="NO_RELEVANT_MATCH_FOUND",
                positive_rules=frozenset(),
                should_abstain=False,
                expected_action_tools=("calendar_event",),
            ),
            personalization_group=group,
        ),
        Scenario(
            scenario_id="personalization_C_unknown",
            category="personalization",
            description="Child C: allergy UNKNOWN ⇒ information missing (not treated as absent).",
            document_id="doc-zoo-C",
            document_text=doc,
            contexts=(
                ContextSpec("food_allergy", ContextStatus.UNKNOWN),
            ),
            expected=Expectations(
                overall_classification="INFORMATION_MISSING",
                positive_rules=frozenset({"missing_allergen_info"}),
                should_abstain=True,
                expected_action_tools=("calendar_event", "gmail_draft"),
            ),
            personalization_group=group,
        ),
    ]
