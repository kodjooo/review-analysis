from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup


class AntiBotDetectedError(RuntimeError):
    """Ошибка распознавания антибот-страницы."""


@dataclass(slots=True)
class PageExpectation:
    target_selectors: list[str]
    anti_bot_selectors: list[str]
    anti_bot_text_markers: list[str]


def inspect_page_state(
    title: str,
    url: str,
    html: str,
    expectation: PageExpectation,
) -> tuple[str, dict[str, bool], dict[str, bool]]:
    soup = BeautifulSoup(html, "html.parser")

    target_hits = {
        selector: soup.select_one(selector) is not None for selector in expectation.target_selectors
    }
    anti_bot_hits = {
        selector: soup.select_one(selector) is not None for selector in expectation.anti_bot_selectors
    }

    has_target = any(target_hits.values())
    has_antibot_selector = any(anti_bot_hits.values())

    url_lower = url.lower()
    title_lower = title.lower()
    html_lower = html.lower()
    has_antibot_text = any(marker in html_lower for marker in expectation.anti_bot_text_markers)

    if has_target:
        return "target", target_hits, anti_bot_hits

    if "captcha" in url_lower or "captcha" in title_lower or "/showcaptcha" in url_lower:
        return "antibot", target_hits, anti_bot_hits

    if has_antibot_selector or has_antibot_text:
        return "antibot", target_hits, anti_bot_hits

    return "unknown", target_hits, anti_bot_hits
