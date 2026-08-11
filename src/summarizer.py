"""Claude API로 통합 뉴스 후보 목록에서 오늘의 주요 뉴스를 선정·요약한다."""

from __future__ import annotations

import re

import anthropic

from src.config import CLAUDE_MODEL

_client = anthropic.Anthropic()

_PROMPT_TEMPLATE = """다음은 최근 24시간 이내, 5대 종합일간지(조선일보/중앙일보/동아일보/한겨레/경향신문)의 \
기사 목록입니다 (총 {count}건, 카테고리 구분 없이 통합). 이 중 '오늘의 주요 뉴스'를 선정하고 요약해 주세요.

[선정 기준]
1. 여러 신문이 함께(같은 시간대에 유사한 내용으로) 다루는 사안을 우선 고려 — 목록의 언론사명을 보고 직접 판단할 것
2. 같은 사안(후속·다른 각도 포함)은 절대 중복 선정하지 말고 하나로 병합할 것
3. 카테고리(정치/경제/사회/세계/IT) 안배는 하지 말고 순수하게 중요도 순으로 선정
4. 단순 흥미/가십성보다 사회·경제·정치·기술적 파급력이 큰 사안 우선
5. 개수를 미리 정하지 말 것 — 오늘 실제로 '주요 뉴스'라 부를 만한 사안이 몇 개든(많으면 15개+, 적으면 5개 이하도 가능) 그 수만큼만 선정. 개수를 맞추려고 덜 중요한 걸 끼워넣거나, 중요한 걸 빼지 말 것

[출력 형식]
• [선정이유 한 줄] 제목 — 2~3문장 요약 (출처번호: N)
- 각 줄 끝의 (출처번호: N)은 기사 목록의 대괄호 번호[N] 중 이 사안을 대표하는 기사 하나의 번호를 그대로 적을 것
- 같은 사안을 여러 신문이 다뤘다면, 그 중 아무 기사 번호나 하나만 골라 적을 것 (여러 개 적지 말 것)

[기사 목록] (각 줄 맨 앞 [N]이 출처번호, 시간 내림차순)
{articles}
"""

_SOURCE_TAG_RE = re.compile(r"\(출처번호:\s*(\d+)\)")


def _format_articles(articles: list[dict]) -> str:
    lines = []
    for i, art in enumerate(articles, 1):
        pub = art["published"].strftime("%m-%d %H:%M")
        lines.append(f"[{i}] [{pub}] ({art['outlet']}) {art['title']}")
    return "\n".join(lines)


def _attach_links(text: str, articles: list[dict]) -> str:
    """(출처번호: N) 태그를 실제 기사 링크로 치환한다. 잘못된/누락된 번호는 조용히 제거한다."""

    def replace(match: re.Match) -> str:
        idx = int(match.group(1))
        if 1 <= idx <= len(articles):
            return f"\n  {articles[idx - 1]['link']}"
        return ""

    return _SOURCE_TAG_RE.sub(replace, text)


def summarize(articles: list[dict]) -> str:
    """통합 기사 후보 목록을 받아 오늘의 주요 뉴스 요약 텍스트를 반환한다."""
    if not articles:
        return "(수집된 기사가 없습니다)"

    prompt = _PROMPT_TEMPLATE.format(count=len(articles), articles=_format_articles(articles))

    response = _client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "max_tokens":
        print("경고: 요약 응답이 max_tokens 한도에서 잘렸습니다 (기사 수를 줄이거나 max_tokens를 늘리세요).")

    for block in response.content:
        if block.type == "text":
            return _attach_links(block.text.strip(), articles)
    return "(요약 생성 실패)"
