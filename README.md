# Tyrano TextPort — TyranoScript Game Text Extraction & Importing Tool

**English** | [简体中文](README.zh-CN.md)

**Offline text extractor / importer for TyranoScript (ティラノスクリプト) games.**

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Tyrano TextPort does **not** inject code into the game, hook the runtime, or modify executables invasively. It directly parses and safely edits TyranoScript scenario scripts (`.ks`), configuration files (`Config.tjs`), and language dictionaries (`tyrano/lang.js`), supporting both loose directory games and packed NW.js executables:

1. **export**: Scans the game and extracts all dialogue, character names, choices (`[glink]`), graphic text (`[ptext]`), window titles, and system messages into a flat JSON file (`{"original": ""}`), split JSON batches, or a Markdown table.
2. **translate**: Translate the values using your preferred method (LLM, CAT tools, machine translation, or manual editing).
3. **import**: Reads the translated file and writes it back into the game data safely, preserving all script tags, macros, JS code, and line indentation, with an automatic timestamped backup.

The game displays the translated text immediately upon restarting.

> **Independent project.** Tyrano TextPort is an independent tool for game localization and translation research. It does not include any game data. You must own the games you translate.
>
> **Translating other engine games?**
> - For RPG Maker MV/MZ, see `rpgm-textport-mv-mz`.
> - For RPG Maker VX Ace, see `rpgm-textport-vx-ace`.
> - For Godot Engine, see `godot-textport`.

---

## Key Features

- **Supports Packaged EXEs & Standalone Projects**:
  - Electron-packaged games (`resources/app.asar` or `app.asar`).
  - NW.js single-file executables (`Game.exe` with appended archive).
  - Standalone NW packages (`package.nw`).
  - Unpacked loose project directories (`data/scenario/*.ks`).
- **Comprehensive TyranoScript Parsing**:
  - Dialogue and narration text tokens in `.ks` scenarios.
  - Speaker names (`#Speaker` and `【Speaker】`).
  - Choice buttons (`[glink text="..."]` / `@glink`).
  - Text display layers (`[ptext text="..."]`), ignoring dynamic code expressions (`&...`).
  - Window titles (`[title name="..."]`, `Config.tjs`, `package.json`).
  - Ruby annotations (`[ruby text="..."]`).
  - Built-in engine messages (`tyrano/lang.js`).
- **Token-Level Lossless Replacement**:
  - Never breaks macros, condition expressions (`cond="..."`, `exp="..."`), jump labels (`*label`), or sound/image paths.
  - 100% roundtrip fidelity.
- **Zero External Dependencies**: Pure Python 3.8+ standard library only. No `pip install` needed.
- **Multiple Export Formats**:
  - Flat JSON (`{"original": ""}`): Optimized for LLM batch translation.
  - Split JSON (`--split N`): Automatically splits text into chunks for batch processing.
  - Markdown table (`--format md`): Formatted for visual inspection and tabular editing.
  - Detailed JSON (`--format detailed`): Includes file origins, line numbers, and occurrences.
- **Safe by Default**:
  - Supports `--dry-run` to preview replacements and matching statistics without writing changes.
  - Automatically creates timestamped backups in `_tyrano_textport_backup/`.
  - Atomic repacking with temporary file write and safety validation.
- **Archive Extraction**: Includes an `unpack` (or `extract-archive`) command to extract all files from packed executables or archives into a folder.

---

## Requirements

- **Python 3.8+** (uses only standard library modules).
- Windows, macOS, or Linux.
- Write permission to the game folder.

Tested on Windows, macOS, and Linux with Python 3.8+ across multiple TyranoScript visual novel and RPG games (supporting both NW.js and Electron packages).

---

## Quick Start

Open a terminal in the folder containing `tyrano_textport.py`:

### 1. Check Game Detection (`info`)

```bat
python tyrano_textport.py info "C:\Games\MyTyranoGame"
```

Expected output:
```text
[*] 引擎类型: TyranoScript (ティラノスクリプト)
[*] 目标模式: embedded_exe
[*] 主文件/目录路径: C:\Games\MyTyranoGame\Game.exe
[+] 数据包文件总数: 450
[+] 剧本文件 (.ks) 数量: 35
[+] 估算可翻译文本条数: 620
```

### 2. Export Text (`export`)

**Export to a single JSON file:**
```bat
python tyrano_textport.py export "C:\Games\MyTyranoGame" -o strings.json
```

**Export to a Markdown table:**
```bat
python tyrano_textport.py export "C:\Games\MyTyranoGame" -o strings.md --format md
```

**Split into batches (e.g., 200 entries per file for LLMs):**
```bat
python tyrano_textport.py export "C:\Games\MyTyranoGame" -o out\ --split 200
```

### 3. Translate the Text

In `strings.json`, translate only the **values**. Do not modify the keys:

```json
{
  "はじめから": "New Game",
  "つづきから": "Continue",
  "【ヒロイン】": "【Heroine】",
  "「こんにちは！ 今日も良い天気ですね」": "\"Hello! It's a nice day today, isn't it?\""
}
```

> Tip: `translation_prompt.txt` in this repository provides a ready-to-use LLM system prompt.

### 4. Import the Translations (`import`)

**Simulate the import first without writing changes:**
```bat
python tyrano_textport.py import "C:\Games\MyTyranoGame" strings.json --dry-run
```

**Apply the translations:**
```bat
python tyrano_textport.py import "C:\Games\MyTyranoGame" strings.json
```

If you used `--split`, point the command to the output directory:
```bat
python tyrano_textport.py import "C:\Games\MyTyranoGame" out\
```

After the import completes, run the game executable to verify the translations in-game.

---

## CLI Reference

### `info`
```bat
python tyrano_textport.py info <game_path>
```
Displays target detection mode, engine type, file count, scenario file list, and estimated translatable strings.

### `export`
```bat
python tyrano_textport.py export <game_path> [options]
```
- `-o, --output <path>`: Output file or folder (default: `strings.json`).
- `--format <json|md|detailed>`: Output format (default: `json`).
- `--split <N>`: Split text into parts with up to N entries per file.
- `--all`: Extract all non-empty strings (default extracts Japanese/CJK text).
- `--min-len <N>`: Minimum string length filter (default: 1).
- `--no-scenarios`: Skip `.ks` scenario files.
- `--no-system`: Skip system language and configuration files (`lang.js`, `Config.tjs`).

### `import`
```bat
python tyrano_textport.py import <game_path> <translation_path> [options]
```
- `--dry-run`: Preview matches and statistics without modifying game files.
- `--no-backup`: Skip creating an automatic backup in `_tyrano_textport_backup/`.

### `unpack` (or `extract-archive`)
```bat
python tyrano_textport.py unpack <game_path> -o <output_dir>
```
Extracts all files from packed executables or `.nw` archives into a local directory for inspection or loose editing.

---

## Credits

- **Project author:** the repository owner.
- **Implementation and documentation assistance:** Gemini 3.8 Flash in Antigravity.

This repository was prepared with the help of **Gemini 3.8 Flash in Antigravity**.

