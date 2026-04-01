from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.adapters.anti_bot import AntiBotDetectedError, PageExpectation, inspect_page_state
from app.core.config import Settings
from app.core.models import MonitoringPoint, PlatformName, PlatformSnapshot, Review
from app.core.utils import make_review_signature

logger = logging.getLogger("review-analysis")


@dataclass(slots=True)
class ReviewSortConfig:
    trigger_selectors: list[str] = field(
        default_factory=lambda: [
            "[data-testid*='sort']",
            "[class*='sort'] button",
            "[class*='ranking']",
            "[aria-haspopup='menu']",
        ]
    )
    trigger_texts: list[str] = field(
        default_factory=lambda: [
            "По умолчанию",
            "Сортировка",
            "Сначала новые",
            "Сначала старые",
        ]
    )
    option_selectors: dict[str, list[str]] = field(
        default_factory=lambda: {"newest": [], "oldest": []}
    )
    option_texts: dict[str, list[str]] = field(
        default_factory=lambda: {
            "newest": ["Сначала новые", "Новые", "Сначала свежие", "По дате", "Newest"],
            "oldest": ["Сначала старые", "Старые", "Сначала ранние", "Oldest"],
        }
    )
    selected_state_texts: dict[str, list[str]] = field(
        default_factory=lambda: {"newest": [], "oldest": []}
    )


class BaseReviewAdapter(ABC):
    def __init__(self, settings: Settings, platform: PlatformName) -> None:
        self.settings = settings
        self.platform = platform
        self.storage_state_path: Path | None = None

    @property
    @abstractmethod
    def platform_url_field(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def page_expectation(self) -> PageExpectation:
        raise NotImplementedError

    @property
    def review_sort_config(self) -> ReviewSortConfig:
        return ReviewSortConfig()

    def fetch(self, point: MonitoringPoint) -> PlatformSnapshot:
        source_url = getattr(point, self.platform_url_field)
        html = self._load_html(source_url)
        review_count, rating, raw_reviews = self.parse_html(html, source_url=source_url)
        reviews: list[Review] = []
        invalid_reviews_count = 0
        for item in raw_reviews:
            review = self._build_review(source_url, item)
            if review is None:
                invalid_reviews_count += 1
                continue
            reviews.append(review)
        if invalid_reviews_count:
            logger.info(
                "Для %s по точке %s отфильтровано некорректных отзывов: %s.",
                self.platform.value,
                point.id,
                invalid_reviews_count,
            )
        return PlatformSnapshot(
            point_id=point.id,
            platform=self.platform,
            source_url=source_url,
            collected_at=datetime.now(tz=self.settings.timezone),
            review_count=review_count,
            rating=self._normalize_rating(rating),
            reviews=reviews[: self.settings.review_fetch_limit],
        )

    def _load_html(self, source_url: str) -> str:
        if source_url.startswith("file://"):
            return Path(source_url.replace("file://", "", 1)).read_text(encoding="utf-8")

        last_error: Exception | None = None
        for _ in range(2):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.settings.playwright_headless,
                    slow_mo=self.settings.playwright_slow_mo_ms,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                try:
                    context = self._create_context(browser)
                    page = context.new_page()
                    self._prepare_page(page)
                    page.goto(
                        source_url,
                        wait_until="domcontentloaded",
                        timeout=self.settings.page_timeout_seconds * 1000,
                    )
                    self._wait_for_interactive_page(page)
                    self._simulate_human_behavior(page)

                    html = page.content()
                    title = page.title()
                    current_url = page.url
                    self._save_debug_html(html)
                    self._save_debug_screenshot(page)

                    page_state, target_hits, anti_bot_hits = inspect_page_state(
                        title=title,
                        url=current_url,
                        html=html,
                        expectation=self.page_expectation,
                    )
                    if page_state == "antibot":
                        raise AntiBotDetectedError(
                            "Обнаружена антибот-страница. "
                            f"target={target_hits}; antibot={anti_bot_hits}; url={current_url}"
                        )
                    if page_state == "unknown":
                        raise RuntimeError(
                            "Не удалось подтвердить целевую страницу по ожидаемым селекторам. "
                            f"target={target_hits}; antibot={anti_bot_hits}; url={current_url}"
                        )

                    self._persist_context_state(context)
                    context.close()
                    return html
                except PlaywrightTimeoutError:
                    last_error = RuntimeError(f"Истек таймаут открытия страницы: {source_url}")
                except Exception as error:  # noqa: BLE001
                    last_error = error
                finally:
                    browser.close()

        if last_error is None:
            raise RuntimeError(f"Не удалось открыть страницу: {source_url}")
        raise last_error

    def _wait_for_interactive_page(self, page: Page) -> None:
        if self.settings.playwright_wait_networkidle:
            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(self.settings.page_timeout_seconds * 1000, 15000),
                )
            except PlaywrightTimeoutError:
                logger.info(
                    "Networkidle не был достигнут вовремя для %s, продолжаем с текущим состоянием.",
                    self.platform.value,
                )

    def _create_context(self, browser) -> BrowserContext:
        state_dir = self._runtime_dir("browser-state")
        state_dir.mkdir(parents=True, exist_ok=True)
        self.storage_state_path = state_dir / f"{self.platform.value}.json"
        context_kwargs: dict[str, Any] = {
            "locale": "ru-RU",
            "timezone_id": "Europe/Moscow",
            "viewport": {"width": 1440, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if self.storage_state_path.exists():
            context_kwargs["storage_state"] = str(self.storage_state_path)
        context = browser.new_context(**context_kwargs)
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'language', { get: () => 'ru-RU' });
            Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru'] });
            window.chrome = { runtime: {} };
            """
        )
        return context

    @staticmethod
    def _prepare_page(page: Page) -> None:
        page.set_extra_http_headers(
            {
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
            }
        )

    @staticmethod
    def _simulate_human_behavior(page: Page) -> None:
        page.wait_for_timeout(2500)
        page.mouse.move(220, 280)
        page.wait_for_timeout(800)
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(1800)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(1200)

    def _prepare_reviews_sort(self, page: Page) -> None:
        logger.info(
            "UI-сортировка для %s пропущена: порядок отзывов задается на уровне данных.",
            self.platform.value,
        )

    def _open_sort_menu(self, page: Page, config: ReviewSortConfig) -> bool:
        for selector in config.trigger_selectors:
            locator = page.locator(selector).first
            if self._try_click_locator(locator, f"trigger selector {selector}"):
                return True
        for text in config.trigger_texts:
            locator = page.get_by_text(text, exact=False).first
            if self._try_click_locator(locator, f"trigger text {text}"):
                return True
        return False

    def _try_click_locator(self, locator: Locator, description: str) -> bool:
        try:
            if locator.count() == 0 or not locator.is_visible():
                logger.info("Пропускаем %s для %s: элемент не найден или не видим.", description, self.platform.value)
                return False
            locator.scroll_into_view_if_needed(timeout=1000)
            obstruction = self._describe_obstruction(locator)
            if obstruction is not None:
                logger.info(
                    "Перед кликом %s для %s: %s",
                    description,
                    self.platform.value,
                    obstruction,
                )
            locator.hover(timeout=1000)
            locator.click(timeout=2000)
            locator.page.wait_for_timeout(600)
            return True
        except Exception as error:
            logger.info(
                "Клик по %s для %s не удался: %s",
                description,
                self.platform.value,
                error,
            )
            return False

    def _describe_obstruction(self, locator: Locator) -> str | None:
        try:
            box = locator.bounding_box()
            if box is None:
                return "bounding_box отсутствует"
            page = locator.page
            payload = page.evaluate(
                """
                ({x, y}) => {
                    const top = document.elementFromPoint(x, y);
                    if (!top) {
                        return { hit: null };
                    }
                    return {
                        hit: {
                            tag: top.tagName,
                            className: top.className,
                            id: top.id,
                            text: (top.textContent || '').trim().slice(0, 120)
                        }
                    };
                }
                """,
                {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2},
            )
            return f"elementFromPoint={json.dumps(payload, ensure_ascii=False)}"
        except Exception as error:  # noqa: BLE001
            return f"не удалось определить перекрытие: {error}"

    def _apply_sort_option(
        self,
        page: Page,
        option_selectors: list[str],
        option_texts: list[str],
    ) -> bool:
        for selector in option_selectors:
            if self._try_click_locator(page.locator(selector).first, f"option selector {selector}"):
                page.wait_for_timeout(1200)
                return True
        for label in option_texts:
            option_candidates = [
                (page.get_by_text(label, exact=True).first, f"option exact text {label}"),
                (page.get_by_text(label, exact=False).first, f"option text {label}"),
                (page.locator(f"[role='menuitem']:has-text('{label}')").first, f"menuitem {label}"),
                (page.locator(f"[role='option']:has-text('{label}')").first, f"role option {label}"),
                (page.locator(f"button:has-text('{label}')").first, f"button {label}"),
                (page.locator(f"label:has-text('{label}')").first, f"label {label}"),
                (page.locator(f"div:has-text('{label}')").first, f"div {label}"),
                (page.locator(f"[class*='item']:has-text('{label}')").first, f"item {label}"),
            ]
            for locator, description in option_candidates:
                if self._try_click_locator(locator, description):
                    page.wait_for_timeout(1200)
                    return True
        return False

    def _is_sort_applied(self, page: Page, expected_texts: list[str]) -> bool:
        for text in expected_texts:
            locator = page.get_by_text(text, exact=True).first
            try:
                if locator.count() and locator.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _save_sort_debug_step(self, page: Page, step: str) -> None:
        if not self.settings.playwright_save_sort_debug_steps:
            return
        debug_dir = self._runtime_dir("debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(debug_dir / f"{self.platform.value}-sort-{step}.png"),
            full_page=True,
        )

    def _persist_context_state(self, context: BrowserContext) -> None:
        if self.storage_state_path is None:
            return
        context.storage_state(path=str(self.storage_state_path))

    def _save_debug_html(self, html: str) -> None:
        debug_dir = self._runtime_dir("debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{self.platform.value}.html").write_text(html, encoding="utf-8")

    def _save_debug_screenshot(self, page: Page) -> None:
        if not self.settings.playwright_save_screenshots:
            return
        debug_dir = self._runtime_dir("debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(debug_dir / f"{self.platform.value}.png"), full_page=True)

    @staticmethod
    def _runtime_dir(name: str) -> Path:
        docker_root = Path("/app")
        if docker_root.exists():
            return docker_root / name
        project_root = Path(__file__).resolve().parents[2]
        return project_root / name

    def _build_review(self, source_url: str, item: dict[str, Any]) -> Review | None:
        review = Review(
            platform=self.platform,
            published_at=str(item.get("published_at", "")).strip(),
            stars=int(item.get("stars", 0)),
            text=str(item.get("text", "")).strip(),
            source_url=str(item.get("source_url") or source_url),
            author_name=self._none_if_empty(item.get("author_name")),
            external_id=self._none_if_empty(item.get("external_id")),
        )
        if not self._is_valid_review(review):
            return None
        review.signature = make_review_signature(review)
        return review

    @staticmethod
    def _is_valid_review(review: Review) -> bool:
        if not 1 <= review.stars <= 5:
            return False
        if review.text:
            return True
        return any([review.external_id, review.published_at, review.author_name])

    @staticmethod
    def _normalize_rating(value: float) -> float:
        return round(float(value), 1)

    @staticmethod
    def _none_if_empty(value: object) -> str | None:
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    @abstractmethod
    def parse_html(
        self,
        html: str,
        source_url: str | None = None,
    ) -> tuple[int, float, list[dict[str, Any]]]:
        raise NotImplementedError
