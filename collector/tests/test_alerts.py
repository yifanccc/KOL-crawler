from collector_agent.alerts import NtfyNotifier, ProviderAlerter


def test_provider_alerts_cool_down_and_send_recovery():
    sent = []
    alerter = ProviderAlerter(lambda title, message: sent.append((title, message)), cooldown_seconds=60)
    assert alerter.update("x", "login_required", 0)
    assert not alerter.update("x", "login_required", 1)
    assert alerter.update("x", "healthy", 2)
    assert len(sent) == 2


def test_authenticated_x_status_is_healthy_for_recovery():
    sent = []
    alerter = ProviderAlerter(lambda title, message: sent.append((title, message)), cooldown_seconds=60)

    assert alerter.update("x", "login_required", 0)
    assert alerter.update("x", "authenticated", 1)
    assert sent[-1] == ("x 已恢复", "Provider 已恢复健康状态")


class Response:
    def raise_for_status(self):
        return None


class Http:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response()


def test_ntfy_notifier_uses_json_for_utf8_title_and_message():
    http = Http()
    notifier = NtfyNotifier(
        "https://ntfy.example/",
        "private-topic",
        token="secret-token",
        http=http,
    )
    notifier("X 需要处理", "Provider 状态：login_required")

    url, request = http.calls[0]
    assert url == "https://ntfy.example"
    assert request["headers"] == {
        "Authorization": "Bearer secret-token",
    }
    assert request["json"] == {
        "topic": "private-topic",
        "title": "X 需要处理",
        "message": "Provider 状态：login_required",
    }
