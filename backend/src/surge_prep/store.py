from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from .models import Calibration, Session, SimulationSnapshot, ToolSample, mongo_document


class Store(ABC):
    name: str

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    @abstractmethod
    async def save_calibration(self, calibration: Calibration) -> None: ...

    @abstractmethod
    async def get_calibration(self, calibration_id: str) -> Calibration | None: ...

    @abstractmethod
    async def save_session(self, session: Session) -> None: ...

    @abstractmethod
    async def get_session(self, session_id: str) -> Session | None: ...

    @abstractmethod
    async def save_sample(self, sample: ToolSample) -> None: ...

    @abstractmethod
    async def save_snapshot(self, snapshot: SimulationSnapshot) -> None: ...

    @abstractmethod
    async def list_samples(self, session_id: str) -> list[ToolSample]: ...

    @abstractmethod
    async def list_snapshots(self, session_id: str) -> list[SimulationSnapshot]: ...

    @abstractmethod
    async def list_sessions(self) -> list[Session]: ...


class MemoryStore(Store):
    name = "memory"

    def __init__(self) -> None:
        self.calibrations: dict[str, Calibration] = {}
        self.sessions: dict[str, Session] = {}
        self.samples: dict[str, list[ToolSample]] = defaultdict(list)
        self.snapshots: dict[str, list[SimulationSnapshot]] = defaultdict(list)

    async def save_calibration(self, calibration: Calibration) -> None:
        self.calibrations[calibration.calibration_id] = calibration

    async def get_calibration(self, calibration_id: str) -> Calibration | None:
        return self.calibrations.get(calibration_id)

    async def save_session(self, session: Session) -> None:
        self.sessions[session.session_id] = session

    async def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def save_sample(self, sample: ToolSample) -> None:
        self.samples[sample.session_id].append(sample)

    async def save_snapshot(self, snapshot: SimulationSnapshot) -> None:
        self.snapshots[snapshot.session_id].append(snapshot)

    async def list_samples(self, session_id: str) -> list[ToolSample]:
        return list(self.samples[session_id])

    async def list_snapshots(self, session_id: str) -> list[SimulationSnapshot]:
        return list(self.snapshots[session_id])

    async def list_sessions(self) -> list[Session]:
        return list(self.sessions.values())


class MongoStore(Store):
    name = "mongodb"

    def __init__(self, uri: str, database: str) -> None:
        from pymongo import AsyncMongoClient

        self.client = AsyncMongoClient(uri)
        self.db = self.client[database]

    async def start(self) -> None:
        await self.client.admin.command("ping")
        await self.db.samples.create_index([("sessionId", 1), ("sequence", 1)], unique=True)
        await self.db.snapshots.create_index([("sessionId", 1), ("tick", 1)], unique=True)

    async def close(self) -> None:
        await self.client.close()

    async def save_calibration(self, calibration: Calibration) -> None:
        document = mongo_document(calibration)
        await self.db.calibrations.replace_one(
            {"calibrationId": calibration.calibration_id}, document, upsert=True
        )

    async def get_calibration(self, calibration_id: str) -> Calibration | None:
        item = await self.db.calibrations.find_one({"calibrationId": calibration_id}, {"_id": 0})
        return Calibration.model_validate(item) if item else None

    async def save_session(self, session: Session) -> None:
        await self.db.sessions.replace_one(
            {"sessionId": session.session_id}, mongo_document(session), upsert=True
        )

    async def get_session(self, session_id: str) -> Session | None:
        item = await self.db.sessions.find_one({"sessionId": session_id}, {"_id": 0})
        return Session.model_validate(item) if item else None

    async def save_sample(self, sample: ToolSample) -> None:
        await self.db.samples.insert_one(mongo_document(sample))

    async def save_snapshot(self, snapshot: SimulationSnapshot) -> None:
        await self.db.snapshots.insert_one(mongo_document(snapshot))

    async def list_samples(self, session_id: str) -> list[ToolSample]:
        cursor = self.db.samples.find({"sessionId": session_id}, {"_id": 0}).sort("sequence", 1)
        return [ToolSample.model_validate(item) async for item in cursor]

    async def list_snapshots(self, session_id: str) -> list[SimulationSnapshot]:
        cursor = self.db.snapshots.find({"sessionId": session_id}, {"_id": 0}).sort("tick", 1)
        return [SimulationSnapshot.model_validate(item) async for item in cursor]

    async def list_sessions(self) -> list[Session]:
        cursor = self.db.sessions.find({}, {"_id": 0}).sort("createdAt", -1)
        return [Session.model_validate(item) async for item in cursor]

