"""Smoke-test the local OIDC flow and real Studio HTTP integration boundaries."""

from __future__ import annotations

import base64
import hashlib
import secrets
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx


class LoginForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action = ""
        self.fields: dict[str, str] = {}
        self.in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action") or ""
            self.in_form = True
        elif self.in_form and tag == "input" and attributes.get("name"):
            self.fields[attributes["name"]] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.in_form = False


def token_for(username: str, password: str) -> str:
    authority = "http://localhost:4081/realms/studio-dev"
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    redirect = "http://localhost:3001/auth/callback"
    with httpx.Client(follow_redirects=False, timeout=15) as client:
        response = client.get(
            f"{authority}/protocol/openid-connect/auth",
            params={
                "client_id": "studio",
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": "openid profile email",
                "state": secrets.token_urlsafe(16),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        response.raise_for_status()
        form = LoginForm()
        form.feed(response.text)
        if not form.action:
            raise RuntimeError("Keycloak did not return a login form")
        if not client.cookies:
            raise RuntimeError("Keycloak did not set login cookies")
        # Browsers accept Secure cookies on localhost; httpx deliberately does not.
        local_cookies = "; ".join(
            f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar
        )
        response = client.post(
            form.action,
            headers={"Cookie": local_cookies},
            data={**form.fields, "username": username, "password": password},
        )
        if response.status_code not in (302, 303):
            raise RuntimeError(
                f"Keycloak login did not redirect to the callback (status={response.status_code}, "
                f"invalid_credentials={'Invalid username or password' in response.text})"
            )
        code = parse_qs(urlparse(response.headers["location"]).query).get(
            "code", [None]
        )[0]
        if not code:
            raise RuntimeError("Keycloak login did not return an authorization code")
        result = client.post(
            f"{authority}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "studio",
                "redirect_uri": redirect,
                "code": code,
                "code_verifier": verifier,
            },
        )
        result.raise_for_status()
        return result.json()["access_token"]


def main() -> None:
    credentials = {}
    for line in (
        (Path(__file__).resolve().parents[1] / ".dev-local/credentials.env")
        .read_text()
        .splitlines()
    ):
        if line and not line.startswith("#"):
            name, value = line.split("=", 1)
            credentials[name] = value
    base = "http://localhost:3001"
    with httpx.Client(base_url=base, timeout=30) as client:
        assert client.get("/api/version").status_code == 200
        assert client.get("/env.js").status_code == 200
        assert client.get("/usage").status_code == 200
        assert client.get("/api/session").status_code == 401
        for username in ("developer", "viewer", "no-access"):
            token = token_for(username, credentials["DEV_USER_PASSWORD"])
            headers = {"Authorization": f"Bearer {token}"}
            session = client.get("/api/session", headers=headers)
            assert session.status_code == (403 if username == "no-access" else 200), (
                username,
                session.status_code,
                session.text[:200],
            )
            policy = client.get("/api/policy-engine/policy", headers=headers)
            assert policy.status_code == (200 if username == "developer" else 403)
            if username == "viewer":
                viewer_id = session.json()["subject"]
                assert (
                    client.get(
                        f"/api/users/{viewer_id}/usage/daily", headers=headers
                    ).status_code
                    == 200
                )
                assert (
                    client.get(
                        f"/api/users/{viewer_id}/agentgateway-permissions",
                        headers=headers,
                    ).status_code
                    == 200
                )
                assert (
                    client.get(
                        f"/api/users/{viewer_id}/api-keys", headers=headers
                    ).status_code
                    == 200
                )
                assert (
                    client.get("/api/admin/users", headers=headers).status_code == 403
                )
                assert (
                    client.get("/api/usage/daily", headers=headers).status_code == 403
                )
                assert (
                    client.get("/api/usage/people", headers=headers).status_code == 403
                )
            if username != "developer":
                continue
            user_id = session.json()["subject"]
            assert client.get("/api/admin/users", headers=headers).status_code == 200
            today = client.get("/api/usage/daily", headers=headers)
            assert today.status_code == 200 and today.json()["days"]
            people = client.get("/api/usage/people", headers=headers)
            assert people.status_code == 200
            assert user_id in [person["user_id"] for person in people.json()["users"]]
            assert sum(
                model["requests"]
                for day in today.json()["days"]
                for model in day["models"]
            ) == sum(person["requests"] for person in people.json()["users"])
            assert client.get(
                "/api/users/" + user_id + "/usage/daily", headers=headers
            ).json()["days"]
            permissions = client.get(
                "/api/users/" + user_id + "/agentgateway-permissions", headers=headers
            )
            assert permissions.status_code == 200
            assert "llm:invoke" in permissions.json()["permissions"]
            assert (
                client.get(
                    "/api/users/" + user_id + "/api-keys", headers=headers
                ).status_code
                == 200
            )
            if "--keys" in sys.argv:
                key = client.post(
                    "/api/users/" + user_id + "/api-keys",
                    headers=headers,
                    json={
                        "name": "dev-smoke-" + secrets.token_hex(4),
                        "permissions": ["llm:invoke"],
                        "expires_in_days": 1,
                    },
                )
                assert key.status_code == 201, key.status_code
                key_id = key.json()["id"]
                assert (
                    client.post(
                        f"/api/users/{user_id}/api-keys/{key_id}/revoke",
                        headers=headers,
                    ).status_code
                    == 200
                )
            assert (
                client.get("/api/logs?q=timeout", headers=headers).json()["total"] == 1
            )
            assert (
                client.get(
                    "/api/admin/recent-signins",
                    headers=headers,
                    params={"user_ids": user_id},
                ).status_code
                == 200
            )
            sample = {
                "request": {
                    "model": "demo-model",
                    "messages": [
                        {"role": "user", "content": "email a@example.com"},
                    ],
                },
                "policy": {"pii": {"defaultAction": "mask"}},
            }
            analysis = client.post(
                "/api/policy-engine/evaluate", headers=headers, json=sample
            )
            assert analysis.status_code == 200, analysis.text[:300]
            assert analysis.json()["valid"] and analysis.json()["entity_counts"] == {
                "EMAIL_ADDRESS": 1
            }
            default_sample = client.post(
                "/api/policy-engine/evaluate",
                headers=headers,
                json={
                    "request": {
                        "model": "studio-policy-test",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Hello John Doe, my email is john@example.com",
                            }
                        ],
                    }
                },
            )
            assert default_sample.status_code == 200
            assert default_sample.json()["entity_counts"] == {"EMAIL_ADDRESS": 1}
            unsupported = client.post(
                "/api/policy-engine/evaluate",
                headers=headers,
                json={**sample, "policy": {"pii": {"defaultAction": "encrypt"}}},
            )
            assert (
                unsupported.status_code == 200 and unsupported.json()["valid"] is False
            )
    print("Studio dev login, roles, bridge, analytics, logs and PII sample passed.")


if __name__ == "__main__":
    main()
