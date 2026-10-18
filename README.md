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
- **Multi-provider support**: Anthropic, OpenAI, and OpenAI reasoning-tier models
  (o1/o3/gpt-5-thinking-style), selectable per invocation or per REPL session
- **Per-provider configuration**: each provider can have its own model, API key,
  and max token budget, configured once and pulled in automatically on switch
- **Session state persistence**: provider, model, max token budget, API key file,
  system prompt, and mode-specific suffix customizations persist across
  invocations by being stored alongside the conversation history, not just in
  global config
- **Real-time streaming responses** via the Anthropic and OpenAI Python SDKs
  (OpenAI reasoning-tier models use a non-streaming blocking call; see Mechanism)
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
- **Home-manager module**: declarative configuration, including per-provider
  settings, and editor keybindings for Helix, Vim, and Neovim


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
   pip install anthropic openai prompt-toolkit rich
   ```
   Only the SDK(s) for the provider(s) you actually configure are imported at
   runtime, so it's fine to omit `openai` if you only ever use Anthropic, or
   vice versa — but both are listed above for simplicity.

3. Install the package:
   ```bash
   pip install -e .
   ```

## Configuration

### With the home-manager module

If you are using the provided home-manager module, configuration is handled
declaratively via `programs.aiv`. Two shapes are supported, and can be mixed:

- A flat, top-level `apiKey`/`apiKeyFile`/`model`/`maxTokens` configuration,
  suitable for a single-provider setup (or as a fallback for providers that
  don't have their own entry — see below).
- A `providers` attribute set, keyed by provider name, for configuring
  multiple providers declaratively so you can switch between them at runtime
  with `-P`/`--provider` or `!provider`.

```nix
{ aiv, config, ... }:

{
  imports = [ aiv.homeManagerModules.default ];

  programs.aiv = {
    enable = true;

    # Optional: the default active provider. Must be one of:
    # "anthropic", "openai", "openai-reasoning". If unset, the tool's own
    # built-in default (anthropic) applies.
    provider = "anthropic";

    # Per-provider configuration. Each attribute name must be a valid
    # provider; home-manager will raise an assertion otherwise. A provider
    # with no entry here (or with some fields left unset) falls back to the
    # top-level apiKey/apiKeyFile/model/maxTokens options below.
    providers = {
      anthropic = {
        apiKeyFile = config.sops.secrets.anthropic-api-key.path;
        model = "claude-sonnet-4-6";
        maxTokens = 4096;
      };
      openai = {
        apiKeyFile = config.sops.secrets.openai-api-key.path;
        model = "gpt-4o-mini";
        maxTokens = 8192;
      };
      openai-reasoning = {
        # Can point at the same key file as "openai" if it's the same account.
        apiKeyFile = config.sops.secrets.openai-api-key.path;
        model = "o3-mini";
        maxTokens = 16384;
      };
    };

    # Top-level fallback settings. Optional if every provider above sets its
    # own apiKey/apiKeyFile and model — only needed to backstop a provider
    # with a partial entry, or if you're using aiv with a single provider and
    # skip the `providers` attribute set entirely.
    # apiKey writes the key directly into the Nix store — only suitable for
    # non-sensitive testing or if you accept that trade-off.
    # apiKey = "sk-ant-...";
    apiKeyFile = config.sops.secrets.anthropic-api-key.path;
    model = "claude-sonnet-4-6";
    maxTokens = 4096;

    # optional, not recommended (see below)
    systemPrompt = "...";
    codePromptSuffix = "...";
    chatPromptSuffix = "...";
  };
}
```

Within each `providers.<name>` entry, and at the top level, `apiKey` and
`apiKeyFile` remain mutually exclusive (asserted separately for each). Unlike
earlier versions of this module, setting one is no longer *required* at the
top level — it's only needed as a fallback if a given provider's entry
doesn't fully specify its own key.

The module writes `~/.config/aiv/config.toml` for you — using the `providers`
table shape described under Manual Configuration below when `providers` is
non-empty — and manages editor keybindings for Helix, Vim, and Neovim.

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

   This flat shape configures a single provider (defaulting to `anthropic`).
   To configure multiple providers so you can switch between them at runtime,
   use the `providers` table instead (see below) — the flat fields above
   remain supported as a fallback for whichever provider has no entry in that
   table, so existing single-provider configs keep working unchanged.

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

   Both suffixes can be edited in place at runtime (and the edit persisted;
   see "Session State" below) via `!suffix`/`--prompt-suffix` while in chat or
   code mode, respectively — see the REPL commands table and Mechanism section.

### Multi-provider configuration

To configure more than one provider so you can switch between them with
`-P`/`--provider` or `!provider`, add a `providers` table to `config.toml`:

```toml
# The default provider used when no session_state override is present and no
# -P/--provider flag is given. Must be one of: anthropic, openai, openai-reasoning
provider = "anthropic"

[providers.anthropic]
api_key_file = "~/.secrets/anthropic-api-key"
model = "claude-sonnet-4-6"
max_tokens = 4096

[providers.openai]
api_key_file = "~/.secrets/openai-api-key"
model = "gpt-4o-mini"
max_tokens = 8192

[providers.openai-reasoning]
# Can point at the same key file as "openai" if it's the same account/org.
api_key_file = "~/.secrets/openai-api-key"
model = "o3-mini"
max_tokens = 16384
```

Each `[providers.<name>]` table accepts the same `api_key`/`api_key_file` and
`model`/`max_tokens` fields as the flat top-level config, scoped to that
provider only. A provider with no table entry falls back to the flat
top-level fields, so you only need to add a `[providers.*]` section for
providers you actually want distinct settings for.

`sys_prompt`, `mode_chat_suffix`, and `mode_code_suffix` remain global
settings, not provider-scoped — they apply the same way regardless of which
provider is active.

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
- `-P, --provider {anthropic|openai|openai-reasoning}`: Set the API provider
  for this and subsequent invocations. Switching providers pulls that
  provider's configured default model, API key, and max token budget
  automatically (see Configuration and Mechanism) — you generally don't need
  to also pass `-m`/`--max-tokens` unless overriding the provider's default.
- `--api-key-file FILE`: Read the API key from `FILE` and use it for the
  session, overriding whatever key is configured for the active provider. The
  key material itself is never written to disk by this flag; only the file
  path is persisted (see Session State below), and it is re-read from disk on
  each subsequent invocation.
- `--max-tokens N`: Set the max output token budget. Like `-m`, this is
  provider-scoped: switching providers resets to that provider's own
  configured `max_tokens` unless overridden again.
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

If another `aiv` invocation (one-shot or a different REPL session) changes the
active provider, model, or other session-state settings while this REPL is
idle at the prompt, the change is detected and picked up automatically — see
Session State below.

#### REPL commands

| Command | Description |
|---|---|
| `!history [range]` | Show conversation history (e.g. `!history 3-7`) |
| `!show <range> [role] [--raw\|-r]` | Show full content of one or more interactions (e.g. `!show 3-7`) |
| `!provider [name]` | Show or set the API provider (`anthropic`, `openai`, `openai-reasoning`); pulls that provider's configured model, key, and max_tokens automatically |
| `!api-key-file <file>` | Read the API key from a file and use it for the session, overriding the active provider's configured key |
| `!model [model]` | Show or set the model |
| `!max-tokens [n]` | Show or set the max output token budget |
| `!sys-prompt [prompt]` | Show or set the system prompt |
| `!chat` | Enter *chat* mode. This is the default mode in the repl. |
| `!code` | Enter *code* mode. Equivalent to `aiv -X -i` |
| `!mode [mode]` | Show or set the mode. use `default` or any value except `chat` or `code` to avoid adding any suffix to the user prompt. |
| `!suffix [text]` | While in chat or code mode, edits that mode's suffix in place (persisted; see Session State). While in default/custom mode, sets a one-off ephemeral suffix override instead (not persisted) — e.g. `!mode default` then `!suffix reply in Portuguese only` |
| `!delete <range>` | Delete interactions with preview and confirmation |
| `!reset` | Wipe the entire conversation with confirmation |
| `!context <path>` | Add a file to context (equivalent to `aiv -c <path>`) |
| `!params` | Show current runtime parameters (provider, model, mode, suffixes, etc.) |
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

### Multi-provider Workflows
```bash
# Switch to OpenAI for this and subsequent invocations, in one step
aiv -P openai "Summarize the tradeoffs between REST and gRPC"

# The switch persists — a later invocation with no -P continues using OpenAI
aiv "What about GraphQL?"

# Switch back to Anthropic; pulls its configured default model/key/max_tokens
aiv -P anthropic "Continue the discussion"

# Use a reasoning-tier OpenAI model for a harder problem, non-streaming
aiv -P openai-reasoning "Design a consistent-hashing scheme for a distributed cache"

# Override the active provider's key for one invocation (path persists, not the key)
aiv --api-key-file ~/.secrets/work-openai-key -P openai "..."

# Start a REPL already on a specific provider
aiv -P openai -i
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
`~/.config/helix/config.toml` (this is also what the home-manager module
generates automatically if you manage Helix through it — see
`programs.helix.settings.keys` in `module.nix`):

```toml
[keys.normal.space.v]
r = ":pipe aiv -X -e 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"  # rewrite selection via inline ## prompt: comments
c = ":pipe-to aiv -X -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"  # load selection as context, no output
C = ":pipe-to aiv -X -R -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"  # load selection as context, resetting conversation
R = ":run-shell-command echo '' | aiv -X -R"  # reset conversation
f = ":run-shell-command aiv -X -c '%{buffer_name}'"  # load entire current buffer as context

[keys.select.space.v]
r = ":pipe aiv -X -e 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
c = ":pipe-to aiv -X -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
C = ":pipe-to aiv -X -R -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
R = ":run-shell-command echo '' | aiv -X -R"
f = ":run-shell-command aiv -X -c '%{buffer_name}'"

[keys.insert]
A-p = [":insert-output printf '## prompt: '", "move_char_right"]  # insert prompt prefix for use with the rewrite binding
```

The `-e`/`--extract` option (used by the `r` binding above) reads
`## prompt: <text>` comment lines from the piped input, strips them from the
content, and sends the remaining code as context with the extracted text as the
prompt. This option accepts the same `stdin,file=PATH,range=L:L` metadata syntax
as `-c`/`--context` (see the Options list above) and also works directly against
a file path instead of stdin, e.g. `aiv -X -e some_file.py`. The range, if provided,
is adjusted to be accurate as if the `## prompt:` lines were not in the file, since
they are considered ephemeral tooling interactions and not a permanent part of the
code file.

### Key binding summary

| Binding | Mode | Action |
|---|---|---|
| `Space+v+r` | normal / select | Rewrite selection using inline `## prompt:` comments (`-e`/`--extract`) |
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

### 4. Rewrite In Place via Inline Prompt Comments (`|`)
Annotate code directly with `## prompt: <instruction>` comment lines, then
pipe the selection through `-e`/`--extract` to rewrite it in place — the
comment lines are stripped and used as the prompt, the remaining code is sent
as context, and the AI's response replaces the selection:
```bash
aiv -X -e -
```

### 5. Shell Command Integration (`!`)
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

Command precedence governs execution order within a single invocation
regardless of the order flags were typed: destructive resets run first,
then provider selection (since switching providers pulls that provider's
configured defaults), then other session configuration (model, max-tokens,
api-key-file, mode, sys-prompt), then prompt-suffix edits (which depend on
mode already being resolved), then context loading, then the prompt itself,
then read-only display commands, with REPL handoff always last.

### Provider Abstraction

`aiv` supports three providers, selected via `-P`/`--provider` or `!provider`:
`anthropic`, `openai`, and `openai-reasoning`. Each is implemented as a small,
self-contained module responsible for translating `aiv`'s provider-agnostic
conversation format into that provider's SDK calls and normalizing its
response back — differences in system-prompt placement (top-level `system`
parameter vs. a `system`/`developer` role message), truncation signaling
(`stop_reason` vs. `finish_reason`), streaming support, and token-limit
parameter naming (`max_tokens` vs. `max_completion_tokens`) are all contained
within the relevant provider module and never leak into the rest of the
pipeline.

`openai-reasoning` targets o1/o3/gpt-5-thinking-style models specifically and
deliberately does not stream — reasoning-tier models have had inconsistent
streaming support across releases, and `aiv`'s UX has no dependency on
incremental output, so a plain blocking call is simpler and more robust than
guessing at a given model's current capabilities.

Anthropic's prompt caching (automatic caching against the stable prefix of
system prompt + accumulated context + earlier turns) is used as-is; OpenAI's
equivalent prefix caching requires no explicit code at all, since it is
applied automatically server-side for eligible prompts.

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

### Session State

In addition to the message history, the conversation file stores a
`session_state` object recording any of the following settings that have been
explicitly changed away from their `config.toml` defaults:

- `provider`, `model`, `max_tokens`, `api_key_file` (provider-scoped — diffed
  against the active provider's own configured defaults)
- `sys_prompt`, `mode_chat_suffix`, `mode_code_suffix` (global — diffed
  against the corresponding flat `config.toml` values)

`session_state` is always a pure diff recomputed from scratch on every
relevant change, not an incrementally accumulated log — switching providers
away and back, for instance, cleanly drops any model override that was set
while a different provider was active rather than remembering it. A setting
that matches its default again is removed from `session_state` entirely
rather than persisted as a redundant entry.

This means a one-shot `aiv -P openai -m gpt-4.1 "..."` both uses that provider
and model for the current call *and* persists the switch, so the very next
`aiv` invocation — one-shot or `-i` — picks it back up automatically, with no
distinction in behavior between CLI flags and REPL commands.

The one setting intentionally **never** persisted is an ad-hoc `!suffix`
override made while in `default`/`custom` mode (e.g. `!mode default` followed
by `!suffix reply in Portuguese only`) — this is treated as a purely
in-memory, per-session override, gone once the process exits. Editing a
mode's suffix while that mode (`chat` or `code`) is already active, by
contrast, edits `mode_chat_suffix`/`mode_code_suffix` in place and *is*
persisted, since it represents a durable preference rather than a one-off
aside.

For security, `--api-key-file`/`!api-key-file` persists only the file *path*
to `session_state`, never the resolved key material itself; the file is
re-read from disk on every subsequent invocation. If a persisted path points
at a file that no longer exists by the time it's re-read — e.g. a key file
rotated or removed out from under a long-running REPL session — `aiv` fails
loudly rather than silently falling back to a different key, since there is no
safe assumption to make about which key the user actually intended at that
point.

If another `aiv` invocation changes `session_state` while a REPL session is
idle, the running REPL detects the change (it already polls the conversation
file's mtime to display externally-added turns) and re-resolves its runtime
settings from the updated `session_state` before continuing.

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
REPL — always confirms first. `--reset` only clears message history;
`session_state` (provider/model/etc. overrides) is orthogonal and survives a
reset.

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

- **Conversation history + session state (in repo)**: `.aiv-conversation.json` at repo root
- **Conversation history + session state (fallback)**: `~/.config/aiv/conversation.json`
- **REPL input history**: `.aiv-history` at repo root (or `~/.config/aiv/.aiv-history`)
- **Configuration**: `~/.config/aiv/config.toml`

## Attribution

This project was forked from https://github.com/o8vm/aiv, a shell script by
Hayato Ohhashi, but has been completely rewritten in Python with a substantially
different architecture and feature set. The core concept — Unix pipe-friendly AI
interaction — is theirs; everything else has been rebuilt from scratch.

Major differences from the original:

- **Language**: Rewritten in Python; no longer a POSIX shell script.
- **No curl dependency**: Uses the official Anthropic and OpenAI Python SDKs,
  with streaming support where applicable.
- **Multi-provider support**: Anthropic, OpenAI, and OpenAI reasoning-tier
  models are all supported, selectable per invocation or per REPL session,
  with per-provider configuration and automatic session-state persistence of
  the active choice.
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
  flake, a home-manager module (with declarative per-provider configuration),
  and bundled editor helper scripts.

## License

[MIT](./LICENSE)
