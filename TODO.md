# Features to Contribute to llm-git-commit

This project is being archived. The following features should be contributed to [llm-git-commit](https://github.com/ShamanicArts/llm-git-commit).

## 1. Token Usage Display (`--usage`)

Show token consumption after message generation.

### Implementation

Add a `--usage` flag that displays input/output token counts after LLM generation:

```python
@click.option("--usage", is_flag=True, help="Show token usage after generation")
```

After calling the LLM, extract usage from response:

```python
if show_usage and hasattr(response, 'usage'):
    click.echo(f"Token usage: {response.usage.input} input, {response.usage.output} output")
```

The `llm` library's `Response` object has a `.usage()` method that returns token counts when available.

---

## 2. Custom Editor Override

Allow users to specify a custom editor via environment variable.

### Implementation

Add environment variable support for editor selection:

```python
import os

def get_editor() -> str:
    """Get editor with priority: LLM_GIT_COMMIT_EDITOR > GIT_EDITOR > VISUAL > EDITOR > vi"""
    return (
        os.environ.get("LLM_GIT_COMMIT_EDITOR")
        or subprocess.run(["git", "config", "core.editor"], capture_output=True, text=True).stdout.strip()
        or os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or "vi"
    )
```

This allows users who prefer a different editor than the built-in prompt_toolkit interface to use their preferred tool.

---

## 3. Persistent File-Based Configuration

Store default settings in config files instead of requiring CLI flags every time.

### Implementation

Config directory: `~/.config/llm-git-commit/`

Files:
- `prompt.txt` - Custom system prompt (overrides default)
- `model.txt` - Default model ID
- `config.toml` - Other settings (char-limit, etc.)

```python
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "llm-git-commit"
PROMPT_FILE = CONFIG_DIR / "prompt.txt"
MODEL_FILE = CONFIG_DIR / "model.txt"

def get_system_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text().strip()
    return DEFAULT_PROMPT

def get_configured_model() -> str | None:
    if MODEL_FILE.exists():
        model = MODEL_FILE.read_text().strip()
        return model if model else None
    return None
```

CLI flags should override config files.

---

## 4. Setup Wizard (`llm git-commit-init`)

Interactive first-run configuration.

### Implementation

Add a subcommand or separate entry point:

```python
@cli.command()
def init():
    """Interactive setup wizard for llm-git-commit."""
    click.echo("Setting up llm-git-commit...")

    # Create config directory
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Model selection
    models = get_available_models()
    click.echo("\nAvailable models:")
    for i, model in enumerate(models, 1):
        click.echo(f"  {i}. {model}")

    choice = click.prompt("Select default model", type=int, default=1)
    MODEL_FILE.write_text(models[choice - 1])

    # Prompt selection (see feature #5)
    prompts = list_builtin_prompts()
    click.echo("\nAvailable prompt styles:")
    for pid, desc in prompts.items():
        click.echo(f"  {pid}: {desc}")

    prompt_choice = click.prompt("Select prompt style", default="conventional")
    # ... save selection

    click.echo("\nSetup complete!")
```

---

## 5. Multiple Built-in Prompt Templates

Allow selection from pre-defined prompt styles.

### Implementation

#### Built-in Prompts

```python
BUILTIN_PROMPTS = {
    "conventional": {
        "description": "Conventional Commits format (feat:, fix:, etc.)",
        "prompt": """You are an expert at writing git commit messages.
Analyze the provided git diff and write a commit message following Conventional Commits:
- Use type prefixes: feat, fix, docs, style, refactor, perf, test, build, ci, chore
- Subject line under 50 characters, imperative mood
- Optional body explaining what and why (not how)
- Only return the commit message, nothing else."""
    },

    "detailed": {
        "description": "Detailed multi-paragraph messages",
        "prompt": """You are an expert at writing git commit messages.
Analyze the provided git diff and write a detailed commit message:
- First line: concise summary under 50 characters
- Blank line
- Body: explain what changed and why in detail
- Use bullet points for multiple changes
- Only return the commit message, nothing else."""
    },

    "minimal": {
        "description": "Short single-line messages",
        "prompt": """Write a single-line git commit message under 50 characters.
Use imperative mood (Add, Fix, Update, Remove).
Only return the message, nothing else."""
    },

    "semantic": {
        "description": "Semantic commit messages with scope",
        "prompt": """Write a semantic commit message in the format: type(scope): description
Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore
Scope: affected component/module in parentheses
Description: imperative mood, under 50 chars total
Only return the commit message, nothing else."""
    },

    "gitmoji": {
        "description": "Gitmoji-style with emoji prefixes",
        "prompt": """Write a git commit message with a gitmoji prefix.
Common gitmojis: ✨ feat, 🐛 fix, 📝 docs, 💄 style, ♻️ refactor, ⚡ perf, ✅ test, 🔧 config
Format: <emoji> Short description
Only return the commit message, nothing else."""
    }
}

def list_builtin_prompts() -> dict[str, str]:
    """Return dict of prompt_id -> description."""
    return {k: v["description"] for k, v in BUILTIN_PROMPTS.items()}

def get_builtin_prompt(prompt_id: str) -> str:
    """Get prompt content by ID."""
    if prompt_id not in BUILTIN_PROMPTS:
        raise ValueError(f"Unknown prompt: {prompt_id}. Available: {list(BUILTIN_PROMPTS.keys())}")
    return BUILTIN_PROMPTS[prompt_id]["prompt"]
```

#### CLI Integration

```python
@click.option(
    "-p", "--prompt-style",
    type=click.Choice(list(BUILTIN_PROMPTS.keys())),
    help="Use a built-in prompt style"
)
@click.option(
    "--list-prompts",
    is_flag=True,
    help="List available built-in prompt styles"
)
def git_commit(prompt_style, list_prompts, ...):
    if list_prompts:
        click.echo("Available prompt styles:")
        for pid, desc in list_builtin_prompts().items():
            click.echo(f"  {pid:12} - {desc}")
        return

    # Priority: -s flag > --prompt-style > config file > default
    if system_prompt:
        prompt = system_prompt
    elif prompt_style:
        prompt = get_builtin_prompt(prompt_style)
    elif config_prompt_style:
        prompt = get_builtin_prompt(config_prompt_style)
    else:
        prompt = BUILTIN_PROMPTS["conventional"]["prompt"]
```

#### Config File Support

In `~/.config/llm-git-commit/config.toml`:

```toml
prompt_style = "conventional"
```

Or store the selected prompt ID in a simple file:
`~/.config/llm-git-commit/prompt_style.txt`

---

## 6. Config Status Command

Show current configuration state.

### Implementation

```python
@cli.command()
def config():
    """Show current configuration."""
    click.echo("llm-git-commit configuration:\n")

    # Config directory
    click.echo(f"Config directory: {CONFIG_DIR}")
    click.echo(f"  Exists: {CONFIG_DIR.exists()}")

    # Model
    if MODEL_FILE.exists():
        click.echo(f"\nDefault model: {MODEL_FILE.read_text().strip()}")
    else:
        click.echo("\nDefault model: (not set, using llm default)")

    # Prompt
    if PROMPT_FILE.exists():
        click.echo(f"\nCustom prompt: {PROMPT_FILE}")
    elif PROMPT_STYLE_FILE.exists():
        style = PROMPT_STYLE_FILE.read_text().strip()
        click.echo(f"\nPrompt style: {style}")
    else:
        click.echo("\nPrompt style: conventional (default)")

    # Environment overrides
    if os.environ.get("LLM_GIT_COMMIT_EDITOR"):
        click.echo(f"\nEditor override: {os.environ['LLM_GIT_COMMIT_EDITOR']}")
```

---

## Summary of CLI Changes

```
llm git-commit [OPTIONS]

New options:
  --usage                  Show token usage after generation
  -p, --prompt-style TEXT  Use a built-in prompt style (conventional, detailed, minimal, semantic, gitmoji)
  --list-prompts           List available built-in prompt styles

New subcommands:
  llm git-commit-init      Interactive setup wizard
  llm git-commit-config    Show current configuration

New environment variables:
  LLM_GIT_COMMIT_EDITOR    Override editor for message editing
```

---

## Contributing Strategy

1. Open an issue discussing these features first
2. Implement incrementally as separate PRs:
   - PR 1: `--usage` flag (smallest, easiest to merge)
   - PR 2: Built-in prompt templates with `--prompt-style` and `--list-prompts`
   - PR 3: Persistent config files
   - PR 4: Setup wizard and config command
   - PR 5: Editor override
3. Follow their code style and testing patterns
