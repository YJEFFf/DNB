"""네이버 뉴스 섹션 목록(news.naver.com/main/list.naver) 크롤링.

카테고리 구분 없이 5개 섹션(정치/경제/사회/세계/IT)을 통합 수집한 뒤,
지정된 언론사(ALLOWED_OUTLETS)의 기사만 남긴다. 중요도 판단은 하지 않고
대상 날짜의 후보 전체를 그대로 반환한다 — 선정은 summarizer가 Claude에게 맡긴다.

수집 창은 실행 시각이 아니라 대상 날짜(KST 00:00~24:00) 하루 전체다. 네이버 목록의
date 파티션이 곧 그 창이므로, 실행이 몇 시간 지연돼도 수집 범위와 알림에 붙는 날짜가
어긋나지 않는다.
"""

from __future__ import annotations

import re
import time as _time
from datetime import date, datetime, time, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from src.config import (
    ALLOWED_OUTLETS,
    FETCH_RETRIES,
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


def yesterday(now: datetime | None = None) -> date:
    """KST 기준 전날 날짜."""
    return ((now or datetime.now(tz=_KST)) - timedelta(days=1)).date()


def _parse_relative_time(now: datetime, text: str) -> datetime | None:
    """'32분전'/'5시간전'처럼 시각을 특정할 수 있는 표기만 datetime으로 환산한다.

    'N일전'은 24시간 폭을 하나로 뭉뚱그린 표기라 시각을 알 수 없으므로 None을 반환하고,
    실제 시각은 _fill_times()가 앞뒤 기사로부터 보간한다.
    """
    match = _REL_RE.search(text)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    if unit == "분":
        return now - timedelta(minutes=amount)
    if unit == "시간":
        return now - timedelta(hours=amount)
    return None


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


def _fetch_page_with_retry(
    session: requests.Session, sid1: str, date_str: str, page: int
) -> list[tuple[str, str, str, str]] | None:
    """일시적 오류는 재시도한다. 끝내 실패하면 None(= 이 섹션 수집 중단 신호)."""
    for attempt in range(FETCH_RETRIES + 1):
        try:
            return _fetch_page(session, sid1, date_str, page)
        except Exception as e:
            if attempt == FETCH_RETRIES:
                print(f"경고: 섹션 {sid1} {date_str} {page}쪽 수집 실패로 이후 페이지를 건너뜁니다 ({e}).")
                return None
            _time.sleep(1 + attempt)
    return None


def _fill_times(articles: list[dict], day_start: datetime, day_end: datetime) -> None:
    """시각을 알 수 없는 기사('N일전' 표기)의 시각을 앞뒤 기준점 사이에서 선형 보간한다.

    파티션 내 기사 순서는 항상 최신순이므로, 보간값은 원래 순서를 그대로 유지한다.
    보간된 기사는 time_estimated=True로 표시해 요약 프롬프트에서 추정치임을 밝힌다.
    """
    n = len(articles)
    if n == 0:
        return

    anchors: list[tuple[int, datetime]] = []
    prev = day_end - timedelta(minutes=1)  # 당일 안에 머무르도록(23:59이 최대)
    for i, art in enumerate(articles):
        known = art["published"]
        if known is None:
            continue
        # 파티션 밖으로 벗어난 값(네이버 상대시각과 실행 시각의 미세한 어긋남)은 경계로 당기고,
        # 최신순 단조성도 함께 보장한다.
        known = min(max(known, day_start), prev)
        anchors.append((i, known))
        prev = known

    for i, known in anchors:
        articles[i]["published"] = known
        articles[i]["time_estimated"] = False

    bounds = [(-1, day_end), *anchors, (n, day_start)]
    for (i0, t0), (i1, t1) in zip(bounds, bounds[1:]):
        for j in range(i0 + 1, i1):
            articles[j]["published"] = t0 + (t1 - t0) * ((j - i0) / (i1 - i0))
            articles[j]["time_estimated"] = True


def _collect_section(session: requests.Session, sid1: str, date_str: str, now: datetime) -> list[dict]:
    seen_links: set[str] = set()
    seen_raw_links: set[str] = set()  # 필터 전 원본(페이지 반복 감지용)
    articles: list[dict] = []

    prev_raw_count = -1
    for page in range(1, MAX_PAGES_PER_DATE + 1):
        items = _fetch_page_with_retry(session, sid1, date_str, page)
        if not items:
            break

        for title, link, time_text, outlet in items:
            seen_raw_links.add(link)
            if link in seen_links or outlet not in ALLOWED_OUTLETS or _is_wire_caption(title, outlet):
                continue
            seen_links.add(link)
            articles.append(
                {
                    "title": title,
                    "link": link,
                    "published": _parse_relative_time(now, time_text),
                    "outlet": outlet,
                }
            )

        if len(seen_raw_links) == prev_raw_count:
            break  # 페이지가 반복됨 = 마지막 페이지 도달
        prev_raw_count = len(seen_raw_links)
    else:
        print(f"경고: 섹션 {sid1} {date_str}가 페이지 상한({MAX_PAGES_PER_DATE})에서 잘렸습니다.")

    return articles


def collect(target_date: date | None = None) -> list[dict]:
    """대상 날짜(KST 00:00~24:00) 하루치, 5대 종합일간지 기사를 통합 수집한다.

    반환: [{title, link, published(datetime), time_estimated(bool), outlet}, ...]
          (최신순 정렬, 중복 제거)
    """
    now = datetime.now(tz=_KST)
    if target_date is None:
        target_date = yesterday(now)
    day_start = datetime.combine(target_date, time.min, tzinfo=_KST)
    day_end = day_start + timedelta(days=1)
    date_str = target_date.strftime("%Y%m%d")

    session = requests.Session()
    all_articles: list[dict] = []
    for sid1 in NAVER_SECTIONS:
        section_articles = _collect_section(session, sid1, date_str, now)
        _fill_times(section_articles, day_start, day_end)
        all_articles.extend(section_articles)

    # 여러 섹션에 동시 노출된 기사(링크 기준) 중복 제거
    dedup: dict[str, dict] = {a["link"]: a for a in all_articles}
    articles = list(dedup.values())
    articles.sort(key=lambda a: a["published"], reverse=True)
    return articles


if __name__ == "__main__":
    import sys

    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    collected = collect(day)
    print(f"총 {len(collected)}건 수집")
    for art in collected[:20]:
        mark = "~" if art["time_estimated"] else " "
        print(f"[{mark}{art['published']:%m-%d %H:%M}] ({art['outlet']}) {art['title']}")
