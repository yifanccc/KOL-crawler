import re

from pydantic import BaseModel


class AssetCandidate(BaseModel):
    symbol: str
    market: str
    asset_type: str
    name: str | None = None


A_SHARE_ALIASES = {
    "300750": "宁德时代",
    "600519": "贵州茅台",
    "300024": "机器人",
}

CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "BNB", "XRP"}
COMMON_US_SYMBOLS = {
    "AAPL",
    "AMD",
    "AMZN",
    "GOOG",
    "GOOGL",
    "META",
    "MSFT",
    "NVDA",
    "QQQ",
    "SPX",
    "TSLA",
}


def normalize_asset_symbol(text: str) -> str | None:
    cleaned = text.strip().upper()
    if cleaned.startswith("$") and len(cleaned) > 1:
        return cleaned[1:]
    if re.fullmatch(r"\d{6}", cleaned):
        return cleaned
    if cleaned in CRYPTO_SYMBOLS:
        return cleaned
    return None


def detect_assets(text: str) -> list[AssetCandidate]:
    found: list[AssetCandidate] = []
    seen: set[str] = set()

    for match in re.findall(r"\$[A-Za-z][A-Za-z0-9.]{0,12}", text):
        symbol = normalize_asset_symbol(match)
        if symbol and symbol not in seen:
            found.append(candidate_from_symbol(symbol))
            seen.add(symbol)

    upper_text = text.upper()
    for symbol in sorted(CRYPTO_SYMBOLS):
        if re.search(rf"\b{symbol}\b", upper_text) and symbol not in seen:
            found.append(AssetCandidate(symbol=symbol, market="CRYPTO", asset_type="crypto"))
            seen.add(symbol)

    for symbol in sorted(COMMON_US_SYMBOLS):
        if re.search(rf"\b{symbol}\b", upper_text) and symbol not in seen:
            found.append(AssetCandidate(symbol=symbol, market="US_STOCK", asset_type="stock"))
            seen.add(symbol)

    for symbol, name in A_SHARE_ALIASES.items():
        if (symbol in text or name in text) and symbol not in seen:
            found.append(
                AssetCandidate(symbol=symbol, market="A_SHARE", asset_type="stock", name=name)
            )
            seen.add(symbol)

    return found


def candidate_from_symbol(symbol: str, market: str = "unknown") -> AssetCandidate:
    normalized = symbol.strip().lstrip("$").upper()
    if normalized in CRYPTO_SYMBOLS or market == "crypto":
        return AssetCandidate(symbol=normalized, market="CRYPTO", asset_type="crypto")
    if re.fullmatch(r"\d{6}", normalized) or market == "a_share":
        return AssetCandidate(
            symbol=normalized,
            market="A_SHARE",
            asset_type="stock",
            name=A_SHARE_ALIASES.get(normalized),
        )
    if market == "hk_stock":
        return AssetCandidate(symbol=normalized, market="HK_STOCK", asset_type="stock")
    return AssetCandidate(symbol=normalized, market="US_STOCK", asset_type="stock")
