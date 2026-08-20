# Personal Child Context Agent

**Same information. Different child. Different action.**

Schools send generic information, but every child has different needs. Parents
still have to figure out what matters to *their* child. This agent closes the gap
between **Generic School Information** and **Personal Child Context**.

It continuously reconciles the two and surfaces — *with evidence* — what is
relevant to this child, explicit conflicts, missing information needed to decide,
questions for the parent, and the next required action. It does not just display a
warning and stop: with the parent's approval it performs real actions, keeps
unresolved items as **persistent actions**, and re-evaluates them when new school
information arrives.

## Core flow

```
Detect → Clarify → Plan → Act → Track → Re-evaluate
```

The initial MVP focuses on **Field Trip / Excursion Readiness**.

## Architecture

```
                 ADK Root Agent            (orchestration only — NOT source of truth)
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
  Document Tool   Conflict Tool   Action Tools
                                   ├─ Calendar
                                   ├─ Reminder
                                   └─ Gmail Draft
                       │
                       ↓
                   Firestore
              Context / Actions          (persistent source of truth)
```

- **ADK Root Agent** — orchestrates the workflow (tool selection, ordering,
  clarification, planning, human approval, re-evaluation). It never holds the
  source of truth; facts and action state come from Firestore. Uses **Gemini via
  Vertex AI**.
- **Document Tool** — turns school documents (PDF / image / newsletter / notice /
  lunch / schedule / text) into structured School Information. Never fabricates
  missing values — unparseable data stays `Unknown`. Keeps evidence & source.
- **Conflict Tool** — reconciles structured School Information against Personal
  Child Context. Prefers **deterministic logic** (e.g. time-overlap) over the LLM.
  Returns one of four classifications plus evidence.
- **Action Tools** — Calendar (dedup-protected), Reminder, Gmail **Draft** (never
  auto-sent; human-in-the-loop). Human approval + idempotency.
- **Firestore** — persistent source of truth for `ChildContext`,
  `SchoolInformation`, `Actions`.

### Conflict classifications

| Classification | Meaning |
| --- | --- |
| `CONFIRMED_RELEVANCE` | An explicit relevance/conflict exists. |
| `INFORMATION_MISSING` | School-side information needed to evaluate is missing. |
| `CLARIFICATION_REQUIRED` | Personal Context is unconfirmed, stale, or ambiguous. |
| `NO_RELEVANT_MATCH_FOUND` | No relevant item found from current evidence. **Not** "safe / no risk". |

### Personal Context model

`known_present` · `explicitly_absent` · `unknown`. `unknown` is **never** treated
as `explicitly_absent`.

## Safety boundaries

- Makes **no** medical judgements; never asserts "safe" / "can eat" / "no risk".
- States missing information explicitly; `unknown` is not treated as safe.
- Keeps evidence for every conflict and action; considers Personal Context
  freshness and detects stale context and inter-document contradictions.
- No unsupported medical generalisation from general knowledge — only relates
  facts explicitly present in Personal Context.
- Personal Context changes and external actions require **human approval**; Gmail
  is draft-only. Minimises stored personal/health data and avoids logging it.

## Status

Bootstrap skeleton (SOT-2738) with the Firestore persistence layer & data models
in place (SOT-2739): `ChildContext` / `SchoolInformation` / `Action` models, the
Personal Context Model (`known_present` / `explicitly_absent` / `unknown`, where
`unknown` is never treated as `explicitly_absent`), the `ActionStatus` enum, and an
idempotency-key-guarded repository with both in-memory and Firestore backends
(`PCCA_PERSISTENCE=memory|firestore`). Tools are still interface stubs; the
deterministic Conflict logic, Document extraction, Action execution, and the
evaluation dataset are implemented in follow-up issues (SOT-2740 … SOT-2744).

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy src && pytest       # CI runs the same
```

See `.env.example` for configuration (no real secrets are committed).
