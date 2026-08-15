"""LLM을 부르지 않는 테스트 대역 — diet-agent와 같은 규약 (비스트리밍 판)."""

from types import SimpleNamespace


def fake_tool_call(name: str, arguments: str, call_id: str = "call_1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
        type="function",
    )


def fake_response(content=None, tool_calls=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        role="assistant",
        model_dump=lambda: {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments},
                }
                for c in (tool_calls or [])
            ]
            or None,
        },
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], model="fake-model")


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("각본에 없는 추가 LLM 호출")
        return self.responses.pop(0)
