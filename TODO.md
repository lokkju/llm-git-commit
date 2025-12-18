# Features Contributed to llm-git-commit

This document tracks features contributed from git-llm-commit to [llm-git-commit](https://github.com/ShamanicArts/llm-git-commit).

## Implemented Features

### 1. Token Usage Display (`--usage`) ✅

Shows token consumption after message generation. Configurable via config or CLI.

```bash
# CLI usage
llm git-commit --usage
llm git-commit --no-usage

# Config (persists setting)
llm git-commit config --usage      # Enable by default
llm git-commit config --no-usage   # Disable by default
```

Output: `Token usage: 450 input, 35 output, 485 total`

---

### 2. Editor Configuration ✅

Three editor modes with clear semantics:

| Mode | Description |
|------|-------------|
| `internal` | Built-in prompt_toolkit editor (default) |
| `env` | Detect from environment variables |
| `<command>` | Specific editor command |

**Environment detection priority (for `env` mode):**
1. `$LLM_GIT_COMMIT_EDITOR`
2. `git config core.editor`
3. `$VISUAL`
4. `$EDITOR`

```bash
# CLI usage
llm git-commit -e              # Use env detection
llm git-commit -e vim          # Use specific editor
llm git-commit -e internal     # Use built-in editor

# Config (persists setting)
llm git-commit config --editor internal  # Built-in (default)
llm git-commit config --editor env       # Detect from environment
llm git-commit config --editor vim       # Specific command
```

---

### 3. Prompt Templates as Editable Files ✅

Prompts are stored as individual text files that users can edit or extend.

**Location:** `~/.config/llm-git-commit/prompts/`

**Built-in prompts:**
| File | Description |
|------|-------------|
| `conventional.txt` | Conventional Commits format (feat:, fix:, etc.) [Default] |
| `detailed.txt` | Detailed multi-paragraph messages with context |
| `minimal.txt` | Short single-line messages only |
| `semantic.txt` | Semantic commits with scope: type(scope): description |
| `gitmoji.txt` | Gitmoji-style with emoji prefixes |
| `custom.txt` | Editable template - edit this for your own prompt! |

```bash
# List available prompts
llm git-commit --list-prompts

# Use a specific prompt
llm git-commit --prompt-style gitmoji

# Set default prompt
llm git-commit config --prompt detailed

# Use custom prompt (edit prompts/custom.txt first!)
llm git-commit config --prompt custom

# Create your own prompt
# 1. Create ~/.config/llm-git-commit/prompts/myproject.txt
# 2. llm git-commit config --prompt myproject
```

---

### 4. Enhanced Config Command ✅

The config command shows all settings and supports all options.

```bash
# View current configuration (default)
llm git-commit config

# Show the full prompt text
llm git-commit config --show-prompt

# Set options
llm git-commit config --model gpt-4-turbo
llm git-commit config --prompt detailed
llm git-commit config --editor env
llm git-commit config --usage
llm git-commit config --max-chars 20000

# Reset to defaults
llm git-commit config --reset
```

**Sample output:**
```
llm-git-commit configuration

Config file:    ~/.config/llm-git-commit/config.json
Prompts dir:    ~/.config/llm-git-commit/prompts/

Model:          gpt-4o
Prompt:         conventional - Conventional Commits format (feat:, fix:, etc.) [Default]
Prompt file:    ~/.config/llm-git-commit/prompts/conventional.txt
Editor:         internal (built-in prompt_toolkit)
Env editor:     vim
Max chars:      15000
Show usage:     True

Use --show-prompt to see the full prompt text.
Edit prompt files directly in: ~/.config/llm-git-commit/prompts/
```

---

## Config File Format

**Location:** `~/.config/llm-git-commit/config.json`

```json
{
  "model": "gpt-4o",
  "prompt": "conventional",
  "editor": "internal",
  "usage": false,
  "max-chars": 15000
}
```

| Key | Values | Default |
|-----|--------|---------|
| `model` | Any llm model ID | (llm default) |
| `prompt` | Prompt file name (without .txt) | `conventional` |
| `editor` | `internal`, `env`, or command | `internal` |
| `usage` | `true` / `false` | `false` |
| `max-chars` | Integer | `15000` |

---

## Features Already Present in llm-git-commit

These features existed in the original project:

- **Model selection** (`-m/--model`) - Specify LLM model
- **Custom prompt** (`-s/--system`) - Override system prompt inline
- **Interactive editing** - Built-in prompt_toolkit editor with Ctrl+I for chat refinement
- **Character limit** (`--max-chars`) - Limit diff size sent to LLM
- **Tracked files** (`--tracked`) - Include tracked but unstaged files
- **Auto-confirm** (`-y/--yes`) - Skip confirmation prompt

---

## Summary of New CLI Options

```
llm git-commit [OPTIONS]

New options:
  --usage / --no-usage   Show token usage after generation
  -e, --editor [CMD]     Use external editor (env detection or specific command)
  -p, --prompt-style ID  Use a prompt style from prompts directory
  --list-prompts         List available prompt styles

Config command options:
  llm git-commit config [--view]
  llm git-commit config --show-prompt
  llm git-commit config --model MODEL
  llm git-commit config --prompt STYLE
  llm git-commit config --editor internal|env|COMMAND
  llm git-commit config --usage / --no-usage
  llm git-commit config --max-chars N
  llm git-commit config --reset

Environment variables:
  LLM_GIT_COMMIT_EDITOR  Editor for 'env' mode (highest priority)
```

---

## Contributing to Upstream

To contribute these changes to the upstream llm-git-commit:

1. Fork https://github.com/ShamanicArts/llm-git-commit
2. Create feature branches for each PR
3. Submit PRs incrementally:
   - PR 1: `--usage` flag with config support
   - PR 2: Prompt templates as editable files
   - PR 3: Editor modes (internal/env/command)
   - PR 4: Enhanced config command
