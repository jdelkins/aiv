{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.aiv;
  tomlFormat = pkgs.formats.toml { };

  # Mirrors aiv.config.VALID_PROVIDER_TYPES.
  validProviderTypes = [
    "anthropic"
    "openai"
    "openai-reasoning"
  ];

  providerOpts =
    { name, ... }:
    {
      options = {
        type = lib.mkOption {
          type = with lib.types; nullOr (enum validProviderTypes);
          default = if lib.elem name validProviderTypes then name else null;
          description = ''
            Implementation type for the "${name}" provider profile.
            Must be one of: ${lib.concatStringsSep ", " validProviderTypes}.
            For compatibility, profiles named after a built-in implementation
            infer their type from their name. Custom profile names must set
            this option explicitly.
          '';
        };

        apiKey = lib.mkOption {
          type = with lib.types; nullOr str;
          default = null;
          description = ''
            API key for the "${name}" provider profile, written directly into
            the aiv config file. Mutually exclusive with apiKeyFile.
            If neither credential option is set, the profile inherits the
            top-level credential source.
            Warning: this value will be written to the Nix store. Prefer
            apiKeyFile with a secrets manager such as sops-nix or agenix.
          '';
        };

        apiKeyFile = lib.mkOption {
          type = with lib.types; nullOr path;
          default = null;
          description = ''
            Path to a file containing the API key for the "${name}" profile.
            aiv reads and strips the file contents at runtime.
            Mutually exclusive with apiKey. If neither credential option is
            set, the profile inherits the top-level credential source.
          '';
        };

        model = lib.mkOption {
          type = with lib.types; nullOr str;
          default = null;
          description = ''
            Default model for the "${name}" provider profile. If null, falls
            back to the top-level programs.aiv.model option.
          '';
        };

        maxTokens = lib.mkOption {
          type = with lib.types; nullOr ints.positive;
          default = null;
          description = ''
            Maximum response tokens for the "${name}" provider profile.
            If null, falls back to programs.aiv.maxTokens.
          '';
        };

        options = lib.mkOption {
          type = tomlFormat.type;
          default = { };
          example = {
            reasoning_effort = "high";
          };
          description = ''
            Implementation-specific request options for this profile.
            Written as [providers.<name>.options] in config.toml.
            The selected implementation validates supported option names and
            values at runtime; options are not forwarded blindly to the SDK.

            The openai-reasoning implementation supports reasoning_effort.
            Availability and accepted effort values depend on the model.
            Other implementations currently accept no options.

            Options are profile-local, have no top-level fallback, and cannot
            currently be overridden through CLI flags or REPL commands.
            Unspecified options preserve the API's defaults.
            Do not place secrets here: values are written to the Nix store.
          '';
        };
      };
    };

  providerToAttrs =
    p:
    lib.filterAttrs (_k: v: v != null) {
      type = p.type;
      api_key = p.apiKey;
      api_key_file = p.apiKeyFile;
      model = p.model;
      max_tokens = p.maxTokens;
    }
    // lib.optionalAttrs (p.options != { }) {
      options = p.options;
    };

  providersAttrs = lib.mapAttrs (_name: providerToAttrs) cfg.providers;

  # Credentials inherit as a pair. Model and token budget inherit independently.
  # Implementation-specific options never inherit from the top level.
  topLevelAttrs = lib.filterAttrs (_k: v: v != null) {
    provider = cfg.provider;
    api_key = cfg.apiKey;
    api_key_file = cfg.apiKeyFile;
    model = cfg.model;
    max_tokens = cfg.maxTokens;
    sys_prompt = cfg.systemPrompt;
    mode_code_suffix = cfg.codePromptSuffix;
    mode_chat_suffix = cfg.chatPromptSuffix;
    prompt_marker = cfg.promptMarker;
  };

  aivConfigAttrs =
    topLevelAttrs
    // lib.optionalAttrs (cfg.providers != { }) {
      providers = providersAttrs;
    };

  aivConfigFile = tomlFormat.generate "aiv-config.toml" aivConfigAttrs;

  effectiveProvider = if cfg.provider == null then "anthropic" else cfg.provider;
in
{
  options.programs.aiv = {
    enable = lib.mkEnableOption "aiv, AI Valve for editor and shell AI workflows";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      description = "The aiv package to install.";
    };

    provider = lib.mkOption {
      type = with lib.types; nullOr str;
      default = null;
      example = "deep";
      description = ''
        Default provider profile name used when no session_state override is
        present. If null, aiv defaults to "anthropic".
        Must name a configured profile or a legacy built-in implementation:
        ${lib.concatStringsSep ", " validProviderTypes}.
        Built-in names without a profile entry use top-level fallback settings.
      '';
    };

    providers = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule providerOpts);
      default = { };
      description = ''
        Named provider profiles, written as [providers.<name>] tables.
        Names may be arbitrary non-empty strings. Each custom-named profile
        must specify an implementation type.

        Missing model and maxTokens values inherit independently from the
        top-level options. A profile with neither apiKey nor apiKeyFile
        inherits the top-level credential source. Options remain profile-local.

        Selecting a profile with -P/--provider or !provider loads all of its
        defaults, even when the previous profile uses the same implementation.
        Session state persists the profile name, not its type or options.
      '';
      example = lib.literalExpression ''
        {
          claude = {
            type = "anthropic";
            apiKeyFile = config.sops.secrets.anthropic-api-key.path;
            model = "claude-sonnet-4-6";
          };
          fast = {
            type = "openai";
            apiKeyFile = config.sops.secrets.openai-api-key.path;
            model = "gpt-4o-mini";
          };
          deep = {
            type = "openai-reasoning";
            apiKeyFile = config.sops.secrets.openai-api-key.path;
            model = "o3-mini";
            maxTokens = 16384;
            options.reasoning_effort = "high";
          };
        }
      '';
    };

    apiKey = lib.mkOption {
      type = with lib.types; nullOr str;
      default = null;
      description = ''
        Top-level fallback API key, written directly into the aiv config file.
        Used by profiles with neither apiKey nor apiKeyFile configured, and by
        legacy built-in selections without a profile entry.
        Mutually exclusive with apiKeyFile.
        Warning: this value will be written to the Nix store. Prefer apiKeyFile
        with a secrets manager such as sops-nix or agenix.
      '';
    };

    apiKeyFile = lib.mkOption {
      type = with lib.types; nullOr path;
      default = null;
      description = ''
        Path to the top-level fallback API key file. aiv reads and strips its
        contents at runtime. Used by profiles with neither credential option
        configured, and by legacy built-in selections without a profile entry.
        Use with sops-nix, agenix, or another file-based secrets manager.
        Mutually exclusive with apiKey.
      '';
    };

    model = lib.mkOption {
      type = with lib.types; nullOr str;
      default = "claude-sonnet-4-6";
      description = ''
        Top-level fallback model. The default preserves legacy configurations.
        Set to null to omit the fallback when each profile specifies its own
        model. Requests without a resolved model fail rather than reusing the
        previous profile's model.
      '';
    };

    maxTokens = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4096;
      description = "Top-level fallback maximum response tokens.";
    };

    systemPrompt = lib.mkOption {
      type = with lib.types; nullOr lines;
      default = null;
      description = ''
        Default system prompt, shared by all profiles.
        If null, the tool's built-in default is used.
      '';
    };

    codePromptSuffix = lib.mkOption {
      type = with lib.types; nullOr lines;
      default = null;
      description = ''
        Prompt suffix for code mode, shared by all profiles.
        If null, the tool's built-in default is used.
      '';
    };

    chatPromptSuffix = lib.mkOption {
      type = with lib.types; nullOr lines;
      default = null;
      description = ''
        Prompt suffix for chat mode, shared by all profiles.
        If null, the tool's built-in default is used.
      '';
    };

    promptMarker = lib.mkOption {
      type = lib.types.str;
      default = "## prompt:";
      description = ''
        Marker text for extracting prompts from input to "aiv --extract".
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = !(cfg.apiKey != null && cfg.apiKeyFile != null);
        message = "programs.aiv: apiKey and apiKeyFile are mutually exclusive.";
      }
      {
        assertion =
          effectiveProvider != ""
          && (
            builtins.hasAttr effectiveProvider cfg.providers || lib.elem effectiveProvider validProviderTypes
          );
        message = ''
          programs.aiv.provider must name a configured profile or a legacy
          built-in implementation (${lib.concatStringsSep ", " validProviderTypes}).
          Got: ${effectiveProvider}
        '';
      }
    ]
    ++ lib.concatLists (
      lib.mapAttrsToList (name: p: [
        {
          assertion = name != "";
          message = "programs.aiv: provider profile names must be non-empty strings.";
        }
        {
          assertion = p.type != null;
          message = ''
            programs.aiv.providers.${name}: custom provider profiles require type.
            Must be one of: ${lib.concatStringsSep ", " validProviderTypes}.
          '';
        }
        {
          assertion = !(p.apiKey != null && p.apiKeyFile != null);
          message = "programs.aiv.providers.${name}: apiKey and apiKeyFile are mutually exclusive.";
        }
      ]) cfg.providers
    );

    home.packages = [ cfg.package ];

    xdg.configFile."aiv/config.toml".source = aivConfigFile;

    programs.git.ignores = [
      ".aiv-conversation.json" # conversation state + session_state
      ".aiv-conversation.lock" # conversation lock file
      ".aiv-history" # repl history file
    ];

    programs.helix.settings.keys = (
      let
        aiv = lib.getExe cfg.package;
        keys.space.v = {
          r = ":pipe ${aiv} -X -e 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"; # replace selection
          c = ":pipe-to ${aiv} -X -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"; # load selection as context, no output
          C = ":pipe-to ${aiv} -X -R -c 'stdin,file=%{buffer_name},range=%{selection_line_start}:%{selection_line_end}'"; # load selection as context, resetting conversation, no output
          R = ":run-shell-command echo '' | ${aiv} -X -R"; # reset conversation
          f = ":run-shell-command ${aiv} -X -c '%{buffer_name}'"; # load current buffer from its file
        };
      in
      {
        select = keys;
        normal = keys;
        insert."A-p" = [
          ":insert-output printf '%%s' '${cfg.promptMarker} '"
          "move_char_right"
        ];
      }
    );

    programs.vim.extraConfig = ''
      " ai-prompt-rewrite: pipe selection through aiv-extract-prompt
      xnoremap <leader>vr :!aiv -X -e stdin,file='%',range=line("'<"):line("'>")<CR>
      " ai-context: pipe selection to aiv (no output)
      xnoremap <leader>vc :w !aiv -X -c stdin,file=%,range=\%('<):\%('>) <CR>
      " ai-context-reset: pipe selection to aiv (reset conversation, no output)
      xnoremap <leader>vC :w !aiv -X -R -c stdin,file=%,range=\%('<):\%('>)<CR>
      " ai-reset: reset conversation
      nnoremap <leader>vR :!echo ''' \| aiv -X -R<CR>
      " ai-context-file: load current buffer from its file
      nnoremap <leader>vf :execute '!aiv -X -c ' .. shellescape(expand('%:p'))<CR>
      " insert ## prompt: prefix
      inoremap <M-p> ${cfg.promptMarker} 
    '';

    programs.neovim.initLua = ''
      -- ai-prompt-rewrite: pipe selection through aiv-extract-prompt
      vim.keymap.set('x', '<leader>vr', function()
        local file = vim.fn.expand('%:p')
        local firstline = vim.fn.line("'<")
        local lastline = vim.fn.line("'>")
        vim.cmd(firstline .. ',' .. lastline .. '!' .. 'aiv -X -e stdin,file=' .. vim.fn.shellescape(file) .. ',range=' .. firstline .. ':' .. lastline)
      end, { desc = 'ai: rewrite selection' })
      -- ai-context: pipe selection to aiv (no output)
      vim.keymap.set('x', '<leader>vc', function()
        local file = vim.fn.expand('%:p')
        local firstline = vim.fn.line("'<")
        local lastline = vim.fn.line("'>")
        vim.cmd("'<,'>w !aiv -X -c " .. vim.fn.shellescape('stdin,file=' .. file .. ',range=' .. firstline .. ':' .. lastline))
      end, { desc = 'ai: load selection as context' })
      -- ai-context-reset: pipe selection to aiv (reset conversation, no output)
      vim.keymap.set('x', '<leader>vC', function()
        local file = vim.fn.expand('%:p')
        local firstline = vim.fn.line("'<")
        local lastline = vim.fn.line("'>")
        vim.cmd("'<,'>w !aiv -X -R -c " .. vim.fn.shellescape('stdin,file=' .. file .. ',range=' .. firstline .. ':' .. lastline))
      end, { desc = 'ai: load selection as context, reset conversation' })
      -- ai-reset: reset conversation
      vim.keymap.set('n', '<leader>vR', function() vim.cmd("!echo ''' | aiv -X -R") end, { desc = 'ai: reset conversation' })
      -- ai-context-file: load current buffer from its file
      vim.keymap.set('n', '<leader>vf', function() vim.cmd('!aiv -X -c ' .. vim.fn.shellescape(vim.fn.expand('%:p'))) end, { desc = 'ai: load current buffer from its file' })
      -- insert ## prompt: prefix
      vim.keymap.set('i', '<M-p>', '${cfg.promptMarker} ', { desc = 'ai: insert prompt prefix' })
    '';
  };
}
