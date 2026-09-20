"""Stored scorecards, session listing and progress across attempts (memory store and a faked MongoDB)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from helpers import completed_session, fresh_service, make_metrics, run
from surge_prep.coaching import COMPONENTS
from surge_prep.models import ProgressSummary, ResultRecord, Session, SessionStatus
from surge_prep.progress import summarize_progress
from surge_prep.store import MemoryStore, MongoStore

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def record(n: int, score: float, device="demo", **metric_overrides) -> ResultRecord:
    return ResultRecord(
        session_id=f"s{n}", exercise_id="chest-tube-access-demo", device_id=device, tool_id="scalpel",
        completed_at=T0 + timedelta(minutes=n),
        metrics=make_metrics(illustrative_score_percent=score, **metric_overrides),
    )


# ---------------------------------------------------------------- completing a session stores its result


def test_complete_session_stores_the_scorecard():
    service = fresh_service()
    session, result = run(completed_session(service))
    stored = run(service.store.get_result(session.session_id))
    assert stored is not None
    assert stored.metrics == result.metrics
    assert stored.device_id == "demo" and stored.tool_id == "scalpel"
    assert stored.completed_at == result.session.completed_at


def test_get_result_returns_stored_record():
    service = fresh_service()
    session, result = run(completed_session(service))
    assert run(service.get_result(session.session_id)).metrics == result.metrics


def test_get_result_unknown_session_is_404():
    with pytest.raises(HTTPException) as error:
        run(fresh_service().get_result("nope"))
    assert error.value.status_code == 404


def test_get_result_for_active_session_is_409():
    async def scenario():
        from helpers import IDENTITY
        from surge_prep.models import CalibrationCreate, SessionCreate
        service = fresh_service()
        cal = await service.create_calibration(CalibrationCreate(device_id="d", transform=IDENTITY, rms_error_mm=0.1))
        session = await service.create_session(SessionCreate(
            exercise_id="x", calibration_id=cal.calibration_id, tool_id="scalpel", device_id="d"))
        return await service.get_result(session.session_id)

    with pytest.raises(HTTPException) as error:
        run(scenario())
    assert error.value.status_code == 409


def test_old_completed_session_without_result_is_rescored_and_saved():
    service = fresh_service()
    session, result = run(completed_session(service))
    service.store.results.clear()                      # simulate a session completed before results were stored
    rebuilt = run(service.get_result(session.session_id))
    assert rebuilt.metrics == result.metrics
    assert run(service.store.get_result(session.session_id)) is not None


def test_completing_twice_does_not_create_a_second_result():
    service = fresh_service()
    session, _ = run(completed_session(service))
    with pytest.raises(HTTPException) as error:
        run(service.complete_session(session.session_id))
    assert error.value.status_code == 409
    assert len(service.store.results) == 1


# ---------------------------------------------------------------- listing sessions


def test_list_sessions_newest_first_with_limit():
    service = fresh_service()
    made = [run(completed_session(service))[0] for _ in range(3)]
    listed = run(service.list_sessions(2))
    assert [s.session_id for s in listed] == [made[2].session_id, made[1].session_id]
    assert len(run(service.list_sessions(10))) == 3
    assert run(service.list_sessions(0)) == []


def test_list_sessions_empty():
    assert run(fresh_service().list_sessions()) == []


# ---------------------------------------------------------------- progress maths


def test_progress_for_no_attempts():
    summary = summarize_progress([])
    assert summary == ProgressSummary(attempts=0)
    assert summary.trend == [] and summary.weakest_component is None


def test_progress_single_attempt_has_no_improvement():
    summary = summarize_progress([record(1, 70)])
    assert summary.attempts == 1
    assert summary.improvement_points is None
    assert summary.latest_score_percent == summary.best_score_percent == summary.average_score_percent == 70


def test_progress_improvement_best_and_average():
    summary = summarize_progress([record(1, 50), record(2, 80), record(3, 65)])
    assert summary.attempts == 3
    assert summary.latest_score_percent == 65
    assert summary.best_score_percent == 80
    assert summary.average_score_percent == 65
    assert summary.improvement_points == 15            # latest minus first


def test_progress_trend_keeps_order_and_scores():
    summary = summarize_progress([record(1, 40), record(2, 60), record(3, 90)])
    assert [p.session_id for p in summary.trend] == ["s1", "s2", "s3"]
    assert [p.score_percent for p in summary.trend] == [40, 60, 90]


def test_progress_weakest_component_is_weighted_shortfall():
    # every attempt loses all corridor points (10%) but only some tube points (5%)
    records = [record(n, 60, outside_corridor_contacts=20, tube_placement_complete=(n % 2 == 0)) for n in range(1, 5)]
    summary = summarize_progress(records)
    assert summary.weakest_component == "corridor"
    assert summary.component_averages["corridor"] == 0
    assert summary.component_averages["tube"] == 50


def test_progress_component_averages_cover_every_component():
    summary = summarize_progress([record(1, 70), record(2, 75)])
    assert set(summary.component_averages) == {name for name, *_ in COMPONENTS}
    assert all(0 <= v <= 100 for v in summary.component_averages.values())


def test_progress_serialises_camel_case():
    data = summarize_progress([record(1, 50), record(2, 70)]).model_dump(by_alias=True, mode="json")
    assert {"attempts", "latestScorePercent", "bestScorePercent", "improvementPoints",
            "weakestComponent", "componentAverages", "trend"} <= set(data)
    assert {"sessionId", "completedAt", "scorePercent"} <= set(data["trend"][0])


def test_service_progress_filters_by_device_and_limits():
    service = fresh_service()
    for n, device in enumerate(["a", "b", "a", "a"], start=1):
        run(service.store.save_result(record(n, 50 + n * 5, device=device)))
    assert run(service.progress("a")).attempts == 3
    assert run(service.progress("b")).attempts == 1
    assert run(service.progress(None)).attempts == 4
    limited = run(service.progress("a", limit=2))
    assert [p.session_id for p in limited.trend] == ["s3", "s4"]     # the most recent two, oldest first
    assert run(service.progress("nobody")).attempts == 0


# ---------------------------------------------------------------- memory store


def test_memory_store_results_are_upserted_by_session():
    store = MemoryStore()
    run(store.save_result(record(1, 40)))
    run(store.save_result(record(1, 90)))
    assert len(store.results) == 1
    assert run(store.get_result("s1")).metrics.illustrative_score_percent == 90


def test_memory_store_list_results_oldest_first():
    store = MemoryStore()
    for n in (3, 1, 2):
        run(store.save_result(record(n, 10 * n)))
    assert [r.session_id for r in run(store.list_results())] == ["s1", "s2", "s3"]
    assert [r.session_id for r in run(store.list_results(limit=2))] == ["s2", "s3"]
    assert run(store.list_results(limit=0)) == []


# ---------------------------------------------------------------- MongoStore against a faked database


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction=None):
        specs = key if isinstance(key, list) else [(key, direction)]
        for name, order in reversed(specs):                 # stable multi-key sort; a missing _id sorts as equal
            self.docs.sort(key=lambda d, n=name: d.get(n, 0), reverse=(order == -1))
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __aiter__(self):
        async def gen():
            for doc in self.docs:
                yield doc
        return gen()


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []
        self.indexes: list[tuple] = []

    async def create_index(self, keys, **kwargs):
        self.indexes.append((tuple(keys), kwargs))

    async def replace_one(self, query, document, upsert=False):
        for i, doc in enumerate(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                self.docs[i] = dict(document)
                return
        if upsert:
            self.docs.append(dict(document))

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return {k: v for k, v in doc.items() if k != "_id"}
        return None

    def find(self, query, projection=None):
        docs = [{k: v for k, v in d.items() if k != "_id"} for d in self.docs
                if all(d.get(k) == v for k, v in query.items())]
        return FakeCursor(docs)


class FakeDb:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getattr__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def fake_mongo_store() -> MongoStore:
    store = MongoStore.__new__(MongoStore)            # skip connecting to a real server
    store.db = FakeDb()
    return store


class FakeAdmin:
    async def command(self, name):
        return {"ok": 1}


class FakeClient:
    admin = FakeAdmin()

    async def close(self):
        pass


def test_mongo_start_creates_the_result_and_session_indexes():
    store = fake_mongo_store()
    store.client = FakeClient()
    run(store.start())
    result_indexes = store.db.results.indexes
    assert ((("sessionId", 1),), {"unique": True}) in result_indexes
    assert ((("deviceId", 1), ("completedAt", -1)), {}) in result_indexes
    assert ((("createdAt", -1),), {}) in store.db.sessions.indexes
    assert ((("sessionId", 1), ("sequence", 1)), {"unique": True}) in store.db.samples.indexes


def test_mongo_result_round_trip_and_upsert():
    store = fake_mongo_store()
    run(store.save_result(record(1, 40)))
    run(store.save_result(record(1, 55)))
    assert len(store.db.results.docs) == 1
    stored = run(store.get_result("s1"))
    assert stored.metrics.illustrative_score_percent == 55
    assert run(store.get_result("missing")) is None


def test_mongo_documents_use_camel_case_keys():
    store = fake_mongo_store()
    run(store.save_result(record(1, 40)))
    doc = store.db.results.docs[0]
    assert {"sessionId", "deviceId", "completedAt", "metrics"} <= set(doc)
    assert "illustrativeScorePercent" in doc["metrics"]


def test_mongo_list_results_orders_filters_and_limits():
    store = fake_mongo_store()
    for n, device in enumerate(["a", "b", "a", "a", "b"], start=1):
        run(store.save_result(record(n, 10 * n, device=device)))
    assert [r.session_id for r in run(store.list_results("a"))] == ["s1", "s3", "s4"]
    assert [r.session_id for r in run(store.list_results("a", limit=2))] == ["s3", "s4"]
    assert [r.session_id for r in run(store.list_results())] == ["s1", "s2", "s3", "s4", "s5"]
    assert run(store.list_results(limit=0)) == []


def test_mongo_list_sessions_newest_first():
    store = fake_mongo_store()
    for n in range(3):
        session = Session(
            exercise_id="x", calibration_id="c", tool_id="scalpel", device_id="d", session_id=f"s{n}",
            status=SessionStatus.active, created_at=T0 + timedelta(minutes=n),
        )
        run(store.save_session(session))
    assert [s.session_id for s in run(store.list_sessions(2))] == ["s2", "s1"]
    assert run(store.list_sessions(0)) == []
