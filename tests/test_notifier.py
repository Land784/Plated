import httpx
import pytest

from menu import notifier
from menu.notifier import DISCLAIMER, SEPARATOR, ConsoleNotifier, NtfyNotifier, compose_body


def test_disclaimer_is_always_the_last_line_under_a_separator():
    assert compose_body("NORTH\nMezze: Quinoa").splitlines()[-3:] == ["", SEPARATOR, DISCLAIMER]
    assert DISCLAIMER == "Data may be incomplete; confirm allergens with staff."


def test_console_prints_title_headers_and_body(capsys):
    ConsoleNotifier().send(
        "Dinner · Thu Sep 24",
        "NORTH\nMezze: Quinoa",
        tags=["plate_with_cutlery"],
        click="https://nd.nutrislice.com/menu/north-dining-hall/",
    )
    assert capsys.readouterr().out == (
        "=== Dinner · Thu Sep 24 ===\n"
        "tags: plate_with_cutlery · click: https://nd.nutrislice.com/menu/north-dining-hall/\n"
        "NORTH\nMezze: Quinoa\n\n"
        f"{SEPARATOR}\n{DISCLAIMER}\n"
    )


def test_console_without_headers_prints_no_header_line(capsys):
    ConsoleNotifier().send("Lunch · Mon Sep 21", "body")
    assert capsys.readouterr().out == (
        f"=== Lunch · Mon Sep 21 ===\nbody\n\n{SEPARATOR}\n{DISCLAIMER}\n"
    )


def test_ntfy_sends_title_tags_and_click(monkeypatch):
    seen: list[httpx.Request] = []

    def post(url, *, timeout, **kwargs):
        request = httpx.Request("POST", url, **kwargs)
        seen.append(request)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(notifier.httpx, "post", post)
    NtfyNotifier(topic="topic-abc").send(
        "Dinner · Thu Sep 24",
        "NORTH\nMezze: Quinoa",
        tags=["plate_with_cutlery"],
        click="https://nd.nutrislice.com/menu/north-dining-hall/",
    )

    [request] = seen
    assert request.url.path == "/topic-abc"
    # The title's "·" can't go in a header (httpx sends headers as
    # ASCII), so every ntfy parameter travels as a query parameter.
    assert request.url.params["title"] == "Dinner · Thu Sep 24"
    assert request.url.params["tags"] == "plate_with_cutlery"
    assert request.url.params["click"] == "https://nd.nutrislice.com/menu/north-dining-hall/"
    assert request.content.decode("utf-8") == compose_body("NORTH\nMezze: Quinoa")


def test_ntfy_omits_parameters_that_are_not_given(monkeypatch):
    seen: list[httpx.Request] = []

    def post(url, *, timeout, **kwargs):
        request = httpx.Request("POST", url, **kwargs)
        seen.append(request)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(notifier.httpx, "post", post)
    NtfyNotifier(topic="topic-abc").send("Lunch", "body")

    assert dict(seen[0].url.params) == {"title": "Lunch"}


def _ntfy_answers(monkeypatch, status: int) -> None:
    """Route the notifier's request to a mock ntfy that answers ``status``."""
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status)))
    monkeypatch.setattr(notifier.httpx, "post", client.post)


def test_ntfy_error_raises_without_naming_the_topic(monkeypatch):
    _ntfy_answers(monkeypatch, 429)
    with pytest.raises(RuntimeError, match="HTTP 429") as caught:
        NtfyNotifier(topic="topic-abc").send("Lunch", "body")
    # The message ends up in the dispatch log; the topic is a secret.
    assert "topic-abc" not in str(caught.value)


def test_ntfy_success_does_not_raise(monkeypatch):
    _ntfy_answers(monkeypatch, 200)
    NtfyNotifier(topic="topic-abc").send("Lunch", "body")
