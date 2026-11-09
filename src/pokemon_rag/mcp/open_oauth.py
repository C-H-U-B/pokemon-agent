"""Façade OAuth à approbation automatique pour le serveur MCP servi en HTTP.

Claude.ai refuse un connecteur sans authentification : il tente toujours une inscription
OAuth dynamique (anthropics/claude-ai-mcp #457, #697). Ce fournisseur lui en donne une
qui approuve tout le monde : l'accès reste public, aucun utilisateur n'est identifié.

Rien ne doit dépendre de la mémoire de l'instance, que Cloud Run arrête au repos :
tout jeton est accepté et n'expire pas (pas de rafraîchissement), et un client inconnu
après redémarrage est reconstitué avec les seules adresses de retour de Claude.ai, pour
ne pas faire du serveur une redirection ouverte. Seuls les codes d'autorisation,
échangés quelques secondes après leur émission, vivent en mémoire.
"""

from __future__ import annotations

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

CLAUDE_CALLBACKS = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]
CODE_LIFETIME_SECONDS = 300
MAX_CLIENTS = 1000


class OpenClient(OAuthClientInformationFull):
    """Client qui obtient toute portée demandée : aucune ne restreint l'accès."""

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        return requested_scope.split(" ") if requested_scope else None


class OpenAccessProvider:
    def __init__(self) -> None:
        self.clients: dict[str, OpenClient] = {}
        self.codes: dict[str, AuthorizationCode] = {}

    async def get_client(self, client_id: str) -> OpenClient:
        known = self.clients.get(client_id)
        if known is not None:
            return known
        return OpenClient(client_id=client_id, redirect_uris=CLAUDE_CALLBACKS, token_endpoint_auth_method="none")

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # ponytail: les plus anciens clients sont oubliés au-delà de MAX_CLIENTS ; Claude.ai
        # reste servi par la reconstitution, un client local devra se reconnecter.
        if len(self.clients) >= MAX_CLIENTS:
            self.clients.pop(next(iter(self.clients)))
        self.clients[client_info.client_id] = OpenClient(**client_info.model_dump())

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        now = time.time()
        self.codes = {code: grant for code, grant in self.codes.items() if grant.expires_at > now}
        code = secrets.token_urlsafe(32)
        self.codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=now + CODE_LIFETIME_SECONDS,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        grant = self.codes.get(authorization_code)
        return grant if grant is not None and grant.client_id == client.client_id else None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        self.codes.pop(authorization_code.code, None)
        return OAuthToken(access_token=secrets.token_urlsafe(32), scope=" ".join(authorization_code.scopes) or None)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return None  # aucun jeton de rafraîchissement émis

    async def exchange_refresh_token(self, client, refresh_token, scopes) -> OAuthToken:
        raise NotImplementedError

    async def load_access_token(self, token: str) -> AccessToken:
        return AccessToken(token=token, client_id="public", scopes=[])

    async def revoke_token(self, token) -> None:
        return None
