"""Start the router service over a merged model on this machine.

The adapter revision reported by the API is read from the merged model's
`merge_provenance.json`, not passed in by hand: a response should be able to
prove which adapter produced it, and a hand-typed version string drifts from
the weights the moment someone forgets to update it.
"""

import argparse
import json
from pathlib import Path


def read_adapter_identity(model_path: Path, name: str | None) -> dict:
    """Derive the reported identity from the merged model's provenance."""
    provenance = model_path / "merge_provenance.json"
    if not provenance.exists():
        raise ValueError(f"{provenance} 不存在，无法确定 adapter 来源")

    record = json.loads(provenance.read_text(encoding="utf-8"))
    digest = record["adapter"]["file_hashes"]["adapter_model.safetensors"]

    return {"name": name or model_path.name, "revision": digest[:12]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, required=True, help="merged model dir")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model-name", default=None)
    args = parser.parse_args()

    import uvicorn

    from agent_toolcall_sft.serving.app import create_app
    from agent_toolcall_sft.serving.backend import LocalBackend

    adapter = read_adapter_identity(args.model, args.model_name)
    print(f"loading {args.model} on {args.device}", flush=True)
    app = create_app(LocalBackend(str(args.model), args.device), adapter=adapter)
    print(f"adapter_revision={adapter['revision']} model_version={adapter['name']}", flush=True)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
