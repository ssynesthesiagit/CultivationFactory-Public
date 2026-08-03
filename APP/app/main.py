from __future__ import annotations

import argparse
import json
import socket
import webbrowser
from pathlib import Path

import uvicorn

from app.api import create_app
from app.core import FoundryError, Settings
from product_bootstrap import ProductBootstrapService


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Tianxia Factory clean-root Linux/source product.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", "--data-root", dest="data_dir", type=Path)
    parser.add_argument("--open-browser", action="store_true", help="Open the local URL after bootstrap.")
    parser.add_argument("--bootstrap-report", type=Path, help="Optional path for the typed bootstrap report.")
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("Tianxia Factory binds only to 127.0.0.1")

    settings = Settings.from_env(data_dir=args.data_dir)
    try:
        bootstrap = ProductBootstrapService(settings).run()
    except FoundryError as exc:
        parser.exit(2, f"Bootstrap blocked [{exc.code}]: {exc.message}\n")
    if args.bootstrap_report:
        args.bootstrap_report.parent.mkdir(parents=True, exist_ok=True)
        args.bootstrap_report.write_text(json.dumps(bootstrap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    app = create_app(settings)
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"Tianxia Factory is ready at {url}", flush=True)
    print(f"Writable data root: {settings.data_dir}", flush=True)
    if args.open_browser:
        webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
