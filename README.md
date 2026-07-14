# AIV - AI Valve: Pipes for AI

AIV is a Python command-line utility designed for seamless integration with text
editors and terminal workflows. It allows you to interact with AI models through
Unix pipes while maintaining conversation context and providing intelligent code
location detection.

## Features

- **Editor-optimized design** for seamless integration with Helix and other editors
- **Terminal-friendly interface** for command-line workflows and automation
- **Interactive REPL** (`aiv -i`) for conversational sessions with history management
- **Per-project conversation state** scoped to the current git repository
- **Pipe-friendly interface** that works with any Unix tool
- **Flexible input handling** supporting files, globs, and stdin
- **Real-time streaming responses** via the Anthropic Python SDK
- **Token-efficient context storage** - when only `-c` option is used without
  a prompt and normal stdin, context is saved to conversation file without making
  API requests
- **Per-request output mode control** via `-C` (conversational) and `-X` (code-only) flags
- **Inline history inspection** via `-H`/`--history`, without needing to enter the REPL
- **Inline content inspection** via `-S`/`--show`, to view full interaction content without entering the REPL
- **Safe destructive operations**: `--reset` skips its confirmation prompt only
  when invoked non-interactively with piped stdin; typed at a terminal or inside
  the REPL, it always asks first
- **Nix flake**: install with `nix profile install` or run directly with `nix run`
  without any manual setup
- **Home-manager module**: declarative configuration including editor keybindings for Helix, Vim,
  and Neovim


## Installation

### With Nix (recommended)

```bash
nix run github:jdelkins/aiv
```

Or install into your profile:

```bash
nix profile install github:jdelkins/aiv
```

### Manual

1. Clone the repository:
   ```bash
   git clone https://github.com/jdelkins/aiv.git
   ```

2. Install dependencies:
   ```bash
   pip install anthropic prompt-toolkit rich
   ```

3. Install the package:
   ```bash
   pip install -e .
   ```

## Configuration

### With the home-manager module

If you are using the provided home-manager module, configuration is handled
declaratively. Set either `apiKey` or `apiKeyFile` in your home-manager config:

```nix
{ aiv, config, ... }:

{
  imports = [ aiv.homeManagerModules.default ];

  programs.aiv = {
    enable = true;
    # apiKey writes the key directly into the Nix store — only suitable for
    # non-sensitive testing or if you accept that trade-off.
    apiKey = "sk-ant-...";

    # apiKeyFile is preferred for production use: point it at a file delivered
    # by sops-nix, agenix, or any other secrets manager. The key is read at
    # runtime and never enters the Nix store.
    apiKeyFile = config.sops.secrets.anthropic-api-key.path;

    # optional, defaults are as follows or change to suit
    model = "claude-sonnet-4-6";
    maxTokens = 4096;

    # optional, not recommended (see below)
    systemPrompt = "...";
    codePromptSuffix = "...";
    chatPromptSuffix = "...";
  };
}
```

`apiKey` and `apiKeyFile` are mutually exclusive; exactly one must be set.
The module writes `~/.config/aiv/config.toml` for you and manages editor
keybindings for Helix, Vim, and Neovim.

### Manual configuration

1. Create a configuration directory and file:
   ```bash
   mkdir -p ~/.config/aiv
   ```

2. Configure your API settings in `~/.config/aiv/config.toml`:
   ```toml
   # Option 1: inline key (simpler, but the key is stored in plaintext on disk)
   api_key = "your_anthropic_api_key"

   # Option 2: read the key from a file at runtime (preferred for security)
   # api_key_file = "~/.secrets/anthropic-api-key"

   model = "claude-sonnet-4-6"
   max_tokens = 4096
   ```

   Use `api_key_file` to keep the key out of the config file itself — useful
   when the config file is version-controlled or shared, or when a secrets
   manager such as sops or pass delivers the key as a file.

3. (Optional; not recommended) Configure `sys_prompt`, `mode_chat_suffix`, and
   `mode_code_suffix`. Defaults are tested to work well with this type of
   workflow, but they are configurable if further tweaking is desired.

   - `sys_prompt` is used to set a baseline for the entire conversation. The
      default establishes a baseline personality and output style for the
      AI: terse, pipe-friendly, and format-aware. By default the model avoids
      unsolicited explanation and preserves input formatting, making it safe to
      use in shell pipelines. `aiv` passes this prompt unchanged to the API on
      every request.

   - `mode_chat_suffix` is used by the `-C` flag to layer per-request
      formatting instructions directly onto the user prompt. It nudges the model
      toward markdown and readable formatting for conversational use.

   - `mode_code_suffix` is used similarly by the `-X` flag to emit raw code
      only with caveats as comments.

## The `aiv` command

```
aiv [options] [prompt]
```

Each invocation of `aiv` builds an ordered pipeline of operations from its
arguments — adding context, sending a prompt, showing history, entering the
REPL — and executes them in sequence. This means flags can be freely combined
in a single invocation; e.g. `aiv -c foo.py -H "explain this file"` adds
context, sends the prompt, and prints history, all in one command.

#### Options

- `-c [pattern|-]`: Add context from files (filename or quoted glob pattern) or stdin (-)
- `-R, --reset`: Reset conversation thread. Prompts for confirmation unless
  invoked non-interactively with piped stdin (e.g. `echo | aiv -R`), in which
  case it resets immediately.
- `-C`: Conversational mode — appends formatting instructions to the user prompt
  that encourage markdown output with triple backticks where appropriate
- `-X`: Code-only mode — appends formatting instructions to the user prompt that
  suppress markdown and triple backtick fences; caveats are emitted as code comments.
  Recommended when piping output back into an editor or shell pipeline.
- `-i, --repl`: Launch the interactive REPL after processing any other options
  given on the command line (context, prompt, history, etc. all run first, in order,
  then the REPL takes over the terminal for further turns). If no other flags or prompt
  are provided on the command line, `-i` is assumed.
- `-H, --history [range]`: Show conversation history and exit. Combine with `-i`
  to view history and then remain in the REPL. Accepts an optional range, e.g.
  `-H 3-7`.
- `-S, --show [range]`: Show full content of one or more interactions and exit.
  Accepts an optional range, e.g. `-S 3-7`; defaults to the entire conversation
  if no range is given. Combine with `-i` to remain in the REPL afterward. You
  may also show only the *user* or *assistant* side of the turn, and specify
  raw mode if desired, like so: `-S "7 assistant -r"`. Here, raw mode means:
  don't pretty-print the output, even if the text looks like markdown.
- `-m MODEL`: Use specified model
- `-s [prompt]`: Override system prompt
- `-h, -v`: Display help/version information

Note: `-C` and `-X` are mutually exclusive. When `-i` is used without either,
`-C` is implied.

### Interactive REPL (`aiv -i`)

`aiv -i` drops into an interactive session for conversational use. It renders
responses with rich markdown display and shares the same conversation
file as any other `aiv` invocation, so context and history built up via pipes
or one-shot commands is immediately available once you enter the REPL, and
vice versa.

Prompts are submitted with **Alt-Enter** (or Escape then Enter), allowing Enter
to be used freely for multiline input.

If stdin is piped when `-i` is used (e.g. `cat file | aiv -i`), that input is
consumed before entering the loop, and the REPL reattaches to the controlling
terminal (`/dev/tty`) for interactive input afterward.

#### REPL commands

| Command | Description |
|---|---|
| `!history [range]` | Show conversation history (e.g. `!history 3-7`) |
| `!show <range> [role] [--raw\|-r]` | Show full content of one or more interactions (e.g. `!show 3-7`) |
| `!sys-prompt [prompt]` | Show or set the system prompt |
| `!chat` | Enter *chat* mode. This is the default mode in the repl. |
| `!code` | Enter *code* mode. Equivalent to `aiv -X -i` |
| `!mode [mode]` | Show or set the mode. use `default` or any value except `chat` or `code` to avoid adding any suffix to the user prompt. |
| `!delete <range>` | Delete interactions with preview and confirmation |
| `!reset` | Wipe the entire conversation with confirmation |
| `!context <path>` | Add a file to context (equivalent to `aiv -c <path>`) |
| `!help` | Show available commands |
| `!version` | Show version information |
| `!quit` / `!exit` | End the session |

## Examples

### Basic Queries
```bash
# Simple question
aiv "What is the difference between TCP and UDP?"

# Get help with shell commands
aiv "How do I find files modified in the last 24 hours?"

# Code explanation
aiv "Explain what this regex does: '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'"

# Conversational mode with markdown formatting
aiv -C "Walk me through the tradeoffs of different caching strategies"

# Interactive REPL session
aiv -i
```

### Working with Files
```bash
# Analyze a single file
aiv -c main.py "What does this script do?"

# Review multiple files
aiv -c "src/*.js" "Find potential security issues in these files"

# Compare implementations
aiv -c old_version.py -c new_version.py "What are the key differences?"

# Load context and launch REPL in one step
aiv -i -c main.py "Walk me through this file"
```

### History and Content Inspection
```bash
# Show full history and exit
aiv -H

# Show a specific range and exit
aiv --history 3-7

# Show full content of interactions 3 through 7
aiv -S 3-7

# Show full content of the entire conversation
aiv -S

# Add context, ask a question, review history, then continue in the REPL
aiv -c foo.py -H -i "How does this file fit into the project?"
```

### Pipeline Integration
```bash
# Analyze log files
tail -f /var/log/nginx/error.log | aiv "Summarize these errors"

# Process command output
ps aux | head -20 | aiv "Explain what these processes are doing"

# Git integration
git diff HEAD~1 | aiv "Review this commit for potential issues"

# System analysis
df -h | aiv "Analyze disk usage and suggest optimizations"

# Reset without confirmation in a script (piped stdin skips the prompt)
echo | aiv -R
```

### Conversation Workflows
```bash
# Start a technical discussion
aiv -C "I need to design a caching system for a web API"

# Continue the conversation (state is preserved automatically)
aiv -C "What about using Redis vs in-memory caching?"

# Add specific context
aiv -C -c current_api.py "How would this integrate with my existing API?"

# Start a fresh topic (prompts for confirmation, since this is a direct terminal invocation)
aiv -R "Completely unrelated question"
```

### Multi-context Analysis
```bash
# Analyze function within file context
cat main.rs | grep -A 20 'fn hoge()' | aiv -c main.rs "Explain this function"

# Combine different data sources
cat error.log | aiv -c "src/*.py" -c config.yaml "Why am I getting these errors?"

# Add context and generate
cat hoge.rs | aiv -c - -c "src/*.rs"
aiv "explain this context"
```

### Debugging Session
```bash
# Start debugging session
echo "This function isn't working as expected" | aiv -c buggy_code.py -c -

# Add test output
python test.py 2>&1 | aiv -c -

# Continue troubleshooting
aiv -C "This is the test output. What specific changes should I make?"
```

## Editor Integration (Helix)

AIV is optimized for Helix editor workflows. When piping text into and out of the
tool, use the `-X` flag to ensure responses are in code-ready format — no markdown
fences, no prose wrapping, just the raw output suitable for insertion into your
buffer.

The key bindings below use `Space+v` as the prefix. Add them to your
`~/.config/helix/config.toml`:

```toml
[keys.normal.space.v]
r = ":pipe aiv-extract-prompt '%{buffer_name}' '%{selection_line_start}' '%{selection_line_end}'"  # rewrite selection via inline ## prompt: comments
c = ":pipe-to aiv -X -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"  # load selection as context, no output
C = ":pipe-to aiv -X -R -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"  # load selection as context, resetting conversation
R = ":run-shell-command echo '' | aiv -X -R"  # reset conversation
f = ":run-shell-command aiv -X -c '%{buffer_name}'"  # load entire current buffer as context

[keys.select.space.v]
r = ":pipe aiv-extract-prompt '%{buffer_name}' '%{selection_line_start}' '%{selection_line_end}'"
c = ":pipe-to aiv -X -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
C = ":pipe-to aiv -X -R -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
R = ":run-shell-command echo '' | aiv -X -R"
f = ":run-shell-command aiv -X -c '%{buffer_name}'"

[keys.insert]
A-p = [":insert-output printf '## prompt: '", "move_char_right"]  # insert prompt prefix for use with the rewrite binding
```

The `aiv-extract-prompt` helper script (used by the `r` binding) reads
`## prompt: <text>` comment lines from the selected region, strips them from
the content, and passes the remaining code as context with the extracted text
as the prompt. This lets you annotate code directly with instructions and
invoke a rewrite in place. The script is included in the repository as
`scripts/aiv-extract-prompt` and should be on your `PATH`.

### Key binding summary

| Binding | Mode | Action |
|---|---|---|
| `Space+v+r` | normal / select | Rewrite selection using inline `## prompt:` comments |
| `Space+v+c` | normal / select | Load selection as context (no output) |
| `Space+v+C` | normal / select | Load selection as context, reset conversation first |
| `Space+v+R` | normal / select | Reset conversation |
| `Space+v+f` | normal / select | Load entire current buffer as context |
| `Alt+p` | insert | Insert `## prompt: ` prefix at cursor |

### 1. Add Selected Text to Context (`Alt+|`)
Select code in Helix and use pipe-ignore to add context without output:
```bash
aiv -c -
```

### 2. Generate Code After Selection (`|`)
After adding context, generate new content that gets inserted after your selection:
```bash
aiv -X "generate unit tests for this function"
```

### 3. Replace Selection with AI Response (`|`)
Replace selected text with AI-generated content:
```bash
aiv -X "refactor this code for better performance"
```

### 4. Shell Command Integration (`!`)
Use shell commands to generate content at cursor position:
```bash
aiv [-c "./*"] "create a README for this project"
```

## Mechanism

### Command Pipeline

Internally, every invocation of `aiv` is translated into an ordered list of
commands (add context, send prompt, show history, show content, reset, enter
REPL, etc.) which are executed in sequence against a shared session context.
This is the same execution path whether you're running a single one-shot
command or interacting inside the REPL — REPL commands (`!history`, `!show`,
`!context`, etc.) are the exact same operations as their command-line
equivalents (`-H`, `-S`, `-c`, etc.), just invoked interactively. There is no
subprocess indirection between the two modes.

### Output Mode Flags (-C and -X)

Rather than modifying the system prompt, `-C` and `-X` append a formatting
instruction to the user prompt for that specific request. This means:

- The system prompt is never altered, avoiding conflicts with your configured `SYS_PROMPT`
- The instruction is scoped to a single turn — subsequent messages are unaffected
  unless the flag is passed again
- The conversation JSON reflects exactly what was sent, making behaviour easy to inspect

Use `-C` for interactive, readable responses during exploration or discussion.
Use `-X` whenever output will be piped into an editor, written to a file, or
consumed by another tool.

When using `-i` (REPL mode), the chosen mode flag applies to every turn in the
session. If neither `-C` nor `-X` is given, `-C` is the default for REPL sessions.

### Context-Only Mode

When using only the `-c` option without providing a prompt and normal stdin:
- No API request is sent to save tokens
- Context is stored in the conversation file for future use
- No output is generated
- Useful for building up context before asking questions

### Confirmation Behaviour for Destructive Operations

`--reset` (and the REPL's `!delete`) ask for confirmation before wiping or
removing conversation state, except in one case: a non-interactive `aiv -R`
invocation with piped stdin skips the prompt, since that pattern implies a
scripted or automated context where no one is present to answer a y/n prompt.
Any other invocation — typed directly at a terminal, or issued from inside the
REPL — always confirms first.

### Per-Project Conversation State

AIV scopes conversation history to the current git repository:
- Inside a git repo, state is stored in `.aiv-conversation.json` at the repo root
- Outside any git repo, state falls back to `~/.config/aiv/conversation.json`
- Conversation is preserved across invocations by default
- Use `-R` or `--reset` to start a fresh conversation

Every `aiv` invocation reads and writes the same conversation file, so you can
freely switch between pipeline use and interactive use within the same session.

It is recommended to add `.aiv-conversation.json` to your global gitignore:
```bash
echo ".aiv-conversation.json" >> ~/.gitignore_global
```

### File Management

- **Conversation history (in repo)**: `.aiv-conversation.json` at repo root
- **Conversation history (fallback)**: `~/.config/aiv/conversation.json`
- **REPL input history**: `.aiv-history` at repo root (or `~/.config/aiv/.aiv-history`)
- **Configuration**: `~/.config/aiv/config.toml`

## Attribution

This project was forked from https://github.com/o8vm/aiv, a shell script by
Hayato Ohhashi, but has been completely rewritten in Python with a substantially
different architecture and feature set. The core concept — Unix pipe-friendly AI
interaction — is theirs; everything else has been rebuilt from scratch.

Major differences from the original:

- **Language**: Rewritten in Python; no longer a POSIX shell script.
- **No curl dependency**: Uses the official Anthropic Python SDK with streaming
  support.
- **Conversation format**: Stored as JSON. Existing conversation files from the
  shell version are not compatible.
- **Conversation preserved by default**: The shell version required `-e` to
  continue a thread. The Python version preserves state automatically; use
  `-R`/`--reset` to start fresh.
- **Per-project state**: Conversation is scoped to the git repo root rather than
  a single global file.
- **Interactive REPL**: A full interactive session mode (`aiv -i`) with history,
  tab completion, and rich markdown rendering.
- **Command pipeline architecture**: Every invocation — including REPL commands
  — is translated into an ordered pipeline of operations executed against a shared
  session context. Flags compose freely in a single invocation.
- **Output mode flags**: `-C` (conversational/markdown) and `-X` (code-only) append
  per-request formatting instructions to the user prompt rather than modifying the
  system prompt, keeping turns independently inspectable.
- **Glob expansion**: Handled internally and consistently when patterns are
  quoted, rather than relying on shell expansion before the script sees them.
- **Nix package and home-manager module**: First-class Nix support including a
  flake, a home-manager module, and bundled editor helper scripts.

## License

[MIT](./LICENSE)
