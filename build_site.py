"""Package the static app: uv run python build_site.py. Does not publish it."""
import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_FILES = ("index.html", "style.css", "app.js")


def build_site(root: Path = ROOT) -> Path:
    # Explicit files only: never recursively copy the project or web directory.
    sources = [(root / "web" / name, name) for name in WEB_FILES]
    sources.append((root / "menus.json", "menus.json"))
    for source, _ in sources:
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Expected a regular source file: {source}")
    data = json.loads((root / "menus.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("meals"), list) or not data["meals"]:
        raise ValueError("menus.json must contain a nonempty meals list")
    date.fromisoformat(data["requested_date"])

    output = root / "dist" / "site"
    if output.parent.is_symlink() or output.is_symlink():
        raise ValueError("Deployment output must not be a symbolic link")
    # Clean the dedicated generated directory so stale files cannot be published.
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for source, name in sources:
        shutil.copyfile(source, output / name)
    return output


if __name__ == "__main__":
    output = build_site()
    print(f"Deployment folder ready: {output}")
    for path in sorted(output.iterdir()):
        print(f"  {path.name}")
    print("No files published. Rebuild after collecting new menus or changing the app.")
