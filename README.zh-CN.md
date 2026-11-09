# Tyrano TextPort — TyranoScript 游戏文本提取与导入工具

[English](README.md) | **简体中文**

**适用于 TyranoScript（ティラノスクリプト）引擎游戏的离线文本提取与导入工具。**

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)](#运行环境)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Tyrano TextPort **不注入**游戏进程、**不挂钩**运行时、也**不进行侵入式修改**。它直接解析并安全编辑 TyranoScript 的剧本脚本（`.ks`）、配置文件（`Config.tjs`）以及语言字典（`tyrano/lang.js`），支持散装目录项目与内嵌 NW.js 的打包可执行程序：

1. **export（导出）**: 扫描游戏并将对话、人物姓名、分支选项（`[glink]`）、图层文本（`[ptext]`）、窗口标题以及系统提示信息汇总为扁平 JSON（`{"原文": ""}`）、分卷 JSON 或 Markdown 表格。
2. **translate（翻译）**: 使用您偏好的方式翻译译文（大语言模型、CAT 翻译工具、机器翻译或人工编辑）。
3. **import（导入）**: 读取翻译文件并安全写回游戏数据，精确保留所有脚本宏、标签、JS 代码及缩进排版，并自动生成时间戳备份。

导入完成后重新启动游戏即可显示翻译后的文本。

> **独立项目说明：** Tyrano TextPort 是用于游戏本地化与翻译研究的独立工具，不包含任何游戏数据。请确保您拥有所翻译游戏的合法副本。
>
> **翻译其他引擎游戏？**
> - RPG Maker MV/MZ 游戏请参见同目录下的 `rpgm-textport-mv-mz`。
> - RPG Maker VX Ace 游戏请参见同目录下的 `rpgm-textport-vx-ace`。
> - Godot Engine 游戏请参见同目录下的 `godot-textport`。

---

## 核心特性

- **全面支持打包 EXE 与散装项目**:
  - Electron 打包游戏（`resources/app.asar` 或 `app.asar`）。
  - NW.js 单文件可执行程序（末尾附加 ZIP 数据的 `Game.exe`）。
  - 独立 NW 数据包（`package.nw`）。
  - 已解包的散装项目目录（`data/scenario/*.ks`）。
- **完善的 TyranoScript 语法解析**:
  - 准确提取 `.ks` 剧本中的对话与叙述文本。
  - 提取说话者名字（`#Speaker` 与 `【Speaker】`）。
  - 提取分支选项按钮（`[glink text="..."]` 与 `@glink`）。
  - 提取图层文本（`[ptext text="..."]`），自动忽略动态代码表达式（`&...`）。
  - 提取窗口标题（`[title name="..."]`、`Config.tjs` 与 `package.json`）。
  - 提取注音文本（`[ruby text="..."]`）。
  - 提取引擎内置系统字典（`tyrano/lang.js` 中的提示语）。
- **词元级（Token-Level）无损替换**:
  - 绝不破坏宏定义、判断条件（`cond="..."`、`exp="..."`）、跳转标签（`*label`）或音频/图像路径。
  - 100% 字节级无损回写机制。
- **零外部依赖**: 仅使用 Python 3.8+ 标准库，无需 `pip install` 任何额外库。
- **多种导出格式**:
  - 扁平 JSON（`{"原文": ""}`）：适合大语言模型批量翻译。
  - 分卷 JSON（`--split N`）：自动按批次拆分，适应模型上下文长度。
  - Markdown 表格（`--format md`）：适合表格化查看与人工校对。
  - 详细 JSON（`--format detailed`）：包含来源剧本文件、行号及出现频次。
- **默认安全保护**:
  - 支持 `--dry-run` 预览替换匹配数量，不修改任何游戏文件。
  - 写入前自动在 `_tyrano_textport_backup/` 创建时间戳备份。
  - 原子化安全写入机制，先写入临时文件校验后再替换原文件。
- **自带解包命令**: 提供 `unpack`（或 `extract-archive`）命令，可一键将打包的 EXE 或 `.nw` 解包为散装目录。

---

## 运行环境

- **Python 3.8+**（仅依赖标准库）。
- Windows、macOS 或 Linux。
- 对游戏目录具有读写权限。

已在 Windows、macOS 与 Linux 系统上针对多款 TyranoScript 视觉小说与 RPG 游戏（涵盖 NW.js 与 Electron 两种打包形式）完成实机测试。

---

## 快速上手

在包含 `tyrano_textport.py` 的目录下打开命令行终端：

### 1. 检查游戏识别状态 (`info`)

```bat
python tyrano_textport.py info "C:\Games\MyTyranoGame"
```

输出示例：
```text
[*] 引擎类型: TyranoScript (ティラノスクリプト)
[*] 目标模式: embedded_exe
[*] 主文件/目录路径: C:\Games\MyTyranoGame\Game.exe
[+] 数据包文件总数: 450
[+] 剧本文件 (.ks) 数量: 35
[+] 估算可翻译文本条数: 620
```

### 2. 导出待翻译文本 (`export`)

**导出为单个扁平 JSON 文件：**
```bat
python tyrano_textport.py export "C:\Games\MyTyranoGame" -o strings.json
```

**导出为 Markdown 格式表格：**
```bat
python tyrano_textport.py export "C:\Games\MyTyranoGame" -o strings.md --format md
```

**分卷导出（例如每卷 200 条，适合送入大语言模型）：**
```bat
python tyrano_textport.py export "C:\Games\MyTyranoGame" -o out\ --split 200
```

### 3. 翻译文本

在导出的 `strings.json` 中，仅需翻译**值（value）**，切勿修改**键（key）**：

```json
{
  "はじめから": "从头开始",
  "つづきから": "继续游戏",
  "【ヒロイン】": "【女主角】",
  "「こんにちは！ 今日も良い天気ですね」": "「你好！今天天气真好呢」"
}
```

> 提示：本仓库内的 `translation_prompt.txt` 提供了专为大语言模型定制的即用型提示词。

### 4. 导入翻译 (`import`)

**先进行安全试运行（仅预览匹配统计，不写入修改）：**
```bat
python tyrano_textport.py import "C:\Games\MyTyranoGame" strings.json --dry-run
```

**正式写入翻译：**
```bat
python tyrano_textport.py import "C:\Games\MyTyranoGame" strings.json
```

如果之前使用了 `--split` 分卷导出，直接传入分卷目录即可批量合并导入：
```bat
python tyrano_textport.py import "C:\Games\MyTyranoGame" out\
```

导入完成后，启动游戏可执行程序即可直接体验汉化/本地化效果。

---

## 命令行参数一览

### `info`
```bat
python tyrano_textport.py info <game_path>
```
探测并打印游戏目标模式、剧本文件列表、总文件数以及估算的可翻译条目数。

### `export`
```bat
python tyrano_textport.py export <game_path> [options]
```
- `-o, --output <path>`: 指定输出文件或目录（默认: `strings.json`）。
- `--format <json|md|detailed>`: 输出格式（默认: `json`）。
- `--split <N>`: 分卷大小，每卷最多 N 条。
- `--all`: 提取所有非空文本（默认仅提取含日文/汉字的条目）。
- `--min-len <N>`: 最小字符长度过滤（默认: 1）。
- `--no-scenarios`: 跳过 `.ks` 剧本文件的文本提取。
- `--no-system`: 跳过系统语言与配置文件（`lang.js`、`Config.tjs`）。

### `import`
```bat
python tyrano_textport.py import <game_path> <translation_path> [options]
```
- `--dry-run`: 仅预览匹配项与数量，不实际改动任何文件。
- `--no-backup`: 跳过自动备份（默认会自动在 `_tyrano_textport_backup/` 生成带时间戳的备份）。

### `unpack`（或 `extract-archive`）
```bat
python tyrano_textport.py unpack <game_path> -o <output_dir>
```
将打包的 EXE 或 `.nw` 数据包解压至指定目录，便于查看原始资源或进行散装开发调试。

---

## 制作人员

- **项目作者：** 本仓库所有者。
- **实现与文档协助：** Antigravity 中的 Gemini 3.8 Flash。

本仓库在 **Antigravity 中的 Gemini 3.8 Flash** 的帮助下完成。

