import argparse
from pathlib import Path

from app.bootstrap import build_application


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review-analysis",
        description="Мониторинг отзывов Яндекс и 2ГИС.",
    )
    parser.add_argument(
        "command",
        choices=["run", "schedule", "test-email", "init-db"],
        nargs="?",
        default="run",
        help="Команда запуска приложения.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Путь к файлу .env.",
    )
    parser.add_argument(
        "--config",
        default="config/points.json",
        help="Путь к файлу с точками мониторинга.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    app = build_application(
        env_path=Path(args.env_file),
        config_path=Path(args.config),
    )
    return app.execute(args.command)
