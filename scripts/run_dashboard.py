"""Zone assistant dashboard: a local web UI over logs/agent.sqlite + the
editable watchlist. Run this alongside scripts/run_assistant.py.

  python scripts/run_dashboard.py              # http://127.0.0.1:8787
  python scripts/run_dashboard.py --port 9000
"""
import argparse

import _setup  # noqa: F401

from live.dashboard_server import serve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
