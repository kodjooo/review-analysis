from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.core.config import Settings
from app.core.models import SheetsReport


@dataclass(slots=True)
class WorksheetPayload:
    title: str
    rows: list[list[str]]


class GoogleSheetsService:
    SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

    def __init__(self, settings: Settings, logger: Logger) -> None:
        self.settings = settings
        self.logger = logger

    def export(self, report: SheetsReport) -> None:
        if not self.settings.google_service_account_file or not self.settings.google_spreadsheet_id:
            self.logger.warning("Google Sheets не настроен, выгрузка отчета пропущена.")
            return

        credentials = Credentials.from_service_account_file(
            str(self.settings.google_service_account_file),
            scopes=self.SCOPES,
        )
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        spreadsheet = service.spreadsheets()

        existing_titles = self._fetch_sheet_titles(spreadsheet)
        for sheet in report.sheets:
            if sheet.title not in existing_titles:
                spreadsheet.batchUpdate(
                    spreadsheetId=self.settings.google_spreadsheet_id,
                    body={"requests": [{"addSheet": {"properties": {"title": sheet.title}}}]},
                ).execute()

            spreadsheet.values().clear(
                spreadsheetId=self.settings.google_spreadsheet_id,
                range=sheet.title,
            ).execute()
            spreadsheet.values().update(
                spreadsheetId=self.settings.google_spreadsheet_id,
                range=f"{sheet.title}!A1",
                valueInputOption="RAW",
                body={"values": sheet.rows},
            ).execute()

        self.logger.info(
            "Отчет выгружен в Google Sheets: %s",
            self.settings.google_spreadsheet_id,
        )

    def _fetch_sheet_titles(self, spreadsheet) -> set[str]:
        response = spreadsheet.get(spreadsheetId=self.settings.google_spreadsheet_id).execute()
        sheets = response.get("sheets", [])
        return {
            item.get("properties", {}).get("title", "")
            for item in sheets
            if item.get("properties", {}).get("title")
        }
