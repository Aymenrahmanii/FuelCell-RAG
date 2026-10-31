from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from fcrag import audit
from fcrag.db.models import AuditRecord, Base


def test_prune_removes_only_rows_past_retention() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 31, tzinfo=UTC)
    with Session(engine) as session:
        for age in (1, 89, 91, 400):
            session.add(AuditRecord(endpoint="ask", question=f"{age}", sources=[],
                                    created_at=now - timedelta(days=age)))  # fmt: skip
        session.commit()
    assert audit.prune(90, engine, now=now) == 2
    with Session(engine) as session:
        assert sorted(session.scalars(select(AuditRecord.question))) == ["1", "89"]


def test_failed_answers_are_recorded_and_write_errors_swallowed() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    audit.record("q", None, user_id="bob", groups=None, endpoint="ask", error="Boom", engine=engine)
    with Session(engine) as session:
        row = session.scalars(select(AuditRecord)).one()
    assert row.error == "Boom" and row.answer is None and row.sources == []
    audit.record("q", None, user_id=None, groups=None, endpoint="ask",
                 engine=create_engine("sqlite://"))  # no table: logged, not raised  # fmt: skip
