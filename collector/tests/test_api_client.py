from collector_agent.api_client import CollectorApiClient


class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


class Http:
    def __init__(self): self.calls = []
    def get(self, url, headers): self.calls.append(("GET", url, headers)); return Response({"agentId": "home", "pollSeconds": 60, "subscriptions": []})
    def post(self, url, headers, json): self.calls.append(("POST", url, headers, json)); return Response({"items": []})


def test_api_client_uses_collector_bearer_contract():
    http = Http()
    client = CollectorApiClient("https://api.example", "token", http)
    assert client.fetch_config()["agentId"] == "home"
    client.upload("home", [])
    assert http.calls[0][2] == {"Authorization": "Bearer token"}
    assert http.calls[1][3] == {"agentId": "home", "posts": []}
