#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Tyrano TextPort
# Created with assistance from Gemini 3.8 Flash in Antigravity.
# Offline text extractor / importer for TyranoScript games
# License: MIT
"""
Tyrano TextPort —— Offline text extractor and importer for TyranoScript games.

Key capabilities:
  * Zero external dependencies (pure Python standard library).
  * Supports standalone directory games (loose files: data/scenario/*.ks).
  * Supports packaged games with embedded zip in NW.js executables (e.g. Game.exe).
  * Supports standalone NW.js packages (package.nw).
  * Supports Electron packaged games (resources/app.asar or app.asar).
  * Extracts dialogue, speaker names, choices, UI labels, window titles, and system messages.
  * Preserves exact script tags, macros, JS scripts, condition expressions, and indentation.
  * Exports to flat JSON ({"original": ""}), split JSON batches (--split N), Markdown table, or detailed JSON.
  * Imports from JSON, split folder, or Markdown table with automatic timestamped backup and --dry-run preview.
  * Includes an unpack command to extract all files from packed executables/archives.

Usage:
    python tyrano_textport.py info   "D:\\Games\\MyTyranoGame"
    python tyrano_textport.py export "D:\\Games\\MyTyranoGame" -o strings.json
    python tyrano_textport.py export "D:\\Games\\MyTyranoGame" -o out\\ --split 200
    python tyrano_textport.py export "D:\\Games\\MyTyranoGame" -o strings.md --format md
    python tyrano_textport.py import "D:\\Games\\MyTyranoGame" strings.json --dry-run
    python tyrano_textport.py import "D:\\Games\\MyTyranoGame" strings.json
    python tyrano_textport.py import "D:\\Games\\MyTyranoGame" out\\
    python tyrano_textport.py unpack "D:\\Games\\MyTyranoGame" -o unpacked\\
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import struct
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

TOOL_NAME = "Tyrano TextPort"
VERSION = "0.2.0"

# CJK detection for Japanese visual novel games
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")
NUMERIC_RE = re.compile(r"^[\s\d\W_]+$", re.UNICODE)

# TyranoScript tags that contain translatable display attributes
TRANSLATABLE_TAG_ATTRS: Dict[str, Tuple[str, ...]] = {
    "glink": ("text",),
    "ptext": ("text",),       # Layer text (skip if starting with '&' expression)
    "dialog": ("text",),      # System alert/confirm popup
    "title": ("name",),       # Game window title
    "button": ("text", "hint"),
    "chara_new": ("jname",),  # Character Japanese display name
    "chara_ptext": ("name",), # Character name display
    "ruby": ("text",),        # Reading annotation text
    "glyph": ("text",),
}


def setup_console() -> None:
    """Ensure standard output and error support UTF-8 on Windows terminals."""
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def is_translatable(val: object, allow_all: bool = False, min_len: int = 1) -> bool:
    """Check whether a string should be extracted for translation."""
    if not isinstance(val, str):
        return False
    text = val.strip()
    if len(text) < min_len:
        return False
    # In TyranoScript, values starting with '&' or '&f.' are dynamic JS expressions
    if text.startswith("&"):
        return False
    # Exclude strings that are purely numbers or punctuation symbols
    if NUMERIC_RE.match(text):
        return False
    if allow_all:
        return True
    return bool(JAPANESE_RE.search(text))


# ==============================================================================
# Electron ASAR Archive Handler
# ==============================================================================

class AsarArchive:
    """Pure-Python implementation of Electron ASAR archive reading, extraction, and repacking."""

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        with open(self.path, "rb") as f:
            u1, u2, u3, u4 = struct.unpack("<IIII", f.read(16))
            self.header = json.loads(f.read(u4).decode("utf-8"))
            self.data_base = 8 + u2

        self.files: Dict[str, Tuple[int, int]] = {}
        self._collect_files(self.header, "")

    def _collect_files(self, node: dict, prefix: str) -> None:
        for name, info in node.get("files", {}).items():
            path = f"{prefix}/{name}" if prefix else name
            if "files" in info:
                self._collect_files(info, path)
            else:
                self.files[path] = (int(info.get("offset", 0)), int(info.get("size", 0)))

    def list_files(self) -> List[str]:
        return list(self.files.keys())

    def read_file(self, rel_path: str) -> bytes:
        norm = rel_path.replace("\\", "/")
        if norm not in self.files:
            raise KeyError(f"File not found in ASAR: {rel_path}")
        offset, size = self.files[norm]
        with open(self.path, "rb") as f:
            f.seek(self.data_base + offset)
            return f.read(size)

    def extract_all(self, out_dir: Path, progress_callback=None) -> None:
        out_dir = Path(out_dir).resolve()
        total = len(self.files)
        with open(self.path, "rb") as src_f:
            for idx, (rel_path, (offset, size)) in enumerate(self.files.items(), 1):
                dest = out_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                src_f.seek(self.data_base + offset)
                with open(dest, "wb") as dst_f:
                    rem = size
                    while rem > 0:
                        chunk = src_f.read(min(rem, 1024 * 1024))
                        if not chunk:
                            break
                        dst_f.write(chunk)
                        rem -= len(chunk)
                if progress_callback:
                    progress_callback(idx, total)

    def repack(self, out_path: Path, modified_files: Dict[str, bytes]) -> None:
        out_path = Path(out_path).resolve()
        new_header = json.loads(json.dumps(self.header))
        file_order: List[Tuple[str, tuple]] = []

        def plan_offsets(node: dict, prefix: str, current_offset: int) -> int:
            for name, info in node.get("files", {}).items():
                path = f"{prefix}/{name}" if prefix else name
                if "files" in info:
                    current_offset = plan_offsets(info, path, current_offset)
                else:
                    if path in modified_files:
                        new_size = len(modified_files[path])
                        data_src = ("modified", modified_files[path])
                    else:
                        orig_offset, orig_size = self.files[path]
                        new_size = orig_size
                        data_src = ("original", orig_offset, orig_size)

                    info["size"] = new_size
                    info["offset"] = str(current_offset)
                    file_order.append((path, data_src))
                    current_offset += new_size
            return current_offset

        plan_offsets(new_header, "", 0)

        json_bytes = json.dumps(new_header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        json_len = len(json_bytes)
        padding_len = (4 - (json_len % 4)) % 4
        padded_json_len = json_len + padding_len

        u1 = 4
        u4 = json_len
        u3 = padded_json_len + 4
        u2 = u3 + 4
        header_bytes = struct.pack("<IIII", u1, u2, u3, u4) + json_bytes + (b"\x00" * padding_len)

        with open(out_path, "wb") as out_f:
            out_f.write(header_bytes)
            with open(self.path, "rb") as src_f:
                for path, data_src in file_order:
                    if data_src[0] == "modified":
                        out_f.write(data_src[1])
                    else:
                        src_f.seek(self.data_base + data_src[1])
                        rem = data_src[2]
                        while rem > 0:
                            chunk = src_f.read(min(rem, 1024 * 1024))
                            if not chunk:
                                break
                            out_f.write(chunk)
                            rem -= len(chunk)


# ==============================================================================
# Game Target Resolution
# ==============================================================================

@dataclass
class GameTarget:
    mode: str          # "embedded_exe", "standalone_nw", "electron_asar", or "loose_dir"
    base_dir: Path     # Folder containing the game (used for backups)
    main_path: Path    # The .exe file, package.nw, app.asar, or project directory


def resolve_game(path_str: str) -> GameTarget:
    """Automatically detects game packaging and returns a GameTarget."""
    p = Path(path_str).expanduser().resolve()
    if not p.exists():
        sys.exit(f"[x] 路径不存在: {p}")

    # 1. Direct file passed
    if p.is_file():
        suffix = p.suffix.lower()
        if suffix == ".asar":
            base = p.parent.parent if p.parent.name.lower() == "resources" else p.parent
            return GameTarget("electron_asar", base, p)
        if suffix == ".nw":
            return GameTarget("standalone_nw", p.parent, p)
        if suffix == ".exe":
            try:
                with zipfile.ZipFile(p, "r") as z:
                    names = z.namelist()
                    if any("scenario" in n or "tyrano" in n or n == "index.html" for n in names):
                        return GameTarget("embedded_exe", p.parent, p)
            except Exception:
                pass
            # Check if this exe is in an Electron folder with resources/app.asar
            cand_asar = p.parent / "resources" / "app.asar"
            if cand_asar.exists():
                return GameTarget("electron_asar", p.parent, cand_asar)
            sys.exit(f"[x] 可执行文件不是有效的 TyranoScript/NW.js 数据包: {p.name}")
        sys.exit(f"[x] 不支持的文件类型: {p.name} (仅支持 .exe、.nw、.asar 或游戏目录)")

    # 2. Directory passed: look for Electron resources/app.asar or app.asar
    if (p / "resources" / "app.asar").exists():
        return GameTarget("electron_asar", p, p / "resources" / "app.asar")
    if (p / "app.asar").exists():
        return GameTarget("electron_asar", p, p / "app.asar")

    # 3. Check for unpacked Electron resources/app
    if (p / "resources" / "app").exists() and ((p / "resources" / "app" / "data" / "scenario").exists() or (p / "resources" / "app" / "tyrano").exists()):
        return GameTarget("loose_dir", p, p / "resources" / "app")

    # 4. Look for NW.js package.nw
    if (p / "package.nw").exists():
        return GameTarget("standalone_nw", p, p / "package.nw")

    # 5. Check for loose directory
    if (p / "data" / "scenario").exists() or (p / "tyrano").exists():
        return GameTarget("loose_dir", p, p)

    # 6. Check for NW.js embedded executables in directory
    exes = list(p.glob("*.exe"))
    for exe in exes:
        try:
            with zipfile.ZipFile(exe, "r") as z:
                names = z.namelist()
                if any("scenario" in n or "tyrano" in n or n == "index.html" for n in names):
                    return GameTarget("embedded_exe", p, exe)
        except Exception:
            continue

    sys.exit(f"[x] 无法在目录中找到 TyranoScript 剧本数据或可执行文件: {p}")


# ==============================================================================
# TyranoScript (.ks) Tokenizer & Parser
# ==============================================================================

def tokenize_line(line: str) -> List[Tuple[str, str]]:
    """
    Splits a single line of a .ks file outside of script blocks into tokens.
    Token types:
      - 'comment': ;...
      - 'label':   *label or *label|title
      - 'speaker': #name or #name:face
      - 'command': @tag ...
      - 'tag':     [...]
      - 'text':    dialogue/narrative characters outside tags
    """
    s = line.strip()
    if not s:
        return [("text", line)]

    # Line comment
    if s.startswith(";"):
        return [("comment", line)]

    # At-command line (@tag ...)
    if s.startswith("@"):
        return [("command", line)]

    # Label line (*label ...)
    if s.startswith("*"):
        return [("label", line)]

    # Speaker line (#name ...)
    if s.startswith("#"):
        return [("speaker", line)]

    tokens: List[Tuple[str, str]] = []
    i = 0
    n = len(line)
    text_buf: List[str] = []

    while i < n:
        if line[i] == "[":
            if text_buf:
                tokens.append(("text", "".join(text_buf)))
                text_buf = []

            # Find matching ']' with bracket nesting support
            j = i + 1
            nest = 1
            while j < n and nest > 0:
                if line[j] == "[":
                    nest += 1
                elif line[j] == "]":
                    nest -= 1
                j += 1

            tag_str = line[i:j]
            tokens.append(("tag", tag_str))
            i = j
        else:
            text_buf.append(line[i])
            i += 1

    if text_buf:
        tokens.append(("text", "".join(text_buf)))

    return tokens


def extract_from_ks_text(
    content: str,
    allow_all: bool = False,
    min_len: int = 1,
    file_path: str = ""
) -> List[Tuple[str, int, str]]:
    """
    Extracts translatable strings from .ks content.
    Returns list of (string_val, line_num, string_type).
    """
    results: List[Tuple[str, int, str]] = []
    in_script = False
    in_comment_block = False

    lines = content.splitlines()
    for idx, raw in enumerate(lines, start=1):
        s = raw.strip()
        if not s:
            continue

        # Handle multi-line block comments /* ... */
        if in_comment_block:
            if "*/" in s:
                in_comment_block = False
            continue
        if "/*" in s and not s.startswith(";"):
            in_comment_block = True
            if "*/" in s:
                in_comment_block = False
            continue

        # Handle JavaScript blocks [iscript] ... [endscript]
        if in_script:
            if "[endscript]" in s or s.startswith("@endscript") or "endscript" in s:
                in_script = False
            continue
        if "[iscript]" in s or s.startswith("@iscript"):
            in_script = True
            continue

        tokens = tokenize_line(raw)
        for tok_type, tok_val in tokens:
            if tok_type == "text":
                val = tok_val.strip()
                if is_translatable(val, allow_all, min_len):
                    results.append((val, idx, "dialogue"))

            elif tok_type == "speaker":
                clean = tok_val.strip()
                if clean.startswith("#"):
                    name = clean[1:].strip().split(":")[0].strip()
                    if is_translatable(name, allow_all, min_len):
                        results.append((name, idx, "speaker"))

            elif tok_type == "label":
                clean = tok_val.strip()
                if "|" in clean:
                    title = clean.split("|", 1)[1].strip()
                    if is_translatable(title, allow_all, min_len):
                        results.append((title, idx, "label_title"))

            elif tok_type in ("tag", "command"):
                body = tok_val
                if tok_type == "tag" and body.startswith("[") and body.endswith("]"):
                    body = body[1:-1]
                elif tok_type == "command" and body.startswith("@"):
                    body = body[1:]

                parts = body.split(None, 1)
                if not parts:
                    continue
                tag_name = parts[0]
                attrs_str = parts[1] if len(parts) > 1 else ""

                if tag_name in TRANSLATABLE_TAG_ATTRS:
                    target_attrs = TRANSLATABLE_TAG_ATTRS[tag_name]
                    for attr in target_attrs:
                        m_attr = re.search(
                            r"\b" + attr + r"\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\]]+))",
                            attrs_str
                        )
                        if m_attr:
                            val = m_attr.group(1) or m_attr.group(2) or m_attr.group(3)
                            if is_translatable(val, allow_all, min_len):
                                results.append((val, idx, f"{tag_name}.{attr}"))

    return results


def patch_tag_or_command(
    content: str,
    prefix: str,
    suffix: str,
    translations: Dict[str, str]
) -> Tuple[str, int]:
    """Replaces translatable attribute values within a tag or @command."""
    parts = content.split(None, 1)
    if not parts or parts[0] not in TRANSLATABLE_TAG_ATTRS or len(parts) == 1:
        return prefix + content + suffix, 0

    tag_name = parts[0]
    attrs_str = parts[1]
    count = 0
    target_attrs = TRANSLATABLE_TAG_ATTRS[tag_name]

    for attr in target_attrs:
        pattern = re.compile(r"(\b" + attr + r"\s*=\s*)(?:\"([^\"]*)\"|'([^']*)'|([^\s\]]+))")

        def repl(m: re.Match) -> str:
            nonlocal count
            attr_prefix = m.group(1)
            val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
            quote = '"' if m.group(2) is not None else ("'" if m.group(3) is not None else "")
            if val in translations and translations[val] != val:
                count += 1
                new_val = translations[val]
                if not quote and (" " in new_val or "\t" in new_val):
                    quote = '"'
                return f"{attr_prefix}{quote}{new_val}{quote}"
            return m.group(0)

        attrs_str = pattern.sub(repl, attrs_str)

    return f"{prefix}{tag_name} {attrs_str}{suffix}", count


def patch_ks_text(content: str, translations: Dict[str, str]) -> Tuple[str, int]:
    """
    Applies translations to a .ks file using token-level replacement.
    Leaves macro definitions, internal logic, coordinates, and scripts intact.
    """
    reconstructed_lines: List[str] = []
    in_script = False
    in_comment_block = False
    total_matches = 0

    for raw in content.splitlines(keepends=True):
        stripped = raw.strip()

        if in_comment_block:
            reconstructed_lines.append(raw)
            if "*/" in stripped:
                in_comment_block = False
            continue

        if "/*" in stripped and not stripped.startswith(";"):
            in_comment_block = True
            reconstructed_lines.append(raw)
            if "*/" in stripped:
                in_comment_block = False
            continue

        if in_script:
            reconstructed_lines.append(raw)
            if "[endscript]" in stripped or stripped.startswith("@endscript") or "endscript" in stripped:
                in_script = False
            continue

        if "[iscript]" in stripped or stripped.startswith("@iscript"):
            in_script = True
            reconstructed_lines.append(raw)
            continue

        # Extract line ending
        nl = ""
        if raw.endswith("\r\n"):
            line_body = raw[:-2]
            nl = "\r\n"
        elif raw.endswith("\n"):
            line_body = raw[:-1]
            nl = "\n"
        else:
            line_body = raw
            nl = ""

        tokens = tokenize_line(line_body)
        new_tokens: List[str] = []

        for tok_type, tok_val in tokens:
            if tok_type == "text":
                l_spaces = len(tok_val) - len(tok_val.lstrip())
                r_spaces = len(tok_val) - len(tok_val.rstrip())
                lead = tok_val[:l_spaces]
                trail = tok_val[len(tok_val) - r_spaces:] if r_spaces > 0 else ""
                clean_key = tok_val.strip()

                if clean_key in translations and translations[clean_key] != clean_key:
                    total_matches += 1
                    new_tokens.append(lead + translations[clean_key] + trail)
                else:
                    new_tokens.append(tok_val)

            elif tok_type == "speaker":
                clean = tok_val.strip()
                if clean.startswith("#"):
                    name_part = clean[1:]
                    face = ""
                    if ":" in name_part:
                        name, face_suffix = name_part.split(":", 1)
                        face = ":" + face_suffix
                    else:
                        name = name_part
                    if name in translations and translations[name] != name:
                        total_matches += 1
                        new_tokens.append(f"#{translations[name]}{face}")
                    else:
                        new_tokens.append(tok_val)
                else:
                    new_tokens.append(tok_val)

            elif tok_type == "label":
                clean = tok_val.strip()
                if clean.startswith("*") and "|" in clean:
                    label_id, title = clean[1:].split("|", 1)
                    if title in translations and translations[title] != title:
                        total_matches += 1
                        new_tokens.append(f"*{label_id}|{translations[title]}")
                    else:
                        new_tokens.append(tok_val)
                else:
                    new_tokens.append(tok_val)

            elif tok_type == "tag":
                inner = tok_val[1:-1]
                patched_tag, cnt = patch_tag_or_command(inner, "[", "]", translations)
                total_matches += cnt
                new_tokens.append(patched_tag)

            elif tok_type == "command":
                inner = tok_val[1:]
                patched_cmd, cnt = patch_tag_or_command(inner, "@", "", translations)
                total_matches += cnt
                new_tokens.append(patched_cmd)

            else:
                new_tokens.append(tok_val)

        reconstructed_lines.append("".join(new_tokens) + nl)

    return "".join(reconstructed_lines), total_matches


# ==============================================================================
# System Files Extraction & Patching
# ==============================================================================

def extract_from_system_files(
    get_file_content_fn,
    file_list: List[str],
    allow_all: bool = False,
    min_len: int = 1
) -> List[Tuple[str, str, str]]:
    """
    Extracts translatable text from system files:
      - tyrano/lang.js (built-in engine strings in 'word' section)
      - data/system/Config.tjs (;System.title=...)
      - package.json (window.title)
    Returns list of (text_val, file_name, type_label).
    """
    results: List[Tuple[str, str, str]] = []

    for fn in file_list:
        norm = fn.replace("\\", "/").lower()

        # 1. Config.tjs
        if norm.endswith("config.tjs"):
            try:
                content = get_file_content_fn(fn).decode("utf-8", errors="replace")
                m = re.search(r";System\.title\s*=\s*(.*)", content)
                if m:
                    val = m.group(1).strip()
                    if is_translatable(val, allow_all, min_len):
                        results.append((val, fn, "config.title"))
            except Exception:
                pass

        # 2. tyrano/lang.js
        elif norm.endswith("tyrano/lang.js") or norm.endswith("lang.js"):
            try:
                content = get_file_content_fn(fn).decode("utf-8", errors="replace")
                for m in re.finditer(
                    r'"(?:go_title|exit_game|not_saved|tag|not_exists|error|label|label_double|error_occurred)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
                    content
                ):
                    val = m.group(1).replace(r"\"", '"')
                    if is_translatable(val, allow_all, min_len):
                        results.append((val, fn, "lang.word"))
            except Exception:
                pass

        # 3. package.json
        elif norm.endswith("package.json") and not norm.startswith("node_modules/"):
            try:
                content = get_file_content_fn(fn).decode("utf-8", errors="replace")
                data = json.loads(content)
                if isinstance(data, dict) and "window" in data and isinstance(data["window"], dict):
                    title = data["window"].get("title")
                    if title and is_translatable(title, allow_all, min_len):
                        results.append((title, fn, "package.title"))
            except Exception:
                pass

    return results


def patch_config_tjs(text: str, translations: Dict[str, str]) -> Tuple[str, int]:
    count = 0
    def repl(m: re.Match) -> str:
        nonlocal count
        key = m.group(1)
        val = m.group(2).strip()
        if val in translations and translations[val] != val:
            count += 1
            return f";{key}={translations[val]}"
        return m.group(0)

    new_text = re.sub(r";(System\.title)\s*=\s*(.*)", repl, text)
    return new_text, count


def patch_tyrano_lang_js(text: str, translations: Dict[str, str]) -> Tuple[str, int]:
    count = 0
    def repl(m: re.Match) -> str:
        nonlocal count
        prefix = m.group(1)
        val = m.group(2).replace(r"\"", '"')
        suffix = m.group(3)
        if val in translations and translations[val] != val:
            count += 1
            escaped_val = translations[val].replace('"', r"\"")
            return f"{prefix}{escaped_val}{suffix}"
        return m.group(0)

    pattern = re.compile(
        r'("(?:go_title|exit_game|not_saved|tag|not_exists|error|label|label_double|error_occurred)"\s*:\s*")'
        r'([^"\\]*(?:\\.[^"\\]*)*)'
        r'(")'
    )
    new_text = pattern.sub(repl, text)
    return new_text, count


def patch_package_json(text: str, translations: Dict[str, str]) -> Tuple[str, int]:
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "window" in data and isinstance(data["window"], dict):
            orig_title = data["window"].get("title")
            if orig_title and orig_title in translations and translations[orig_title] != orig_title:
                data["window"]["title"] = translations[orig_title]
                return json.dumps(data, ensure_ascii=False, indent=2), 1
    except Exception:
        pass
    return text, 0


# ==============================================================================
# Translation Loader
# ==============================================================================

def load_translations_from_path(trans_path: Path) -> Dict[str, str]:
    """
    Reads user translation files with broad compatibility:
      * Flat JSON: {"original": "translation"}
      * Wrapped JSON: {"strings": {...}}
      * Item list: [{"original": "...", "translation": "..."}, ...]
      * Markdown table: | 原文 | 译文 |
      * Folder with multiple .json or .md files
    """
    res: Dict[str, str] = {}

    def parse_single_file(p: Path) -> None:
        ext = p.suffix.lower()
        if ext == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, dict):
                    if "strings" in data and isinstance(data["strings"], dict):
                        data = data["strings"]
                    for k, v in data.items():
                        if isinstance(v, str) and v.strip() and v != k:
                            res[k] = v
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            orig = item.get("original") or item.get("text")
                            trans = item.get("translation")
                            if orig and trans and trans.strip() and trans != orig:
                                res[orig] = trans
            except Exception as e:
                print(f"[!] 读取 JSON 文件失败 {p.name}: {e}")

        elif ext == ".md":
            content = p.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                s = line.strip()
                if s.startswith("|") and s.endswith("|"):
                    parts = [pt.strip() for pt in s[1:-1].split("|")]
                    if len(parts) >= 2 and parts[0] not in ("---", "原文", "Original", ":---", ":---:"):
                        orig = parts[0].replace(r"\|", "|").replace("<br>", "\n")
                        trans = parts[1].replace(r"\|", "|").replace("<br>", "\n")
                        if orig and trans and trans != orig:
                            res[orig] = trans

    if trans_path.is_file():
        parse_single_file(trans_path)
    elif trans_path.is_dir():
        for f in sorted(trans_path.glob("*.json")):
            parse_single_file(f)
        for f in sorted(trans_path.glob("*.md")):
            parse_single_file(f)

    return res


# ==============================================================================
# Subcommand: info
# ==============================================================================

def cmd_info(args: argparse.Namespace) -> None:
    target = resolve_game(args.game_path)
    print(f"[*] 引擎类型: TyranoScript (ティラノスクリプト)")
    print(f"[*] 目标模式: {target.mode}")
    print(f"[*] 主文件/目录路径: {target.main_path}")

    scenario_count = 0
    total_files = 0
    sample_scenarios: List[str] = []
    total_estimated_strings = 0

    if target.mode in ("embedded_exe", "standalone_nw"):
        with zipfile.ZipFile(target.main_path, "r") as z:
            names = z.namelist()
            total_files = len(names)
            scenarios = [n for n in names if n.endswith(".ks")]
            scenario_count = len(scenarios)
            sample_scenarios = scenarios[:5]

            seen: Set[str] = set()
            for sc in scenarios:
                try:
                    c = z.read(sc).decode("utf-8", errors="replace")
                    for s, _, _ in extract_from_ks_text(c):
                        seen.add(s)
                except Exception:
                    pass
            total_estimated_strings = len(seen)

    elif target.mode == "electron_asar":
        asar = AsarArchive(target.main_path)
        names = asar.list_files()
        total_files = len(names)
        scenarios = [n for n in names if n.endswith(".ks")]
        scenario_count = len(scenarios)
        sample_scenarios = scenarios[:5]

        seen = set()
        for sc in scenarios:
            try:
                c = asar.read_file(sc).decode("utf-8", errors="replace")
                for s, _, _ in extract_from_ks_text(c):
                    seen.add(s)
            except Exception:
                pass
        total_estimated_strings = len(seen)

    elif target.mode == "loose_dir":
        all_files = list(target.main_path.rglob("*"))
        total_files = len(all_files)
        scenarios = list(target.main_path.rglob("*.ks"))
        scenario_count = len(scenarios)
        sample_scenarios = [str(sc.relative_to(target.main_path)).replace("\\", "/") for sc in scenarios[:5]]

        seen = set()
        for sc in scenarios:
            try:
                c = sc.read_text(encoding="utf-8", errors="replace")
                for s, _, _ in extract_from_ks_text(c):
                    seen.add(s)
            except Exception:
                pass
        total_estimated_strings = len(seen)

    print(f"[+] 数据包文件总数: {total_files}")
    print(f"[+] 剧本文件 (.ks) 数量: {scenario_count}")
    if sample_scenarios:
        print(f"[*] 部分剧本示例: {', '.join(sample_scenarios)}")
    print(f"[+] 估算可翻译文本条数: {total_estimated_strings}")


# ==============================================================================
# Subcommand: export
# ==============================================================================

def cmd_export(args: argparse.Namespace) -> None:
    target = resolve_game(args.game_path)
    out_path = Path(args.output).expanduser().resolve()

    extracted_dict: Dict[str, str] = {}
    detailed_list: List[Dict[str, object]] = []
    occurrence_map: Dict[str, List[Dict[str, object]]] = {}

    def process_ks_file(rel_name: str, content: str) -> None:
        items = extract_from_ks_text(
            content,
            allow_all=args.all,
            min_len=args.min_len,
            file_path=rel_name
        )
        for s, line_num, stype in items:
            extracted_dict[s] = ""
            if s not in occurrence_map:
                occurrence_map[s] = []
            occurrence_map[s].append({
                "file": rel_name,
                "line": line_num,
                "type": stype
            })

    def process_system_text(s: str, rel_name: str, stype: str) -> None:
        extracted_dict[s] = ""
        if s not in occurrence_map:
            occurrence_map[s] = []
        occurrence_map[s].append({
            "file": rel_name,
            "type": stype
        })

    # Read from archive or directory
    if target.mode in ("embedded_exe", "standalone_nw"):
        with zipfile.ZipFile(target.main_path, "r") as z:
            names = z.namelist()
            if not args.no_scenarios:
                for n in names:
                    if n.endswith(".ks"):
                        try:
                            c = z.read(n).decode("utf-8", errors="replace")
                            process_ks_file(n, c)
                        except Exception as e:
                            print(f"[!] 读取剧本失败 {n}: {e}")

            if not args.no_system:
                sys_items = extract_from_system_files(
                    lambda name: z.read(name),
                    names,
                    allow_all=args.all,
                    min_len=args.min_len
                )
                for val, fn, stype in sys_items:
                    process_system_text(val, fn, stype)

    elif target.mode == "electron_asar":
        asar = AsarArchive(target.main_path)
        names = asar.list_files()
        if not args.no_scenarios:
            for n in names:
                if n.endswith(".ks"):
                    try:
                        c = asar.read_file(n).decode("utf-8", errors="replace")
                        process_ks_file(n, c)
                    except Exception as e:
                        print(f"[!] 读取剧本失败 {n}: {e}")

        if not args.no_system:
            sys_items = extract_from_system_files(
                lambda name: asar.read_file(name),
                names,
                allow_all=args.all,
                min_len=args.min_len
            )
            for val, fn, stype in sys_items:
                process_system_text(val, fn, stype)

    elif target.mode == "loose_dir":
        if not args.no_scenarios:
            for sc in target.main_path.rglob("*.ks"):
                rel = str(sc.relative_to(target.main_path)).replace("\\", "/")
                try:
                    c = sc.read_text(encoding="utf-8", errors="replace")
                    process_ks_file(rel, c)
                except Exception as e:
                    print(f"[!] 读取剧本失败 {rel}: {e}")

        if not args.no_system:
            all_rel_files = [
                str(p.relative_to(target.main_path)).replace("\\", "/")
                for p in target.main_path.rglob("*")
                if p.is_file()
            ]
            sys_items = extract_from_system_files(
                lambda name: (target.main_path / name).read_bytes(),
                all_rel_files,
                allow_all=args.all,
                min_len=args.min_len
            )
            for val, fn, stype in sys_items:
                process_system_text(val, fn, stype)

    total_keys = len(extracted_dict)
    print(f"[+] 提取完成！共计 {total_keys} 条不重复文本。")

    if total_keys == 0:
        print("[!] 未提取到任何符合条件的文本。")
        return

    # Output formatting
    if args.format == "detailed":
        for k in extracted_dict:
            detailed_list.append({
                "original": k,
                "translation": "",
                "occurrences": len(occurrence_map.get(k, [])),
                "locations": occurrence_map.get(k, [])
            })
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(detailed_list, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[+] 详细文本已保存至: {out_path}")
        return

    if args.format == "md":
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Tyrano TextPort Export",
            "",
            "| 原文 | 译文 |",
            "| --- | --- |"
        ]
        for k in extracted_dict:
            esc = k.replace("|", r"\|").replace("\n", "<br>")
            lines.append(f"| {esc} | |")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[+] Markdown 表格已保存至: {out_path}")
        return

    # Standard JSON format (with split support)
    if args.split and args.split > 0:
        out_dir = out_path if out_path.suffix == "" else out_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        keys = list(extracted_dict.keys())
        part_idx = 1
        for i in range(0, total_keys, args.split):
            chunk = {k: extracted_dict[k] for k in keys[i : i + args.split]}
            part_file = out_dir / f"strings_part{part_idx}.json"
            part_file.write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")
            part_idx += 1
        print(f"[+] 分卷导出完成，共生成 {part_idx - 1} 个分卷文件在: {out_dir}")
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(extracted_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[+] 翻译模板已保存至: {out_path}")


# ==============================================================================
# Subcommand: import
# ==============================================================================

def cmd_import(args: argparse.Namespace) -> None:
    target = resolve_game(args.game_path)
    trans_path = Path(args.translation_path).expanduser().resolve()
    if not trans_path.exists():
        sys.exit(f"[x] 翻译文件或目录不存在: {trans_path}")

    translations = load_translations_from_path(trans_path)
    if not translations:
        sys.exit(f"[x] 未能从 {trans_path} 中找到有效的翻译条目（需要非空且与原文不同的译文）。")

    print(f"[+] 已加载 {len(translations)} 条有效翻译。")

    if args.dry_run:
        print("[*] 正在执行试运行 (--dry-run)，不会修改任何游戏文件...")

    # Handle NW.js packed archives (.exe or package.nw)
    if target.mode in ("embedded_exe", "standalone_nw"):
        modified_files: Dict[str, bytes] = {}
        total_matches = 0

        with zipfile.ZipFile(target.main_path, "r") as z:
            first_info = z.infolist()[0] if z.infolist() else None
            zip_offset = first_info.header_offset if first_info else 0

            with open(target.main_path, "rb") as f_in:
                exe_prefix = f_in.read(zip_offset) if zip_offset > 0 else b""

            for info in z.infolist():
                fn = info.filename
                norm = fn.replace("\\", "/").lower()

                if norm.endswith(".ks"):
                    content = z.read(fn).decode("utf-8", errors="replace")
                    patched, cnt = patch_ks_text(content, translations)
                    if cnt > 0:
                        modified_files[fn] = patched.encode("utf-8")
                        total_matches += cnt
                elif norm.endswith("config.tjs"):
                    content = z.read(fn).decode("utf-8", errors="replace")
                    patched, cnt = patch_config_tjs(content, translations)
                    if cnt > 0:
                        modified_files[fn] = patched.encode("utf-8")
                        total_matches += cnt
                elif norm.endswith("tyrano/lang.js") or norm.endswith("lang.js"):
                    content = z.read(fn).decode("utf-8", errors="replace")
                    patched, cnt = patch_tyrano_lang_js(content, translations)
                    if cnt > 0:
                        modified_files[fn] = patched.encode("utf-8")
                        total_matches += cnt
                elif norm.endswith("package.json") and not norm.startswith("node_modules/"):
                    content = z.read(fn).decode("utf-8", errors="replace")
                    patched, cnt = patch_package_json(content, translations)
                    if cnt > 0:
                        modified_files[fn] = patched.encode("utf-8")
                        total_matches += cnt

        print(f"[+] 匹配并准备替换 {total_matches} 处文本，涉及 {len(modified_files)} 个剧本/配置文件。")

        if args.dry_run:
            print("[*] 试运行结束，未写入任何更改。")
            return

        if not modified_files:
            print("[!] 没有匹配到任何需要写入的文件。")
            return

        if not args.no_backup:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = target.base_dir / "_tyrano_textport_backup" / ts
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / target.main_path.name
            shutil.copy2(target.main_path, backup_path)
            print(f"[+] 原始文件已备份至: {backup_path}")

        temp_out = target.main_path.with_name(f"{target.main_path.name}.tmp_{int(time.time())}")
        try:
            with open(temp_out, "wb") as f_out:
                if exe_prefix:
                    f_out.write(exe_prefix)
                with zipfile.ZipFile(f_out, "a", compression=zipfile.ZIP_DEFLATED) as z_out:
                    with zipfile.ZipFile(target.main_path, "r") as z_in:
                        for info in z_in.infolist():
                            if info.filename in modified_files:
                                z_out.writestr(info, modified_files[info.filename])
                            else:
                                data = z_in.read(info.filename)
                                z_out.writestr(info, data)

            shutil.move(str(temp_out), str(target.main_path))
            print(f"[+] 导入成功！已将译文写回数据包: {target.main_path}")
        except Exception as e:
            if temp_out.exists():
                temp_out.unlink()
            sys.exit(f"[x] 重新打包失败: {e}")

    # Handle Electron ASAR archives
    elif target.mode == "electron_asar":
        asar = AsarArchive(target.main_path)
        modified_files_asar: Dict[str, bytes] = {}
        total_matches = 0

        for fn in asar.list_files():
            norm = fn.replace("\\", "/").lower()

            if norm.endswith(".ks"):
                content = asar.read_file(fn).decode("utf-8", errors="replace")
                patched, cnt = patch_ks_text(content, translations)
                if cnt > 0:
                    modified_files_asar[fn] = patched.encode("utf-8")
                    total_matches += cnt
            elif norm.endswith("config.tjs"):
                content = asar.read_file(fn).decode("utf-8", errors="replace")
                patched, cnt = patch_config_tjs(content, translations)
                if cnt > 0:
                    modified_files_asar[fn] = patched.encode("utf-8")
                    total_matches += cnt
            elif norm.endswith("tyrano/lang.js") or norm.endswith("lang.js"):
                content = asar.read_file(fn).decode("utf-8", errors="replace")
                patched, cnt = patch_tyrano_lang_js(content, translations)
                if cnt > 0:
                    modified_files_asar[fn] = patched.encode("utf-8")
                    total_matches += cnt
            elif norm.endswith("package.json") and not norm.startswith("node_modules/"):
                content = asar.read_file(fn).decode("utf-8", errors="replace")
                patched, cnt = patch_package_json(content, translations)
                if cnt > 0:
                    modified_files_asar[fn] = patched.encode("utf-8")
                    total_matches += cnt

        print(f"[+] 匹配并准备替换 {total_matches} 处文本，涉及 {len(modified_files_asar)} 个剧本/配置文件。")

        if args.dry_run:
            print("[*] 试运行结束，未写入任何更改。")
            return

        if not modified_files_asar:
            print("[!] 没有匹配到任何需要写入的文件。")
            return

        if not args.no_backup:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = target.base_dir / "_tyrano_textport_backup" / ts
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / target.main_path.name
            shutil.copy2(target.main_path, backup_path)
            print(f"[+] 原始 ASAR 文件已备份至: {backup_path}")

        temp_out = target.main_path.with_name(f"{target.main_path.name}.tmp_{int(time.time())}")
        try:
            asar.repack(temp_out, modified_files_asar)
            shutil.move(str(temp_out), str(target.main_path))
            print(f"[+] 导入成功！已将译文写回 ASAR 数据包: {target.main_path}")
        except Exception as e:
            if temp_out.exists():
                temp_out.unlink()
            sys.exit(f"[x] 重新打包 ASAR 失败: {e}")

    # Handle loose directory games
    elif target.mode == "loose_dir":
        modified_files_loose: Dict[Path, str] = {}
        total_matches = 0

        for sc in target.main_path.rglob("*.ks"):
            try:
                content = sc.read_text(encoding="utf-8", errors="replace")
                patched, cnt = patch_ks_text(content, translations)
                if cnt > 0:
                    modified_files_loose[sc] = patched
                    total_matches += cnt
            except Exception as e:
                print(f"[!] 读取剧本失败 {sc.name}: {e}")

        for f in target.main_path.rglob("*"):
            if not f.is_file():
                continue
            norm = str(f.relative_to(target.main_path)).replace("\\", "/").lower()
            if norm.endswith("config.tjs"):
                content = f.read_text(encoding="utf-8", errors="replace")
                patched, cnt = patch_config_tjs(content, translations)
                if cnt > 0:
                    modified_files_loose[f] = patched
                    total_matches += cnt
            elif norm.endswith("tyrano/lang.js") or norm.endswith("lang.js"):
                content = f.read_text(encoding="utf-8", errors="replace")
                patched, cnt = patch_tyrano_lang_js(content, translations)
                if cnt > 0:
                    modified_files_loose[f] = patched
                    total_matches += cnt
            elif norm.endswith("package.json") and not norm.startswith("node_modules/"):
                content = f.read_text(encoding="utf-8", errors="replace")
                patched, cnt = patch_package_json(content, translations)
                if cnt > 0:
                    modified_files_loose[f] = patched
                    total_matches += cnt

        print(f"[+] 匹配并准备替换 {total_matches} 处文本，涉及 {len(modified_files_loose)} 个文件。")

        if args.dry_run:
            print("[*] 试运行结束，未写入任何更改。")
            return

        if not modified_files_loose:
            print("[!] 没有匹配到任何需要写入的文件。")
            return

        if not args.no_backup:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = target.base_dir / "_tyrano_textport_backup" / ts
            for file_path in modified_files_loose:
                rel = file_path.relative_to(target.main_path)
                dest = backup_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest)
            print(f"[+] 被修改的原始文件已备份至: {backup_dir}")

        for file_path, content in modified_files_loose.items():
            file_path.write_text(content, encoding="utf-8")

        print(f"[+] 导入成功！已更新 {len(modified_files_loose)} 个游戏文件。")


# ==============================================================================
# Subcommand: unpack / extract-archive
# ==============================================================================

def cmd_unpack(args: argparse.Namespace) -> None:
    target = resolve_game(args.game_path)
    out_dir = Path(args.output).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if target.mode == "loose_dir":
        sys.exit(f"[!] 目标已经是解包的散装目录: {target.main_path}")

    print(f"[*] 正在解包数据包至: {out_dir}")

    if target.mode in ("embedded_exe", "standalone_nw"):
        with zipfile.ZipFile(target.main_path, "r") as z:
            total = len(z.infolist())
            for i, info in enumerate(z.infolist(), 1):
                z.extract(info, out_dir)
                if i % 100 == 0 or i == total:
                    print(f"\r[*] 进度: {i}/{total} ({i * 100 // total}%)", end="")
    elif target.mode == "electron_asar":
        asar = AsarArchive(target.main_path)
        asar.extract_all(
            out_dir,
            lambda i, total: print(f"\r[*] 进度: {i}/{total} ({i * 100 // total}%)", end="") if (i % 100 == 0 or i == total) else None
        )

    print()
    print(f"[+] 解包完成！游戏文件已提取至: {out_dir}")


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main() -> None:
    setup_console()
    parser = argparse.ArgumentParser(
        prog="tyrano_textport",
        description="Tyrano TextPort —— Offline text extractor and importer for TyranoScript games.",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {VERSION}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. info
    p_info = subparsers.add_parser("info", help="探测 TyranoScript 游戏包信息与可翻译文本数量")
    p_info.add_argument("game_path", help="游戏主目录、.exe 文件、package.nw 或 app.asar 路径")
    p_info.set_defaults(func=cmd_info)

    # 2. export
    p_export = subparsers.add_parser("export", help="提取游戏中的全部可翻译文本")
    p_export.add_argument("game_path", help="游戏主目录、.exe 文件、package.nw 或 app.asar 路径")
    p_export.add_argument("-o", "--output", default="strings.json", help="输出文件或目录 (默认: strings.json)")
    p_export.add_argument("--format", choices=["json", "md", "detailed"], default="json", help="输出格式: json, md, detailed (默认: json)")
    p_export.add_argument("--split", type=int, default=0, help="每卷最大文本条数 (0 表示不分卷)")
    p_export.add_argument("--all", action="store_true", help="提取所有文本 (默认仅提取日文/汉字)")
    p_export.add_argument("--min-len", type=int, default=1, help="提取的最小字符串长度 (默认: 1)")
    p_export.add_argument("--no-scenarios", action="store_true", help="跳过 .ks 剧本文件提取")
    p_export.add_argument("--no-system", action="store_true", help="跳过系统语言及配置文件 (lang.js, Config.tjs)")
    p_export.set_defaults(func=cmd_export)

    # 3. import
    p_import = subparsers.add_parser("import", help="将翻译好的文本导入回游戏")
    p_import.add_argument("game_path", help="游戏主目录、.exe 文件、package.nw 或 app.asar 路径")
    p_import.add_argument("translation_path", help="翻译后的 JSON、MD 文件或分卷目录")
    p_import.add_argument("--dry-run", action="store_true", help="仅预览替换数量，不实际修改游戏文件")
    p_import.add_argument("--no-backup", action="store_true", help="不创建自动备份 (不推荐)")
    p_import.set_defaults(func=cmd_import)

    # 4. unpack / extract-archive
    p_unpack = subparsers.add_parser("unpack", aliases=["extract-archive"], help="从内嵌 EXE、NW 或 ASAR 数据包中解包全部文件")
    p_unpack.add_argument("game_path", help="游戏主目录、.exe 文件、package.nw 或 app.asar 路径")
    p_unpack.add_argument("-o", "--output", required=True, help="解包目标输出目录")
    p_unpack.set_defaults(func=cmd_unpack)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
