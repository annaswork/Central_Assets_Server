"""Typed block models for asset more_fields payload.

Uses a discriminated union on 'type' to strictly validate blocks and reject unsupported types.
"""

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from config.constants import MAX_JSON_BLOCK_BYTES
from database.models.frames import Placeholder
from utils.validators import validate_json_depth


class AudioItem(BaseModel):
    url: str
    duration_ms: int | None = None
    duration: float | int | None = None
    mime: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None

    @model_validator(mode="after")
    def sync_audio_metadata(self) -> "AudioItem":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        if self.duration_ms is not None and self.duration is None:
            self.duration = round(self.duration_ms / 1000.0, 3)
        elif self.duration is not None and self.duration_ms is None:
            self.duration_ms = int(self.duration * 1000)
        return self


class AudioBlock(BaseModel):
    type: Literal["audio"] = "audio"
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    items: list[AudioItem] = Field(default_factory=list)
    duration_ms: int | None = None
    duration: float | int | None = None
    mime: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None
    filename: str | None = None

    @model_validator(mode="after")
    def sync_urls_and_items(self) -> "AudioBlock":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        if self.duration_ms is not None and self.duration is None:
            self.duration = round(self.duration_ms / 1000.0, 3)
        elif self.duration is not None and self.duration_ms is None:
            self.duration_ms = int(self.duration * 1000)

        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        if self.urls and not self.url:
            self.url = self.urls[0]
        elif self.url and not self.urls:
            self.urls = [self.url]
        if not self.items and self.urls:
            self.items = [
                AudioItem(
                    url=u,
                    duration_ms=self.duration_ms if idx == 0 else None,
                    duration=self.duration if idx == 0 else None,
                    mime=self.mime if idx == 0 else None,
                    size_bytes=self.size_bytes if idx == 0 else None,
                    filesize=self.filesize if idx == 0 else None,
                    filename=self.filename if idx == 0 else None,
                )
                for idx, u in enumerate(self.urls)
                if u
            ]
        elif self.items:
            first = self.items[0]
            if self.duration_ms is None:
                self.duration_ms = first.duration_ms
            if self.duration is None:
                self.duration = first.duration
            if self.size_bytes is None:
                self.size_bytes = first.size_bytes
            if self.filesize is None:
                self.filesize = first.filesize
            if self.filename is None:
                self.filename = first.filename
            elif first.filename is None:
                first.filename = self.filename
        return self


class AudioListBlock(BaseModel):
    type: Literal["audio_list"] = "audio_list"
    items: list[AudioItem] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_urls(self) -> "AudioListBlock":
        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        return self


class ImageItem(BaseModel):
    url: str
    width: int | None = None
    height: int | None = None
    dimensions: str | None = None
    mime: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None

    @model_validator(mode="after")
    def sync_image_metadata(self) -> "ImageItem":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        if self.dimensions and (self.width is None or self.height is None):
            parts = str(self.dimensions).split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                self.width = int(parts[0])
                self.height = int(parts[1])
        elif self.width is not None and self.height is not None and not self.dimensions:
            self.dimensions = f"{self.width}x{self.height}"
        return self


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    items: list[ImageItem] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    dimensions: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None
    filename: str | None = None

    @model_validator(mode="after")
    def sync_urls_and_items(self) -> "ImageBlock":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        if self.dimensions and (self.width is None or self.height is None):
            parts = str(self.dimensions).split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                self.width = int(parts[0])
                self.height = int(parts[1])
        elif self.width is not None and self.height is not None and not self.dimensions:
            self.dimensions = f"{self.width}x{self.height}"

        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        if self.urls and not self.url:
            self.url = self.urls[0]
        elif self.url and not self.urls:
            self.urls = [self.url]
        if not self.items and self.urls:
            self.items = [
                ImageItem(
                    url=u,
                    width=self.width if idx == 0 else None,
                    height=self.height if idx == 0 else None,
                    dimensions=self.dimensions if idx == 0 else None,
                    mime=self.mime if idx == 0 else None,
                    size_bytes=self.size_bytes if idx == 0 else None,
                    filesize=self.filesize if idx == 0 else None,
                    filename=self.filename if idx == 0 else None,
                )
                for idx, u in enumerate(self.urls)
                if u
            ]
        elif self.items:
            first = self.items[0]
            if self.width is None:
                self.width = first.width
            if self.height is None:
                self.height = first.height
            if self.dimensions is None:
                self.dimensions = first.dimensions
            if self.size_bytes is None:
                self.size_bytes = first.size_bytes
            if self.filesize is None:
                self.filesize = first.filesize
            if self.filename is None:
                self.filename = first.filename
            elif first.filename is None:
                first.filename = self.filename
        return self


class ImageListBlock(BaseModel):
    type: Literal["image_list"] = "image_list"
    items: list[ImageItem] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_urls(self) -> "ImageListBlock":
        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        return self


class VideoItem(BaseModel):
    url: str
    duration_ms: int | None = None
    duration: float | int | None = None
    width: int | None = None
    height: int | None = None
    dimensions: str | None = None
    mime: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None

    @model_validator(mode="after")
    def sync_video_metadata(self) -> "VideoItem":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        if self.dimensions and (self.width is None or self.height is None):
            parts = str(self.dimensions).split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                self.width = int(parts[0])
                self.height = int(parts[1])
        elif self.width is not None and self.height is not None and not self.dimensions:
            self.dimensions = f"{self.width}x{self.height}"
        if self.duration_ms is not None and self.duration is None:
            self.duration = round(self.duration_ms / 1000.0, 3)
        elif self.duration is not None and self.duration_ms is None:
            self.duration_ms = int(self.duration * 1000)
        return self


class VideoBlock(BaseModel):
    type: Literal["video"] = "video"
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    items: list[VideoItem] = Field(default_factory=list)
    duration_ms: int | None = None
    duration: float | int | None = None
    width: int | None = None
    height: int | None = None
    dimensions: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None
    filename: str | None = None

    @model_validator(mode="after")
    def sync_urls_and_items(self) -> "VideoBlock":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        if self.dimensions and (self.width is None or self.height is None):
            parts = str(self.dimensions).split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                self.width = int(parts[0])
                self.height = int(parts[1])
        elif self.width is not None and self.height is not None and not self.dimensions:
            self.dimensions = f"{self.width}x{self.height}"
        if self.duration_ms is not None and self.duration is None:
            self.duration = round(self.duration_ms / 1000.0, 3)
        elif self.duration is not None and self.duration_ms is None:
            self.duration_ms = int(self.duration * 1000)

        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        if self.urls and not self.url:
            self.url = self.urls[0]
        elif self.url and not self.urls:
            self.urls = [self.url]
        if not self.items and self.urls:
            self.items = [
                VideoItem(
                    url=u,
                    duration_ms=self.duration_ms if idx == 0 else None,
                    duration=self.duration if idx == 0 else None,
                    width=self.width if idx == 0 else None,
                    height=self.height if idx == 0 else None,
                    dimensions=self.dimensions if idx == 0 else None,
                    mime=self.mime if idx == 0 else None,
                    size_bytes=self.size_bytes if idx == 0 else None,
                    filesize=self.filesize if idx == 0 else None,
                    filename=self.filename if idx == 0 else None,
                )
                for idx, u in enumerate(self.urls)
                if u
            ]
        elif self.items:
            first = self.items[0]
            if self.duration_ms is None:
                self.duration_ms = first.duration_ms
            if self.duration is None:
                self.duration = first.duration
            if self.width is None:
                self.width = first.width
            if self.height is None:
                self.height = first.height
            if self.dimensions is None:
                self.dimensions = first.dimensions
            if self.size_bytes is None:
                self.size_bytes = first.size_bytes
            if self.filesize is None:
                self.filesize = first.filesize
            if self.filename is None:
                self.filename = first.filename
            elif first.filename is None:
                first.filename = self.filename
        return self


class VideoListBlock(BaseModel):
    type: Literal["video_list"] = "video_list"
    items: list[VideoItem] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_urls(self) -> "VideoListBlock":
        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        return self


class JsonBlock(BaseModel):
    type: Literal["json", "json_data"] = "json"
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def validate_data_depth_and_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not validate_json_depth(v):
            raise ValueError("JSON data exceeds maximum allowable nesting depth of 8")
        serialized = json.dumps(v)
        if len(serialized.encode("utf-8")) > MAX_JSON_BLOCK_BYTES:
            raise ValueError(
                f"JSON data exceeds maximum allowable size of {MAX_JSON_BLOCK_BYTES} bytes"
            )
        return v


class FramesBlock(BaseModel):
    type: Literal["frames"] = "frames"
    image_url: str = ""
    coordinates: list[Placeholder] = Field(default_factory=list)
    width: int | float | None = None
    height: int | float | None = None
    placeholders: list[Placeholder] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_frames(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "type" not in data:
                data["type"] = "frames"
            if not data.get("image_url") and data.get("imageUrl"):
                data["image_url"] = data["imageUrl"]
            coords = data.get("coordinates")
            places = data.get("placeholders")
            if coords and not places:
                data["placeholders"] = coords
            elif places and not coords:
                data["coordinates"] = places
        return data

    @model_validator(mode="after")
    def sync_coords(self) -> "FramesBlock":
        if self.coordinates and not self.placeholders:
            self.placeholders = self.coordinates
        elif self.placeholders and not self.coordinates:
            self.coordinates = self.placeholders
        return self


class StringListBlock(BaseModel):
    type: Literal["string_list", "strings"] = "string_list"
    items: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_items(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data["type"] = "string_list"
            if "items" not in data:
                if "values" in data:
                    data["items"] = data["values"]
                elif "strings" in data:
                    data["items"] = data["strings"]
            if "items" in data and isinstance(data["items"], list):
                data["items"] = [
                    str(item).strip()
                    for item in data["items"]
                    if item is not None and str(item).strip()
                ]
        elif isinstance(data, list):
            data = {
                "type": "string_list",
                "items": [
                    str(item).strip() for item in data if item is not None and str(item).strip()
                ],
            }
        return data


class HtmlItem(BaseModel):
    url: str
    mime: str | None = "text/html"
    filename: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None
    title: str | None = None

    @model_validator(mode="after")
    def sync_html_metadata(self) -> "HtmlItem":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        return self


class HtmlBlock(BaseModel):
    type: Literal["html"] = "html"
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    items: list[HtmlItem] = Field(default_factory=list)
    mime: str | None = "text/html"
    size_bytes: int | None = None
    filesize: int | None = None
    filename: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def sync_urls_and_items(self) -> "HtmlBlock":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes

        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        if self.urls and not self.url:
            self.url = self.urls[0]
        elif self.url and not self.urls:
            self.urls = [self.url]
        if not self.items and self.urls:
            self.items = [
                HtmlItem(
                    url=u,
                    mime=self.mime if idx == 0 else "text/html",
                    size_bytes=self.size_bytes if idx == 0 else None,
                    filesize=self.filesize if idx == 0 else None,
                    filename=self.filename if idx == 0 else None,
                    title=self.title if idx == 0 else None,
                )
                for idx, u in enumerate(self.urls)
                if u
            ]
        elif self.items:
            first = self.items[0]
            if self.size_bytes is None:
                self.size_bytes = first.size_bytes
            if self.filesize is None:
                self.filesize = first.filesize
            if self.filename is None:
                self.filename = first.filename
            elif first.filename is None:
                first.filename = self.filename
            if self.title is None:
                self.title = first.title
            elif first.title is None:
                first.title = self.title
        return self


class HtmlListBlock(BaseModel):
    type: Literal["html_list"] = "html_list"
    items: list[HtmlItem] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_urls(self) -> "HtmlListBlock":
        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        return self


class FileItem(BaseModel):
    url: str
    mime: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None
    title: str | None = None

    @model_validator(mode="after")
    def sync_file_metadata(self) -> "FileItem":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes
        return self


class FileBlock(BaseModel):
    type: Literal["file", "document"] = "file"
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    items: list[FileItem] = Field(default_factory=list)
    mime: str | None = None
    size_bytes: int | None = None
    filesize: int | None = None
    filename: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def sync_urls_and_items(self) -> "FileBlock":
        if self.filesize is not None and self.size_bytes is None:
            self.size_bytes = self.filesize
        elif self.size_bytes is not None and self.filesize is None:
            self.filesize = self.size_bytes

        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        if self.urls and not self.url:
            self.url = self.urls[0]
        elif self.url and not self.urls:
            self.urls = [self.url]
        if not self.items and self.urls:
            self.items = [
                FileItem(
                    url=u,
                    mime=self.mime if idx == 0 else None,
                    size_bytes=self.size_bytes if idx == 0 else None,
                    filesize=self.filesize if idx == 0 else None,
                    filename=self.filename if idx == 0 else None,
                    title=self.title if idx == 0 else None,
                )
                for idx, u in enumerate(self.urls)
                if u
            ]
        elif self.items:
            first = self.items[0]
            if self.size_bytes is None:
                self.size_bytes = first.size_bytes
            if self.filesize is None:
                self.filesize = first.filesize
            if self.filename is None:
                self.filename = first.filename
            elif first.filename is None:
                first.filename = self.filename
            if self.mime is None:
                self.mime = first.mime
            elif first.mime is None:
                first.mime = self.mime
            if self.title is None:
                self.title = first.title
            elif first.title is None:
                first.title = self.title
        return self


class FileListBlock(BaseModel):
    type: Literal["file_list", "document_list"] = "file_list"
    items: list[FileItem] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_urls(self) -> "FileListBlock":
        if self.items and not self.urls:
            self.urls = [item.url for item in self.items if item.url]
        return self


TypedBlock = Annotated[
    AudioBlock
    | AudioListBlock
    | ImageBlock
    | ImageListBlock
    | VideoBlock
    | VideoListBlock
    | JsonBlock
    | FramesBlock
    | StringListBlock
    | HtmlBlock
    | HtmlListBlock
    | FileBlock
    | FileListBlock,
    Field(discriminator="type"),
]
