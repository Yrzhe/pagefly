"""Suggestion service: anchor resolution + storage + markdown apply.

Multiple pending suggestions per document are supported. On accept
the anchor is RE-resolved against the document's current canonical markdown so
an unrelated human edit that shifted offsets is handled, and a human edit that
removed the anchored text is refused as drift (the document is never mutated at
a wrong location). See docs/workspace spec §3a (drift).
"""

from __future__ import annotations

from src.shared import md
from src.storage import db
from src.workspace.anchor import AnchorNotFound, resolve_anchor


class SuggestionDrifted(Exception):
    """Anchored text changed since the suggestion was created; refuse to apply."""


def create_pending(
    *,
    document_id: str,
    quote: str,
    new_content: str,
    created_by: str,
    prefix: str | None = None,
    suffix: str | None = None,
    kind: str = "replace",
    idempotency_key: str | None = None,
) -> dict:
    """Resolve the quote against canonical markdown and store a pending row.

    Raises AnchorNotFound if the quote does not resolve uniquely.
    If idempotency_key replays a prior create, the original row is returned.
    """
    if idempotency_key:
        prior = db.get_suggestion_by_idempotency_key(idempotency_key)
        if prior:
            return prior

    doc = db.get_workspace_document(document_id)
    if not doc:
        raise ValueError("document not found")

    res = resolve_anchor(
        {"quote": quote, "prefix": prefix, "suffix": suffix}, doc["content_md"]
    )
    try:
        sid = db.create_workspace_suggestion(
            document_id=document_id,
            kind=kind,
            quote=quote,
            prefix=prefix,
            suffix=suffix,
            range_start=res.absolute_start,
            range_end=res.absolute_end,
            new_content=new_content,
            content_hash=res.content_hash,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
    except ValueError as e:
        # Concurrent replay of the same Idempotency-Key — return the winner.
        if str(e) == "IDEMPOTENCY_REPLAY" and idempotency_key:
            prior = db.get_suggestion_by_idempotency_key(idempotency_key)
            if prior:
                return prior
        raise
    return db.get_workspace_suggestion(sid)


def resolve(
    suggestion_id: str,
    *,
    action: str,
    resolved_by: str,
    rejection_reason: str | None = None,
) -> None:
    """Resolve a pending suggestion.

    accept → re-resolve anchor on current markdown, apply replacement, bump
             revision (optimistic lock). reject/cancel → document untouched.
    """
    sug = db.get_workspace_suggestion(suggestion_id)
    if not sug:
        raise ValueError("suggestion not found")
    if sug["status"] != "pending":
        raise ValueError(f"suggestion already resolved: {sug['status']}")

    if action != "accept":
        db.resolve_workspace_suggestion(
            suggestion_id, action=action, resolved_by=resolved_by,
            rejection_reason=rejection_reason,
        )
        return

    doc = db.get_workspace_document(sug["document_id"])
    if not doc:
        raise ValueError("document not found")

    # Re-resolve against the CURRENT markdown — tolerates unrelated offset
    # shifts, refuses if the anchored text itself changed.
    try:
        res = resolve_anchor(
            {"quote": sug["quote"], "prefix": sug["prefix"], "suffix": sug["suffix"]},
            doc["content_md"],
        )
    except AnchorNotFound as e:
        raise SuggestionDrifted(
            "anchored text no longer present; suggestion no longer applies"
        ) from e
    if res.content_hash != sug["content_hash"]:
        raise SuggestionDrifted("anchored text changed since the suggestion was made")

    new_md = (
        doc["content_md"][: res.absolute_start]
        + (sug["new_content"] or "")
        + doc["content_md"][res.absolute_end :]
    )
    new_html = md.markdown_to_html(new_md)

    # Optimistic lock on the document revision; re-derives content_md from HTML.
    db.update_workspace_document(
        sug["document_id"], expected_revision=doc["revision"], content=new_html
    )
    db.resolve_workspace_suggestion(
        suggestion_id, action="accept", resolved_by=resolved_by
    )
