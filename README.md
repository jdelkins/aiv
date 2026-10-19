# AIV - AI Valve: Pipes for AI

AIV is a Python command-line utility designed for seamless integration with text
editors and terminal workflows. It allows you to interact with AI models through
Unix pipes while maintaining conversation context and providing intelligent code
location detection.

## Features

- **Editor-optimized design** for Helix and other editors
- **Terminal-friendly interface** for command-line workflows and automation
- **Interactive REPL** (`aiv -i`) with input history and tab completion
- **Per-project conversation state** scoped to the current git repository
- **Pipe-friendly interface** supporting files, globs, and stdin
- **Named provider profiles** with arbitrary names, selectable with
  `-P`/`--provider` or `!provider`
- **Three provider implementations**: `anthropic`, `openai`, and
  `openai-reasoning`
- **Per-profile configuration** for implementation type, model, credentials,
  token budget, and implementation-specific request options
- **Reasoning effort control** through `options.reasoning_effort` on
  `openai-reasoning` profiles
- **Session-state persistence** for the selected profile, model, token budget,
  API key file, system prompt, and chat/code suffix customizations
- **Streaming responses** for Anthropic and standard OpenAI profiles;
  reasoning-tier OpenAI profiles use a blocking request
- **Context-only operations** that store input without making API requests
- **Per-request output modes** via `-C` (conversational) and `-X` (code-only)
- **History and content inspection** via `-H`/`--history` and `-S`/`--show`
- **Confirmation for destructive operations**, except non-interactive resets
  with piped stdin
- **Nix flake** for installation and direct execution
- **Home-manager module** with declarative profiles and editor keybindings

## Installation

### With Nix (recommended)

Run directly:

    nix run github:jdelkins/aiv

Or install into your profile:

    nix profile install github:jdelkins/aiv

### Manual

1. Clone the repository:

       git clone https://github.com/jdelkins/aiv.git
       cd aiv

2. Install dependencies:

       pip install anthropic openai prompt-toolkit rich

   Only the SDK for the selected implementation is imported at runtime. You
   can omit `openai` if you only use Anthropic, or vice versa.

3. Install the package:

       pip install -e .

## Configuration

### Provider names and implementation types

A **provider name** identifies a configured profile, such as `claude`, `fast`,
or `deep`. Its **type** selects the implementation used to call the API:

| Type | API behavior |
|---|---|
| `anthropic` | Anthropic Messages API with streaming |
| `openai` | OpenAI Chat Completions with streaming |
| `openai-reasoning` | OpenAI Chat Completions using a developer message, `max_completion_tokens`, and a blocking request |

Multiple profiles can use the same type with different models, credentials,
token budgets, or options.

For example, `aiv -P deep` selects the profile named `deep`; its
`type = "openai-reasoning"` selects the implementation.

### Manual configuration

Create the configuration directory:

    mkdir -p ~/.config/aiv

Configure `~/.config/aiv/config.toml`:

    provider = "claude"

    [providers.claude]
    type = "anthropic"
    api_key_file = "~/.secrets/anthropic-api-key"
    model = "claude-sonnet-4-6"
    max_tokens = 4096

    [providers.fast]
    type = "openai"
    api_key_file = "~/.secrets/openai-api-key"
    model = "gpt-4o-mini"
    max_tokens = 8192

    [providers.deep]
    type = "openai-reasoning"
    api_key_file = "~/.secrets/openai-api-key"
    model = "o3-mini"
    max_tokens = 16384

    [providers.deep.options]
    reasoning_effort = "high"

Select profiles with:

    aiv -P fast "Summarize the tradeoffs between REST and gRPC"
    aiv -P deep "Investigate this concurrency bug"

The selection persists for subsequent invocations in the same conversation.

Profile names are case-sensitive, non-empty strings. Quote TOML keys containing
spaces or punctuation that would otherwise be interpreted as TOML syntax, and
quote such names when passing them through a shell.

#### Common profile fields

Each `[providers.<name>]` table supports:

| Field | Meaning |
|---|---|
| `type` | Implementation: `anthropic`, `openai`, or `openai-reasoning` |
| `api_key` | Inline API key |
| `api_key_file` | File containing the API key; expanded and read at runtime |
| `model` | Default model |
| `max_tokens` | Maximum output token budget |
| `options` | Table of implementation-specific request settings |

Prefer `api_key_file` to keep key material out of the configuration file itself.
File contents are stripped of surrounding whitespace.

In manual configuration, an inline `api_key` takes precedence if both credential
fields are present. Configure only one to avoid ambiguity; the home-manager
module enforces mutual exclusion.

#### Fallback rules

Top-level `api_key`/`api_key_file`, `model`, and `max_tokens` remain supported:

- A profile with neither credential field inherits the top-level credential
  source. Credentials inherit as a pair, never as independent fields.
- Missing `model` and `max_tokens` inherit independently from their top-level
  values.
- Without a configured token budget, `max_tokens` defaults to `4096`.
- There is no implicit model or credential fallback from the previously active
  profile. Requests fail if no model or API key is resolved.
- `options` are profile-local and never inherit from a top-level table.

Read-only and context-only operations do not require an API key or model.
However, configuration and configured key files are still loaded and validated;
missing or unreadable configured key files remain errors.

#### Legacy configuration compatibility

Existing flat configurations continue working:

    api_key_file = "~/.secrets/anthropic-api-key"
    model = "claude-sonnet-4-6"
    max_tokens = 4096

The default provider name is `anthropic`.

Profiles named `anthropic`, `openai`, or `openai-reasoning` can omit `type`;
it is inferred from the name for compatibility:

    [providers.openai]
    api_key_file = "~/.secrets/openai-api-key"
    model = "gpt-4o-mini"

These built-in names also remain selectable without a corresponding table,
using the flat fallback settings. Custom names require a configured entry
with an explicit `type`. Unknown names fail rather than silently falling back.

An explicit `type` always takes precedence over a legacy built-in profile name.

### Implementation-specific options

Options are validated by the selected adapter before creating an SDK client or
making a request. Unknown option names are rejected rather than forwarded
blindly to the SDK.

Currently:

- `anthropic` accepts no implementation-specific options.
- `openai` accepts no implementation-specific options.
- `openai-reasoning` supports `reasoning_effort`.

Example:

    [providers.deep.options]
    reasoning_effort = "high"

The reasoning adapter recognizes `none`, `minimal`, `low`, `medium`, `high`,
and `xhigh`. **Availability and accepted values depend on the selected model
and the installed SDK.** Recognition by AIV does not imply every model accepts
every value; model-specific compatibility is checked by the API.

Unspecified options are omitted from requests so API defaults apply.

Options are configuration-only: there is currently no CLI or REPL command to
override them. To switch effort levels conveniently, define separate profiles:

    provider = "reasoning-low"
    api_key_file = "~/.secrets/openai-api-key"
    model = "o3-mini"

    [providers.reasoning-low]
    type = "openai-reasoning"
    max_tokens = 8192
    options.reasoning_effort = "low"

    [providers.reasoning-high]
    type = "openai-reasoning"
    max_tokens = 16384
    options.reasoning_effort = "high"

Then:

    aiv -P reasoning-low "Outline an approach"
    aiv -P reasoning-high "Check the correctness of this algorithm"

Configuration is cached within a running process. Restart a long-running REPL
after editing `config.toml`; external session-state reload is not a general
configuration-file reload.

### Global prompts

`sys_prompt`, `mode_chat_suffix`, `mode_code_suffix`, and `prompt_marker` are
top-level settings, shared by all profiles. Put them before any TOML table
headers.

Defaults are designed for editor and pipeline workflows; customization is
optional and generally unnecessary.

- `sys_prompt` establishes the baseline personality and output style. AIV passes
  it unchanged as the system instruction for every request.
- `mode_chat_suffix` adds conversational formatting instructions to user prompts
  in chat mode.
- `mode_code_suffix` requests raw code without markdown fences in code mode.
- `prompt_marker` identifies inline instructions for extraction; the default
  is `## prompt:`.

While chat or code mode is active, `!suffix` edits that mode's suffix and persists
the change. In default/custom mode, it sets an ephemeral suffix instead.

### With the home-manager module

    { aiv, config, ... }:

    {
      imports = [ aiv.homeManagerModules.default ];

      programs.aiv = {
        enable = true;
        provider = "claude";

        providers = {
          claude = {
            type = "anthropic";
            apiKeyFile = config.sops.secrets.anthropic-api-key.path;
            model = "claude-sonnet-4-6";
            maxTokens = 4096;
          };

          fast = {
            type = "openai";
            apiKeyFile = config.sops.secrets.openai-api-key.path;
            model = "gpt-4o-mini";
            maxTokens = 8192;
          };

          deep = {
            type = "openai-reasoning";
            apiKeyFile = config.sops.secrets.openai-api-key.path;
            model = "o3-mini";
            maxTokens = 16384;
            options.reasoning_effort = "high";
          };
        };

        # Optional flat fallback settings:
        # apiKeyFile = config.sops.secrets.anthropic-api-key.path;
        # model = "claude-sonnet-4-6";
        # maxTokens = 4096;

        # Omit the module's legacy Claude model fallback when every profile
        # should supply its own model:
        model = null;

        # Optional global customizations:
        # systemPrompt = "...";
        # codePromptSuffix = "...";
        # chatPromptSuffix = "...";
        # promptMarker = "## prompt:";
      };
    }

The module:

- Writes `~/.config/aiv/config.toml`.
- Accepts arbitrary non-empty profile names.
- Requires an explicit type for custom names, while inferring legacy built-in
  names.
- Checks that the default profile is configured or is a legacy built-in name.
- Enforces mutual exclusion of `apiKey` and `apiKeyFile`, separately at the top
  level and within every profile.
- Supports TOML-compatible profile `options`, with adapter-specific validation
  performed by AIV at runtime.
- Manages editor keybindings for Helix, Vim, and Neovim.
- Adds conversation, lock, and REPL history files to Git ignores.

The module's top-level model defaults to `claude-sonnet-4-6` for compatibility.
Set `model = null` to omit that fallback. The top-level token budget defaults to
`4096`.

Inline `apiKey` values are written into the Nix store. Prefer `apiKeyFile`
with sops-nix, agenix, or another file-based secrets manager. Profile options
also go into the Nix store and must not contain secrets.

## The `aiv` command

    aiv [options] [prompt]

Each invocation builds an ordered pipeline of operations. Flags compose freely:
for example, `aiv -c foo.py -H "explain this file"` adds context, sends the
prompt, and then prints history.

### Options

- `-c, --context PATTERN`: Add context from a file or quoted glob pattern.
  Use `-` or `stdin` for piped input. Optional metadata:
  `stdin,file=PATH,range=START:END`.
- `-e, --extract PATTERN`: Extract inline prompt-marker lines, add the remaining
  content as context, and output the response. Accepts the same stdin metadata
  syntax as `--context`. Without markers, passes input through unchanged and
  stores it as context.
- `-R, --reset`: Reset conversation history. Confirms unless invoked
  non-interactively with piped stdin. Session settings survive.
- `-C, --chat`: Conversational mode, encouraging markdown where appropriate.
- `-X, --code`: Code-only mode, suppressing markdown fences and putting caveats
  in code comments. Recommended for editor replacement and pipelines.
- `-i, --repl`: Enter the REPL after other operations. With no flags or prompt,
  REPL mode is assumed.
- `-H, --history [range]`: Show history, optionally restricted to a range such
  as `3-7`.
- `-S, --show [args]`: Show full interaction content. Defaults to the entire
  conversation. Supports a range, role filter, and raw rendering, for example
  `-S "7 assistant -r"`.
- `-P, --provider NAME`: Select a named profile and load its implementation,
  options, model, credentials, and token budget. The selection persists.
- `-m, --model MODEL`: Override the active profile's model.
- `--max-tokens N`: Override the active profile's output token budget.
- `--api-key-file FILE`: Read a session credential override from a file.
  Only its path is persisted, never its contents.
- `-s, --sys-prompt PROMPT`: Override the system prompt.
- `--prompt-suffix TEXT`: Edit the current chat/code suffix, or set an ephemeral
  override in default/custom mode.
- `--prompt-marker TEXT`: Set the prompt extraction marker for the process.
- `-d, --working-directory DIR`: Change working directory before pipeline
  operations.
- `-h, --help`: Show help.
- `-v, --version`: Show version.

`-C` and `-X` are mutually exclusive. When entering the REPL in default mode,
chat mode is selected automatically.

History and show operations can be combined with `-i` to continue interactively.

## Interactive REPL

    aiv -i

The REPL renders markdown responses and shares conversation state with one-shot
and pipeline invocations.

Submit input with **Alt-Enter**, or Escape followed by Enter. Ordinary Enter
inserts a newline for multiline input. Tab completes command names, profile
names, and paths for applicable commands.

If stdin is piped, it is consumed before entering the loop. The REPL then
reattaches to `/dev/tty` for interactive input.

### REPL commands

| Command | Description |
|---|---|
| `!history [range]` | Show conversation history |
| `!show <range> [role] [--raw\|-r]` | Show full interaction content |
| `!provider [name]` | Show or select a profile; selection reloads its defaults |
| `!api-key-file <file>` | Set a file-backed credential override |
| `!model [model]` | Show or set the model |
| `!max-tokens [n]` | Show or set the token budget |
| `!sys-prompt [prompt]` | Show or set the system prompt |
| `!chat` | Enter chat mode |
| `!code` | Enter code mode |
| `!mode [chat\|code\|default]` | Show or set interaction mode |
| `!suffix [text]` | Edit the active chat/code suffix, or set an ephemeral custom suffix |
| `!prompt-marker [text]` | Show or set the extraction marker |
| `!delete <range>` | Delete interactions with preview and confirmation |
| `!reset` | Reset history with confirmation |
| `!context <path>` | Add file context |
| `!extract <path>` | Extract inline instructions and process file content |
| `!cd [directory]` | Show or change working directory |
| `!params` | Show runtime settings, including profile name, type, and options |
| `!help` | Show commands |
| `!version` | Show version |
| `!quit` / `!exit` | End the session |

## Examples

### Basic queries

    aiv "What is the difference between TCP and UDP?"
    aiv "How do I find files modified in the last 24 hours?"
    aiv -C "Walk me through the tradeoffs of different caching strategies"
    aiv -i

### Working with files

    # Analyze a file
    aiv -c main.py "What does this script do?"

    # Review a quoted glob
    aiv -c "src/*.js" "Find potential security issues"

    # Compare implementations
    aiv -c old_version.py -c new_version.py "What changed?"

    # Load context, ask a question, then enter the REPL
    aiv -i -c main.py "Walk me through this file"

### History and content inspection

    aiv -H
    aiv --history 3-7
    aiv -S
    aiv -S "3-7 assistant -r"
    aiv -c foo.py -H -i "How does this file fit into the project?"

### Profile workflows

These examples use the `claude`, `fast`, and `deep` profiles configured above.

    # Switch to a fast OpenAI profile
    aiv -P fast "Summarize the tradeoffs between REST and gRPC"

    # Subsequent invocations retain the profile selection
    aiv "What about GraphQL?"

    # Switch to a reasoning profile with configured effort
    aiv -P deep "Design a consistent-hashing scheme"

    # Explicit overrides run after profile selection, regardless of flag order
    aiv --api-key-file ~/.secrets/work-openai-key -P deep "Review this design"

    # Start a REPL with a selected profile
    aiv -P claude -i

### Pipeline integration

    # Analyze a finite snapshot of logs
    tail -n 200 /var/log/nginx/error.log | aiv "Summarize these errors"

    # Explain command output
    ps aux | head -20 | aiv "Explain what these processes are doing"

    # Review a diff
    git diff HEAD~1 | aiv "Review this commit for potential issues"

    # Analyze disk usage
    df -h | aiv "Analyze disk usage and suggest optimizations"

    # Reset without confirmation in automation
    echo | aiv -R

AIV reads piped stdin to completion before processing it. An unbounded input
such as `tail -f` must end before a request can be made.

### Conversation workflows

    aiv -C "I need to design a caching system for a web API"
    aiv -C "What about Redis versus in-memory caching?"
    aiv -C -c current_api.py "How would this integrate?"

    # A direct terminal invocation confirms before resetting
    aiv -R "Completely unrelated question"

### Multiple context sources

    cat main.rs | grep -A 20 'fn hoge()' | aiv -c main.rs "Explain this function"

    cat error.log | aiv -c "src/*.py" -c config.yaml "Why am I getting these errors?"

    # Store context without making a request
    cat hoge.rs | aiv -c - -c "src/*.rs"
    aiv "Explain this context"

### Debugging session

    echo "This function isn't working as expected" | aiv -c buggy_code.py -c -
    python test.py 2>&1 | aiv -c -
    aiv -C "What specific changes should I make?"

## Editor Integration (Helix)

Use `-X` when piping responses into a buffer so output is raw code rather than
markdown-wrapped prose.

The following bindings use `Space+v` as a prefix. Add them to
`~/.config/helix/config.toml`; the home-manager module generates equivalent
bindings using the installed package path.

    [keys.normal.space.v]
    r = ":pipe aiv -X -e 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
    c = ":pipe-to aiv -X -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
    C = ":pipe-to aiv -X -R -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
    R = ":run-shell-command echo '' | aiv -X -R"
    f = ":run-shell-command aiv -X -c '%{buffer_name}'"

    [keys.select.space.v]
    r = ":pipe aiv -X -e 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
    c = ":pipe-to aiv -X -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
    C = ":pipe-to aiv -X -R -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"
    R = ":run-shell-command echo '' | aiv -X -R"
    f = ":run-shell-command aiv -X -c '%{buffer_name}'"

    [keys.insert]
    A-p = [":insert-output printf '## prompt: '", "move_char_right"]

### Key binding summary

| Binding | Mode | Action |
|---|---|---|
| `Space+v+r` | normal / select | Rewrite selection using inline prompt comments |
| `Space+v+c` | normal / select | Store selection as context |
| `Space+v+C` | normal / select | Reset history, then store selection as context |
| `Space+v+R` | normal / select | Reset conversation history |
| `Space+v+f` | normal / select | Load the current buffer's file from disk |
| `Alt+p` | insert | Insert the prompt marker |

The file binding reads the saved file, not unsaved buffer contents.

### Inline prompt extraction

Annotate selected code with lines such as:

    ## prompt: Refactor this function without changing its behavior.

Then pipe the selection through:

    aiv -X -e -

The extraction command removes marker lines, combines their text into the
prompt, stores the remaining content as context, and outputs the AI response.
Without marker lines, it passes the input through unchanged and stores it as
context.

Metadata can identify the source location:

    aiv -X -e 'stdin,file=src/example.py,range=10:30'

The range end is reduced by the number of extracted prompt lines, treating
those comments as ephemeral tooling instructions rather than permanent code.

Extraction also works against a file:

    aiv -X -e some_file.py

### Other editor operations

Store a selection without generating output:

    aiv -c -

Replace a selection with a response:

    aiv -X "Refactor this code for better performance"

Generate content from previously stored context:

    aiv -X "Generate unit tests for this function"

Use a shell-output insertion command to generate a new document:

    aiv -X -c "./*" "Create a README for this project"

## Mechanism

### Command pipeline

CLI flags and REPL commands use the same in-process command implementations.
There is no subprocess indirection between one-shot and interactive operations.

Precedence determines execution order rather than the order flags were typed:

1. Working directory changes.
2. Destructive history resets.
3. Provider profile selection.
4. Other session settings: model, token budget, credential file, mode, system
   prompt, and extraction marker.
5. Prompt-suffix edits.
6. Context loading and extraction.
7. The positional prompt.
8. Read-only display commands.
9. REPL handoff.

Extraction can make a request during its own context/extraction operation.

Profile selection precedes explicit model, key, and budget overrides because it
loads the profile's defaults.

### Provider abstraction

Configuration resolution separates profile identity from API implementation:

- The profile name identifies configuration and is persisted in session state.
- Its type selects an adapter.
- Its options are interpreted and validated by that adapter.

Adapters translate the provider-agnostic message format into SDK requests and
normalize responses. Differences in system/developer message placement,
streaming, token-limit arguments, and truncation signaling stay inside the
adapters.

Anthropic and standard OpenAI responses stream. The `openai-reasoning`
implementation deliberately uses blocking Chat Completions requests rather than
guessing at individual models' streaming support.

Anthropic requests retain the configured automatic prompt-caching behavior.
OpenAI prefix caching is applied server-side for eligible requests without an
explicit caching option.

### Output modes

`-C` and `-X` append formatting instructions to the user prompt rather than
modifying the system prompt. Stored messages therefore reflect the prompt
actually sent to the API.

Use `-C` for readable conversation and `-X` for editor replacement, file output,
and pipelines. In the REPL, the active mode applies to subsequent turns until
changed. One-shot invocations do not persist mode selection.

### Session state

The conversation file stores messages alongside a `session_state` object
containing explicit overrides relative to configuration defaults:

- `provider`: selected profile name, relative to the configured default name.
- `model`, `max_tokens`, `api_key_file`: relative to the active profile's resolved
  defaults.
- `sys_prompt`, `mode_chat_suffix`, `mode_code_suffix`: relative to global
  defaults.

Implementation type and provider options are never persisted. They are derived
from the selected profile on startup and session-state reload.

Session state is recomputed as a pure diff after relevant changes. Settings
matching their defaults are removed rather than redundantly stored.

Selecting a profile reloads all of its defaults—even when selecting the same
profile again or switching between profiles sharing an implementation type.
Prior model, credential-file, and token-budget overrides are discarded. Missing
model or credential values clear the previous profile's values rather than
reusing them.

For example:

    aiv -P deep -m custom-model "Analyze this"

persists both the profile selection and model override. A later invocation
restores them. Selecting another profile loads that profile's defaults instead.

Only key-file paths are persisted, never resolved key material. A persisted
override file is re-read on subsequent invocations and session reload. If it
disappears or becomes unreadable, AIV fails rather than silently selecting
another credential source.

Ad-hoc suffix overrides made in default/custom mode are intentionally ephemeral.
Chat/code suffix edits are durable and included in session-state diffs. Mode
selection and runtime prompt-marker edits are not persisted.

### External changes during a REPL session

The REPL watches the conversation file while idle. When another invocation
changes it, the REPL reloads session settings and displays newly added
interactions. A settings-only change does not reprint old turns.

If the selected profile or credential source cannot be resolved, the REPL reports
the error and exits rather than continuing with stale settings.

This reload uses the process's cached configuration; restart the REPL to pick up
edits to `config.toml`.

### Context-only operations

Use `-c` without a prompt to store files or explicit stdin context without an
API request:

    aiv -c main.py
    python test.py 2>&1 | aiv -c -

No response is generated. Stored context is available to later prompts and REPL
sessions.

Without an explicit stdin context argument, piped input becomes the prompt when
no positional prompt is supplied; otherwise it becomes implicit context.

### Destructive operations

`--reset` and REPL deletion ask for confirmation, except non-interactive resets
with piped stdin:

    echo | aiv -R

Direct terminal resets and REPL resets always use confirmation behavior.
Reset clears message history only; session settings survive.

### Per-project conversation state

Inside a Git repository, AIV stores state at the repository root:

- `.aiv-conversation.json`: messages and session state
- `.aiv-conversation.lock`: conversation lock
- `.aiv-history`: REPL input history

Outside Git, state falls back to `~/.config/aiv/`:

- `conversation.json`
- `.aiv-history`

Every invocation uses the applicable conversation file, allowing pipeline and
interactive workflows to share history.

Add repository-local state files to your global Git ignore file:

    printf '%s\n' \
      '.aiv-conversation.json' \
      '.aiv-conversation.lock' \
      '.aiv-history' >> ~/.gitignore_global

Configure Git to use that file if it is not already your global excludes file.
The home-manager module manages these ignore entries automatically.

## Development and Tests

Run the Python test suite with:

    pytest -q

Provider and API unit tests mock SDK clients or the provider factory. They do
not require API keys or network access. SDK-specific adapter tests are skipped
when their optional SDK dependency is not installed.

## Attribution

This project was forked from https://github.com/o8vm/aiv, a shell script by
Hayato Ohhashi, but has been completely rewritten in Python with a substantially
different architecture and feature set. The core concept—Unix pipe-friendly AI
interaction—is theirs; everything else has been rebuilt from scratch.

Major differences from the original:

- **Python implementation** using official SDKs rather than curl.
- **Named provider profiles** with separate implementation types, credentials,
  model defaults, token budgets, and validated request options.
- **JSON conversation storage** with per-project history and session settings.
  Conversation files from the original shell version are not compatible.
- **Conversation preservation by default**; use `-R` to reset history.
- **Interactive REPL** with multiline input, history, completion, and markdown
  rendering.
- **Shared command pipeline** for CLI and REPL operations.
- **Per-turn output instructions** for conversational and code-only workflows.
- **Internal glob expansion** for consistently handled quoted patterns.
- **First-class Nix support** through a flake and home-manager module with editor
  integration.

## License

[MIT](./LICENSE)
