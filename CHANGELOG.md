# Changelog

All notable changes to this project are documented in this file.

## 0.2.0 — 2026-11-08

- Added full support for **Electron**-packaged TyranoScript games (`resources/app.asar` or `app.asar`).
- Implemented pure Python standard library ASAR archive reading, unpack/extraction, and atomic repacking.
- Automatically detects Electron applications when passing the game folder, `.exe`, or `.asar` file.

## 0.1.0 — 2026-11-08

- Initial release of **Tyrano TextPort**.
- Supports games built with the **TyranoScript** (ティラノスクリプト) visual novel / RPG engine.
- Supports packaged games with embedded zip in NW.js executables (`Game.exe`), standalone NW packages (`package.nw`), and loose project directories (`data/scenario/*.ks`).
- Extracts dialogue, speaker names (`#Name` and `【Name】`), choice buttons (`[glink]`), graphic layer texts (`[ptext]`), window titles (`[title]`, `Config.tjs`, `package.json`), and system messages (`tyrano/lang.js`).
- Token-level replacement: preserves script macros, tags, condition expressions, JavaScript blocks, and indentation with 100% roundtrip fidelity.
- Supports exporting to flat JSON (`{"original": ""}`), split JSON batches (`--split N`), Markdown table (`--format md`), and detailed JSON with line contexts (`--format detailed`).
- Supports importing from JSON, split directory, or Markdown table.
- Automatic timestamped backups before writing.
- Safe `--dry-run` simulation mode.
- `unpack` (`extract-archive`) command to unpack all game files from NW.js executables or `.nw` archives.
- Zero external dependencies: pure Python 3.8+ standard library only.
