import httpx

from menu import notifier
from menu.notifier import DISCLAIMER, ConsoleNotifier, NtfyNotifier, compose_body


def test_disclaimer_is_always_the_last_line():
    assert compose_body("NORTH\nMezze: Quinoa").splitlines()[-1] == DISCLAIMER
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
        f"{DISCLAIMER}\n"
    )


def test_console_without_headers_prints_no_header_line(capsys):
    ConsoleNotifier().send("Lunch · Mon Sep 21", "body")
    assert capsys.readouterr().out == f"=== Lunch · Mon Sep 21 ===\nbody\n\n{DISCLAIMER}\n"


def test_ntfy_sends_title_tags_and_click(monkeypatch):
    seen: list[httpx.Request] = []

    def post(url, *, timeout, **kwargs):
        seen.append(httpx.Request("POST", url, **kwargs))

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
        seen.append(httpx.Request("POST", url, **kwargs))

    monkeypatch.setattr(notifier.httpx, "post", post)
    NtfyNotifier(topic="topic-abc").send("Lunch", "body")

    assert dict(seen[0].url.params) == {"title": "Lunch"}
