"""Current invalid-reason choices retain separate verified-source provenance."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.invalid_ballot_defaults import DEFAULT_INVALID_REASONS
from election.server.invalid_ballot_models import InvalidBallotReason, InvalidBallotReasonRevision
from election.server.polling import as_utc


def seed_invalid_ballot_reasons(
    db: Session,
    election_id: int,
    actor_id: int | None,
    now: datetime,
) -> None:
    for seed in DEFAULT_INVALID_REASONS:
        reason = InvalidBallotReason(
            election_id=election_id,
            code=seed["code"],
            stage=seed["stage"],
            verified_source=seed["verified_source"],
            source_english=seed["source_english"],
            source_letter=seed["source_letter"],
            reference_page=seed["reference_page"],
            reference_printed_page=seed["reference_printed_page"],
            is_other=seed["is_other"],
        )
        db.add(reason)
        db.flush()
        db.add(
            InvalidBallotReasonRevision(
                reason_id=reason.id,
                revision=1,
                label_en=seed["label_en"],
                label_tc=seed["label_tc"],
                label_sc=seed["label_sc"],
                enabled=True,
                explanation_required=seed["explanation_required"],
                entered_at=now,
                actor_id=actor_id,
            )
        )


def invalid_reason_view(
    reason: InvalidBallotReason,
    row: InvalidBallotReasonRevision,
) -> dict[str, Any]:
    return {
        "id": reason.id,
        "election_id": reason.election_id,
        "code": reason.code,
        "stage": reason.stage,
        "verified_source": reason.verified_source,
        "source": "verified_reference" if reason.verified_source else "project_configured",
        "source_english": reason.source_english,
        "source_letter": reason.source_letter,
        "reference_page": reason.reference_page,
        "reference_printed_page": reason.reference_printed_page,
        "is_other": reason.is_other,
        "revision": row.revision,
        "revision_id": row.id,
        "label_en": row.label_en,
        "label_tc": row.label_tc,
        "label_sc": row.label_sc,
        "translation_provenance": "project_translation",
        "enabled": row.enabled,
        "explanation_required": row.explanation_required,
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
    }


def invalid_reason_rows(db: Session, election_id: int) -> list[dict[str, Any]]:
    reasons = list(
        db.scalars(
            select(InvalidBallotReason)
            .where(
                InvalidBallotReason.election_id == election_id,
            )
            .order_by(InvalidBallotReason.id)
            .with_for_update()
        )
    )
    revisions = list(
        db.scalars(
            select(InvalidBallotReasonRevision)
            .join(
                InvalidBallotReason,
                InvalidBallotReason.id == InvalidBallotReasonRevision.reason_id,
            )
            .where(InvalidBallotReason.election_id == election_id)
            .order_by(
                InvalidBallotReasonRevision.revision,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    latest = {row.reason_id: row for row in revisions}
    return [invalid_reason_view(reason, latest[reason.id]) for reason in reasons]
