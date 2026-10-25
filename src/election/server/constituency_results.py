"""Current provisional constituency totals from explicitly selected scope rounds."""

import hashlib
import json
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.box_models import BallotBox
from election.server.configuration_models import Candidate, Constituency, Election
from election.server.counting_round_models import CountRoundRevision
from election.server.counting_rounds import round_at, round_context, round_view
from election.server.counting_scopes import scope_options
from election.server.models import Account
from election.server.station_models import PollingStation
from election.server.stock import stock_scope


def _digest(inputs: dict[str, Any]) -> str:
    encoded = json.dumps(
        jsonable_encoder(inputs), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pending(
    code: str,
    *,
    station_id: int | None = None,
    scope_id: int | None = None,
    box_ids: list[int] | None = None,
    **details: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code}
    if station_id is not None:
        result["station_id"] = station_id
    if scope_id is not None:
        result["scope_id"] = scope_id
    if box_ids is not None:
        result["box_ids"] = sorted(box_ids)
    result.update(details)
    return result


def _selected_round(
    db: Session, actor: Account, station_id: int, scope_id: int
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    options = round_context(db, actor, station_id, scope_id)
    selection = options.get("selection")
    if selection is None:
        return options, None
    revision = db.get(CountRoundRevision, selection["round_revision_id"])
    if revision is None:
        return options, None
    count_round = round_at(db, scope_id, selection["round_id"])
    return options, round_view(db, count_round, revision, options)


def constituency_results_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/constituencies", tags=["Constituency results"])
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/{constituency_id}/results")
    def read_results(constituency_id: int, db: Database, actor: Ready) -> dict[str, Any]:
        if actor.role != "supervisor":
            raise HTTPException(403, detail={"code": "supervisor_required"})
        constituency = db.scalar(
            select(Constituency).where(Constituency.id == constituency_id)
        )
        if constituency is None:
            raise HTTPException(404, detail={"code": "constituency_not_found"})
        election = db.get(Election, constituency.election_id)
        if election is None:
            raise HTTPException(404, detail={"code": "constituency_not_found"})
        stations = list(
            db.scalars(
                select(PollingStation)
                .where(PollingStation.constituency_id == constituency_id)
                .order_by(PollingStation.id)
            )
        )
        if not stations:
            raise HTTPException(409, detail={"code": "constituency_stations_missing"})
        station_states = []
        for station in stations:
            stock_scope(db, actor, station.id)
            station_states.append(
                {
                    "id": station.id,
                    "code": station.code,
                    "name": station.name,
                    "revision": station.revision,
                    "counting_mode": station.counting_mode,
                    "destination_station_id": station.destination_station_id,
                }
            )

        candidates = list(
            db.scalars(
                select(Candidate)
                .where(Candidate.constituency_id == constituency_id)
                .order_by(Candidate.ballot_number, Candidate.id)
            )
        )
        candidate_states = [
            {"id": row.id, "ballot_number": row.ballot_number, "name": row.name,
             "revision": row.revision}
            for row in candidates
        ]
        totals: dict[int, int | None] = {row.id: None for row in candidates}
        station_ids = [row.id for row in stations]
        origin_boxes: dict[int, list[int]] = {station_id: [] for station_id in station_ids}
        for origin_id, box_id in db.execute(
            select(BallotBox.origin_station_id, BallotBox.id)
            .where(BallotBox.origin_station_id.in_(station_ids))
            .order_by(BallotBox.origin_station_id, BallotBox.id)
        ):
            origin_boxes[origin_id].append(box_id)

        pending: list[dict[str, Any]] = []
        for station in stations:
            if not origin_boxes[station.id]:
                pending.append(_pending("station_boxes_missing", station_id=station.id, box_ids=[]))

        contributions: list[dict[str, Any]] = []
        scope_inputs: list[dict[str, Any]] = []
        counting_station_inputs: list[dict[str, Any]] = []
        for station in stations:
            if station.counting_mode != "local":
                counting_station_inputs.append(
                    {"station_id": station.id, "counting_applicable": False,
                     "origin_box_ids": origin_boxes[station.id]}
                )
                continue
            options = scope_options(db, actor, station.id)
            unscoped = [box["id"] for box in options["boxes"] if box.get("scope_id") is None]
            if unscoped:
                pending.append(_pending("box_unscoped", station_id=station.id, box_ids=unscoped))
            counting_station_inputs.append(
                {
                    "station_id": station.id,
                    "counting_applicable": options["counting_applicable"],
                    "origin_box_ids": origin_boxes[station.id],
                    "boxes": options["boxes"],
                    "source_accounting": options["source_accounting"],
                }
            )
            for scope in options["scopes"]:
                box_basis = scope.get("box_basis", [])
                if not box_basis:
                    continue
                scope_id = scope["id"]
                box_ids = sorted(box["id"] for box in box_basis)
                state = {
                    "station_id": station.id,
                    "scope_id": scope_id,
                    "scope_revision": scope["revision"],
                    "revision_id": scope["revision_id"],
                    "status": scope["status"],
                    "is_current": scope["is_current"],
                    "source_current": scope["source_current"],
                    "count_ready": scope["count_ready"],
                    "blockers": scope["blockers"],
                    "box_basis": box_basis,
                    "accounting_basis": scope["accounting_basis"],
                    "coverage": scope["coverage"],
                    "estimated_box_from_stock_quantity": scope[
                        "estimated_box_from_stock_quantity"
                    ],
                    "estimated_box_from_turnout_quantity": scope[
                        "estimated_box_from_turnout_quantity"
                    ],
                }
                if not scope["count_ready"]:
                    pending.append(
                        _pending("scope_not_ready", station_id=station.id, scope_id=scope_id,
                                 box_ids=box_ids, blockers=scope["blockers"])
                    )

                round_options, selected = _selected_round(db, actor, station.id, scope_id)
                pointer = round_options.get("selection")
                state["selection"] = pointer
                if pointer is None:
                    pending.append(
                        _pending("selected_count_missing", station_id=station.id,
                                 scope_id=scope_id, box_ids=box_ids)
                    )
                elif (
                    not pointer.get("valid") or not pointer.get("is_current") or selected is None
                    or not selected["approval_valid"] or not selected["source_current"]
                    or not selected["count_complete"] or selected["status"] != "approved"
                    or not selected["selected"]
                ):
                    pending.append(
                        _pending("selected_count_stale", station_id=station.id,
                                 scope_id=scope_id, box_ids=box_ids,
                                 selection_revision=pointer["revision"],
                                 round_id=pointer["round_id"],
                                 round_revision=pointer["round_revision"])
                    )
                else:
                    final_votes = selected.get("final_candidate_votes", [])
                    by_candidate = {row["candidate_id"]: row["quantity"] for row in final_votes}
                    if (
                        set(by_candidate) != set(totals)
                        or any(quantity is None for quantity in by_candidate.values())
                    ):
                        pending.append(
                            _pending("selected_count_stale", station_id=station.id,
                                     scope_id=scope_id, box_ids=box_ids,
                                     selection_revision=pointer["revision"],
                                     round_id=pointer["round_id"],
                                     round_revision=pointer["round_revision"])
                        )
                    else:
                        for candidate_id, quantity in by_candidate.items():
                            totals[candidate_id] = (totals[candidate_id] or 0) + quantity
                        contributions.append(
                            {
                                "scope_id": scope_id,
                                "station_id": station.id,
                                "scope_revision": scope["revision"],
                                "round_id": selected["id"],
                                "round_number": selected["round_number"],
                                "round_revision": selected["revision"],
                                "round_revision_id": selected["revision_id"],
                                "selection_revision": pointer["revision"],
                                "frozen_source_context": selected["scope_basis"],
                                "final_candidate_votes": final_votes,
                            }
                        )
                        state["selected_round"] = {
                            "round_id": selected["id"],
                            "round_number": selected["round_number"],
                            "revision_id": selected["revision_id"],
                            "revision": selected["revision"],
                            "status": selected["status"],
                            "source_current": selected["source_current"],
                            "count_complete": selected["count_complete"],
                            "approval_valid": selected["approval_valid"],
                            "final_candidate_votes": final_votes,
                            "scope_basis": selected["scope_basis"],
                        }
                scope_inputs.append(state)

        known = [quantity for quantity in totals.values() if quantity is not None]
        leaders = []
        if known:
            highest = max(known)
            leaders = [candidate_id for candidate_id, quantity in totals.items()
                       if quantity == highest]
        ties = leaders if len(leaders) > 1 else []
        total_rows = [
            {"candidate_id": row.id, "ballot_number": row.ballot_number,
             "name": row.name, "quantity": totals[row.id]}
            for row in candidates
        ]
        complete = bool(stations and candidates and contributions) and not pending
        provisional = election.status != "finalized"
        context = {
            "election": {"id": election.id, "name": election.name,
                         "status": election.status, "revision": election.revision},
            "constituency": {"id": constituency.id, "code": constituency.code,
                              "name": constituency.name, "revision": constituency.revision},
        }
        basis = {
            "context": context,
            "candidates": candidate_states,
            "stations": station_states,
            "origin_box_ids": origin_boxes,
            "counting_stations": counting_station_inputs,
            "scopes": scope_inputs,
            "pending": pending,
            "contributions": contributions,
            "candidate_totals": total_rows,
            "complete": complete,
            "provisional": provisional,
            "leader_candidate_ids": leaders,
            "tie_candidate_ids": ties,
        }
        return {
            "context": context,
            "candidate_totals": total_rows,
            "contributions": contributions,
            "pending": pending,
            "complete": complete,
            "provisional": provisional,
            "leader_candidate_ids": leaders,
            "tie_candidate_ids": ties,
            "basis_digest": _digest(basis),
        }

    return router
