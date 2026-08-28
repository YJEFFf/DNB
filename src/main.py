"""매일 아침 뉴스 요약 알림 - 오케스트레이션."""

from __future__ import annotations

import os
import traceback
from datetime import date

from src.collector import collect, yesterday
from src.notifier import send_message
from src.summarizer import summarize


def resolve_target_date() -> date:
    """요약 대상 날짜(KST 기준 전날). TARGET_DATE로 특정 날짜를 다시 돌릴 수 있다."""
    override = os.environ.get("TARGET_DATE", "").strip()
    return date.fromisoformat(override) if override else yesterday()


def format_message(summary: str, target_date: date) -> str:
    return f"📰 {target_date:%Y-%m-%d} 주요 뉴스\n\n{summary}"


def run() -> None:
    target_date = resolve_target_date()
    collected = collect(target_date)
    summary = summarize(collected, target_date)
    message = format_message(summary, target_date)
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
