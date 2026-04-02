from __future__ import annotations

from types import SimpleNamespace

from app.core.models import SheetTab, SheetsReport
from app.services.sheets_service import GoogleSheetsService


class FakeRequest:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class FakeValuesApi:
    def __init__(self, sheets: dict[str, list[list[str]]]) -> None:
        self.sheets = sheets

    def clear(self, spreadsheetId: str, range: str):
        def callback():
            self.sheets[range] = []
            return {}

        return FakeRequest(callback)

    def update(self, spreadsheetId: str, range: str, valueInputOption: str, body: dict):
        title = range.split("!", 1)[0]

        def callback():
            self.sheets[title] = body["values"]
            return {}

        return FakeRequest(callback)

    def get(self, spreadsheetId: str, range: str):
        title = range.split("!", 1)[0]

        def callback():
            return {"values": self.sheets.get(title, [])}

        return FakeRequest(callback)


class FakeSpreadsheetApi:
    def __init__(self, sheets: dict[str, list[list[str]]]) -> None:
        self.sheets = sheets

    def values(self):
        return FakeValuesApi(self.sheets)

    def batchUpdate(self, spreadsheetId: str, body: dict):
        title = body["requests"][0]["addSheet"]["properties"]["title"]

        def callback():
            self.sheets.setdefault(title, [])
            return {}

        return FakeRequest(callback)

    def get(self, spreadsheetId: str):
        def callback():
            return {
                "sheets": [
                    {"properties": {"title": title}}
                    for title in self.sheets.keys()
                ]
            }

        return FakeRequest(callback)


def build_service(existing_sheets: dict[str, list[list[str]]]) -> GoogleSheetsService:
    settings = SimpleNamespace(
        google_service_account_file="unused.json",
        google_spreadsheet_id="sheet-id",
        sheets_api_retry_delay_seconds=0,
        sheets_api_max_attempts=3,
    )
    service = GoogleSheetsService(settings=settings, logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None))
    service._get_spreadsheet = lambda: FakeSpreadsheetApi(existing_sheets)
    return service


def test_export_merge_keeps_existing_summary_and_replaces_skipped_sheet() -> None:
    existing = {
        "run_info": [["Параметр", "Значение"], ["Начало запуска", "old"]],
        "summary": [
            ["Тип магазина", "Адрес", "Площадка"],
            ["Мильстрим", "Адрес 1", "yandex"],
        ],
        "low_rated_new_reviews": [
            ["Тип магазина", "Адрес", "Площадка", "Дата", "Звезды", "Текст", "Ссылка"],
            ["Мильстрим", "Адрес 1", "yandex", "2026-04-01", "2", "Старый отзыв", "https://example.com/1"],
        ],
        "skipped_points_last_run": [
            ["ID точки", "Тип магазина"],
            ["8", "Мильстрим"],
        ],
    }
    report = SheetsReport(
        spreadsheet_title="test",
        sheets=[
            SheetTab(title="run_info", rows=[["Параметр", "Значение"], ["Начало запуска", "new"]]),
            SheetTab(
                title="summary",
                rows=[
                    ["Тип магазина", "Адрес", "Площадка"],
                    ["Мильстрим", "Адрес 2", "2gis"],
                ],
            ),
            SheetTab(
                title="low_rated_new_reviews",
                rows=[
                    ["Тип магазина", "Адрес", "Площадка", "Дата", "Звезды", "Текст", "Ссылка"],
                    ["Мильстрим", "Адрес 2", "2gis", "2026-04-02", "3", "Новый отзыв", "https://example.com/2"],
                ],
            ),
            SheetTab(title="skipped_points_last_run", rows=[["ID точки", "Тип магазина"]]),
        ],
    )

    service = build_service(existing)

    service.export(report, merge_with_existing=True)

    assert existing["run_info"][1][1] == "old"
    assert existing["summary"][1:] == [
        ["Мильстрим", "Адрес 1", "yandex"],
        ["Мильстрим", "Адрес 2", "2gis"],
    ]
    assert existing["low_rated_new_reviews"][1:] == [
        ["Мильстрим", "Адрес 1", "yandex", "2026-04-01", "2", "Старый отзыв", "https://example.com/1"],
        ["Мильстрим", "Адрес 2", "2gis", "2026-04-02", "3", "Новый отзыв", "https://example.com/2"],
    ]
    assert existing["skipped_points_last_run"] == [["ID точки", "Тип магазина"]]


def test_export_default_run_merges_summary_instead_of_overwriting() -> None:
    existing = {
        "summary": [
            ["Тип магазина", "Адрес", "Площадка"],
            ["Мильстрим", "Адрес 1", "yandex"],
        ],
        "run_info": [["Параметр", "Значение"], ["Начало запуска", "old"]],
        "skipped_points_last_run": [["ID точки", "Тип магазина"], ["8", "Мильстрим"]],
    }
    report = SheetsReport(
        spreadsheet_title="test",
        sheets=[
            SheetTab(title="run_info", rows=[["Параметр", "Значение"], ["Начало запуска", "new"]]),
            SheetTab(
                title="summary",
                rows=[
                    ["Тип магазина", "Адрес", "Площадка"],
                    ["Мильстрим", "Адрес 2", "2gis"],
                ],
            ),
            SheetTab(title="skipped_points_last_run", rows=[["ID точки", "Тип магазина"]]),
        ],
    )

    service = build_service(existing)

    service.export(report, merge_with_existing=False)

    assert existing["summary"][1:] == [
        ["Мильстрим", "Адрес 1", "yandex"],
        ["Мильстрим", "Адрес 2", "2gis"],
    ]
    assert existing["run_info"][1][1] == "new"
    assert existing["skipped_points_last_run"] == [["ID точки", "Тип магазина"]]


def test_execute_retries_google_sheets_request_until_success() -> None:
    attempts = {"count": 0}

    def callback():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("boom")
        return {"ok": True}

    service = build_service({})

    result = service._execute(FakeRequest(callback), action="test")

    assert result == {"ok": True}
    assert attempts["count"] == 3
