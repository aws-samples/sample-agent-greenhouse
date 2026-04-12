"""Cognito token exchange for Slack → AgentCore Identity integration.

Maps Slack user IDs to Cognito users and obtains JWT access tokens
for authenticating with AgentCore Runtime's JWT Authorizer.

Flow:
    1. Slack event → slack_user_id
    2. Look up Cognito user by custom:slack_id attribute
    3. Obtain access_token via admin_initiate_auth (ADMIN_USER_PASSWORD_AUTH)
    4. Return access_token for use as Bearer token with AgentCore Runtime

Tokens are cached per-user with expiry to avoid repeated Cognito calls.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

# Token cache: slack_user_id → CachedToken
_token_cache: dict[str, "CachedToken"] = {}
_TOKEN_EXPIRY_BUFFER_SECONDS = 300  # Refresh 5 min before expiry


@dataclass
class CachedToken:
    """Cached Cognito access token for a Slack user."""
    access_token: str
    id_token: str
    refresh_token: str
    expires_at: float  # Unix timestamp
    cognito_username: str
    slack_user_id: str
    role: str = "standard"

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - _TOKEN_EXPIRY_BUFFER_SECONDS)


@dataclass
class CognitoConfig:
    """Configuration for Cognito token exchange."""
    user_pool_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-west-2"))

    @classmethod
    def from_env(cls) -> "CognitoConfig":
        """Load config from environment variables."""
        return cls(
            user_pool_id=os.environ.get("COGNITO_USER_POOL_ID", ""),
            client_id=os.environ.get("COGNITO_CLIENT_ID", ""),
            client_secret=os.environ.get("COGNITO_CLIENT_SECRET", ""),
            region=os.environ.get("AWS_REGION", "us-west-2"),
        )

    @classmethod
    def from_ssm(cls, region: str = "") -> "CognitoConfig":
        """Load config from AWS SSM Parameter Store."""
        if not region:
            region = os.environ.get("AWS_REGION", "us-west-2")
        ssm = boto3.client("ssm", region_name=region)

        def _get(name: str, decrypt: bool = False) -> str:
            try:
                resp = ssm.get_parameter(Name=name, WithDecryption=decrypt)
                return resp["Parameter"]["Value"]
            except Exception as e:
                logger.warning("Failed to get SSM param %s: %s", name, e)
                return ""

        return cls(
            user_pool_id=_get("/plato/cognito/user-pool-id"),
            client_id=_get("/plato/cognito/client-id"),
            client_secret=_get("/plato/cognito/client-secret", decrypt=True),
            region=region,
        )


class CognitoTokenExchange:
    """Exchanges Slack user IDs for Cognito JWT access tokens."""

    def __init__(self, config: Optional[CognitoConfig] = None):
        self.config = config or CognitoConfig.from_env()
        if not self.config.user_pool_id:
            # Try SSM as fallback
            self.config = CognitoConfig.from_ssm(self.config.region)
        self._cognito = boto3.client(
            "cognito-idp", region_name=self.config.region
        )
        # Cache: slack_user_id → cognito_username
        self._user_map: dict[str, tuple[str, str]] = {}  # slack_id → (username, role)

    def get_access_token(self, slack_user_id: str) -> Optional[str]:
        """Get a valid access token for a Slack user.

        Returns the access token string, or None if the user is not found
        or authentication fails.
        """
        self._ensure_tokens(slack_user_id)
        cached = _token_cache.get(slack_user_id)
        return cached.access_token if cached else None

    def get_id_token(self, slack_user_id: str) -> Optional[str]:
        """Get a valid ID token for a Slack user.

        The ID token contains custom claims (custom:slack_id, custom:role,
        email, cognito:username) needed by the AgentCore Runtime JWT
        Authorizer to identify the user.  Use this as the Bearer token.
        """
        self._ensure_tokens(slack_user_id)
        cached = _token_cache.get(slack_user_id)
        return cached.id_token if cached else None

    def _ensure_tokens(self, slack_user_id: str) -> None:
        """Ensure fresh tokens are cached for the given Slack user."""
        # Check cache first
        cached = _token_cache.get(slack_user_id)
        if cached and not cached.is_expired:
            logger.debug("Using cached token for %s", slack_user_id)
            return

        # If we have a cached refresh token, try to refresh
        if cached and cached.refresh_token:
            try:
                self._refresh_token(cached)
                return
            except Exception as e:
                logger.warning(
                    "Token refresh failed for %s, re-authenticating: %s",
                    slack_user_id, e,
                )

        # Full authentication flow
        self._authenticate(slack_user_id)

    def get_user_role(self, slack_user_id: str) -> str:
        """Get the role for a Slack user from cache or Cognito."""
        cached = _token_cache.get(slack_user_id)
        if cached:
            return cached.role

        # Look up from user map or Cognito
        if slack_user_id in self._user_map:
            return self._user_map[slack_user_id][1]

        self._lookup_user(slack_user_id)
        if slack_user_id in self._user_map:
            return self._user_map[slack_user_id][1]

        return "standard"

    def _lookup_user(self, slack_user_id: str) -> Optional[tuple[str, str]]:
        """Look up Cognito username by Slack user ID.

        Custom attributes (custom:slack_id) are not searchable via Cognito's
        ListUsers Filter unless marked at pool creation time.  We list all
        users and filter client-side.  This is fine for small user pools
        (< 100 users).  The result is cached in self._user_map.

        Returns (cognito_username, role) or None.
        """
        if slack_user_id in self._user_map:
            return self._user_map[slack_user_id]

        try:
            # List all users and filter client-side (custom attrs not searchable)
            paginator = self._cognito.get_paginator("list_users")
            for page in paginator.paginate(
                UserPoolId=self.config.user_pool_id,
                Limit=60,
            ):
                for user in page.get("Users", []):
                    attrs = {
                        a["Name"]: a["Value"]
                        for a in user.get("Attributes", [])
                    }
                    uid = attrs.get("custom:slack_id", "")
                    if uid == slack_user_id:
                        username = user["Username"]
                        role = attrs.get("custom:role", "standard")
                        self._user_map[slack_user_id] = (username, role)
                        logger.info(
                            "Mapped Slack user %s → Cognito user %s (role=%s)",
                            slack_user_id, username, role,
                        )
                        return (username, role)

            logger.warning("No Cognito user found for Slack ID %s", slack_user_id)
            return None

        except Exception as e:
            logger.error("Failed to look up Cognito user for %s: %s", slack_user_id, e)
            return None

    def _authenticate(self, slack_user_id: str) -> Optional[str]:
        """Full authentication: look up user and get tokens.

        Uses ADMIN_USER_PASSWORD_AUTH flow. The user's password is stored
        in SSM and retrieved server-side. This is appropriate for a
        bot-to-backend flow where the user doesn't directly enter credentials.
        """
        user_info = self._lookup_user(slack_user_id)
        if not user_info:
            return None

        username, role = user_info

        # Get user's password from SSM
        try:
            ssm = boto3.client("ssm", region_name=self.config.region)
            password_resp = ssm.get_parameter(
                Name=f"/plato/cognito/users/{username}/password",
                WithDecryption=True,
            )
            password = password_resp["Parameter"]["Value"]
        except Exception as e:
            logger.error(
                "Failed to get password for user %s from SSM: %s", username, e
            )
            return None

        try:
            # Compute SECRET_HASH if client has a secret
            auth_params = {
                "USERNAME": username,
                "PASSWORD": password,
            }

            if self.config.client_secret:
                import hashlib
                import hmac
                import base64

                msg = username + self.config.client_id
                secret_hash = base64.b64encode(
                    hmac.new(
                        self.config.client_secret.encode("utf-8"),
                        msg.encode("utf-8"),
                        hashlib.sha256,
                    ).digest()
                ).decode("utf-8")
                auth_params["SECRET_HASH"] = secret_hash

            response = self._cognito.admin_initiate_auth(
                UserPoolId=self.config.user_pool_id,
                ClientId=self.config.client_id,
                AuthFlow="ADMIN_USER_PASSWORD_AUTH",
                AuthParameters=auth_params,
            )

            result = response.get("AuthenticationResult", {})
            access_token = result.get("AccessToken", "")
            id_token = result.get("IdToken", "")
            refresh_token = result.get("RefreshToken", "")
            expires_in = result.get("ExpiresIn", 3600)

            if not access_token:
                logger.error("No access token in auth response for %s", username)
                return None

            # Cache the token
            _token_cache[slack_user_id] = CachedToken(
                access_token=access_token,
                id_token=id_token,
                refresh_token=refresh_token,
                expires_at=time.time() + expires_in,
                cognito_username=username,
                slack_user_id=slack_user_id,
                role=role,
            )

            logger.info(
                "Authenticated Slack user %s (Cognito: %s, role=%s, expires_in=%ds)",
                slack_user_id, username, role, expires_in,
            )
            return access_token

        except Exception as e:
            logger.error(
                "Authentication failed for %s (Cognito: %s): %s",
                slack_user_id, username, e,
            )
            return None

    def _refresh_token(self, cached: CachedToken) -> Optional[str]:
        """Refresh an expired token using the refresh_token."""
        try:
            auth_params = {
                "REFRESH_TOKEN": cached.refresh_token,
            }

            if self.config.client_secret:
                import hashlib
                import hmac
                import base64

                msg = cached.cognito_username + self.config.client_id
                secret_hash = base64.b64encode(
                    hmac.new(
                        self.config.client_secret.encode("utf-8"),
                        msg.encode("utf-8"),
                        hashlib.sha256,
                    ).digest()
                ).decode("utf-8")
                auth_params["SECRET_HASH"] = secret_hash

            response = self._cognito.admin_initiate_auth(
                UserPoolId=self.config.user_pool_id,
                ClientId=self.config.client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters=auth_params,
            )

            result = response.get("AuthenticationResult", {})
            access_token = result.get("AccessToken", "")
            expires_in = result.get("ExpiresIn", 3600)

            if not access_token:
                return None

            # Update cache (refresh_token stays the same)
            cached.access_token = access_token
            cached.id_token = result.get("IdToken", cached.id_token)
            cached.expires_at = time.time() + expires_in
            _token_cache[cached.slack_user_id] = cached

            logger.info("Refreshed token for %s", cached.slack_user_id)
            return access_token

        except Exception as e:
            logger.error("Token refresh failed for %s: %s", cached.slack_user_id, e)
            raise
