"""텔레그램으로 메시지를 전송한다."""

from __future__ import annotations

import os

import requests

from src.config import REQUEST_TIMEOUT, TELEGRAM_MAX_MESSAGE_LENGTH

_TELEGRAM_API_BASE = "https://api.telegram.org"


def _send_single_message(text: str) -> None:
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    url = f"{_TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def _split_message(text: str, max_length: int) -> list[str]:
    """긴 메시지를 줄 단위로 max_length 이하 청크로 분할한다."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_length:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_message(text: str) -> None:
    """텔레그램 메시지를 전송한다. 길이 제한 초과 시 자동 분할."""
    for chunk in _split_message(text, TELEGRAM_MAX_MESSAGE_LENGTH):
        _send_single_message(chunk)
