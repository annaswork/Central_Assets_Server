"""CentralRepository and InstanceRepository base classes with hard physical boundary guards."""

import logging
from collections.abc import Mapping
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from database.collections import (
    CENTRAL_COLLECTIONS,
    INSTANCE_CONTENT_COLLECTIONS,
    get_collection,
)
from utils.datetimes import utc_now
from utils.ids import to_object_id

logger = logging.getLogger(__name__)


class BaseRepository:
    """Base repository handling raw Mongo queries with soft delete filtering."""

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str) -> None:
        self.db = db
        self.collection_name = collection_name
        self.collection: AsyncIOMotorCollection = get_collection(db, collection_name)

    def _apply_soft_delete_filter(
        self, query: dict[str, Any], include_deleted: bool = False
    ) -> dict[str, Any]:
        """Apply default deleted_at: None filter unless explicitly requested."""
        if include_deleted:
            return query
        q = dict(query)
        if "deleted_at" not in q:
            q["deleted_at"] = None
        return q

    async def find_one(
        self,
        query: dict[str, Any],
        include_deleted: bool = False,
        projection: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        filtered = self._apply_soft_delete_filter(query, include_deleted)
        return await self.collection.find_one(filtered, projection)

    async def find_by_id(
        self,
        doc_id: str | ObjectId,
        include_deleted: bool = False,
        projection: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        oid = to_object_id(doc_id)
        return await self.find_one(
            {"_id": oid}, include_deleted=include_deleted, projection=projection
        )

    async def find_many(
        self,
        query: dict[str, Any],
        skip: int = 0,
        limit: int = 50,
        sort: list[tuple[str, int]] | None = None,
        include_deleted: bool = False,
        projection: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        filtered = self._apply_soft_delete_filter(query, include_deleted)
        cursor = self.collection.find(filtered, projection).skip(skip).limit(limit)
        if sort:
            cursor = cursor.sort(sort)
        return await cursor.to_list(length=limit)

    async def count(self, query: dict[str, Any], include_deleted: bool = False) -> int:
        filtered = self._apply_soft_delete_filter(query, include_deleted)
        return await self.collection.count_documents(filtered)

    async def insert_one(self, doc: dict[str, Any]) -> ObjectId:
        now = utc_now()
        if "created_at" not in doc:
            doc["created_at"] = now
        if "updated_at" not in doc:
            doc["updated_at"] = now
        res = await self.collection.insert_one(doc)
        return res.inserted_id

    async def insert_many(self, docs: list[dict[str, Any]]) -> list[ObjectId]:
        if not docs:
            return []
        now = utc_now()
        for doc in docs:
            if "created_at" not in doc:
                doc["created_at"] = now
            if "updated_at" not in doc:
                doc["updated_at"] = now
        res = await self.collection.insert_many(docs, ordered=False)
        return list(res.inserted_ids.values())

    async def update_one(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        include_deleted: bool = False,
    ) -> int:
        filtered = self._apply_soft_delete_filter(query, include_deleted)
        if "$set" not in update:
            update["$set"] = {}
        update["$set"]["updated_at"] = utc_now()
        res = await self.collection.update_one(filtered, update)
        return res.modified_count

    async def update_many(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        include_deleted: bool = False,
    ) -> int:
        filtered = self._apply_soft_delete_filter(query, include_deleted)
        if "$set" not in update:
            update["$set"] = {}
        update["$set"]["updated_at"] = utc_now()
        res = await self.collection.update_many(filtered, update)
        return res.modified_count

    async def soft_delete(self, query: dict[str, Any]) -> int:
        now = utc_now()
        update = {
            "$set": {
                "deleted_at": now,
                "updated_at": now,
            }
        }
        res = await self.collection.update_many(self._apply_soft_delete_filter(query), update)
        return res.modified_count

    async def hard_delete(self, query: dict[str, Any]) -> int:
        res = await self.collection.delete_many(query)
        return res.deleted_count

    async def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cursor = self.collection.aggregate(pipeline)
        return await cursor.to_list(length=None)


class CentralRepository(BaseRepository):
    """Repository restricted to central library collections (categories, subcategories, assets)."""

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str) -> None:
        if collection_name not in CENTRAL_COLLECTIONS:
            raise ValueError(
                f"CentralRepository can only bind to central collections {CENTRAL_COLLECTIONS}, "
                f"got '{collection_name}'"
            )
        super().__init__(db, collection_name)


class InstanceRepository(BaseRepository):
    """Repository strictly restricted to instance_* collections.

    PHYSICAL ISOLATION GUARD:
    Raises ValueError immediately at instantiation if handed any central collection.
    Instance code cannot write to central collections.
    """

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str) -> None:
        if collection_name in CENTRAL_COLLECTIONS:
            raise ValueError(
                f"SECURITY VIOLATION: InstanceRepository cannot bind to central collection "
                f"'{collection_name}'. Instance operations may never touch central data."
            )
        if collection_name not in INSTANCE_CONTENT_COLLECTIONS:
            raise ValueError(
                f"InstanceRepository must bind to an instance content collection "
                f"{INSTANCE_CONTENT_COLLECTIONS}, got '{collection_name}'"
            )
        super().__init__(db, collection_name)
