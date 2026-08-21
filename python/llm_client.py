"""Shared Azure OpenAI / AI Foundry chat-completions transport.

Targets the OpenAI-compatible chat-completions surface (request body with
`messages`, response read from `choices[0].message.content`). If you point
this at a Claude deployment instead, note that Claude on Azure AI Foundry
speaks the Anthropic Messages API (`/anthropic/v1/messages`, response read
from `content[0].text`) — a different wire format that this module does not
implement; use the `anthropic` SDK's AnthropicFoundry client for that.

Endpoint/key/model come from env vars ONLY — never hardcoded, never exposed
via NEXT_PUBLIC_*. Every function here is non-raising: on any transport or
parse failure it logs and returns None, so a caller can degrade gracefully
rather than crash the pipeline.
"""

import json
import os
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

REQUEST_TIMEOUT_SECONDS = 45

# Used only when the configured endpoint is a bare resource URL and the
# full chat-completions path has to be constructed. Override with
# AZURE_FOUNDRY_API_VERSION if your deployment needs a different one.
DEFAULT_API_VERSION = "2024-02-15-preview"


def is_configured() -> bool:
    return bool(
        os.environ.get("AZURE_FOUNDRY_ENDPOINT")
        and os.environ.get("AZURE_FOUNDRY_API_KEY")
        and os.environ.get("AZURE_FOUNDRY_MODEL")
    )


def _resolve_chat_completions_url(endpoint: str, model: str) -> str:
    """Accept either a full chat-completions URL or a bare resource URL.

    Azure's portal shows several different "endpoint" values depending on
    which blade you copy from, and only the full one works as-is. Rather
    than requiring the long hand-built form in .env, treat anything without
    "/chat/completions" as a base and construct the standard Azure OpenAI
    path from it:

        https://<resource>.openai.azure.com
          -> https://<resource>.openai.azure.com/openai/deployments/
             <deployment>/chat/completions?api-version=<version>
    """
    endpoint = endpoint.strip()
    if "/chat/completions" in endpoint:
        return endpoint  # already a full path; use verbatim

    base = endpoint.rstrip("/")
    # a bare resource URL may still carry a stray surface path (e.g.
    # "/anthropic" or "/openai") — strip it so it isn't doubled up
    for stray in ("/anthropic", "/openai"):
        if base.endswith(stray):
            base = base[: -len(stray)]
    api_version = os.environ.get("AZURE_FOUNDRY_API_VERSION", DEFAULT_API_VERSION)
    return f"{base}/openai/deployments/{model}/chat/completions?api-version={api_version}"


def post_chat_json(system_prompt: str, user_content: str, log_prefix: str = "llm") -> object | None:
    """POST a chat completion and return the assistant's message parsed as
    JSON, or None on any failure (unconfigured, transport error, malformed
    envelope, or content that isn't valid JSON).

    Env vars are read at call time, not import time, so a service that loads
    .env after importing this module still works.
    """
    endpoint = os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
    api_key = os.environ.get("AZURE_FOUNDRY_API_KEY", "")
    model = os.environ.get("AZURE_FOUNDRY_MODEL", "")

    if not (endpoint and api_key and model):
        print(f"[{log_prefix}] Azure Foundry not configured (missing endpoint/key/model)")
        return None

    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")

    url = _resolve_chat_completions_url(endpoint, model)

    req = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "api-key": api_key},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            envelope = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        # Log the failing URL path (never the key) — a 404 here almost always
        # means the deployment name or api-version in the path is wrong, and
        # the bare status code alone gives no way to tell.
        safe_path = url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url
        print(f"[{log_prefix}] Azure request failed: HTTP {exc.code} {exc.reason} (path: /{safe_path})")
        if exc.code == 404:
            print(
                f"[{log_prefix}] 404 usually means AZURE_FOUNDRY_MODEL ('{model}') does not match a "
                "deployment name on this resource, or the api-version is unsupported."
            )
        return None
    except (URLError, TimeoutError) as exc:
        print(f"[{log_prefix}] Azure request failed: {exc}")
        return None
    except json.JSONDecodeError as exc:
        print(f"[{log_prefix}] Azure Foundry returned an invalid JSON envelope: {exc}")
        return None

    try:
        content = envelope["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        print(f"[{log_prefix}] Azure Foundry response missing expected envelope shape: {exc}")
        return None

    # Strip markdown fencing if the model added it despite instructions.
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[{log_prefix}] Azure Foundry content was not valid JSON: {exc}")
        return None
