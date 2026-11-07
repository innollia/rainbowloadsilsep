import json
import mimetypes
from pathlib import Path

import catalog
from catalog import discover_games


def test_sample_game_is_discovered():
    games = discover_games()
    assert any(game.title == "CIRCUIT / 09" for game in games)
    assert games[0].url == "/app/static/games/demo-switchboard/index.html"
    assert games[0].cover_url == "/app/static/games/demo-switchboard/cover.svg"


def test_scan_multiple_exports_and_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "GAMES_ROOT", tmp_path)
    a = tmp_path / "테스트 게임"
    a.mkdir()
    (a / "MyGame.html").write_text("<html></html>", encoding="utf-8")
    (a / "MyGame.wasm").write_bytes(b"\0asm")
    (a / "MyGame.pck").write_bytes(b"pack")
    b = tmp_path / "tetris"
    (b / "release").mkdir(parents=True)
    (b / "release" / "index.html").write_text("<html></html>", encoding="utf-8")
    (b / "game.json").write_text(json.dumps({"title":"취향의 게임", "height":900,"order":2},ensure_ascii=False), encoding="utf-8")
    games = discover_games(tmp_path)
    assert len(games) == 2
    assert games[0].title == "취향의 게임"
    assert games[0].url == "/app/static/games/tetris/release/index.html"
    assert games[1].url == "/app/static/games/%ED%85%8C%EC%8A%A4%ED%8A%B8%20%EA%B2%8C%EC%9E%84/MyGame.html"
    assert games[1].entry.name == "MyGame.html"


def test_ignore_invalid_and_hidden(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "GAMES_ROOT", tmp_path)
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "index.html").write_text("ignored")
    (hidden / "game.json").write_text('{"hidden":true}')
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "README.md").write_text("not a web export")
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "index.html").write_text("valid")
    (invalid / "game.json").write_text("{invalid json")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.html").write_text("valid")
    (outside / "game.json").write_text('{"entry":"../../secrets.html"}')
    games = discover_games(tmp_path)
    assert [g.id for g in games] == ["invalid"]


def test_static_mime_types():
    assert mimetypes.guess_type("index.html")[0] == "text/html"
    assert "javascript" in mimetypes.guess_type("index.js")[0]
    assert mimetypes.guess_type("index.wasm")[0] == "application/wasm"
