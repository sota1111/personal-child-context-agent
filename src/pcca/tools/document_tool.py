"""Document Tool — school document → structured School Information.

Interface stub (SOT-2738). Full extraction (PDF / image / newsletter / notice /
lunch / schedule / text), evidence retention, Unknown handling, and processing-
failure handling are implemented in SOT-2740.

Contract the real implementation must honour:
  * Never fabricate missing values — unparseable fields stay absent (Unknown).
  * Always retain `evidence` and `source`.
"""

from __future__ import annotations


def extract_school_information(document_ref: str, source: str = "unknown") -> dict:
    """Extract structured school information from a document.

    Args:
        document_ref: Reference to the document to parse (path, id, or raw text).
        source: Where the document came from (e.g. "email", "pdf", "portal").

    Returns:
        A dict with the structured fields, `evidence`, `source`, and a `status`.
        Missing fields are omitted rather than guessed.
    """

    return {
        "status": "not_implemented",
        "detail": "Document extraction is implemented in SOT-2740.",
        "document_ref": document_ref,
        "source": source,
        "structured_information": {},
        "evidence": [],
    }
