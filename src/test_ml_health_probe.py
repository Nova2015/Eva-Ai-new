import asyncio

import httpx

from src.ml_health import probe_ml_health


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeAsyncClient:
    def __init__(self, response=None, error=None, **_kwargs):
        self.response = response
        self.error = error
        self.requested_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url):
        self.requested_url = url
        if self.error:
            raise self.error
        return self.response


def test_probe_uses_ml_health_endpoint_and_returns_status(monkeypatch):
    client = FakeAsyncClient(response=FakeResponse(200))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    status = asyncio.run(probe_ml_health("https://ml.example.com///"))

    assert status == 200
    assert client.requested_url == "https://ml.example.com/ml/health"


def test_probe_preserves_non_200_status(monkeypatch):
    client = FakeAsyncClient(response=FakeResponse(503))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    assert asyncio.run(probe_ml_health("https://ml.example.com")) == 503


def test_probe_returns_zero_when_service_is_unreachable(monkeypatch):
    client = FakeAsyncClient(error=httpx.ConnectError("offline"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    assert asyncio.run(probe_ml_health("https://ml.example.com")) == 0


def test_probe_returns_zero_for_missing_url():
    assert asyncio.run(probe_ml_health("")) == 0
