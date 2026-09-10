"""Explicitly selected OpenRouter/VAPI structured-output client (stdlib only)."""

import json
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _response_text(message_content):
    if isinstance(message_content, str):
        return message_content
    if isinstance(message_content, list):
        parts = []
        for part in message_content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return ""


class OpenRouterClient:
    """Issue one independent structured-output request per pipeline stage."""

    def __init__(self, api_key, site_url=None, timeout=120, *, provider="openrouter", base_url=None):
        if provider not in {"openrouter", "vapi"}:
            raise ValueError("Unsupported prompt provider: " + provider)
        self.provider = provider
        self.label = "OpenRouter" if provider == "openrouter" else "VAPI"
        if not api_key or not api_key.strip():
            raise ValueError(provider.upper() + "_API_KEY is not configured.")
        self.api_key = api_key.strip()
        self.site_url = site_url
        if timeout <= 0:
            raise ValueError("API timeout must be positive.")
        self.timeout = timeout
        base_url = (base_url or ("https://openrouter.ai/api/v1" if provider == "openrouter"
                                else "https://api.gpt.ge/v1")).rstrip("/")
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError("API base URL must be HTTPS without credentials, query, or fragment.")
        if provider == "openrouter" and base_url != "https://openrouter.ai/api/v1":
            raise ValueError("OpenRouter credentials may only be sent to OpenRouter.")
        if provider == "vapi" and parsed.hostname == "openrouter.ai":
            raise ValueError("VAPI credentials must not be sent to OpenRouter.")
        self.endpoint = base_url + "/chat/completions"

    def complete(
        self,
        *,
        stage,
        model,
        schema_name,
        schema,
        system,
        input_value,
        temperature,
        trace,
    ):
        last_error = None
        for attempt in range(1, 5):
            try:
                payload = self._request(
                    model=model,
                    schema_name=schema_name,
                    schema=schema,
                    system=system,
                    input_value=input_value,
                    temperature=temperature,
                )
                choices = payload.get("choices") or []
                content = choices[0].get("message", {}).get("content") if choices else None
                text = _response_text(content)
                if not text:
                    raise RuntimeError(
                        "{} returned no structured content for {}.".format(self.label, stage)
                    )
                value = json.loads(text)
                trace.append(
                    {
                        "stage": stage,
                        "request_model": model,
                        "response_model": payload.get("model", model),
                        "response_id": payload.get("id"),
                        "usage": payload.get("usage"),
                        "provider": self.provider,
                        "endpoint": self.endpoint,
                    }
                )
                return value
            except PermanentOpenRouterError:
                raise
            except (HTTPError, URLError, TimeoutError, ConnectionError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(2 * (2 ** (attempt - 1)))
        raise RuntimeError("{} request failed for {}: {}".format(self.label, stage, last_error))

    def _request(
        self,
        *,
        model,
        schema_name,
        schema,
        system,
        input_value,
        temperature,
    ):
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(input_value, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if self.provider == "openrouter":
            body["max_tokens"] = 5000
            body["provider"] = {"require_parameters": True}
        else:
            body["max_completion_tokens"] = 5000
        if temperature is not None:
            body["temperature"] = temperature

        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers["X-Title"] = "WorldLine Prompt Pipeline"
            if self.site_url:
                headers["HTTP-Referer"] = self.site_url

        request = Request(
            self.endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace").replace(self.api_key, "[REDACTED]")[:500]
            message = "{} {}: {}".format(self.label, exc.code, raw)
            if exc.code != 429 and exc.code < 500:
                raise PermanentOpenRouterError(message, status_code=exc.code) from exc
            raise RuntimeError(message) from exc


class PermanentOpenRouterError(RuntimeError):
    """A request error that should not be retried."""

    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code
