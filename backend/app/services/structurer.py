import json
import re
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import get_settings
from app.services.assets import detect_assets


Stance = Literal["bullish", "bearish", "neutral", "unclear"]
Market = Literal["crypto", "us_stock", "a_share", "hk_stock", "macro", "unknown"]

DEFAULT_SYSTEM_PROMPT = """你是金融交易 KOL 情报分析器。你的任务是忠实提取作者明确表达的观点，不补充原文没有的信息，也不把新闻事实强行解释为交易观点。

要求：
1. 原文可能是英文、中文或混合语言，所有展示字段必须使用简体中文。
2. 只有作者明确表达方向时才使用 bullish 或 bearish；无法判断时必须使用 unclear。
3. 识别 $SPX、$BTC、BTC、ETH、NVDA、AAPL、A 股代码等标的，统一去掉 $ 并大写；没有明确标的返回空数组。
4. key_points 最多 5 条，但不用强制凑满 5 条，只保留原文可验证的依据。
5. translated_text_cn 对原文主要内容进行完整、自然的中文翻译或意译。
6. action_hint 只描述观点如何理解，不提供直接买卖建议；risk_warning 必须说明观点局限。
7. 严格按 JSON Schema 输出，不要添加 Markdown 或额外文字。
8. 内容简洁，不需要增加作者认为，作者表示之类的说明。"""

DEFAULT_USER_PROMPT = """请分析下面这条金融 KOL 内容并输出结构化结果：

{raw_content}"""

DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary_cn": {"type": "string"},
        "stance": {
            "type": "string",
            "enum": ["bullish", "bearish", "neutral", "unclear"],
        },
        "stance_cn": {
            "type": "string",
            "enum": ["多", "空", "中性", "不明确"],
        },
        "symbols": {"type": "array", "items": {"type": "string"}},
        "market": {
            "type": "string",
            "enum": ["crypto", "us_stock", "a_share", "hk_stock", "macro", "unknown"],
        },
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
        "tags": {"type": "array", "items": {"type": "string"}},
        "action_hint": {"type": "string"},
        "source_language": {"type": "string"},
        "translated_text_cn": {"type": "string"},
        "risk_warning": {"type": "string"},
    },
    "required": [
        "summary_cn",
        "stance",
        "stance_cn",
        "symbols",
        "market",
        "key_points",
        "confidence",
        "importance",
        "tags",
        "action_hint",
        "source_language",
        "translated_text_cn",
        "risk_warning",
    ],
}

# Backward-compatible export for existing imports.
STRUCTURED_SIGNAL_JSON_SCHEMA = DEFAULT_OUTPUT_SCHEMA

STANCE_CN = {
    "bullish": "多",
    "bearish": "空",
    "neutral": "中性",
    "unclear": "不明确",
}

CORE_DISPLAY_FIELDS = tuple(DEFAULT_OUTPUT_SCHEMA["required"])
STANCE_ALIASES = {
    "bullish": "bullish",
    "bull": "bullish",
    "long": "bullish",
    "buy": "bullish",
    "多": "bullish",
    "看多": "bullish",
    "bearish": "bearish",
    "bear": "bearish",
    "short": "bearish",
    "sell": "bearish",
    "空": "bearish",
    "看空": "bearish",
    "neutral": "neutral",
    "中性": "neutral",
    "中立": "neutral",
    "unclear": "unclear",
    "unknown": "unclear",
    "不明确": "unclear",
    "不明": "unclear",
}


def _validate_output_schema(output_schema: Any) -> None:
    if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
        raise ValueError("Output schema root type must be object")
    if output_schema.get("additionalProperties") is not False:
        raise ValueError("Output schema must disable additional properties")
    properties = output_schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("Output schema properties must be an object")
    missing = set(CORE_DISPLAY_FIELDS) - set(properties)
    if missing:
        raise ValueError(f"Output schema is missing core fields: {', '.join(sorted(missing))}")
    required = output_schema.get("required")
    if not isinstance(required, list) or set(CORE_DISPLAY_FIELDS) - set(required):
        raise ValueError("Output schema must require every core display field")


def _first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text[start:], start):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _decode_json_object(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Model output JSON root must be an object")
    return payload


def _extract_model_payload(output: str) -> dict[str, Any]:
    try:
        return _decode_json_object(output)
    except (json.JSONDecodeError, ValueError) as direct_error:
        last_error: Exception = direct_error

    for fenced_content in re.findall(r"```(?:json)?\s*(.*?)```", output, flags=re.IGNORECASE | re.DOTALL):
        candidate = _first_balanced_json_object(fenced_content)
        if candidate is None:
            continue
        try:
            return _decode_json_object(candidate)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    candidate = _first_balanced_json_object(output)
    if candidate is not None:
        try:
            return _decode_json_object(candidate)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    raise ValueError("Model output did not contain a valid JSON object") from last_error


def _repair_payload(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(payload)
    stance = repaired.get("stance")
    if isinstance(stance, str):
        normalized_stance = STANCE_ALIASES.get(stance.strip().lower())
        if normalized_stance is not None:
            repaired["stance"] = normalized_stance
            repaired["stance_cn"] = STANCE_CN[normalized_stance]
    return repaired


class ModelClient(Protocol):
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: dict[str, Any],
    ) -> str:
        raise NotImplementedError


class StructuredSignal(BaseModel):
    summary_cn: str
    stance: Stance
    stance_cn: Literal["多", "空", "中性", "不明确"]
    symbols: list[str] = Field(default_factory=list)
    market: Market = "unknown"
    key_points: list[str] = Field(default_factory=list, max_length=5)
    confidence: int = Field(ge=0, le=100)
    importance: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    action_hint: str
    source_language: str
    translated_text_cn: str
    risk_warning: str
    used_fallback: bool = Field(default=False, exclude=True)
    fallback_error: str | None = Field(default=None, exclude=True)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            symbol = str(value).strip().lstrip("$").upper()
            if symbol and symbol not in normalized:
                normalized.append(symbol)
        return normalized

    @field_validator("key_points")
    @classmethod
    def limit_key_points(cls, values: list[str]) -> list[str]:
        return [str(value).strip() for value in values if str(value).strip()][:5]

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            tag = str(value).strip()
            if tag and tag not in result:
                result.append(tag)
        return result

    @model_validator(mode="after")
    def align_stance_translation(self) -> "StructuredSignal":
        self.stance_cn = STANCE_CN[self.stance]
        return self


class ResponsesModelClient:
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: dict[str, Any],
    ) -> str:
        settings = get_settings()
        if not settings.model_api_key:
            raise RuntimeError("Model API key is not configured")
        response = httpx.post(
            f"{settings.openai_base_url.rstrip('/')}/v1/responses",
            headers={"Authorization": f"Bearer {settings.model_api_key}"},
            json={
                "model": settings.openai_model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "reasoning": {"effort": settings.model_reasoning_effort},
                "store": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "financial_kol_signal",
                        "strict": True,
                        "schema": output_schema,
                    }
                },
            },
            timeout=settings.model_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("output_text"):
            return payload["output_text"]
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    return content["text"]
        raise RuntimeError("Responses API returned no text")


class ChatCompletionsModelClient:
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: dict[str, Any],
    ) -> str:
        settings = get_settings()
        if not settings.model_api_key:
            raise RuntimeError("Model API key is not configured")
        schema_prompt = (
            f"{system_prompt.rstrip()}\n\n"
            "请仅输出一个符合以下 JSON Schema 的 JSON 对象：\n"
            f"{json.dumps(output_schema, ensure_ascii=False)}"
        )
        response = httpx.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.model_api_key}"},
            json={
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": schema_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "reasoning_effort": settings.model_reasoning_effort,
                "response_format": {"type": "json_object"},
                "stream": False,
            },
            timeout=settings.model_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content")
            if content:
                return content
        raise RuntimeError("Chat Completions API returned no text")


def _render_user_prompt(template: str, raw_text: str) -> str:
    if "{raw_content}" in template:
        return template.replace("{raw_content}", raw_text)
    return f"{template.rstrip()}\n\n原文：\n{raw_text}"


class Structurer:
    def __init__(self, model_client: ModelClient) -> None:
        self.model_client = model_client

    def structure(
        self,
        raw_text: str,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> StructuredSignal:
        active_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        active_user_prompt = _render_user_prompt(user_prompt or DEFAULT_USER_PROMPT, raw_text)
        active_schema = DEFAULT_OUTPUT_SCHEMA if output_schema is None else output_schema
        _validate_output_schema(active_schema)
        output = self.model_client.complete(
            active_system_prompt,
            active_user_prompt,
            active_schema,
        )
        return StructuredSignal.model_validate(_repair_payload(_extract_model_payload(output)))


class FallbackStructurer:
    def __init__(self, primary: Structurer, fallback: "HeuristicStructurer") -> None:
        self.primary = primary
        self.fallback = fallback

    def structure(
        self,
        raw_text: str,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> StructuredSignal:
        try:
            return self.primary.structure(raw_text, system_prompt, user_prompt, output_schema)
        except Exception as exc:
            result = self.fallback.structure(raw_text, system_prompt, user_prompt, output_schema)
            result.used_fallback = True
            result.fallback_error = str(exc)
            return result


class HeuristicStructurer:
    def structure(
        self,
        raw_text: str,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> StructuredSignal:
        assets = detect_assets(raw_text)
        symbols = [asset.symbol for asset in assets]
        lower = raw_text.lower()
        bearish = ["short", "bearish", "sell", "breakdown", "看空", "下跌", "做空"]
        bullish = ["long", "bullish", "buy", "breakout", "看多", "上涨", "做多"]
        stance: Stance = "unclear"
        if any(word in lower for word in bearish):
            stance = "bearish"
        elif any(word in lower for word in bullish):
            stance = "bullish"

        key_points: list[str] = []
        for label, needles in {
            "出现订单或资金流信息": ["order", "大单", "资金流"],
            "提及关键价格位置": ["breakout", "breakdown", "support", "resistance", "突破", "支撑", "阻力"],
            "提及宏观或流动性因素": ["macro", "liquidity", "fed", "宏观", "流动性"],
            "提及链上或资金费率数据": ["on-chain", "funding", "链上", "资金费率"],
        }.items():
            if any(needle in lower for needle in needles):
                key_points.append(label)

        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", raw_text))
        language = "中文" if has_chinese else "English"
        compact = " ".join(raw_text.split())
        if has_chinese:
            translated = compact[:500]
            summary = f"原文主要表达：{compact[:160]}" if compact else "原文没有可分析内容。"
        else:
            subject = "、".join(symbols) if symbols else "市场"
            translated = f"模型暂时不可用，{subject}相关原文需人工复核：{compact[:320]}"
            summary = f"模型暂时不可用；原文涉及{subject}，暂无法可靠生成中文观点摘要。"

        markets = {asset.market for asset in assets}
        market_map = {"CRYPTO": "crypto", "US_STOCK": "us_stock", "A_SHARE": "a_share"}
        market: Market = market_map.get(next(iter(markets)), "unknown") if len(markets) == 1 else "unknown"
        confidence = 35 if stance != "unclear" and symbols else 15
        return StructuredSignal(
            summary_cn=summary,
            stance=stance,
            stance_cn=STANCE_CN[stance],
            symbols=symbols,
            market=market,
            key_points=key_points,
            confidence=confidence,
            importance=2 if stance != "unclear" or symbols else 1,
            tags=[point.replace("提及", "") for point in key_points[:3]],
            action_hint="仅记录原文观点，需结合价格和其他信息确认。",
            source_language=language,
            translated_text_cn=translated,
            risk_warning="自动兜底结果可能遗漏语义，不构成投资建议。",
        )


def build_structurer() -> Structurer | HeuristicStructurer | FallbackStructurer:
    settings = get_settings()
    if settings.model_api_key:
        client: ModelClient
        if settings.model_api_style == "chat_completions":
            client = ChatCompletionsModelClient()
        else:
            client = ResponsesModelClient()
        return FallbackStructurer(Structurer(client), HeuristicStructurer())
    return HeuristicStructurer()
