# Features Contributed to llm-git-commit

This document tracks features contributed from git-llm-commit to [llm-git-commit](https://github.com/ShamanicArts/llm-git-commit).

## Implemented Features

### 1. Token Usage Display (`--usage`) ✅

**Status:** Implemented

Shows token consumption after message generation.

```bash
llm git-commit --usage
# Output: Token usage: 450 input, 35 output, 485 total
```

### 2. Custom Editor Override (`-e/--editor`) ✅

**Status:** Implemented

Use external editor instead of built-in prompt_toolkit interface.

```bash
# Use external editor for this commit
llm git-commit -e

# Use specific editor
llm git-commit --editor vim

# Set default editor in config
llm git-commit config --editor code

# Disable external editor (use built-in)
llm git-commit config --editor none
```

**Environment variable priority:**
1. `LLM_GIT_COMMIT_EDITOR`
2. `git config core.editor`
3. `$VISUAL`
4. `$EDITOR`

### 3. Built-in Prompt Templates (`--prompt-style`) ✅

**Status:** Implemented

Select from pre-defined prompt styles.

```bash
# List available styles
llm git-commit --list-prompts

# Use a specific style
llm git-commit --prompt-style gitmoji

# Set default style in config
llm git-commit config --prompt-style detailed
```

**Available styles:**
- `conventional` - Conventional Commits format (feat:, fix:, etc.) [Default]
- `detailed` - Detailed multi-paragraph messages
- `minimal` - Short single-line messages
- `semantic` - Semantic commit messages with scope
- `gitmoji` - Gitmoji-style with emoji prefixes

### 4. Persistent Configuration ✅

**Status:** Implemented

Config stored in `~/.config/llm-git-commit/config.json`:

```json
{
  "model": "gpt-4o",
  "prompt_style": "conventional",
  "editor": "vim"
}
```

**CLI for configuration:**
```bash
# View current config
llm git-commit config

# Set options
llm git-commit config --model claude-3-5-sonnet
llm git-commit config --prompt-style detailed
llm git-commit config --editor code
```

---

## Features Already Present in llm-git-commit

These features existed in the original project:

- **Config command** (`llm git-commit config`) - View and set configuration
- **Model selection** (`-m/--model`) - Specify LLM model
- **Custom prompt** (`-s/--system-prompt`) - Override system prompt
- **Interactive editing** - Built-in prompt_toolkit editor with Ctrl+I for chat refinement
- **Character limit** (`--char-limit`) - Limit diff size sent to LLM
- **Tracked files** (`--tracked`) - Include tracked but unstaged files

---

## Summary of New CLI Options

```
llm git-commit [OPTIONS]

New options:
  --usage                  Show token usage after generation
  -e, --editor TEXT        Use external editor (overrides config)
  -p, --prompt-style TEXT  Use a built-in prompt style
  --list-prompts           List available built-in prompt styles

Config options:
  llm git-commit config --model MODEL
  llm git-commit config --prompt-style STYLE
  llm git-commit config --editor EDITOR

New environment variables:
  LLM_GIT_COMMIT_EDITOR    Override editor for message editing
```

---

## Contributing to Upstream

To contribute these changes to the upstream llm-git-commit:

1. Fork https://github.com/ShamanicArts/llm-git-commit
2. Create feature branches for each PR
3. Submit PRs incrementally:
   - PR 1: `--usage` flag
   - PR 2: Built-in prompt templates with `--prompt-style` and `--list-prompts`
   - PR 3: External editor support with `-e/--editor` and config option
