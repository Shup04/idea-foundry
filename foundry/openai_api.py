"""Bounded, text-only OpenAI transport. No SDK agents, tools or file access.

Only credentials come from the environment. Endpoints cannot be supplied by
model output or imported data. Usage is estimated from published token prices;
it is not an invoice. Uncertain calls keep their full budget reservation.
"""

import json
import math
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .validation import Invalid, _pairs, require

BASE_URL = "https://api.openai.com/v1/"
KEY_NAMES = ("OPENM_AI_API_KEY", "OPENAI_API_KEY")
# Standard prices checked 2026-09-24 at developers.openai.com/api/docs/pricing.
# Use the highest input/cache-write rate so a cache write cannot exceed the
# local reservation. Cached reads receive no assumed discount in this estimate.
MODELS = {"gpt-6-sol": (2.50, 10.00), "gpt-6-luna": (.125, .50),
          "gpt-5.4-mini": (.75, 4.50)}
DEFAULT_MODEL = "gpt-6-sol"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_RATE = .02
DIMENSIONS = 384
MAX_OUTPUT_TOKENS = 6000
MAX_REQUEST_BYTES = 60_000
MAX_RESPONSE_BYTES = 2_000_000


def key_name():
    return next((name for name in KEY_NAMES if os.environ.get(name, "").strip()), None)


def parse_json(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs,
                          parse_constant=lambda _: require(False, "Non-finite JSON value."))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise Invalid("OpenAI returned invalid JSON.") from exc


def request_bytes(body):
    raw = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    require(len(raw) <= MAX_REQUEST_BYTES, "This request is too large. Select fewer answers.")
    return raw


def reservation(endpoint, body):
    # UTF-8 byte count plus framing is a deliberately conservative token estimate,
    # including the schema. Fixed token/output limits also bound each request.
    tokens = len(request_bytes(body)) + 2048
    if endpoint == "embeddings":
        return round(tokens * EMBEDDING_RATE / 1_000_000, 8)
    input_rate, output_rate = MODELS[body["model"]]
    return round((tokens * input_rate + body["max_output_tokens"] * output_rate) / 1_000_000, 8)


def usage_cost(endpoint, model, response):
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None, None
    input_tokens = usage.get("prompt_tokens" if endpoint == "embeddings" else "input_tokens")
    output_tokens = 0 if endpoint == "embeddings" else usage.get("output_tokens")
    if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
        return None, None
    rates = (EMBEDDING_RATE, 0) if endpoint == "embeddings" else MODELS[model]
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}, round(
        (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000, 8)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenAI:
    """One HTTP call, no automatic retries or implicit model/provider fallbacks."""

    def post(self, endpoint, body):
        require(endpoint in ("responses", "embeddings"), "Unsupported OpenAI endpoint.")
        name = key_name()
        require(name is not None, "Set OPENM_AI_API_KEY or OPENAI_API_KEY before using AI understanding.")
        raw = request_bytes(body)
        request = Request(BASE_URL + endpoint, data=raw, method="POST", headers={
            "Authorization": "Bearer " + os.environ[name].strip(), "Content-Type": "application/json"})
        try:
            with build_opener(NoRedirect()).open(request, timeout=60) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
            require(len(content) <= MAX_RESPONSE_BYTES, "OpenAI response exceeded the size limit.")
            result = parse_json(content)
            require(isinstance(result, dict), "OpenAI returned an invalid response object.")
            return result
        except HTTPError as exc:
            # Never surface the provider's error body, headers, key or request text.
            code = exc.code
            exc.close()
            messages = {401: "OpenAI did not accept the API key.",
                        403: "This API key does not have permission for the selected model.",
                        404: "The selected OpenAI model is unavailable to this API account.",
                        429: "OpenAI rate or billing limit reached. Try again later.",
                        400: "OpenAI rejected the request. Check model and request compatibility."}
            raise Invalid(messages.get(code, f"OpenAI request failed (HTTP {code}). No automatic retry.")) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise Invalid("OpenAI could not be reached or timed out. Your answer is saved; the request was not retried.") from None


def structured_result(response):
    require(response.get("status") == "completed", "OpenAI did not finish the response. No suggestions were applied.")
    output = response.get("output")
    require(isinstance(output, list), "OpenAI response has no output.")
    texts = []
    for item in output:
        require(isinstance(item, dict), "Invalid OpenAI output item.")
        if item.get("type") == "reasoning":
            continue
        require(item.get("type") == "message" and item.get("role") == "assistant", "Unexpected OpenAI output type.")
        for part in item.get("content", []):
            require(isinstance(part, dict) and part.get("type") != "refusal", "OpenAI declined this request. No suggestions were applied.")
            require(part.get("type") == "output_text" and isinstance(part.get("text"), str), "Unexpected OpenAI content.")
            texts.append(part["text"])
    require(len(texts) == 1, "Expected one structured OpenAI reply.")
    return parse_json(texts[0])


def vectors(response, count):
    data = response.get("data")
    require(isinstance(data, list) and len(data) == count, "OpenAI returned the wrong number of embeddings.")
    result = {}
    for item in data:
        require(isinstance(item, dict) and type(item.get("index")) is int and 0 <= item["index"] < count,
                "Invalid embedding index.")
        index, vector = item["index"], item.get("embedding")
        require(index not in result and isinstance(vector, list) and len(vector) == DIMENSIONS,
                "Invalid embedding dimensions or duplicate index.")
        require(all(type(v) in (int, float) and math.isfinite(v) for v in vector), "Invalid embedding values.")
        norm = math.sqrt(sum(v * v for v in vector))
        require(math.isfinite(norm) and norm > 0, "Invalid embedding length.")
        result[index] = [v / norm for v in vector]
    return [result[i] for i in range(count)]
