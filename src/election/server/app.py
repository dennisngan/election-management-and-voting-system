from collections.abc import AsyncIterator, Callable, Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from election.server.accounting import accounting_router
from election.server.accounting_reports import accounting_reports_router
from election.server.allocation_reports import allocation_reports_router
from election.server.allocations import allocation_router
from election.server.box_reports import box_reports_router
from election.server.boxes import box_router
from election.server.complaint_categories import complaint_categories_router
from election.server.complaint_periods import complaint_periods_router
from election.server.complaint_reports import complaint_reports_router
from election.server.complaints import complaints_router
from election.server.config import Settings
from election.server.configuration import configuration_router
from election.server.constituency_reports import constituency_reports_router
from election.server.constituency_results import constituency_results_router
from election.server.constituency_ties import constituency_ties_router
from election.server.count_reports import count_reports_router
from election.server.counting_discrepancies import counting_discrepancies_router
from election.server.counting_outcomes import counting_outcomes_router
from election.server.counting_rounds import counting_rounds_router
from election.server.counting_scope_reports import counting_scope_reports_router
from election.server.counting_scopes import counting_scopes_router
from election.server.counting_workflow import counting_workflow_router
from election.server.db import make_engine
from election.server.f1_reports import f1_reports_router
from election.server.fallback import fallback_router
from election.server.invalid_ballot_reasons import invalid_ballot_reasons_router
from election.server.lifecycle import lifecycle_router
from election.server.models import Account, AuditEvent, LoginSession
from election.server.polling import polling_router
from election.server.queue import queue_router
from election.server.queue_reports import queue_reports_router
from election.server.security import hash_password, token_digest, verify_password
from election.server.special_paper_reports import special_paper_reports_router
from election.server.special_papers import special_paper_router
from election.server.staff import staff_router, station_access_router
from election.server.stations import stations_router
from election.server.stock import stock_router
from election.server.stock_reports import stock_reports_router
from election.server.stock_returns import stock_return_router
from election.server.stock_snapshot_reports import stock_snapshot_reports_router
from election.server.stock_snapshots import stock_snapshot_router
from election.server.turnout import turnout_router
from election.server.turnout_reports import turnout_reports_router


def utc_now() -> datetime:
    return datetime.now(UTC)


def account_view(account: Account) -> dict[str, Any]:
    return {
        "id": account.id,
        "username": account.username,
        "display_name": account.display_name,
        "role": account.role,
        "must_change_password": account.must_change_password,
    }


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128, repr=False)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128, repr=False)
    new_password: str = Field(min_length=12, max_length=128, repr=False)


def create_app(
    database_url: str | None = None, *, now: Callable[[], datetime] = utc_now
) -> FastAPI:
    engine = make_engine(database_url or Settings().database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="Election management", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def timestamp() -> datetime:
        return now().astimezone(UTC).replace(tzinfo=None)

    def database() -> Generator[Session]:
        with Session(engine) as session:
            yield session

    Database = Annotated[Session, Depends(database)]

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "validation_error",
                    "fields": [str(error["loc"][-1]) for error in exc.errors()],
                }
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": {"code": "database_unavailable"}})

    def authenticated(
        db: Database,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> tuple[Account, LoginSession]:
        session = (
            db.get(LoginSession, token_digest(credentials.credentials)) if credentials else None
        )
        account = db.get(Account, session.account_id) if session else None
        if not session or not account or not account.enabled or timestamp() >= session.expires_at:
            raise HTTPException(401, detail={"code": "session_expired"})
        return account, session

    Identity = Annotated[tuple[Account, LoginSession], Depends(authenticated)]

    def ready_account(identity: Identity) -> Account:
        account = identity[0]
        if account.must_change_password:
            raise HTTPException(403, detail={"code": "password_change_required"})
        return account

    ReadyAccount = Annotated[Account, Depends(ready_account)]

    def administrator(account: ReadyAccount) -> Account:
        if account.role != "administrator":
            raise HTTPException(403, detail={"code": "administrator_required"})
        return account

    app.include_router(configuration_router(database, administrator, timestamp))
    app.include_router(constituency_results_router(database, ready_account, timestamp))
    app.include_router(constituency_reports_router(database, ready_account, timestamp))
    app.include_router(constituency_ties_router(database, ready_account, timestamp))
    app.include_router(
        complaint_categories_router(database, administrator, ready_account, timestamp)
    )
    app.include_router(
        invalid_ballot_reasons_router(database, administrator, ready_account, timestamp)
    )
    app.include_router(complaints_router(database, ready_account, timestamp))
    app.include_router(complaint_reports_router(database, ready_account, timestamp))
    app.include_router(complaint_periods_router(database, ready_account, timestamp))
    app.include_router(stations_router(database, administrator, timestamp))
    app.include_router(lifecycle_router(database, administrator, ready_account, timestamp))
    app.include_router(staff_router(database, administrator, timestamp))
    app.include_router(station_access_router(database, ready_account))
    app.include_router(polling_router(database, ready_account, timestamp))
    app.include_router(queue_router(database, ready_account, timestamp))
    app.include_router(queue_reports_router(database, ready_account, timestamp))
    app.include_router(box_reports_router(database, ready_account, timestamp))
    app.include_router(box_router(database, ready_account, timestamp))
    app.include_router(turnout_reports_router(database, ready_account, timestamp))
    app.include_router(turnout_router(database, ready_account, timestamp))
    app.include_router(fallback_router(database, ready_account, timestamp))
    app.include_router(stock_router(database, ready_account, timestamp))
    app.include_router(stock_reports_router(database, ready_account, timestamp))
    app.include_router(allocation_reports_router(database, ready_account, timestamp))
    app.include_router(allocation_router(database, ready_account, timestamp))
    app.include_router(stock_snapshot_reports_router(database, ready_account, timestamp))
    app.include_router(stock_snapshot_router(database, ready_account, timestamp))
    app.include_router(stock_return_router(database, ready_account, timestamp))
    app.include_router(special_paper_reports_router(database, ready_account, timestamp))
    app.include_router(special_paper_router(database, ready_account, timestamp))
    app.include_router(accounting_router(database, ready_account, timestamp))
    app.include_router(counting_scopes_router(database, ready_account, timestamp))
    app.include_router(counting_rounds_router(database, ready_account, timestamp))
    app.include_router(counting_outcomes_router(database, ready_account, timestamp))
    app.include_router(counting_workflow_router(database, ready_account, timestamp))
    app.include_router(counting_discrepancies_router(database, ready_account, timestamp))
    app.include_router(f1_reports_router(database, ready_account, timestamp))
    app.include_router(count_reports_router(database, ready_account, timestamp))
    app.include_router(counting_scope_reports_router(database, ready_account, timestamp))
    app.include_router(accounting_reports_router(database, ready_account, timestamp))

    def new_session(db: Session, account: Account) -> dict[str, Any]:
        token = token_urlsafe(32)
        created = timestamp()
        expires = created + timedelta(hours=24)
        db.add(
            LoginSession(
                token_hash=token_digest(token),
                account_id=account.id,
                created_at=created,
                expires_at=expires,
            )
        )
        return {
            "token": token,
            "expires_at": expires.replace(tzinfo=UTC),
            "account": account_view(account),
        }

    @app.get("/api/health")
    def health(db: Database) -> dict[str, object]:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "server_time": now().astimezone(UTC)}

    @app.post("/api/auth/login")
    def login(data: LoginInput, db: Database) -> dict[str, Any]:
        account = db.scalar(
            select(Account).where(Account.username == data.username).with_for_update()
        )
        if not verify_password(account.password_hash if account else None, data.password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        if not account or not account.enabled:
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        result = new_session(db, account)
        db.add(
            AuditEvent(actor_id=account.id, action="sign_in", occurred_at=timestamp(), details={})
        )
        db.commit()
        return result

    @app.get("/api/auth/me")
    def me(identity: Identity) -> dict[str, Any]:
        return account_view(identity[0])

    @app.post("/api/auth/password")
    def password(data: PasswordInput, db: Database, identity: Identity) -> dict[str, Any]:
        account = db.scalar(
            select(Account)
            .where(Account.id == identity[0].id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not account or not verify_password(account.password_hash, data.current_password):
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        if data.current_password == data.new_password:
            raise HTTPException(422, detail={"code": "password_unchanged"})
        account.password_hash = hash_password(data.new_password)
        account.must_change_password = False
        account.revision += 1
        db.execute(delete(LoginSession).where(LoginSession.account_id == account.id))
        result = new_session(db, account)
        db.add(
            AuditEvent(
                actor_id=account.id, action="password_changed", occurred_at=timestamp(), details={}
            )
        )
        db.commit()
        return result

    @app.get("/api/workspace")
    def workspace(identity: Identity) -> dict[str, Any]:
        account = identity[0]
        if account.must_change_password:
            raise HTTPException(403, detail={"code": "password_change_required"})
        return {
            "account": account_view(account),
            "election": None,
            "constituency": None,
            "station": None,
            "server_time": now().astimezone(UTC),
        }

    @app.delete("/api/auth/session", status_code=204)
    def logout(db: Database, identity: Identity) -> Response:
        account, session = identity
        db.delete(session)
        db.add(
            AuditEvent(actor_id=account.id, action="sign_out", occurred_at=timestamp(), details={})
        )
        db.commit()
        return Response(status_code=204)

    return app
