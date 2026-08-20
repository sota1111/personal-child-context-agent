"""Structured School Information produced by the Document Tool.

The Document Tool never fabricates missing values; unparseable fields stay absent
(``Unknown``). Evidence and source are always retained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SchoolInformation:
    """One school document, parsed into structured fields.

    `structured_information` holds extracted fields such as event / date /
    start_time / end_time / food_information / required_items / transportation /
    activity / relevant_instructions. Missing fields are simply absent (Unknown).
    """

    document_id: str
    structured_information: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    source: str | None = None
    created_at: datetime | None = None
