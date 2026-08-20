"""Domain models — the shape of the persistent source of truth (Firestore).

Skeleton definitions (SOT-2738). The full field set / validation / Firestore
mapping is completed in SOT-2739.
"""

from pcca.models.actions import Action, ActionStatus, ActionType
from pcca.models.child_context import ChildContext, ContextStatus, treat_as_absent
from pcca.models.conflict import ConflictClassification, ConflictResult
from pcca.models.school_information import SchoolInformation

__all__ = [
    "Action",
    "ActionStatus",
    "ActionType",
    "ChildContext",
    "ContextStatus",
    "treat_as_absent",
    "ConflictClassification",
    "ConflictResult",
    "SchoolInformation",
]
