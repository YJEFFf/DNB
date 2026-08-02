"""매일 아침 뉴스 요약 알림 - 오케스트레이션."""

from __future__ import annotations

import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from src.collector import collect
from src.notifier import send_message
from src.summarizer import summarize

_KST = ZoneInfo("Asia/Seoul")


def format_message(summary: str) -> str:
    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")
    return f"📰 {today} 오늘의 주요 뉴스\n\n{summary}"


def run() -> None:
    collected = collect()
    summary = summarize(collected)
    message = format_message(summary)
    send_message(message)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        error_text = f"⚠️ 뉴스 요약 알림 실행 중 오류 발생:\n{e}\n\n{traceback.format_exc()[-1500:]}"
        print(error_text)
        try:
            send_message(error_text[:4096])
        except Exception:
            pass
        raise
