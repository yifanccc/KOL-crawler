import json
from types import SimpleNamespace

import httpx
import pytest

from app.services import structurer as structurer_module
from app.services.structurer import (
    ChatCompletionsModelClient,
    DEFAULT_OUTPUT_SCHEMA,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT,
    FallbackStructurer,
    HeuristicStructurer,
    ResponsesModelClient,
    Structurer,
    build_structurer,
)


def valid_payload(**overrides) -> dict:
    payload = {
        "summary_cn": "市场出现明确交易信号。",
        "stance": "bullish",
        "stance_cn": "多",
        "symbols": ["SPX", "BTC"],
        "market": "macro",
        "key_points": ["大额订单流入", "突破关键位置"],
        "confidence": 82,
        "importance": 4,
        "tags": ["大单", "突破"],
        "action_hint": "仅表达看多倾向，需结合价格确认。",
        "source_language": "English",
        "translated_text_cn": "标普指数与比特币出现大额买单。",
        "risk_warning": "市场观点可能快速失效，不构成投资建议。",
    }
    payload.update(overrides)
    return payload


def test_responses_client_uses_separate_prompts_and_strict_schema(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output_text": json.dumps(valid_payload())}

    def fake_post(url, *, headers, json, timeout):
        captured.update(json)
        return FakeResponse()

    monkeypatch.setattr(
        structurer_module,
        "get_settings",
        lambda: SimpleNamespace(
            model_api_key="test-key",
            openai_base_url="https://example.test",
            openai_model="test-model",
            model_reasoning_effort="xhigh",
            model_timeout_seconds=180,
        ),
    )
    monkeypatch.setattr(structurer_module.httpx, "post", fake_post)

    ResponsesModelClient().complete("system", "user", DEFAULT_OUTPUT_SCHEMA)

    assert captured["input"][0] == {"role": "system", "content": "system"}
    assert captured["input"][1] == {"role": "user", "content": "user"}
    assert captured["text"]["format"]["schema"] == DEFAULT_OUTPUT_SCHEMA
    assert captured["text"]["format"]["strict"] is True


def test_chat_completions_client_uses_json_mode_and_embeds_schema(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": json.dumps(valid_payload())}}]}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse()

    monkeypatch.setattr(
        structurer_module,
        "get_settings",
        lambda: SimpleNamespace(
            model_api_key="test-key",
            openai_base_url="https://api.deepseek.com",
            openai_model="deepseek-v4-pro",
            model_reasoning_effort="high",
            model_timeout_seconds=180,
        ),
    )
    monkeypatch.setattr(structurer_module.httpx, "post", fake_post)

    output = ChatCompletionsModelClient().complete("system", "user", DEFAULT_OUTPUT_SCHEMA)

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert "system" in captured["payload"]["messages"][0]["content"]
    assert '"summary_cn"' in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["messages"][1] == {"role": "user", "content": "user"}
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["reasoning_effort"] == "high"
    assert json.loads(output) == valid_payload()


def test_build_structurer_selects_chat_completions_client(monkeypatch) -> None:
    monkeypatch.setattr(
        structurer_module,
        "get_settings",
        lambda: SimpleNamespace(
            model_api_key="test-key",
            model_api_style="chat_completions",
        ),
    )

    result = build_structurer()

    assert isinstance(result, FallbackStructurer)
    assert isinstance(result.primary.model_client, ChatCompletionsModelClient)


def test_default_prompt_and_schema_cover_financial_chinese_output() -> None:
    assert "金融" in DEFAULT_SYSTEM_PROMPT
    assert "简体中文" in DEFAULT_SYSTEM_PROMPT
    assert "{raw_content}" in DEFAULT_USER_PROMPT
    assert set(DEFAULT_OUTPUT_SCHEMA["required"]) == set(DEFAULT_OUTPUT_SCHEMA["properties"])
    assert DEFAULT_OUTPUT_SCHEMA["properties"]["stance"]["enum"] == [
        "bullish",
        "bearish",
        "neutral",
        "unclear",
    ]


def test_english_x_post_returns_chinese_structured_signal() -> None:
    class Client:
        def complete(self, system_prompt, user_prompt, output_schema):
            assert "Large buy orders" in user_prompt
            return json.dumps(valid_payload(), ensure_ascii=False)

    result = Structurer(Client()).structure(
        "Large buy orders hit $SPX while BTC breaks resistance."
    )

    assert result.summary_cn == "市场出现明确交易信号。"
    assert result.stance == "bullish"
    assert result.stance_cn == "多"
    assert result.symbols == ["SPX", "BTC"]
    assert result.translated_text_cn.startswith("标普指数")


def test_chinese_post_without_symbol_is_valid() -> None:
    class Client:
        def complete(self, system_prompt, user_prompt, output_schema):
            return json.dumps(
                valid_payload(
                    summary_cn="流动性环境仍有不确定性。",
                    stance="unclear",
                    stance_cn="不明确",
                    symbols=[],
                    market="macro",
                    source_language="中文",
                    translated_text_cn="流动性环境仍有不确定性。",
                ),
                ensure_ascii=False,
            )

    result = Structurer(Client()).structure("当前流动性变化较快，暂时无法判断方向。")

    assert result.symbols == []
    assert result.stance == "unclear"
    assert result.stance_cn == "不明确"


def test_binance_square_post_uses_crypto_market() -> None:
    class Client:
        def complete(self, system_prompt, user_prompt, output_schema):
            return json.dumps(
                valid_payload(symbols=["ETH"], market="crypto", tags=["链上数据"]),
                ensure_ascii=False,
            )

    result = Structurer(Client()).structure("ETH funding is rising on Binance Square")

    assert result.market == "crypto"
    assert result.symbols == ["ETH"]
    assert result.tags == ["链上数据"]


def test_invalid_json_falls_back_without_failing_task() -> None:
    class BrokenClient:
        def complete(self, system_prompt, user_prompt, output_schema):
            raise httpx.ReadTimeout("timed out")

    structurer = FallbackStructurer(Structurer(BrokenClient()), HeuristicStructurer())
    result = structurer.structure("No clear trade here")

    assert result.used_fallback is True
    assert result.stance == "unclear"
    assert result.symbols == []
    assert result.summary_cn


@pytest.mark.parametrize(
    "model_output",
    [
        json.dumps(valid_payload(), ensure_ascii=False),
        f"```json\n{json.dumps(valid_payload(), ensure_ascii=False)}\n```",
        f"模型分析如下：\n{json.dumps(valid_payload(), ensure_ascii=False)}\n以上为结果。",
    ],
    ids=["raw_json", "fenced_json", "leading_prose"],
)
def test_structurer_accepts_json_wrappers_without_retrying_model(model_output: str) -> None:
    class Client:
        calls = 0

        def complete(self, system_prompt, user_prompt, output_schema):
            self.calls += 1
            return model_output

    client = Client()
    result = Structurer(client).structure("$SPX 出现买单")

    assert result.symbols == ["SPX", "BTC"]
    assert client.calls == 1


def test_structurer_repairs_stance_alias_before_validation() -> None:
    class Client:
        def complete(self, system_prompt, user_prompt, output_schema):
            return json.dumps(valid_payload(stance="看多", stance_cn="看多"), ensure_ascii=False)

    result = Structurer(Client()).structure("$SPX 观点偏多")

    assert result.stance == "bullish"
    assert result.stance_cn == "多"


def test_invalid_model_text_uses_fallback_after_one_attempt() -> None:
    class Client:
        calls = 0

        def complete(self, system_prompt, user_prompt, output_schema):
            self.calls += 1
            return "这不是 JSON，也没有可提取对象。"

    client = Client()
    result = FallbackStructurer(Structurer(client), HeuristicStructurer()).structure(
        "No symbol or directional opinion here"
    )

    assert result.used_fallback is True
    assert result.symbols == []
    assert client.calls == 1


def test_invalid_custom_schema_uses_fallback_without_calling_model() -> None:
    class Client:
        calls = 0

        def complete(self, system_prompt, user_prompt, output_schema):
            self.calls += 1
            return json.dumps(valid_payload())

    client = Client()
    result = FallbackStructurer(Structurer(client), HeuristicStructurer()).structure(
        "$BTC 的观点待确认",
        output_schema={"type": "array", "additionalProperties": False, "properties": {}},
    )

    assert result.used_fallback is True
    assert client.calls == 0


def test_non_object_custom_schema_is_rejected_before_model_call() -> None:
    class Client:
        calls = 0

        def complete(self, system_prompt, user_prompt, output_schema):
            self.calls += 1
            return json.dumps(valid_payload())

    client = Client()
    with pytest.raises(ValueError, match="root type must be object"):
        Structurer(client).structure("$BTC", output_schema=[])

    assert client.calls == 0
