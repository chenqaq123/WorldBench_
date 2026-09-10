#!/usr/bin/env python3
"""Two tiny paid JSON-schema requests; no case, video, or evaluation generation."""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from generate_prompt import load_env_file
from worldline.artifacts import write_json
from worldline.openrouter import OpenRouterClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow the small paid connection test")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parent / ".env")
    parser.add_argument("--timeout", type=int, help="Override VAPI_TIMEOUT_SECONDS")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Connection testing uses paid model calls; pass --execute")
    load_env_file(args.env_file)
    timeout = args.timeout if args.timeout is not None else int(os.environ.get("VAPI_TIMEOUT_SECONDS", "240"))
    if timeout < 1:
        parser.error("--timeout must be positive")
    provider = os.environ.get("PROMPT_PROVIDER", "openrouter")
    if provider != "vapi":
        parser.error("This smoke test requires PROMPT_PROVIDER=vapi")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    client = OpenRouterClient(os.environ.get("VAPI_API_KEY", ""), provider="vapi",
                              base_url=os.environ.get("VAPI_BASE_URL"), timeout=timeout)
    models = [os.environ.get("VAPI_PROMPT_MODEL", "gpt-5.6-sol"),
              os.environ.get("VAPI_AUDIT_MODEL", "gpt-5.6-luna")]
    trace = []
    record = {"created_at": datetime.now(timezone.utc).isoformat(), "provider": "vapi",
              "endpoint": client.endpoint, "models": models, "timeout_seconds": timeout,
              "status": "running", "trace": trace,
              "results": [], "video_generation": False}
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    write_json(output / "result.json", record)
    try:
        for model in dict.fromkeys(models):
            result = client.complete(stage="connection_test", model=model, schema_name="connection_test",
                                     schema=schema, system='Return exactly {"ok":true}.',
                                     input_value={"purpose": "Verify structured JSON output only."},
                                     temperature=0, trace=trace)
            if result != {"ok": True}:
                raise ValueError("Unexpected structured output for " + model)
            record["results"].append({"model": model, "output": result})
            write_json(output / "result.json", record)
            print(model + ": structured output passed", flush=True)
        record["status"] = "passed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        raise
    finally:
        write_json(output / "result.json", record)


if __name__ == "__main__":
    main()
