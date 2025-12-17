import click
import llm # Main LLM library
import subprocess # For running git commands
from prompt_toolkit import PromptSession # For interactive editing
from prompt_toolkit.patch_stdout import patch_stdout # Important for prompt_toolkit
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings
import os
import json
import tempfile
import shutil
from importlib import resources
from pathlib import Path

# ---  Configuration Management ---
# This section handles loading and saving configuration.
CONFIG_DIR = Path(click.get_app_dir("llm-git-commit"))
CONFIG_FILE = CONFIG_DIR / "config.json"
PROMPTS_DIR = CONFIG_DIR / "prompts"
DEFAULT_MAX_CHARS = 15000
DEFAULT_PROMPT_STYLE = "conventional"

# Built-in prompt styles (names and descriptions only - content is in files)
BUILTIN_PROMPT_STYLES = {
    "conventional": "Conventional Commits format (feat:, fix:, etc.) [Default]",
    "detailed": "Detailed multi-paragraph messages with context",
    "minimal": "Short single-line messages only",
    "semantic": "Semantic commits with scope: type(scope): description",
    "gitmoji": "Gitmoji-style with emoji prefixes",
    "custom": "Editable custom prompt - edit prompts/custom.txt to customize",
}


def ensure_prompts_installed():
    """Ensure prompt files are installed to the config directory."""
    if not PROMPTS_DIR.exists():
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    # Copy prompts from package to config directory if they don't exist
    try:
        package_prompts = resources.files("llm_git_commit").joinpath("prompts")
        for style_name in BUILTIN_PROMPT_STYLES:
            dest_file = PROMPTS_DIR / f"{style_name}.txt"
            if not dest_file.exists():
                source_file = package_prompts.joinpath(f"{style_name}.txt")
                if source_file.is_file():
                    dest_file.write_text(source_file.read_text())
    except Exception:
        # If package resources aren't available, that's okay - user can create their own
        pass


def load_config():
    """Loads configuration from the JSON file."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_config(config_data):
    """Saves configuration to the JSON file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=2)


def get_prompt_content(prompt_name: str) -> str | None:
    """Load prompt content from file in config directory.

    Returns the prompt text, or None if not found.
    """
    prompt_file = PROMPTS_DIR / f"{prompt_name}.txt"
    if prompt_file.exists():
        return prompt_file.read_text().strip()

    # Fall back to package resources
    try:
        package_prompts = resources.files("llm_git_commit").joinpath("prompts")
        source_file = package_prompts.joinpath(f"{prompt_name}.txt")
        if source_file.is_file():
            return source_file.read_text().strip()
    except Exception:
        pass

    return None


def list_available_prompts() -> dict[str, str]:
    """List all available prompt styles with descriptions."""
    available = {}

    # Start with built-in styles
    for name, desc in BUILTIN_PROMPT_STYLES.items():
        if get_prompt_content(name):
            available[name] = desc

    # Add any custom prompts in the prompts directory
    if PROMPTS_DIR.exists():
        for prompt_file in PROMPTS_DIR.glob("*.txt"):
            name = prompt_file.stem
            if name not in available:
                available[name] = f"Custom prompt: {name}"

    return available


# --- System Prompt  ---
# Default prompt is loaded from files, but we keep a fallback for when files aren't available
DEFAULT_GIT_COMMIT_SYSTEM_PROMPT = """You are an expert programmer tasked with writing a concise and conventional git commit message.
Analyze the provided 'git diff' output and create a commit message following Conventional Commits format.
Use type prefixes: feat, fix, docs, style, refactor, test, chore.
Subject line under 50 characters, imperative mood.
Optional body explaining what and why (not how).
Return ONLY the commit message text, nothing else."""


def get_system_prompt(config: dict, prompt_style_override: str | None = None, system_override: str | None = None) -> str:
    """Get the system prompt based on configuration and overrides.

    Priority: system_override > prompt_style_override > config["prompt"] > default

    Prompts are loaded from text files in ~/.config/llm-git-commit/prompts/
    """
    # Explicit system prompt override (from -s flag)
    if system_override:
        return system_override

    # Prompt style override (from -p/--prompt-style flag)
    if prompt_style_override:
        content = get_prompt_content(prompt_style_override)
        if content:
            return content
        raise ValueError(f"Prompt style '{prompt_style_override}' not found. "
                        f"Create {PROMPTS_DIR / prompt_style_override}.txt or use --list-prompts")

    # Config-based prompt (a style name like "conventional", "custom", etc.)
    config_prompt = config.get("prompt")
    if config_prompt:
        content = get_prompt_content(config_prompt)
        if content:
            return content

    # Legacy: check for old "prompt-style" key
    config_style = config.get("prompt-style")
    if config_style:
        content = get_prompt_content(config_style)
        if content:
            return content

    # Default to conventional
    content = get_prompt_content(DEFAULT_PROMPT_STYLE)
    if content:
        return content

    # Absolute fallback
    return DEFAULT_GIT_COMMIT_SYSTEM_PROMPT


# --- Editor Configuration ---
# Editor modes:
#   "internal" (default) - use built-in prompt_toolkit editor
#   "env" - detect from environment (LLM_GIT_COMMIT_EDITOR > git config > VISUAL > EDITOR)
#   "<command>" - use specific editor command (e.g., "vim", "code --wait")

def get_editor_from_env() -> str | None:
    """Get editor from environment variables.

    Priority: LLM_GIT_COMMIT_EDITOR > git config core.editor > VISUAL > EDITOR
    Returns None if no editor is found.
    """
    # Check LLM_GIT_COMMIT_EDITOR first
    editor = os.environ.get("LLM_GIT_COMMIT_EDITOR")
    if editor:
        return editor

    # Check git config core.editor
    try:
        result = subprocess.run(
            ["git", "config", "core.editor"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        pass

    # Fall back to standard editor environment variables
    return os.environ.get("VISUAL") or os.environ.get("EDITOR")


def resolve_editor(config: dict, use_external_flag: bool = False) -> tuple[str, str | None]:
    """Resolve which editor to use based on config and flags.

    Args:
        config: Configuration dict
        use_external_flag: Whether -e/--editor flag was passed without value

    Returns:
        Tuple of (mode, editor_command):
        - ("internal", None) - use built-in prompt_toolkit
        - ("env", "vim") - using editor from environment
        - ("command", "code --wait") - using specific command
    """
    editor_config = config.get("editor", "internal")

    # -e flag without value means use env
    if use_external_flag and editor_config == "internal":
        editor_config = "env"

    if editor_config == "internal":
        return ("internal", None)

    if editor_config == "env":
        env_editor = get_editor_from_env()
        if env_editor:
            return ("env", env_editor)
        # No env editor found, fall back to internal
        return ("internal", None)

    # Specific command
    return ("command", editor_config)


def edit_with_external_editor(initial_text: str, editor: str) -> str | None:
    """Open an external editor to edit the commit message.

    Returns the edited text, or None if the user cancelled.
    """
    # Create a temporary file with the initial text
    help_text = """
# Edit your commit message above.
# Lines starting with '#' will be ignored.
# Save and close the editor to proceed.
# Leave the message empty to cancel the commit.
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(initial_text)
        f.write("\n")
        f.write(help_text)
        temp_path = f.name

    try:
        # Open the editor
        result = subprocess.run([editor, temp_path], check=False)
        if result.returncode != 0:
            click.echo(click.style(f"Editor exited with code {result.returncode}", fg="yellow"))
            return None

        # Read the edited content
        with open(temp_path, 'r') as f:
            content = f.read()

        # Strip comment lines and trailing whitespace
        lines = [line for line in content.splitlines() if not line.startswith('#')]
        edited_text = '\n'.join(lines).strip()

        return edited_text if edited_text else None
    finally:
        # Clean up the temporary file
        try:
            os.unlink(temp_path)
        except OSError:
            pass


# System Prompts for Chat Refinement
CHAT_REFINEMENT_SYSTEM_PROMPT_TEMPLATE = """
You are an expert AI programmer specializing in crafting concise, conventional, and high-quality Git commit messages. Your primary objective is to assist the user in refining their current working draft of a commit message through an interactive dialogue, prioritizing their specific requests for content and style.

**Context Provided:**
1.  **Original Git Diff:**
    --- DIFF START ---
    {original_diff}
    --- DIFF END ---
2.  **Programmer's Current Working Draft:** (This draft will evolve if you make proposals that are accepted by the user)
    --- CURRENT DRAFT START ---
    {current_draft_for_llm_context}
    --- CURRENT DRAFT END ---

**Core Principle: User-Directed Refinement**
While your expertise should guide towards clear, concise, and conventionally formatted commit messages (as detailed in "Commit Message Formatting and Content Standards" below), **if the user makes an explicit request for a specific content change, stylistic alteration (e.g., a different tone, a specific phrasing), or structural modification, your primary goal for any proposal you make is to fulfill that user's directive.** You should attempt to incorporate their request into a new commit message proposal. If a user's stylistic request conflicts with strict conventional commit formatting (e.g., for type or subject), prioritize the user's explicit stylistic request for the proposal's content, while still aiming for overall clarity and basic commit structure (subject/body).

**Interaction Protocol:**

1.  **Analyze User Input:** Carefully consider the user's queries, requests for changes, or questions.
2.  **Conversational Interaction:** Respond naturally. Provide explanations or ask clarifying questions.
3.  **Proposing Revisions to the Commit Message:**
    *   When the user asks for a modification and you are ready to propose a new version of the *entire commit message*, structure your response in two parts:
        a.  **Conversational Part:** Explain how you've addressed their request. 
        b.  **Structured Proposal Block (Mandatory):** Following your conversational text, you **MUST** provide the ** raw commit message text** clearly demarcated:
            ```
            PROPOSED_COMMIT_MESSAGE_START
            <type>(<scope>): <subject>

            <optional body>
            PROPOSED_COMMIT_MESSAGE_END
            ```
            The content between these markers **MUST strictly adhere to the "Commit Message Formatting and Content Standards" below, UNLESS the user's explicit request necessitates a deviation (e.g., a highly stylistic tone).** In case of such a deviation, prioritize the user's request for the content between the markers.

4.  **Answering Questions / General Discussion:**
    *   If *only* answering a question or discussing parts *without the user asking for a modification to the entire commit message*, **DO NOT use the `PROPOSED_COMMIT_MESSAGE_START`/`END` markers.**

**Commit Message Formatting and Content Standards (applies to text within markers by default; user requests may override style):**
*   **Output ONLY Raw Text:** (As detailed previously)
*   **Conventional Commits:** (As detailed previously - type, scope, subject)
*   **Subject Line:** (As detailed previously - 50 chars, imperative, no caps, no dot)
*   **Body (Optional):** (As detailed previously - blank line, what/why, concise, bullets, 72 chars)
*   **Content Focus (CRITICAL):** (As detailed previously - diff focus, new files purpose, DO NOTs)

**Exemplar of Proposing a (Standard, Professional) Commit Message:**

User: The subject is weak, and the body doesn't explain the 'why'.

Assistant: You're right, we can definitely improve that. I've rephrased the subject to be a clear action and added a brief explanation to the body about the motivation for the change.
Here's my suggestion:

PROPOSED_COMMIT_MESSAGE_START
refactor: improve data pipeline efficiency

Replaces iterative loop in data transformation with vectorized pandas operations.
This change significantly reduces processing time for large datasets,
improving overall system performance.
PROPOSED_COMMIT_MESSAGE_END

**End of Exemplar.**

The system will use the text between the markers for user confirmation.
"""



PROPOSED_COMMIT_MARKER_START = "PROPOSED_COMMIT_MESSAGE_START"
PROPOSED_COMMIT_MARKER_END = "PROPOSED_COMMIT_MESSAGE_END"

# --- LLM Plugin Hook ---
@llm.hookimpl
def register_commands(cli):
    """
    Registers the 'git-commit' command group with the LLM CLI.
    """
    
    @cli.group(name="git-commit", invoke_without_command=True)
    @click.pass_context
    @click.option(
        "--staged", "diff_mode", flag_value="staged", default=True,
        help="Generate commit message based on staged changes (git diff --staged). [Default]"
    )
    @click.option(
        "--tracked", "diff_mode", flag_value="tracked",
        help="Generate commit message based on all changes to tracked files (git diff HEAD)."
    )
    @click.option(
        "-m", "--model", "model_id_override", default=None,
        help="Specify the LLM model to use (e.g., gpt-4, claude-3-opus)."
    )
    @click.option(
        "-s", "--system", "system_prompt_override", default=None,
        help="Custom system prompt to override the default."
    )
    @click.option(
        "-p", "--prompt-style", "prompt_style",
        default=None,
        help="Use a prompt style (conventional, detailed, minimal, semantic, gitmoji, or custom)."
    )
    @click.option(
        "--list-prompts", is_flag=True,
        help="List available prompt styles and exit."
    )
    @click.option(
        "--max-chars", "max_chars_override", type=int, default=None,
        help="Set max characters for the diff sent to the LLM."
    )
    @click.option(
        "--key", "api_key_override", default=None,
        help="API key for the LLM model (if required and not set globally)."
    )
    @click.option(
        "-y", "--yes", is_flag=True,
        help="Automatically confirm and proceed with the commit without interactive editing (uses LLM output directly)."
    )
    @click.option(
        "-e", "--editor", "editor_override", is_flag=False, flag_value="env", default=None,
        help="Use external editor. Without value: detect from env. With value: use that command."
    )
    @click.option(
        "--usage", "show_usage", is_flag=True,
        help="Show token usage after LLM generation."
    )
    def git_commit_command(ctx, diff_mode, model_id_override, system_prompt_override, prompt_style, list_prompts, max_chars_override, api_key_override, yes, editor_override, show_usage):
        """
        Generates Git commit messages using an LLM.

        Run 'llm git-commit config --help' to manage persistent defaults.
        """
       
        if ctx.invoked_subcommand is not None:
            return

        # Ensure prompts are installed
        ensure_prompts_installed()

        config = load_config()

        # Handle --list-prompts
        if list_prompts:
            click.echo("Available prompt styles:\n")
            current_prompt = config.get("prompt", DEFAULT_PROMPT_STYLE)
            for pid, desc in list_available_prompts().items():
                marker = " (current)" if pid == current_prompt else ""
                click.echo(f"  {click.style(pid, bold=True):20} {desc}{marker}")
            click.echo(f"\nPrompt files location: {PROMPTS_DIR}")
            click.echo("\nUsage: llm git-commit --prompt-style <style>")
            click.echo("       llm git-commit config --prompt <style>  (set as default)")
            return

        #  Check if inside a Git repository
        if not _is_git_repository():
            click.echo(click.style("Error: Not inside a git repository.", fg="red"))
            return

        #  Get Git diff
        diff_output, diff_description = _get_git_diff(diff_mode)

        if diff_output is None: # Error occurred in _get_git_diff
            return

        if not diff_output.strip():
            if diff_mode == "staged":
                click.echo("No staged changes found.")
                _show_git_status()
                if click.confirm("Do you want to stage all changes and commit?", default=True):
                    click.echo("Staging all changes...")
                    try:
                        subprocess.run(["git", "add", "."], check=True, cwd=".")
                        click.echo(click.style("Changes staged.", fg="green"))
                        diff_output, diff_description = _get_git_diff("staged")
                        if diff_output is None or not diff_output.strip():
                            click.echo(click.style("No changes to commit even after staging.", fg="yellow"))
                            return
                    except (subprocess.CalledProcessError, FileNotFoundError) as e:
                        click.echo(click.style(f"Error staging changes: {e}", fg="red"))
                        return
                else:
                    click.echo("Commit aborted.")
                    return
            else: # diff_mode is "tracked"
                click.echo(f"No {diff_description} to commit.")
                _show_git_status()
                return

        # Prepare for and call LLM
        from llm.cli import get_default_model # Import here to ensure LLM environment is ready

        
        configured_model = config.get("model")
        actual_model_id = model_id_override or configured_model or get_default_model()
        
        if not actual_model_id:
            click.echo(click.style("Error: No LLM model specified or configured.", fg="red"))
            click.echo("Try 'llm models list' or set a default with 'llm git-commit config --model <id>'.")
            return

        try:
            model_obj = llm.get_model(actual_model_id)
        except llm.UnknownModelError:
            click.echo(click.style(f"Error: Model '{actual_model_id}' not recognized.", fg="red"))
            click.echo("Try 'llm models list' to see available models.")
            return
        
        if model_obj.needs_key:
            model_obj.key = llm.get_key(api_key_override, model_obj.needs_key, model_obj.key_env_var)
            if not model_obj.key:
                click.echo(click.style(f"Error: API key for model '{actual_model_id}' not found.", fg="red"))
                click.echo(f"Set via 'llm keys set {model_obj.needs_key}', --key option, or ${model_obj.key_env_var}.")
                return

        # --- Truncate diff using the resolved max_chars value ---
        max_chars = max_chars_override or config.get("max-chars") or DEFAULT_MAX_CHARS
        if len(diff_output) > max_chars:
            click.echo(click.style(f"Warning: Diff is very long ({len(diff_output)} chars), truncating to {max_chars} chars for LLM.", fg="yellow"))
            diff_output = diff_output[:max_chars] + "\n\n... [diff truncated]"

        # --- Logic to determine the system prompt with config precedence ---
        try:
            system_prompt = get_system_prompt(config, prompt_style, system_prompt_override)
        except ValueError as e:
            click.echo(click.style(f"Error: {e}", fg="red"))
            click.echo("Use --list-prompts to see available styles.")
            return
        
        click.echo(f"Generating commit message using {click.style(actual_model_id, bold=True)} based on {diff_description}...")
        
        try:
            response_obj = model_obj.prompt(diff_output, system=system_prompt)
            generated_message = response_obj.text().strip()

            # Display token usage if requested
            if show_usage:
                try:
                    usage = response_obj.usage()
                    if usage:
                        input_tokens = usage.get("input", usage.get("prompt_tokens", "?"))
                        output_tokens = usage.get("output", usage.get("completion_tokens", "?"))
                        total = "?"
                        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                            total = input_tokens + output_tokens
                        click.echo(click.style(f"Token usage: {input_tokens} input, {output_tokens} output, {total} total", fg="cyan"))
                except Exception:
                    click.echo(click.style("Token usage: not available for this model", fg="yellow"))
        except Exception as e:
            click.echo(click.style(f"Error calling LLM: {e}", fg="red"))
            return

        if not generated_message:
            click.echo(click.style("LLM returned an empty commit message. Please write one manually or try again.", fg="yellow"))
            generated_message = ""

        #  Interactive Edit & Commit or Direct Commit
        if yes:
            if not generated_message:
                click.echo(click.style("LLM returned an empty message and --yes was used. Aborting commit.", fg="red"))
                return
            final_message = generated_message
            click.echo(click.style("\nUsing LLM-generated message directly:", fg="cyan"))
            click.echo(f'"""\n{final_message}\n"""')
        else:
            # Determine editor mode
            # CLI override takes precedence
            if editor_override:
                if editor_override == "env":
                    editor_mode, editor_cmd = "env", get_editor_from_env()
                elif editor_override == "internal":
                    editor_mode, editor_cmd = "internal", None
                else:
                    editor_mode, editor_cmd = "command", editor_override
            else:
                editor_mode, editor_cmd = resolve_editor(config)

            if editor_mode == "internal":
                final_message = _interactive_edit_message(generated_message, diff_output, model_obj)
            elif editor_cmd:
                click.echo(click.style(f"\nOpening {editor_cmd} to edit commit message...", fg="cyan"))
                final_message = edit_with_external_editor(generated_message, editor_cmd)
            else:
                # env mode but no editor found
                click.echo(click.style("Warning: No external editor found in environment. Using built-in editor.", fg="yellow"))
                final_message = _interactive_edit_message(generated_message, diff_output, model_obj)

        if final_message is None or not final_message.strip():
            click.echo("Commit aborted.")
            return
        
        _execute_git_commit(final_message, diff_mode == "tracked")

    # --- 'config' subcommand attached to the git_commit_command group ---
    @git_commit_command.command(name="config")
    @click.option("--view", is_flag=True, help="View the current configuration (default if no options given).")
    @click.option("--reset", is_flag=True, help="Reset all configurations to default.")
    @click.option("-m", "--model", "model_config", default=None, help="Set the default model.")
    @click.option("-p", "--prompt", "prompt_config", default=None,
                  help="Set the default prompt style (e.g., conventional, detailed, custom).")
    @click.option("-e", "--editor", "editor_config", default=None,
                  help="Set editor: 'internal' (built-in), 'env' (from environment), or a command.")
    @click.option("--max-chars", "max_chars_config", type=int, default=None, help="Set the default max characters.")
    @click.option("--show-prompt", is_flag=True, help="Show the full text of the current prompt.")
    @click.pass_context
    def config_command(ctx, view, reset, model_config, prompt_config, editor_config, max_chars_config, show_prompt):
        """
        View or set persistent default options for llm-git-commit.

        Prompts are stored as text files in the prompts directory.
        Edit the files directly to customize, or create new ones.

        Editor options:
        \b
          internal  - Built-in prompt_toolkit editor (default)
          env       - Detect from $LLM_GIT_COMMIT_EDITOR, git config, $VISUAL, $EDITOR
          <command> - Specific command like 'vim', 'code --wait', 'nano'

        Examples:
        \b
          llm git-commit config                    # Show current config
          llm git-commit config --show-prompt      # Show current prompt text
          llm git-commit config --model gpt-4-turbo
          llm git-commit config --prompt detailed
          llm git-commit config --prompt custom    # Use prompts/custom.txt (edit it!)
          llm git-commit config --editor internal  # Use built-in editor (default)
          llm git-commit config --editor env       # Use editor from environment
          llm git-commit config --editor vim       # Use specific editor
          llm git-commit config --reset
        """
        # Ensure prompts are installed
        ensure_prompts_installed()

        config_data = load_config()

        # Default to --view if no options given
        no_options = not any([reset, model_config, prompt_config,
                              editor_config, max_chars_config, show_prompt])
        if view or no_options:
            click.echo(click.style("llm-git-commit configuration\n", bold=True))
            click.echo(f"Config file:    {CONFIG_FILE}")
            click.echo(f"Prompts dir:    {PROMPTS_DIR}")
            click.echo("")

            # Model
            model = config_data.get("model", "(llm default)")
            click.echo(f"Model:          {model}")

            # Prompt
            prompt_name = config_data.get("prompt", DEFAULT_PROMPT_STYLE)
            desc = BUILTIN_PROMPT_STYLES.get(prompt_name, f"Custom: {prompt_name}")
            prompt_file = PROMPTS_DIR / f"{prompt_name}.txt"
            click.echo(f"Prompt:         {prompt_name} - {desc}")
            click.echo(f"Prompt file:    {prompt_file}")

            # Editor
            editor_config = config_data.get("editor", "internal")
            env_editor = get_editor_from_env()
            if editor_config == "internal":
                click.echo(f"Editor:         internal (built-in prompt_toolkit)")
            elif editor_config == "env":
                click.echo(f"Editor:         env -> {env_editor or '(not found, will use internal)'}")
            else:
                click.echo(f"Editor:         {editor_config}")
            if env_editor:
                click.echo(f"Env editor:     {env_editor}")

            # Max chars
            max_chars = config_data.get("max-chars", DEFAULT_MAX_CHARS)
            click.echo(f"Max chars:      {max_chars}")

            click.echo("")
            click.echo("Use --show-prompt to see the full prompt text.")
            click.echo(f"Edit prompt files directly in: {PROMPTS_DIR}")
            return

        if show_prompt:
            prompt_name = config_data.get("prompt", DEFAULT_PROMPT_STYLE)
            prompt_file = PROMPTS_DIR / f"{prompt_name}.txt"
            click.echo(click.style(f"Current prompt ({prompt_name}):\n", bold=True))
            click.echo(click.style(f"File: {prompt_file}\n", fg="cyan"))
            try:
                prompt_text = get_system_prompt(config_data)
                click.echo(prompt_text)
            except ValueError as e:
                click.echo(click.style(f"Error: {e}", fg="red"))
            return

        if reset:
            if click.confirm("Are you sure you want to reset all configurations?"):
                if CONFIG_FILE.exists():
                    CONFIG_FILE.unlink()
                click.echo("Configuration has been reset.")
            else:
                click.echo("Reset cancelled.")
            return

        updates_made = False
        if model_config is not None:
            config_data["model"] = model_config
            click.echo(f"Default model set to: {model_config}")
            updates_made = True

        if prompt_config is not None:
            # Validate the prompt file exists
            if not get_prompt_content(prompt_config):
                prompt_file = PROMPTS_DIR / f"{prompt_config}.txt"
                click.echo(click.style(f"Error: Prompt '{prompt_config}' not found.", fg="red"))
                click.echo(f"Create a prompt file at: {prompt_file}")
                click.echo("Or use --list-prompts to see available styles.")
                return
            config_data["prompt"] = prompt_config
            # Clear legacy keys
            config_data.pop("prompt-style", None)
            config_data.pop("system", None)
            prompt_file = PROMPTS_DIR / f"{prompt_config}.txt"
            click.echo(f"Default prompt set to: {prompt_config}")
            click.echo(f"Edit the prompt at: {prompt_file}")
            updates_made = True

        if editor_config is not None:
            editor_val = editor_config.lower()
            if editor_val == "internal":
                config_data["editor"] = "internal"
                click.echo("Editor set to: internal (built-in prompt_toolkit)")
            elif editor_val == "env":
                config_data["editor"] = "env"
                env_editor = get_editor_from_env()
                if env_editor:
                    click.echo(f"Editor set to: env (currently: {env_editor})")
                else:
                    click.echo("Editor set to: env (no editor found in environment, will fall back to internal)")
            else:
                config_data["editor"] = editor_config
                click.echo(f"Editor set to: {editor_config}")
            updates_made = True

        if max_chars_config is not None:
            config_data["max-chars"] = max_chars_config
            click.echo(f"Default max-chars set to: {max_chars_config}")
            updates_made = True

        if updates_made:
            save_config(config_data)
        else:
            click.echo(ctx.get_help())


# --- Helper Functions  ---

def _format_chat_history_for_prompt(chat_history: list) -> str: 
    """Formats chat history for inclusion in a prompt."""
    if not chat_history:
        return "No conversation history yet."
    return "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in chat_history])

def _is_git_repository():
    """Checks if the current directory is part of a git repository."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True, capture_output=True, text=True, cwd=".",
            encoding="utf-8", errors="ignore"
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def _get_git_diff(diff_mode):
    """Gets the git diff output based on the specified mode."""
    diff_command = ["git", "diff"]
    if diff_mode == "staged":
        diff_command.append("--staged")
        description = "staged changes"
    elif diff_mode == "tracked":
        diff_command.append("HEAD")
        description = "unstaged changes in tracked files"
    else:
        click.echo(click.style(f"Internal error: Unknown diff mode '{diff_mode}'.", fg="red"))
        return None, "unknown changes"
        
    try:
        process = subprocess.run(
            diff_command, capture_output=True, text=True, check=True, cwd=".",
            encoding="utf-8", errors="ignore"
        )
        return process.stdout, description
    except subprocess.CalledProcessError as e:
        click.echo(click.style(f"Error getting git diff ({' '.join(diff_command)}):\n{e.stderr or e.stdout}", fg="red"))
        return None, description
    except FileNotFoundError:
        click.echo(click.style("Error: 'git' command not found. Is Git installed and in your PATH?", fg="red"))
        return None, description


def _show_git_status():
    """Shows a brief git status."""
    try:
        status_output = subprocess.check_output(
            ["git", "status", "--short"], text=True, cwd=".",
            encoding="utf-8", errors="ignore"
        ).strip()
        if status_output:
            click.echo("\nCurrent git status (--short):")
            click.echo(status_output)
        else:
            click.echo("Git status is clean (no changes detected by 'git status --short').")
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo(click.style("Could not retrieve git status.", fg="yellow"))


def _interactive_edit_message(suggestion: str, original_diff: str, model_obj: llm.Model):
    """Allows interactive editing of the commit message."""
    click.echo(click.style("\nSuggested commit message (edit below):", fg="cyan"))
    
    prompt_instructions_text = """\
Type/edit your commit message below.
  - To add a NEW LINE: Press Enter.
  - To SUBMIT message: Press Esc, then press Enter.
                     (Alternatively, try Alt+Enter or Option+Enter on Mac).
  - Chat to Refine: Ctrl+I.
  - To CANCEL: Press Ctrl+D or Ctrl-C.

Commit Message:
"""
    custom_style = Style.from_dict({
        'instruction': 'ansicyan' 
    })

    formatted_instructions = FormattedText([
        ('class:instruction', prompt_instructions_text)
    ])

    kb = KeyBindings()
    
    @kb.add('c-i')
    async def _handle_chat_refine(event): # Renamed for clarity
        """Handle Ctrl+I: Open chat for refinement."""
        current_text_in_editor_buffer = event.app.current_buffer.text
        
        app_style = event.app.style # Get the current application's style

        print_formatted_text(FormattedText([
            ('bold fg:ansimagenta', "\n==> Entering Chat Mode...")
        ]), style=app_style)   
        
        # Call the async chat refinement function
        # This function handles its own click.echo UI elements for the chat interaction
        refined_message_from_chat = await _chat_for_refinement(
            current_text_in_editor_buffer,
            original_diff,
            model_obj,
            custom_style
        )

        print_formatted_text(FormattedText([
            ('bold fg:ansimagenta', "<== Exiting Chat Mode...")
        ]), style=app_style)
        


        if refined_message_from_chat is not None: 
            if refined_message_from_chat != current_text_in_editor_buffer:
                # buffer update
                event.app.current_buffer.text = refined_message_from_chat
                event.app.current_buffer.cursor_position = len(refined_message_from_chat)
            
        event.app.invalidate() # CRUCIAL: Force redraw of the main prompt UI

    session = PromptSession(
        message=formatted_instructions,
        style=custom_style,
        key_bindings=kb,
        multiline=True, 
    )
    
    with patch_stdout():
        edited_message = session.prompt(
            default=suggestion, 
            #multiline=True 
        )
    return edited_message

def _execute_git_commit(message, commit_all_tracked):
    """Executes the git commit command."""
    commit_command = ["git"]
    action_description = "Committing"

    if commit_all_tracked:
        commit_command.extend(["commit", "-a", "-m", message])
        action_description = "Staging all tracked file changes and committing"
    else: # Staged changes
        commit_command.extend(["commit", "-m", message])
        action_description = "Committing staged changes"
        
    click.echo(f"\n{action_description} with message:")
    click.echo(click.style(f'"""\n{message}\n"""', fg="yellow"))
    
    if not click.confirm(f"Proceed?", default=True):
        click.echo("Commit aborted by user.")
        return

    try:
        process = subprocess.run(
            commit_command, capture_output=True, text=True, check=True, cwd=".",
            encoding="utf-8", errors="ignore"
        )
        click.echo(click.style("\nCommit successful!", fg="green"))
        if process.stdout:
            click.echo("Git output:")
            click.echo(process.stdout)
        if process.stderr:
            click.echo("Git stderr:")
            click.echo(process.stderr)

        if click.confirm("Do you want to push the changes?", default=False):
            click.echo("Pushing changes...")
            try:
                subprocess.run(
                    ["git", "push"], check=True, cwd=".",
                    capture_output=True, text=True, encoding="utf-8", errors="ignore"
                )
                click.echo(click.style("Push successful!", fg="green"))
            except subprocess.CalledProcessError as e:
                click.echo(click.style(f"\nError during git push:", fg="red"))
                output = (e.stdout or "") + (e.stderr or "")
                click.echo(output if output else "No output from git push.")
            except FileNotFoundError:
                click.echo(click.style("Error: 'git' command not found.", fg="red"))
            
    except subprocess.CalledProcessError as e:
        click.echo(click.style("\nError during git commit:", fg="red"))
        output = (e.stdout or "") + (e.stderr or "")
        click.echo(output if output else "No output from git.")
    except FileNotFoundError:
        click.echo(click.style("Error: 'git' command not found.", fg="red"))


async def _chat_for_refinement(initial_commit_draft: str, original_diff: str, model: llm.Model, passed_style: Style) -> str:
    """
    Handles interactive chat for refining commit messages.
    - Ctrl+A or /apply: Uses the current working draft, confirms, and exits.
    - LLM proposals (via markers) get a Y/N prompt to update the current working draft.
    """

    # Helper for printing FormattedText using the passed style sheet
    def print_styled(text_parts_tuples, end='\n'):
        print_formatted_text(FormattedText(text_parts_tuples), style=passed_style, end=end)

    # --- Bottom Toolbar Definition ---
    def get_bottom_toolbar_ft():
        return FormattedText([
            ('fg:ansiblack bg:ansicyan bold', "[Chat]"),
            ('fg:ansiblack bg:ansicyan', " Ctrl+A or /apply: Use Current Draft & Exit | "),
            ('fg:ansiblack bg:ansicyan bold', "/cancel"), ('fg:ansiblack bg:ansicyan', ":Discard & Exit"),
        ])

    print_styled([('bold fg:ansimagenta', "\n--- Chat Session Started ---")])
    print_styled([('class:dim', "LLM considers original diff & the initial draft context.")]) # Uses 'dim' from passed_style

    print_styled([('bold fg:ansiyellow', f"\nReference: Initial Draft (when chat started):")])
    for line in initial_commit_draft.splitlines():
        print_styled([('class:instruction', line)]) # Uses 'instruction' from passed_style for cyan
    print_formatted_text("---", style=passed_style)

    chat_history = []
    message_being_refined_in_chat = initial_commit_draft # This is the evolving draft
    # Stores the text of the last proposal from markers, cleared after Y/N or Ctrl+A action on it.
    last_marker_proposal_text = None 
    
    def get_current_chat_system_prompt():
        # Use the CHAT_REFINEMENT_SYSTEM_PROMPT_TEMPLATE defined globally
        return CHAT_REFINEMENT_SYSTEM_PROMPT_TEMPLATE.format(
            original_diff=original_diff,
            current_draft_for_llm_context=message_being_refined_in_chat
        )

    # KeyBindings for the chat input session
    chat_kb = KeyBindings()
    @chat_kb.add('c-a') # Ctrl+A for FINAL APPLY
    async def _handle_apply_via_ctrl_a(event):
        print_styled([('fg:ansicyan', "\n(Ctrl+A pressed, initiating apply sequence...)")])
        event.app.exit(result="/apply") # Make the prompt return "/apply"

    chat_input_prompt_style_dict = {'prompt': 'fg:ansimagenta'}
    effective_chat_session_style = Style(list(passed_style.style_rules) + list(Style.from_dict(chat_input_prompt_style_dict).style_rules))

    chat_session = PromptSession(
        message=FormattedText([('class:prompt', "Your Query: ")]),
        style=effective_chat_session_style,
        bottom_toolbar=get_bottom_toolbar_ft,
        key_bindings=chat_kb # Attach keybindings
    )
    
    confirm_prompt_style_dict = {'prompt': 'bold fg:ansiyellow'}
    confirm_session_style = Style.from_dict(confirm_prompt_style_dict)

    while True:
        print_styled([('bold fg:ansiyellow', f"\nCurrent Draft being refined in chat:")])
        for line in message_being_refined_in_chat.splitlines():
            print_styled([('class:instruction', line)]) # Uses 'instruction' for cyan
        print_formatted_text("---", style=passed_style)

        user_input_from_prompt = ""
        try:
            with patch_stdout():
                user_input_from_prompt = await chat_session.prompt_async()
        
        except KeyboardInterrupt: user_input_from_prompt = "/cancel"
        except EOFError: user_input_from_prompt = "/cancel"; print_styled([('class:dim', "(Ctrl+D treated as /cancel)")])
        
        if user_input_from_prompt is None: user_input_from_prompt = "/cancel" 
        
        cleaned_user_query = user_input_from_prompt.strip() 
        
        if not cleaned_user_query and user_input_from_prompt != "/apply":
            cleaned_user_query = "/cancel"
            print_styled([('class:dim', "(Empty input treated as /cancel)")])

        if cleaned_user_query.lower() != "/apply" or user_input_from_prompt == "/apply":
             print_styled([('bold fg:ansiblue', "You: "), ('fg:ansiwhite', cleaned_user_query if cleaned_user_query else "(Action via Keybinding / Empty)")])

        if cleaned_user_query.lower() == "/cancel":
            print_styled([('bold fg:ansiyellow', "\nChat cancelled. Returning original draft.")])
            return initial_commit_draft

        elif cleaned_user_query.lower() == "/apply":
            last_marker_proposal_text = None # Clear any pending proposal, this is a final action path
            print_styled([('fg:ansicyan', "Preparing to apply current draft...")])
            
            final_message_to_apply = message_being_refined_in_chat

            if not final_message_to_apply.strip():
                print_styled([('fg:ansired', "Current draft is empty. Cannot apply.")])
                print_formatted_text("---", style=passed_style)
                continue 

            print_styled([('fg:ansigreen', "This is the current draft that will be applied:")])
            for line in final_message_to_apply.splitlines():
                print_styled([('class:instruction', line)]) # Show current draft styled cyan
            print_formatted_text("---", style=passed_style)
            
            confirm_prompt_ft = FormattedText([('class:prompt', "Use this message & exit chat? (Y/n): ")])
            confirmation = ""
            with patch_stdout():
                temp_session = PromptSession(message=confirm_prompt_ft, style=confirm_session_style)
                confirmation = await temp_session.prompt_async()

            if confirmation.lower().strip() == 'y' or not confirmation.strip(): # Default Y
                print_styled([('bold fg:ansigreen', "--- Current draft confirmed. Returning to editor. ---")])
                return final_message_to_apply 
            else:
                print_styled([('bold fg:ansiyellow', "/apply action discarded by user. Continuing chat.")])
            
            print_formatted_text("---", style=passed_style)
            continue 
        
        # --- Regular chat query ---
        else:
            chat_history.append({"role": "user", "content": cleaned_user_query})
            messages_for_llm = [{"role": "system", "content": get_current_chat_system_prompt()}] + chat_history
            
            extracted_proposal_text = None
            llm_full_response_text = ""
            conversational_parts_to_print = []
            conversational_text_for_history_if_proposal_rejected = ""
            # Don't clear last_marker_proposal_text here; user might type a new query before Ctrl+A for previous proposal

            try:
                print_styled([('fg:ansiblue class:dim', "LLM thinking...")])
                response_obj = model.chat(messages_for_llm) if hasattr(model, "chat") else model.prompt(
                    _format_chat_history_for_prompt(messages_for_llm[1:]), system=get_current_chat_system_prompt()
                )
                
                if hasattr(response_obj, 'text') and callable(response_obj.text):
                     llm_full_response_text = response_obj.text()
                elif isinstance(response_obj, str):
                     llm_full_response_text = response_obj
                else: 
                     llm_full_response_text = str(response_obj)

                print_styled([('bold fg:ansigreen', "LLM:")]) # LLM Prefix
                if not llm_full_response_text.strip():
                    print_styled([('class:dim', "(LLM returned no text)")])
                    conversational_text_for_history_if_proposal_rejected = "" # Explicitly empty
                else:
                    start_marker_idx = llm_full_response_text.find(PROPOSED_COMMIT_MARKER_START)
                    end_marker_idx = -1
                    if start_marker_idx != -1:
                        end_marker_idx = llm_full_response_text.find(PROPOSED_COMMIT_MARKER_END, start_marker_idx + len(PROPOSED_COMMIT_MARKER_START))

                    if start_marker_idx != -1 and end_marker_idx != -1:
                        conv_before = llm_full_response_text[:start_marker_idx].strip()
                        if conv_before: conversational_parts_to_print.append(conv_before)
                        
                        proposal_start_content_idx = start_marker_idx + len(PROPOSED_COMMIT_MARKER_START)
                        temp_extracted = llm_full_response_text[proposal_start_content_idx:end_marker_idx].strip()
                        if temp_extracted: 
                             extracted_proposal_text = temp_extracted
                             last_marker_proposal_text = extracted_proposal_text # Available for Ctrl+A
                        else: # Markers present but empty content
                             last_marker_proposal_text = None 
                        
                        conv_after = llm_full_response_text[end_marker_idx + len(PROPOSED_COMMIT_MARKER_END):].strip()
                        if conv_after: conversational_parts_to_print.append(conv_after)
                        
                        conversational_text_for_history_if_proposal_rejected = "\n".join(filter(None, [conv_before, conv_after])).strip()
                    else: 
                        conversational_parts_to_print.append(llm_full_response_text.strip())
                        conversational_text_for_history_if_proposal_rejected = llm_full_response_text.strip()
                        last_marker_proposal_text = None # No valid proposal this turn

                    for part in conversational_parts_to_print:
                        if part:
                            for line in part.splitlines():
                                print_formatted_text(FormattedText([('', line)]), style=passed_style, end='\n')
            
            except Exception as e:
                print_styled([('fg:ansired', f"\nLLM Error: {e}")])
                conversational_text_for_history_if_proposal_rejected = f"(LLM Error: {e})"
                extracted_proposal_text = None 
                last_marker_proposal_text = None # Error means no valid proposal pending
            
            # --- Add assistant's response to history (deferred until after Y/N) ---
            assistant_response_for_history = ""

            if extracted_proposal_text:
                print_formatted_text("---", style=passed_style) 
                print_styled([('bold fg:ansiyellow', "LLM Proposes Update to Draft:")])
                for line in extracted_proposal_text.splitlines():
                    print_styled([('class:instruction', line)])
                print_formatted_text("---", style=passed_style)

                confirm_prompt_ft = FormattedText([('class:prompt', "Accept this proposal as current draft? (Y/n): ")])
                acceptance = ""
                with patch_stdout():
                    temp_session = PromptSession(message=confirm_prompt_ft, style=confirm_session_style)
                    acceptance = await temp_session.prompt_async()

                if acceptance.lower().strip() == 'y' or not acceptance.strip():
                    message_being_refined_in_chat = extracted_proposal_text
                    print_styled([('bold fg:ansigreen', "Proposal accepted. Current draft updated.")])
                    chat_history.append({"role": "user", "content": "(User accepted LLM's proposal to update draft)"}) 
                    assistant_response_for_history = message_being_refined_in_chat # Store accepted draft as "assistant's response"
                else:
                    print_styled([('fg:ansiyellow', "Proposal rejected. Current draft remains unchanged.")])
                    if conversational_text_for_history_if_proposal_rejected:
                        assistant_response_for_history = conversational_text_for_history_if_proposal_rejected
                    else: 
                        assistant_response_for_history = "(LLM made a proposal which was rejected by the user.)"
                last_marker_proposal_text = None # Proposal has been acted upon (Y/N), clear for Ctrl+A
            
            else: # No proposal was extracted, so all LLM output was conversational (or an error)
                 assistant_response_for_history = conversational_text_for_history_if_proposal_rejected
                 # last_marker_proposal_text remains None or its previous value if user didn't Y/N last turn

            # Add the determined assistant response to history
            if assistant_response_for_history or not llm_full_response_text.strip(): # Add even if empty if LLM returned empty
                chat_history.append({"role": "assistant", "content": assistant_response_for_history})
            
        print_formatted_text("---", style=passed_style) # End of turn separator


        
