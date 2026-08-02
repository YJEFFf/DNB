"""크롤링 대상 및 상수 설정."""

from dotenv import load_dotenv

load_dotenv()

# 네이버 뉴스 섹션 목록 페이지(news.naver.com/main/list.naver)의 sid1 코드.
# 카테고리 구분 없이 전부 통합 수집하며, 이 딕셔너리는 크롤링 대상 섹션을 정의할 뿐이다.
NAVER_SECTIONS = {
    "100": "정치",
    "101": "경제",
    "102": "사회",
    "104": "세계",
    "105": "IT/과학",
}

# 이 언론사들의 기사만 후보로 채택한다 (보수/진보 균형 5대 종합일간지).
ALLOWED_OUTLETS = {"조선일보", "중앙일보", "동아일보", "한겨레", "경향신문"}

LOOKBACK_HOURS = 24
MAX_PAGES_PER_DATE = 250  # 크롤링 안전장치(무한 페이지네이션 방지)
CLAUDE_MODEL = "claude-sonnet-5"
REQUEST_TIMEOUT = 10
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
