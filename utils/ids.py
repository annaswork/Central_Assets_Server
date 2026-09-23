"""ObjectId <-> str helpers and Pydantic v2 PyObjectId type."""

from typing import Annotated, Any

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class _PyObjectIdAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def validate(value: Any) -> ObjectId:
            if isinstance(value, ObjectId):
                return value
            if isinstance(value, str) and ObjectId.is_valid(value):
                return ObjectId(value)
            raise ValueError(f"Invalid ObjectId: {value}")

        return core_schema.no_info_after_validator_function(
            validate,
            core_schema.union_schema(
                [
                    core_schema.is_instance_schema(ObjectId),
                    core_schema.str_schema(),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x), return_schema=core_schema.str_schema(), when_used="json"
            ),
        )


PyObjectId = Annotated[ObjectId, _PyObjectIdAnnotation]


def is_valid_object_id(val: Any) -> bool:
    """Check if the provided value is a valid 24-character hex ObjectId."""
    if isinstance(val, ObjectId):
        return True
    if isinstance(val, str):
        return ObjectId.is_valid(val)
    return False


def to_object_id(val: str | ObjectId) -> ObjectId:
    """Convert string to ObjectId or return as-is. Raises ValueError if invalid."""
    if isinstance(val, ObjectId):
        return val
    try:
        return ObjectId(val)
    except (InvalidId, TypeError, ValueError) as err:
        raise ValueError(f"'{val}' is not a valid ObjectId") from err
