from __future__ import annotations

import time
from dataclasses import dataclass
from logging import Logger

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.core.config import Settings
from app.core.models import SheetTab, SheetsReport


@dataclass(slots=True)
class WorksheetPayload:
    title: str
    rows: list[list[str]]


class GoogleSheetsService:
    SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
    SUMMARY_SHEET = "summary"
    LOW_RATED_SHEET = "low_rated_new_reviews"
    SKIPPED_SHEET = "skipped_points_last_run"
    RUN_INFO_SHEET = "run_info"

    def __init__(self, settings: Settings, logger: Logger) -> None:
        self.settings = settings
        self.logger = logger

    def export(self, report: SheetsReport, merge_with_existing: bool = False) -> None:
        spreadsheet = self._get_spreadsheet()
        if spreadsheet is None:
            return

        existing_titles = self._fetch_sheet_titles(spreadsheet)
        for sheet in report.sheets:
            if sheet.title not in existing_titles:
                self._execute(
                    spreadsheet.batchUpdate(
                        spreadsheetId=self.settings.google_spreadsheet_id,
                        body={"requests": [{"addSheet": {"properties": {"title": sheet.title}}}]},
                    ),
                    action=f"create-sheet:{sheet.title}",
                )
                existing_titles.add(sheet.title)

            rows = sheet.rows
            should_merge = sheet.title in {self.SUMMARY_SHEET, self.LOW_RATED_SHEET}
            should_replace = sheet.title in {self.RUN_INFO_SHEET, self.SKIPPED_SHEET}
            if should_merge:
                if sheet.title == self.SUMMARY_SHEET:
                    rows = self._merge_summary_rows(spreadsheet, sheet)
                elif sheet.title == self.LOW_RATED_SHEET:
                    rows = self._merge_low_rated_rows(spreadsheet, sheet)
            elif merge_with_existing and sheet.title == self.RUN_INFO_SHEET:
                continue

            if should_replace:
                self._execute(
                    spreadsheet.values().clear(
                        spreadsheetId=self.settings.google_spreadsheet_id,
                        range=sheet.title,
                    ),
                    action=f"clear-sheet:{sheet.title}",
                )
            self._execute(
                spreadsheet.values().update(
                    spreadsheetId=self.settings.google_spreadsheet_id,
                    range=f"{sheet.title}!A1",
                    valueInputOption="RAW",
                    body={"values": rows},
                ),
                action=f"write-sheet:{sheet.title}",
            )

        self.logger.info(
            "Отчет выгружен в Google Sheets: %s",
            self.settings.google_spreadsheet_id,
        )

    def clear_worksheet(self, title: str) -> None:
        spreadsheet = self._get_spreadsheet()
        if spreadsheet is None:
            return

        if title not in self._fetch_sheet_titles(spreadsheet):
            return

        self._execute(
            spreadsheet.values().clear(
                spreadsheetId=self.settings.google_spreadsheet_id,
                range=title,
            ),
            action=f"clear-sheet:{title}",
        )

    def load_skipped_point_ids(self, title: str = SKIPPED_SHEET) -> list[str]:
        spreadsheet = self._get_spreadsheet()
        if spreadsheet is None:
            return []

        if title not in self._fetch_sheet_titles(spreadsheet):
            return []

        values = self._execute(
            spreadsheet.values().get(
                spreadsheetId=self.settings.google_spreadsheet_id,
                range=f"{title}!A2:A",
            ),
            action=f"load-skipped:{title}",
        ).get("values", [])
        return [row[0] for row in values if row and row[0].strip()]

    def _get_spreadsheet(self):
        if not self.settings.google_service_account_file or not self.settings.google_spreadsheet_id:
            self.logger.warning("Google Sheets не настроен, выгрузка отчета пропущена.")
            return None

        credentials = Credentials.from_service_account_file(
            str(self.settings.google_service_account_file),
            scopes=self.SCOPES,
        )
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return service.spreadsheets()

    def _fetch_sheet_titles(self, spreadsheet) -> set[str]:
        response = self._execute(
            spreadsheet.get(spreadsheetId=self.settings.google_spreadsheet_id),
            action="fetch-sheet-titles",
        )
        sheets = response.get("sheets", [])
        return {
            item.get("properties", {}).get("title", "")
            for item in sheets
            if item.get("properties", {}).get("title")
        }

    def _read_rows(self, spreadsheet, title: str) -> list[list[str]]:
        values = self._execute(
            spreadsheet.values().get(
                spreadsheetId=self.settings.google_spreadsheet_id,
                range=title,
            ),
            action=f"read-sheet:{title}",
        ).get("values", [])
        return values if values else []

    def _merge_summary_rows(self, spreadsheet, sheet: SheetTab) -> list[list[str]]:
        existing_rows = self._read_rows(spreadsheet, sheet.title)
        if not existing_rows:
            return sheet.rows

        header = sheet.rows[0]
        merged: dict[tuple[str, str, str], list[str]] = {}
        for row in existing_rows[1:]:
            key = self._summary_row_key(row)
            if key is not None:
                merged[key] = row
        for row in sheet.rows[1:]:
            key = self._summary_row_key(row)
            if key is not None:
                merged[key] = row
        return [header, *merged.values()]

    def _merge_low_rated_rows(self, spreadsheet, sheet: SheetTab) -> list[list[str]]:
        existing_rows = self._read_rows(spreadsheet, sheet.title)
        if not existing_rows:
            return sheet.rows

        header = sheet.rows[0]
        merged: dict[tuple[str, ...], list[str]] = {}
        for row in existing_rows[1:]:
            merged[tuple(row)] = row
        for row in sheet.rows[1:]:
            merged[tuple(row)] = row
        return [header, *merged.values()]

    @staticmethod
    def _summary_row_key(row: list[str]) -> tuple[str, str, str] | None:
        if len(row) < 3:
            return None
        return row[0], row[1], row[2]

    def _execute(self, request, action: str):
        last_error = None
        for attempt in range(1, self.settings.sheets_api_max_attempts + 1):
            try:
                return request.execute()
            except Exception as error:
                last_error = error
                if attempt >= self.settings.sheets_api_max_attempts:
                    self.logger.error(
                        "Google Sheets запрос %s не выполнился после %s попыток: %s",
                        action,
                        attempt,
                        error,
                    )
                    raise
                self.logger.warning(
                    "Google Sheets запрос %s завершился ошибкой на попытке %s/%s: %s. Повтор через %s сек.",
                    action,
                    attempt,
                    self.settings.sheets_api_max_attempts,
                    error,
                    self.settings.sheets_api_retry_delay_seconds,
                )
                time.sleep(self.settings.sheets_api_retry_delay_seconds)
        raise last_error
