from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PlatformName(StrEnum):
    YANDEX = "yandex"
    TWOGIS = "twogis"


class PlatformStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(slots=True)
class MonitoringPoint:
    id: str
    type: str
    address: str
    yandex_url: str
    twogis_url: str
    is_active: bool
    name: str | None = None


@dataclass(slots=True)
class Review:
    platform: PlatformName
    published_at: str
    stars: int
    text: str
    source_url: str
    author_name: str | None = None
    external_id: str | None = None
    signature: str | None = None


@dataclass(slots=True)
class PlatformSnapshot:
    point_id: str
    platform: PlatformName
    source_url: str
    collected_at: datetime
    review_count: int
    rating: float
    reviews: list[Review]
    status: PlatformStatus = PlatformStatus.SUCCESS
    error_message: str | None = None


@dataclass(slots=True)
class PlatformDelta:
    point_id: str
    platform: PlatformName
    previous_review_count: int | None
    current_review_count: int | None
    previous_rating: float | None
    current_rating: float | None
    new_reviews: list[Review] = field(default_factory=list)
    low_rated_new_reviews: list[Review] = field(default_factory=list)
    status: PlatformStatus = PlatformStatus.SUCCESS
    error_message: str | None = None


@dataclass(slots=True)
class PointReport:
    point: MonitoringPoint
    deltas: dict[PlatformName, PlatformDelta]


@dataclass(slots=True)
class MonitoringRunResult:
    run_started_at: datetime
    run_finished_at: datetime
    point_reports: list[PointReport]


@dataclass(slots=True)
class SheetTab:
    title: str
    rows: list[list[str]]


@dataclass(slots=True)
class SheetsReport:
    spreadsheet_title: str
    sheets: list[SheetTab]
