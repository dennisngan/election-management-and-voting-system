"""Project preserved round occurrences into an authorized station timeline."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.counting_round_models import CountRound, CountRoundRevision
from election.server.counting_rounds import round_context, round_view
from election.server.counting_scope_models import CountingScope
from election.server.models import Account


def round_events(db: Session, actor: Account, station_id: int) -> list[dict[str, Any]]:
    scopes = list(
        db.scalars(
            select(CountingScope)
            .where(CountingScope.station_id == station_id)
            .order_by(CountingScope.id)
            .with_for_update()
        )
    )
    events = []
    for scope in scopes:
        options = round_context(db, actor, station_id, scope.id)
        rounds = list(
            db.scalars(
                select(CountRound)
                .where(CountRound.scope_id == scope.id)
                .order_by(CountRound.round_number)
                .with_for_update()
            )
        )
        for round in rounds:
            rows = list(
                db.scalars(
                    select(CountRoundRevision)
                    .where(CountRoundRevision.round_id == round.id)
                    .order_by(CountRoundRevision.revision.desc())
                    .with_for_update()
                )
            )
            if not rows:
                continue
            head = rows[0]
            current = round_view(db, round, head, options)
            by_revision = {row.revision: row for row in rows}
            seen = set()
            for row in rows:
                occurrences = (
                    ("determination_start", (row.data.get("f2") or {}).get("determination_event")),
                    ("count_completion", row.data.get("completion_event")),
                )
                for kind, occurrence in occurrences:
                    if occurrence is None:
                        continue
                    origin_revision = occurrence["origin_revision"]
                    key = (kind, origin_revision)
                    if key in seen:
                        continue
                    seen.add(key)
                    origin = by_revision[origin_revision]
                    head_event = (
                        (head.data.get("f2") or {}).get("determination_event")
                        if kind == "determination_start"
                        else head.data.get("completion_event")
                    )
                    is_current = bool(
                        head_event and head_event["origin_revision"] == origin_revision
                    )
                    events.append(
                        {
                            "event_id": f"round:{round.id}:{kind}:{origin_revision}",
                            "kind": kind,
                            "station_id": station_id,
                            "scope_id": scope.id,
                            "scope_reference": origin.data["scope_basis"]["reference"],
                            "scope_revision": origin.data["scope_revision"],
                            "round_id": round.id,
                            "round_number": round.round_number,
                            "round_revision": origin.revision,
                            "round_revision_id": origin.id,
                            "current_round_revision": head.revision,
                            "current_round_revision_id": head.id,
                            "event_at": occurrence["event_at"],
                            "entered_at": occurrence["entered_at"],
                            "actor_id": occurrence["actor_id"],
                            "amendment_reason": occurrence["amendment_reason"],
                            "is_current": is_current,
                            "source_current": current["source_current"],
                            "status": head.status if is_current else origin.status,
                            "approval_valid": bool(is_current and current["approval_valid"]),
                            "selected": bool(is_current and current["selected"]),
                            "selection_revision": options["selection"]["revision"]
                            if options["selection"]
                            else None,
                        }
                    )
    return sorted(events, key=lambda row: (row["event_at"], row["event_id"]), reverse=True)
