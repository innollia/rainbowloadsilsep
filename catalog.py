"""Pure file-system discovery for trusted, repository-managed Godot web exports.

No upload endpoint, no runtime unzip, and no custom server are necessary:
Streamlit serves each export through /app/static/games/<folder>/<entry>.html.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

GAMES_ROOT = Path(__file__).resolve().parent / "static" / "games"
HTML_SUFFIXES = {".html", ".htm"}
COVER_NAMES = ("cover.webp", "cover.png", "cover.jpg", "cover.jpeg", "thumbnail.png", "thumbnail.jpg", "icon.png")


@dataclass(frozen=True)
class Game:
    id: str
    title: str
    description: str
    genre: str
    tags: tuple[str, ...]
    entry: Path
    cover: Path | None
    height: int
    order: int
    folder: Path

    @property
    def url(self) -> str:
        return static_url(self.entry)

    @property
    def cover_url(self) -> str | None:
        return static_url(self.cover) if self.cover else None


def static_url(path: Path) -> str:
    """Construct a path without accidental slashes or URL-encoding bugs."""
    path = path.resolve()
    relative = path.relative_to(GAMES_ROOT.resolve())
    return "/app/static/games/" + "/".join(quote(part, safe="") for part in relative.parts)


def _safe_inside(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
        return candidate.is_file() and not candidate.is_symlink()
    except (OSError, ValueError):
        return False


def _pick_entry(folder: Path, manifest: dict) -> Path | None:
    if "entry" in manifest:
        entry = folder / str(manifest["entry"])
        return entry if entry.suffix.lower() in HTML_SUFFIXES and _safe_inside(folder, entry) else None

    # Prefer the export's root entry, but allow builds nested one level deeper.
    html_files = [
        file for file in folder.rglob("*")
        if file.suffix.lower() in HTML_SUFFIXES
        and _safe_inside(folder, file)
        and not any(part.startswith(".") for part in file.relative_to(folder).parts)
    ]
    if not html_files:
        return None

    def priority(file: Path) -> tuple[int, int, str]:
        relative = file.relative_to(folder)
        return (
            0 if relative.name.lower() == "index.html" and len(relative.parts) == 1 else
            1 if len(relative.parts) == 1 else
            2 if relative.name.lower() == "index.html" else 3,
            len(relative.parts),
            str(relative).casefold(),
        )

    return min(html_files, key=priority)


def _cover(folder: Path, manifest: dict) -> Path | None:
    cover_path = manifest.get("cover")
    if isinstance(cover_path, str) and cover_path.strip():
        file = folder / cover_path
        if _safe_inside(folder, file) and file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
            return file
    for filename in COVER_NAMES:
        file = folder / filename
        if _safe_inside(folder, file):
            return file
    return None


def discover_games(root: Path = GAMES_ROOT) -> list[Game]:
    """Every immediate child folder with an HTML entry becomes one game."""
    if not root.is_dir():
        return []
    found = []
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name.startswith(".") or folder.is_symlink():
            continue
        manifest = {}
        config_file = folder / "game.json"
        if _safe_inside(folder, config_file):
            try:
                raw = json.loads(config_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    manifest = raw
            except (OSError, ValueError, UnicodeError):
                pass  # Broken metadata must not hide an otherwise valid game.
        if manifest.get("hidden") is True:
            continue
        entry = _pick_entry(folder, manifest)
        if entry is None:
            continue
        tags = manifest.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        try:
            height = max(420, min(1200, int(manifest.get("height", 700))))
        except (ValueError, TypeError):
            height = 700
        try:
            order = int(manifest.get("order", 100))
        except (ValueError, TypeError):
            order = 100
        found.append(Game(
            id=folder.name,
            title=str(manifest.get("title") or folder.name.replace("-", " ").replace("_", " ")).strip()[:120],
            description=str(manifest.get("description") or "Godot / HTML 웹 게임").strip()[:500],
            genre=str(manifest.get("genre") or "웹 게임").strip()[:60],
            tags=tuple(str(tag)[:40] for tag in tags if isinstance(tag, str))[:8],
            entry=entry,
            cover=_cover(folder, manifest),
            height=height,
            order=order,
            folder=folder,
        ))
    return sorted(found, key=lambda game: (game.order, game.title.casefold(), game.id.casefold()))
