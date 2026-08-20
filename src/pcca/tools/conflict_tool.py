"""Conflict Tool — reconcile School Information with Personal Child Context.

Implements SOT-2741: a **deterministic-first** reconciler. Everything that can be
decided by a rule is decided by a rule; the LLM is never handed the whole judgement.
The result is one of four classifications, each carrying both sides of the evidence.

Contract this implementation honours:
  * **Deterministic over LLM.** Time-overlap, explicit allergen match, missing-info,
    freshness and inter-source contradiction are all decided by rules here — offline,
    no credentials — matching the project's "prefer deterministic" rule.
  * **`NO_RELEVANT_MATCH_FOUND` is not "safe".** It only means no rule matched the
    current evidence; it never asserts the absence of risk.
  * **`unknown` is never "safe".** A relevant category with an unknown/missing fact
    yields ``INFORMATION_MISSING`` (a potential False Negative), not a no-match.
  * **Grounding Rules.** Only facts explicitly present in the child's Personal Context
    relate a document to the child. We never infer a medical concern from general
    knowledge (e.g. Asthma alone never flags a petting-zoo activity — only an explicit
    ``known_trigger`` does).
  * **Evidence on every finding.** Each finding keeps the School Information Evidence
    and the Personal Context Evidence it was derived from.

Classifications (see :class:`pcca.models.ConflictClassification`):
  CONFIRMED_RELEVANCE / INFORMATION_MISSING / CLARIFICATION_REQUIRED /
  NO_RELEVANT_MATCH_FOUND.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from pcca.models import (
    ChildContext,
    ConflictClassification,
    ConflictFinding,
    SchoolInformation,
    most_severe,
)
from pcca.persistence import Repository, get_repository

# Context types the tool understands (matched case-insensitively). Synonyms map to a
# canonical concern so parent-entered context is robust to minor wording differences.
MEDICATION_TYPES = frozenset({"scheduled_medication", "medication"})
FOOD_ALLERGY_TYPES = frozenset({"food_allergy", "allergy", "allergen"})
KNOWN_TRIGGER_TYPES = frozenset({"known_trigger", "trigger"})

# A relevant context older than this (when a `now` is supplied) is flagged for
# re-confirmation. Freshness is only evaluated when the caller passes ``now`` — we
# never invent the current time.
DEFAULT_FRESHNESS_MAX_AGE = timedelta(days=180)

# Status constants for the tool's dict output.
STATUS_EVALUATED = "evaluated"
STATUS_DOCUMENT_NOT_FOUND = "document_not_found"

# Negation cues that flip an allergen mention from "present in the food" to
# "explicitly excluded" (e.g. "no peanuts", "peanut-free", "含まない"). Kept small and
# explicit; when in doubt we do NOT treat a mention as negated (fail toward flagging).
_NEGATION_CUES = ("no ", "not ", "without ", "free of ", "なし", "無し", "含まない", "不使用")

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def evaluate_conflict(
    child_id: str,
    document_id: str,
    repository: Repository | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile one School Information document against a child's Personal Context.

    Args:
        child_id: The child whose Personal Context to reconcile against.
        document_id: The structured School Information document to evaluate.
        repository: Storage backend (defaults to the configured one). Injectable so
            the deterministic logic can be tested with an in-memory repository.
        now: Current time for freshness checks. When ``None`` freshness is not
            evaluated (we never fabricate the current time).

    Returns:
        A dict with ``status``, the overall ``classification`` (the most severe
        finding's name, e.g. ``"CONFIRMED_RELEVANCE"``), the full ``findings`` list,
        and the de-duplicated ``school_evidence`` / ``personal_context_evidence``
        across all findings. ``NO_RELEVANT_MATCH_FOUND`` never means "safe".
    """

    repository = repository or get_repository()

    school = repository.get_school_information(document_id)
    if school is None:
        return {
            "status": STATUS_DOCUMENT_NOT_FOUND,
            "detail": f"No School Information found for document_id {document_id!r}.",
            "child_id": child_id,
            "document_id": document_id,
            "classification": None,
            "findings": [],
            "school_evidence": [],
            "personal_context_evidence": [],
        }

    contexts = repository.list_child_context(child_id)
    findings = evaluate(school, contexts, now=now)

    overall = most_severe([f.classification for f in findings])
    return {
        "status": STATUS_EVALUATED,
        "child_id": child_id,
        "document_id": document_id,
        "classification": overall.name,
        "findings": [f.to_dict() for f in findings],
        "school_evidence": _dedupe(e for f in findings for e in f.school_evidence),
        "personal_context_evidence": _dedupe(
            e for f in findings for e in f.personal_context_evidence
        ),
        "detail": _OVERALL_DETAIL[overall],
    }


# --- deterministic core -----------------------------------------------------------


def evaluate(
    school: SchoolInformation,
    contexts: list[ChildContext],
    now: datetime | None = None,
) -> list[ConflictFinding]:
    """Run every deterministic rule and return all findings.

    Pure function over its inputs (no I/O) so it is trivially unit-testable. Always
    returns at least one finding — a ``NO_RELEVANT_MATCH_FOUND`` when nothing else
    fired, which still does not assert safety.
    """

    si = school.structured_information or {}
    school_summary = _school_summary(school)

    findings: list[ConflictFinding] = []

    # Rule 0: nothing at all is known about this child -> we cannot assess risk.
    if not contexts:
        findings.append(
            ConflictFinding(
                classification=ConflictClassification.INFORMATION_MISSING,
                rule="missing_personal_context",
                reason=(
                    "No Personal Context is recorded for this child, so relevance "
                    "cannot be assessed. This is not a determination of safety."
                ),
                school_evidence=school_summary,
                personal_context_evidence=["(none recorded)"],
            )
        )
        return findings

    findings += _rule_medication_overlap(si, contexts, now)
    findings += _rule_food_allergen(si, contexts, now)
    findings += _rule_known_trigger(si, contexts, now)
    findings += _rule_source_contradiction(contexts)

    if not findings:
        findings.append(
            ConflictFinding(
                classification=ConflictClassification.NO_RELEVANT_MATCH_FOUND,
                rule="no_relevant_match",
                reason=(
                    "No deterministic rule related this document to the child's "
                    "Personal Context. NO_RELEVANT_MATCH_FOUND does NOT mean safe / "
                    "no risk — only that nothing relevant was found in current evidence."
                ),
                school_evidence=school_summary,
                personal_context_evidence=[_ctx_evidence(c) for c in contexts],
            )
        )

    return findings


# --- rules ------------------------------------------------------------------------


def _rule_medication_overlap(
    si: dict[str, Any], contexts: list[ChildContext], now: datetime | None
) -> list[ConflictFinding]:
    """Medication time falling inside the event window -> CONFIRMED_RELEVANCE.

    If the event has no usable time window we cannot confirm the overlap, so a
    scheduled medication yields INFORMATION_MISSING rather than a silent no-match.
    """

    meds = [c for c in contexts if _is_type(c, MEDICATION_TYPES) and c.is_present]
    if not meds:
        return []

    start = _parse_minutes(si.get("start_time"))
    end = _parse_minutes(si.get("end_time"))
    event_ev = _fields_evidence(si, ("event", "date", "start_time", "end_time"))

    findings: list[ConflictFinding] = []
    for med in meds:
        med_min = _parse_minutes(med.value)
        if start is None or end is None or med_min is None:
            findings.append(
                ConflictFinding(
                    classification=ConflictClassification.INFORMATION_MISSING,
                    rule="medication_overlap_undetermined",
                    reason=(
                        "The child has a scheduled medication but the event's time "
                        "window (or the medication time) is not fully known, so a "
                        "schedule overlap cannot be ruled out."
                    ),
                    school_evidence=event_ev,
                    personal_context_evidence=[_ctx_evidence(med)],
                )
            )
            continue
        if start <= med_min <= end:
            findings.append(
                ConflictFinding(
                    classification=ConflictClassification.CONFIRMED_RELEVANCE,
                    rule="medication_schedule_overlap",
                    reason=(
                        f"Scheduled medication at {med.value} falls within the event "
                        f"window {si.get('start_time')}–{si.get('end_time')}."
                    ),
                    school_evidence=event_ev,
                    personal_context_evidence=[_ctx_evidence(med)],
                )
            )
            findings += _freshness_finding(med, now, "the scheduled medication")
    return findings


def _rule_food_allergen(
    si: dict[str, Any], contexts: list[ChildContext], now: datetime | None
) -> list[ConflictFinding]:
    """Explicit allergen match -> CONFIRMED_RELEVANCE; unconfirmed food -> INFORMATION_MISSING.

    Only fires when the document is food-relevant (has food information). A negated
    mention ("no peanuts", "peanut-free") is treated as excluded, not confirmed.
    """

    food_text = _food_text(si)
    if not food_text:
        return []

    food_ev = _fields_evidence(si, ("food_information", "required_items", "activity"))

    allergies = [c for c in contexts if _is_type(c, FOOD_ALLERGY_TYPES)]
    known = [c for c in allergies if c.is_present and c.value]
    findings: list[ConflictFinding] = []

    for allergy in known:
        term = allergy.value or ""
        state = _mention_state(food_text, term)
        if state == "positive":
            findings.append(
                ConflictFinding(
                    classification=ConflictClassification.CONFIRMED_RELEVANCE,
                    rule="explicit_allergen_match",
                    reason=(
                        f"The child's known allergen {term!r} is explicitly present in "
                        f"the document's food information."
                    ),
                    school_evidence=food_ev,
                    personal_context_evidence=[_ctx_evidence(allergy)],
                )
            )
            findings += _freshness_finding(allergy, now, f"the {term!r} allergy")
        elif state == "absent":
            # The allergen is not mentioned; the food's full ingredients are not
            # confirmed, so we cannot rule the allergen out. Unknown != safe.
            findings.append(
                ConflictFinding(
                    classification=ConflictClassification.INFORMATION_MISSING,
                    rule="allergen_ingredients_unconfirmed",
                    reason=(
                        f"This is a food event and the child has a known {term!r} "
                        f"allergy, but the document does not confirm the full "
                        f"ingredients, so {term!r} cannot be ruled out."
                    ),
                    school_evidence=food_ev,
                    personal_context_evidence=[_ctx_evidence(allergy)],
                )
            )
        # state == "negated" -> the allergen is explicitly excluded; no finding, but
        # we still never assert safety elsewhere.

    # Food event but we have no known allergy status at all (only unknown / none):
    # cannot rule out an allergy -> INFORMATION_MISSING. An explicit-absence
    # (parent-confirmed no allergies) is a real answer and does not trigger this.
    has_known = bool(known)
    has_absent = any(c.is_absent for c in allergies)
    if not has_known and not has_absent:
        findings.append(
            ConflictFinding(
                classification=ConflictClassification.INFORMATION_MISSING,
                rule="missing_allergen_info",
                reason=(
                    "This is a food event but the child has no confirmed allergy "
                    "information, so an allergen cannot be ruled out. Unknown is not "
                    "treated as safe."
                ),
                school_evidence=food_ev,
                personal_context_evidence=(
                    [_ctx_evidence(c) for c in allergies] or ["(no allergy info recorded)"]
                ),
            )
        )
    return findings


def _rule_known_trigger(
    si: dict[str, Any], contexts: list[ChildContext], now: datetime | None
) -> list[ConflictFinding]:
    """Explicit Known Trigger appearing in the document -> CONFIRMED_RELEVANCE.

    Grounding Rule: ONLY an explicit ``known_trigger`` relates the child to an
    activity. A medical condition alone (e.g. asthma) never flags an activity here —
    that would be an ungrounded medical generalisation.
    """

    triggers = [
        c for c in contexts if _is_type(c, KNOWN_TRIGGER_TYPES) and c.is_present and c.value
    ]
    if not triggers:
        return []

    activity_text = _activity_text(si)
    if not activity_text:
        return []

    activity_ev = _fields_evidence(
        si, ("event", "activity", "transportation", "relevant_instructions", "food_information")
    )
    findings: list[ConflictFinding] = []
    for trig in triggers:
        term = trig.value or ""
        if _mention_state(activity_text, term) == "positive":
            findings.append(
                ConflictFinding(
                    classification=ConflictClassification.CONFIRMED_RELEVANCE,
                    rule="known_trigger_match",
                    reason=(
                        f"The child's explicit known trigger {term!r} is present in the "
                        f"document. (Only explicit triggers relate the child; no medical "
                        f"generalisation is made.)"
                    ),
                    school_evidence=activity_ev,
                    personal_context_evidence=[_ctx_evidence(trig)],
                )
            )
            findings += _freshness_finding(trig, now, f"the {term!r} trigger")
    return findings


def _rule_source_contradiction(contexts: list[ChildContext]) -> list[ConflictFinding]:
    """Same context type asserted both present and explicitly-absent -> CLARIFICATION.

    Guards against contradictory Personal Context coming from different sources
    (inter-document contradiction) before it is relied upon.
    """

    by_type: dict[str, list[ChildContext]] = defaultdict(list)
    for c in contexts:
        by_type[c.context_type].append(c)

    findings: list[ConflictFinding] = []
    for ctype, items in by_type.items():
        if any(c.is_present for c in items) and any(c.is_absent for c in items):
            findings.append(
                ConflictFinding(
                    classification=ConflictClassification.CLARIFICATION_REQUIRED,
                    rule="source_contradiction",
                    reason=(
                        f"Personal Context for {ctype!r} is contradictory: it is marked "
                        f"both present and explicitly absent. A human must reconcile it."
                    ),
                    school_evidence=[],
                    personal_context_evidence=[_ctx_evidence(c) for c in items],
                )
            )
    return findings


def _freshness_finding(
    ctx: ChildContext, now: datetime | None, label: str
) -> list[ConflictFinding]:
    """Emit a CLARIFICATION finding when a relied-upon context is stale.

    Only evaluated when ``now`` is supplied — freshness is never assumed.
    """

    if now is None or not ctx.is_stale(now, DEFAULT_FRESHNESS_MAX_AGE):
        return []
    return [
        ConflictFinding(
            classification=ConflictClassification.CLARIFICATION_REQUIRED,
            rule="stale_personal_context",
            reason=(
                f"The Personal Context for {label} has not been confirmed recently and "
                f"should be re-confirmed before it is relied upon."
            ),
            school_evidence=[],
            personal_context_evidence=[_ctx_evidence(ctx)],
        )
    ]


# --- helpers ----------------------------------------------------------------------


def _is_type(ctx: ChildContext, types: frozenset[str]) -> bool:
    return ctx.context_type.strip().lower() in types


def _parse_minutes(value: Any) -> int | None:
    """Parse the first ``HH:MM`` in ``value`` into minutes-since-midnight."""

    if not isinstance(value, str):
        return None
    m = _TIME_RE.search(value)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def _mention_state(text: str, term: str) -> str:
    """Classify how ``term`` appears in ``text``: 'positive' | 'negated' | 'absent'.

    ASCII terms are matched on word-ish boundaries to avoid substring false positives
    (e.g. 'nut' inside 'minute'); non-ASCII terms (e.g. Japanese) fall back to a plain
    substring test. A negation cue in the same clause flips 'positive' to 'negated'.
    """

    term = term.strip()
    if not term:
        return "absent"
    lo_text = text.lower()
    lo_term = term.lower()

    if term.isascii():
        pattern = r"(?<![a-z0-9])" + re.escape(lo_term) + r"(?![a-z0-9])"
        matches = list(re.finditer(pattern, lo_text))
        if not matches:
            return "absent"
        positions = [m.start() for m in matches]
    else:
        idx = lo_text.find(lo_term)
        if idx == -1:
            return "absent"
        positions = [idx]

    # Negated only if EVERY occurrence sits in a negated clause; a single unqualified
    # mention is enough to flag (fail toward flagging risk).
    for pos in positions:
        if not _is_negated(lo_text, pos):
            return "positive"
    return "negated"


def _is_negated(text: str, pos: int) -> bool:
    """True when the mention at ``pos`` is within a negation clause."""

    seps = (".", ",", ";", "\n", "。", "、")
    clause_start = max((text.rfind(sep, 0, pos) for sep in seps), default=-1)
    clause_start = clause_start + 1 if clause_start >= 0 else 0
    window = text[clause_start:pos]
    after = text[pos:]
    if any(cue in window for cue in _NEGATION_CUES):
        return True
    # trailing forms: "peanut-free", "peanut free", "含まない" immediately after
    return bool(re.match(r"[a-z0-9]*[\s-]*free\b", after)) or "含まない" in after[:8]


def _food_text(si: dict[str, Any]) -> str:
    parts = [_as_text(si.get(f)) for f in ("food_information", "required_items", "activity")]
    return " ".join(p for p in parts if p).strip()


def _activity_text(si: dict[str, Any]) -> str:
    fields = ("event", "activity", "transportation", "relevant_instructions", "food_information")
    parts = [_as_text(si.get(f)) for f in fields]
    return " ".join(p for p in parts if p).strip()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def _fields_evidence(si: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    """Render the present school fields (in the given order) as ``field: value``."""

    out: list[str] = []
    for f in fields:
        if f in si and si[f] not in (None, "", []):
            out.append(f"{f}: {_as_text(si[f])}")
    return out


def _school_summary(school: SchoolInformation) -> list[str]:
    si = school.structured_information or {}
    summary = _fields_evidence(si, ("event", "date", "start_time", "end_time"))
    if summary:
        return summary
    return [f"document_id: {school.document_id}"]


def _ctx_evidence(ctx: ChildContext) -> str:
    value = f"={ctx.value}" if ctx.value else ""
    return f"{ctx.context_type}{value} ({ctx.status.value})"


def _dedupe(items: Any) -> list[str]:
    seen: dict[str, None] = {}
    for it in items:
        if it not in seen:
            seen[it] = None
    return list(seen)


_OVERALL_DETAIL: dict[ConflictClassification, str] = {
    ConflictClassification.CONFIRMED_RELEVANCE: (
        "A deterministic rule confirmed this document is relevant to the child."
    ),
    ConflictClassification.INFORMATION_MISSING: (
        "A relevant fact is unknown; risk cannot be ruled out (potential False Negative)."
    ),
    ConflictClassification.CLARIFICATION_REQUIRED: (
        "Known facts are stale or contradictory; a human must reconcile them."
    ),
    ConflictClassification.NO_RELEVANT_MATCH_FOUND: (
        "No rule matched. This is NOT an assertion of safety / no risk."
    ),
}
