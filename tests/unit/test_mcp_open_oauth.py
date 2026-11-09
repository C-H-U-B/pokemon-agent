"""Façade OAuth du serveur HTTP : le parcours qu'impose Claude.ai aboutit, sans redirection ouverte."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from pokemon_rag.mcp import server
from pokemon_rag.mcp.open_oauth import CLAUDE_CALLBACKS

CALLBACK = CLAUDE_CALLBACKS[0]
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def http():
    with TestClient(server.mcp.streamable_http_app(stateless_http=True), base_url=server.PUBLIC_URL) as client:
        yield client


def _authorize(http, client_id, redirect_uri=CALLBACK, scope=None):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
              "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "etat"}
    if scope:
        params["scope"] = scope
    return http.get("/authorize", params=params, follow_redirects=False)


def test_claude_flow_from_discovery_to_tool_call(http):
    assert http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS).status_code == 401
    assert http.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
    metadata = http.get("/.well-known/oauth-authorization-server").json()
    assert metadata["registration_endpoint"].endswith("/register")

    registered = http.post("/register", json={"redirect_uris": [CALLBACK], "client_name": "Claude"}).json()
    authorized = _authorize(http, registered["client_id"], scope="claudeai")
    assert authorized.status_code == 302
    location = urlparse(authorized.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == CALLBACK
    query = parse_qs(location.query)
    assert query["state"] == ["etat"]

    token = http.post("/token", data={
        "grant_type": "authorization_code", "code": query["code"][0], "redirect_uri": CALLBACK,
        "client_id": registered["client_id"], "client_secret": registered["client_secret"],
        "code_verifier": VERIFIER}).json()
    reply = http.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": f"Bearer {token['access_token']}"})
    assert reply.status_code == 200
    assert "serverInfo" in reply.text


def test_code_is_single_use_and_bound_to_pkce(http):
    registered = http.post("/register", json={"redirect_uris": [CALLBACK]}).json()
    code = parse_qs(urlparse(_authorize(http, registered["client_id"]).headers["location"]).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
            "client_id": registered["client_id"], "client_secret": registered["client_secret"]}
    assert http.post("/token", data={**form, "code_verifier": "w" * 64}).status_code == 400
    assert http.post("/token", data={**form, "code_verifier": VERIFIER}).status_code == 200
    assert http.post("/token", data={**form, "code_verifier": VERIFIER}).status_code == 400


def test_client_forgotten_after_restart_reaches_claude_but_no_other_site(http):
    assert _authorize(http, "client-d-avant-le-redemarrage").status_code == 302
    elsewhere = _authorize(http, "client-d-avant-le-redemarrage", redirect_uri="https://pirate.example/callback")
    assert elsewhere.status_code == 400
    assert "location" not in elsewhere.headers
