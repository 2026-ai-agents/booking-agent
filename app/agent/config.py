"""모델 선택 — day-01 랩과 같은 규약. 모델 문자열은 이 파일에만 둔다."""

import os

PROVIDERS: list[tuple[str, str]] = [
    ("GEMINI_API_KEY", "gemini/gemini-3.5-flash-lite"),
    ("OPENAI_API_KEY", "openai/gpt-5.4-nano"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
]

NO_KEY_MESSAGE = (
    "API 키가 없습니다. 저장소 루트에서 cp .env.sample .env 후 셋 중 하나를 "
    "채우고 docker compose up -d --force-recreate 하세요."
)


def pick_model() -> str:
    for env_var, model in PROVIDERS:
        if os.environ.get(env_var):
            return model
    raise RuntimeError(NO_KEY_MESSAGE)
