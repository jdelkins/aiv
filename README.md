# AIV - AI Valve: Pipes for AI

AIV is a Python command-line utility designed for seamless integration with text
editors and terminal workflows. It allows you to interact with AI models through
Unix pipes while maintaining conversation context and providing intelligent code
location detection.

## Features

- **Editor-optimized design** for seamless integration with Helix and other editors
- **Terminal-friendly interface** for command-line workflows and automation
- **Interactive REPL** (`aiv-repl` or `aiv -i`) for conversational sessions with history management
- **Smart context detection** that automatically identifies source files and line locations
- **Per-project conversation state** scoped to the current git repository
- **Pipe-friendly interface** that works with any Unix tool
- **Flexible input handling** supporting files, globs, and stdin
- **Real-time streaming responses** via the Anthropic Python SDK
- **Token-efficient context storage** - when only `-c` option is used without
  a prompt and normal stdin, context is saved to conversation file without making
  API requests
- **Per-request output mode control** via `-C` (conversational) and `-X` (code-only) flags


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
   You will also need [glow](https://github.com/charmbracelet/glow) on your PATH
   for the REPL to render markdown responses.

3. Install the package:
   ```bash
   pip install -e .
   ```

## Configuration

1. Create a configuration directory and file:
   ```bash
   mkdir -p ~/.config/aiv
   ```

2. Configure your API settings in `~/.config/aiv/config`:
   ```
   API_KEY="your_anthropic_api_key"
   MODEL="claude-sonnet-4-20250514"
   MAX_TOKENS=4096
   SYS_PROMPT="You are an expert programmer and a shell master and an expert support engineer. You value code efficiency and clarity above all things. What you write will be piped in and out of CLI programs, so do not explain anything unless explicitly asked to. In conversational responses, you may use markdown formatting including triple backticks where it aids readability. When providing direct output intended for piping, avoid triple backticks and provide only the raw result. Preserve input formatting. If I say \"code only\" or similar, please provide only code responses, without wrapping them in markdown; however, in this case, if you have important information, caveats, or usage nuances, feel free to include that information in a code comment."
   ```

### About the SYS_PROMPT setting

   The recommended system prompt above establishes a baseline personality and
   output style for the AI: terse, pipe-friendly, and format-aware. By default the
   model avoids unsolicited explanation and preserves input formatting, making it
   safe to use in shell pipelines. `aiv` passes this prompt unchanged to the API
   on every request. The `-C` and `-X` flags then layer per-request formatting
   instructions directly onto the user prompt — `-C` nudges the model toward
   markdown and readable formatting for conversational use, while `-X` instructs it
   to emit raw code only with caveats as comments. This separation means the system
   prompt sets a sensible default, and the mode flags override formatting behaviour
   only for the turn they are applied to, without permanently altering the session.

## Tools

### `aiv` — pipe-oriented CLI

```
aiv [options] [prompt]
```

#### Options

- `-c [pattern|-]`: Add context from files (filename or quoted glob pattern) or stdin (-)
- `-R, --reset`: Reset conversation thread
- `-C`: Conversational mode — appends formatting instructions to the user prompt
  that encourage markdown output with triple backticks where appropriate
- `-X`: Code-only mode — appends formatting instructions to the user prompt that
  suppress markdown and triple backtick fences; caveats are emitted as code comments.
  Recommended when piping output back into an editor or shell pipeline.
- `-i, --repl`: Launch the interactive REPL. If a prompt or context files are
  also supplied, they are processed as the first turn inside the REPL (with output
  rendered through `glow`) before the interactive prompt appears.
- `-m MODEL`: Use specified model
- `-s [prompt]`: Override system prompt
- `-h, -v`: Display help/version information

Note: `-C` and `-X` are mutually exclusive. When `-i` is used without either,
`-C` is implied.

### `aiv-repl` — interactive REPL

`aiv-repl` provides an interactive session for conversational use. It is
equivalent to `aiv -i` with no initial prompt. It renders responses via `glow`
for rich markdown display and shares the same conversation file as `aiv`, so
context built up in one tool is immediately available in the other.

Prompts are submitted with **Alt-Enter** (or Escape then Enter), allowing Enter
to be used freely for multiline input.

#### REPL commands

| Command | Description |
|---|---|
| `!history [range]` | Show conversation history (e.g. `!history 3-7`) |
| `!show <num> [role] [--raw\|-r]` | Show full content of an interaction |
| `!delete <range>` | Delete interactions with preview and confirmation |
| `!reset` | Wipe the entire conversation with confirmation |
| `!context <path>` | Add a file to context (equivalent to `aiv -c <path>`) |
| `!help` | Show available commands |
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
# or equivalently:
aiv-repl
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
```

### Conversation Workflows
```bash
# Start a technical discussion
aiv -C "I need to design a caching system for a web API"

# Continue the conversation (state is preserved automatically)
aiv -C "What about using Redis vs in-memory caching?"

# Add specific context
aiv -C -c current_api.py "How would this integrate with my existing API?"

# Start a fresh topic
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

### Smart Location Detection

When you pipe code through AIV, it automatically:
- Identifies the source file using content matching
- Finds the exact line range in the file
- Adds location context like `[src/main.rs:45:67]`

This helps the AI provide more precise, location-aware assistance.

### Context-Only Mode

When using only the `-c` option without providing a prompt and normal stdin:
- No API request is sent to save tokens
- Context is stored in the conversation file for future use
- No output is generated
- Useful for building up context before asking questions

### Per-Project Conversation State

AIV scopes conversation history to the current git repository:
- Inside a git repo, state is stored in `.aiv-conversation.json` at the repo root
- Outside any git repo, state falls back to `~/.config/aiv/conversation.json`
- Conversation is preserved across invocations by default
- Use `-R` or `--reset` to start a fresh conversation

Both `aiv` and `aiv-repl` read and write the same conversation file, so you can
freely switch between pipeline use and interactive use within the same session.

It is recommended to add `.aiv-conversation.json` to your global gitignore:
```bash
echo ".aiv-conversation.json" >> ~/.gitignore_global
```

### File Management

- **Conversation history (in repo)**: `.aiv-conversation.json` at repo root
- **Conversation history (fallback)**: `~/.config/aiv/conversation.json`
- **REPL input history**: `.aiv-history` at repo root (or `~/.config/aiv/.aiv-history`)
- **Configuration**: `~/.config/aiv/config`

## Differences from Shell Version

- **Conversation file**: Now stored as JSON. Existing conversation files from
  the shell version are not compatible.
- **Conversation is preserved by default**: The shell version required `-e` to
  continue a thread. The Python version preserves state automatically; use
  `-R`/`--reset` to start fresh.
- **Per-project state**: Conversation is scoped to the git repo root rather than
  being a single global file.
- **Glob expansion**: The shell version relied on the shell to expand glob
  patterns before they reached the script when unquoted. The Python version
  handles glob expansion internally and behaves consistently whether patterns are
  quoted or unquoted.
- **No curl dependency**: HTTP is handled natively via the Anthropic Python SDK
  rather than shelling out to `curl`.
- **Streaming**: Responses are streamed to stdout in real time as before, but
  via the SDK's streaming interface rather than raw HTTP chunked transfer.
- **`-r` flag removed**: The shell version attempted to repeat the stdin portion
  of the input. This flag is not present in the Python version.
- **Output mode flags**: `-C` and `-X` are new. They inject per-request
  formatting instructions into the user prompt rather than altering the system
  prompt, keeping behaviour predictable and the system prompt stable.
- **Integrated REPL**: `aiv -i` launches an interactive session directly, optionally
  with an initial prompt and context files that are processed as the first REPL turn.

## License

MIT License

---

AIV transforms both your terminal and editor into an AI-powered development
environment, making it easy to get contextual assistance without disrupting
your workflow.
