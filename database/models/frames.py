"""Placeholder and frame payload models."""

from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


class Placeholder(BaseModel):
    x: int = Field(..., description="Top-left x in source image pixels (integer)")
    y: int = Field(..., description="Top-left y in source image pixels (integer)")
    height: int = Field(..., gt=0, description="Box height in pixels (integer)")
    width: int = Field(..., gt=0, description="Box width in pixels (integer)")
    rotation: float = Field(
        default=0.0, ge=-45.0, le=45.0, description="Degrees clockwise (-45.0 to 45.0)"
    )
    elevation: int = Field(default=0, description="Stacking order hint; higher draws later")
    index: int | None = Field(default=None, description="Zero-based stable slot index")

    @model_validator(mode="before")
    @classmethod
    def normalize_placeholder(cls, data: Any) -> Any:
        if isinstance(data, dict):
            rot = float(data.get("rotation", 0.0) or 0.0)
            w = float(data.get("width", 0.0) or 0.0)
            h = float(data.get("height", 0.0) or 0.0)
            while rot > 45.0:
                rot -= 90.0
                w, h = h, w
            while rot < -45.0:
                rot += 90.0
                w, h = h, w
            data["rotation"] = round(max(-45.0, min(45.0, rot)), 2)
            data["width"] = int(round(w))
            data["height"] = int(round(h))
            if "x" in data:
                data["x"] = int(round(float(data["x"])))
            if "y" in data:
                data["y"] = int(round(float(data["y"])))
            if "elevation" in data:
                data["elevation"] = int(round(float(data["elevation"] or 0)))
        return data

    @field_validator("x", "y", "height", "width", mode="before")
    @classmethod
    def coerce_integer(cls, v: Any) -> int:
        return int(round(float(v)))

    @field_validator("elevation", mode="before")
    @classmethod
    def coerce_elevation(cls, v: Any) -> int:
        return int(round(float(v or 0)))


class FramesBlockPayload(BaseModel):
    image_url: str = Field(..., description="URL to the frame background image")
    coordinates: list[Placeholder] = Field(
        default_factory=list, description="Detected or configured placeholder coordinates"
    )
    width: int | None = Field(default=None, description="Source image width in pixels")
    height: int | None = Field(default=None, description="Source image height in pixels")
    placeholders: list[Placeholder] = Field(
        default_factory=list, description="Detected or configured empty placeholder slots"
    )

    @model_validator(mode="before")
    @classmethod
    def sync_coords_and_placeholders(cls, data: Any) -> Any:
        if isinstance(data, dict):
            coords = data.get("coordinates")
            places = data.get("placeholders")
            if coords and not places:
                data["placeholders"] = coords
            elif places and not coords:
                data["coordinates"] = places
            if not data.get("image_url") and data.get("imageUrl"):
                data["image_url"] = data["imageUrl"]
        return data

    @model_validator(mode="after")
    def ensure_synced(self) -> "FramesBlockPayload":
        if self.coordinates and not self.placeholders:
            self.placeholders = self.coordinates
        elif self.placeholders and not self.coordinates:
            self.coordinates = self.placeholders
        return self
