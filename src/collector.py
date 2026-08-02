"""네이버 뉴스 섹션 목록(news.naver.com/main/list.naver) 크롤링.

카테고리 구분 없이 5개 섹션(정치/경제/사회/세계/IT)을 통합 수집한 뒤,
지정된 언론사(ALLOWED_OUTLETS)의 기사만 남긴다. 중요도 판단은 하지 않고
최근 LOOKBACK_HOURS 이내 전체 후보를 그대로 반환한다 — 선정은 summarizer가
Claude에게 맡긴다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from src.config import (
    ALLOWED_OUTLETS,
    LOOKBACK_HOURS,
    MAX_PAGES_PER_DATE,
    NAVER_SECTIONS,
    REQUEST_TIMEOUT,
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_KST = timezone(timedelta(hours=9))
_LIST_URL = "https://news.naver.com/main/list.naver"

_REL_RE = re.compile(r"(\d+)\s*(분|시간|일)전")
_HANGUL_RE = re.compile(r"[가-힣]")
_WIRE_OUTLETS = {"AP연합뉴스", "EPA연합뉴스", "UPI연합뉴스", "로이터"}


def _parse_relative_time(now: datetime, text: str) -> datetime | None:
    match = _REL_RE.search(text)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    if unit == "분":
        delta = timedelta(minutes=amount)
    elif unit == "시간":
        delta = timedelta(hours=amount)
    else:
        delta = timedelta(days=amount)
    return now - delta


def _is_wire_caption(title: str, outlet: str) -> bool:
    """AP/EPA 사진통신사 캡션(실제 기사가 아닌 사진 캡션)을 걸러낸다."""
    if outlet in _WIRE_OUTLETS:
        return True
    return not _HANGUL_RE.search(title)


def _fetch_page(session: requests.Session, sid1: str, date_str: str, page: int) -> list[tuple[str, str, str, str]]:
    resp = session.get(
        _LIST_URL,
        params={"mode": "LSD", "mid": "sec", "sid1": sid1, "date": date_str, "page": page},
        headers=_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items: list[tuple[str, str, str, str]] = []
    for li in soup.select("ul.type06_headline > li, ul.type06 > li"):
        dts = li.select("dt")
        text_dt = next((d for d in dts if "photo" not in (d.get("class") or [])), None)
        a = text_dt.find("a") if text_dt else None
        if not a:
            continue
        title = a.get_text(strip=True)
        link = a.get("href")
        if not title or not link:
            continue
        time_el = li.select_one("span.date")
        writing_el = li.select_one("span.writing")
        time_text = time_el.get_text(strip=True) if time_el else ""
        outlet = writing_el.get_text(strip=True) if writing_el else ""
        items.append((title, link, time_text, outlet))
    return items


def _collect_section(session: requests.Session, sid1: str, now: datetime) -> list[dict]:
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    today_str = now.strftime("%Y%m%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y%m%d")

    seen_links: set[str] = set()
    seen_raw_links: set[str] = set()  # 필터 전 원본(페이지 반복 감지용)
    articles: list[dict] = []

    for date_str in (today_str, yesterday_str):
        prev_raw_count = -1
        for page in range(1, MAX_PAGES_PER_DATE + 1):
            try:
                items = _fetch_page(session, sid1, date_str, page)
            except Exception:
                break
            if not items:
                break

            reached_cutoff = False
            for title, link, time_text, outlet in items:
                seen_raw_links.add(link)
                published = _parse_relative_time(now, time_text)
                if published is None:
                    continue  # 이례적 시간 포맷 -> 안전하게 건너뜀
                if published < cutoff:
                    reached_cutoff = True
                    continue
                if link in seen_links or outlet not in ALLOWED_OUTLETS or _is_wire_caption(title, outlet):
                    continue
                seen_links.add(link)
                articles.append(
                    {"title": title, "link": link, "published": published, "outlet": outlet}
                )

            if len(seen_raw_links) == prev_raw_count:
                break  # 페이지가 반복됨 = 마지막 페이지 도달
            prev_raw_count = len(seen_raw_links)

            if reached_cutoff:
                break

    return articles


def collect() -> list[dict]:
    """24시간 이내, 5대 종합일간지 기사를 카테고리 구분 없이 통합 수집한다.

    반환: [{title, link, published(datetime), outlet}, ...] (최신순 정렬, 중복 제거)
    """
    now = datetime.now(tz=_KST)
    session = requests.Session()

    all_articles: list[dict] = []
    for sid1 in NAVER_SECTIONS:
        all_articles.extend(_collect_section(session, sid1, now))

    # 여러 섹션에 동시 노출된 기사(링크 기준) 중복 제거
    dedup: dict[str, dict] = {a["link"]: a for a in all_articles}
    articles = list(dedup.values())
    articles.sort(key=lambda a: a["published"], reverse=True)
    return articles


if __name__ == "__main__":
    collected = collect()
    print(f"총 {len(collected)}건 수집")
    for art in collected[:20]:
        pub = art["published"].strftime("%m-%d %H:%M")
        print(f"[{pub}] ({art['outlet']}) {art['title']}")
