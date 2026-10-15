"""Run today's menu collection manually: uv run python collect_menus.py."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from openai import OpenAI

import menu_pipeline as pipeline
from tavily_agent import save_menus

ROOT = Path(__file__).resolve().parent


@contextmanager
def collection_lock(path: Path):
    """Prevent overlapping command runs; the OS releases the lock after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A menu collection command is already running") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def already_saved(path: Path, restaurants: list[dict], target) -> bool:
    """Avoid paying for another run when today's full restaurant list is already saved."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data.get("requested_date") == target.isoformat()
                and bool(data.get("meals"))
                and {(m["restaurant"], m["address"]) for m in data["meals"]}
                == {(r["name"], r["address"]) for r in restaurants})
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def collect(root: Path, target, model: str, api_key: str, client, force=False) -> int:
    """Run the pipeline and save only a fully validated batch. Return a process exit code."""
    restaurants = pipeline.load_restaurants(root / "restaurants.json")
    output_path = root / "menus.json"
    with collection_lock(root / "data/runs/collection.lock"):
        if not force and already_saved(output_path, restaurants, target):
            print("Today's menus are already saved. Use --force to request a fresh collection.", flush=True)
            return 0
        print(f"Collecting {target.isoformat()} for {len(restaurants)} restaurants; model: {model}", flush=True)
        print("1/4 Searching with Tavily…", flush=True)
        searches = pipeline.search_restaurants(restaurants, target, api_key)
        print("2/4 Downloading HTML/PDF menus…", flush=True)
        retrieved = pipeline.retrieve_restaurants(searches, restaurants, target)
        diagnostics = root / "data/diagnostics/latest-run.json"
        previous = []
        if not force and diagnostics.exists():
            previous = json.loads(diagnostics.read_text(encoding="utf-8")).get("menu_results", [])
        print("3/4 Extracting and validating with OpenAI…", flush=True)
        records = pipeline.extract_menus(retrieved, restaurants, target, client, model, diagnostics,
                                         previous_results=previous, retry_failed_only=not force)
        for record in records:
            print(record["restaurant"]["name"], record["status"], len(record["meals"]), "meals", flush=True)
            if record.get("reason"):
                print(" ", record["reason"], flush=True)
        print("4/4 Saving verified menus…", flush=True)
        try:
            saved = save_menus(records, restaurants, target, output_path)
        except ValueError as error:
            print(str(error), file=sys.stderr, flush=True)
            print(f"Existing menus unchanged. Diagnostics: {diagnostics}", file=sys.stderr, flush=True)
            return 1
        print(f"Saved {len(saved['meals'])} meals to {output_path}. Refresh the app.", flush=True)
        return 0


def main(argv=None, root=ROOT) -> int:
    parser = argparse.ArgumentParser(description="Collect today's Bratislava lunch menus manually.")
    parser.add_argument("--check", action="store_true", help="Check configuration; no API calls or menu writes")
    parser.add_argument("--force", action="store_true", help="Repeat search and all extraction, even if today's menus exist")
    args = parser.parse_args(argv)
    load_dotenv(root / ".env", override=True)
    target = datetime.now(ZoneInfo("Europe/Bratislava")).date()
    model = os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    try:
        restaurants = pipeline.load_restaurants(root / "restaurants.json")
        missing = [key for key in ("TAVILY_API_KEY", "OPENAI_API_KEY") if not os.getenv(key)]
        if missing:
            raise ValueError("Add to .env: " + ", ".join(missing))
        if args.check:
            print(f"Configuration OK: {len(restaurants)} restaurants; date: {target}; model: {model}")
            print("Both API keys loaded. No API calls made.")
            return 0
        with OpenAI(max_retries=0, timeout=120) as client:
            return collect(root, target, model, os.environ["TAVILY_API_KEY"], client, force=args.force)
    except (OSError, ValueError) as error:
        print(f"Collection stopped: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        # Avoid echoing request payloads, credentials or provider internals into logs.
        print(f"Collection stopped ({type(error).__name__}). Existing menus unchanged. "
              "Inspect data/diagnostics/latest-run.json before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
