from collector_agent.providers.binance_square import BinanceSquareProvider


class Client:
    def user_by_username(self, handle):
        if handle == "missing":
            return None
        return {
            "username": handle,
            "squareUid": "square-user-1",
            "displayName": "Btc星辰",
            "avatar": "https://example.com/avatar.png",
        }

    def user_posts(self, square_uid):
        assert square_uid == "square-user-1"
        return {
            "contents": [
                {
                    "id": 343206852746066,
                    "username": "btc7873",
                    "displayName": "Btc星辰",
                    "avatar": "https://example.com/avatar.png",
                    "bodyTextOnly": "$BTC 突破后继续观察。",
                    "firstReleaseTime": 1783681941000,
                    "webLink": "https://www.binance.com/zh-CN/square/post/343206852746066",
                    "tradingPairs": [{"code": "BTC"}],
                },
                {
                    "id": 343206852746065,
                    "username": "btc7873",
                    "displayName": "Btc星辰",
                    "avatar": "https://example.com/avatar.png",
                    "bodyTextOnly": "$ETH 之前的空单已经离场。",
                    "firstReleaseTime": 1783681935000,
                    "webLink": "https://www.binance.com/zh-CN/square/post/343206852746065",
                    "tradingPairs": [{"code": "ETH"}],
                },
            ]
        }


def test_binance_provider_parses_real_api_shape_and_orders_oldest_first():
    provider = BinanceSquareProvider(Client())

    posts = provider.fetch("btc7873", None, 20)

    assert [post.external_id for post in posts] == [
        "343206852746065",
        "343206852746066",
    ]
    assert posts[0].author_name == "Btc星辰"
    assert posts[0].raw_content == "$ETH 之前的空单已经离场。"
    assert posts[0].raw_payload == {
        "id": 343206852746065,
        "bodyTextOnly": "$ETH 之前的空单已经离场。",
        "firstReleaseTime": 1783681935000,
        "webLink": "https://www.binance.com/zh-CN/square/post/343206852746065",
        "tradingPairs": [{"code": "ETH"}],
    }
    assert provider.health().status == "healthy"


def test_binance_provider_filters_checkpoint():
    provider = BinanceSquareProvider(Client())

    posts = provider.fetch("btc7873", "343206852746065", 20)

    assert [post.external_id for post in posts] == ["343206852746066"]


def test_binance_invalid_profile_is_reported_as_provider_failure():
    provider = BinanceSquareProvider(Client())

    assert provider.fetch("missing", None, 20) == []
    assert provider.health().status == "failed"
    assert provider.health().message == "Binance Square profile was not found"
