{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.aiv;

  # Mirrors aiv.config.VALID_PROVIDERS (aiv/config.py)
  validProviders = [
    "anthropic"
    "openai"
    "openai-reasoning"
  ];

  # Per-provider submodule: mirrors a single [providers.<name>] table in
  # config.toml. All fields are optional — a provider with no entry (or with
  # some fields unset) falls back to the flat top-level apiKey/apiKeyFile/
  # model/maxTokens options, exactly as aiv.config.get_provider_settings()
  # does at runtime.
  providerOpts =
    { name, ... }:
    {
      options = {
        apiKey = lib.mkOption {
          type = with lib.types; nullOr str;
          default = null;
          description = ''
            API key for the "${name}" provider, written directly into the aiv
            config file. Mutually exclusive with apiKeyFile.
            Warning: this value will be written to the Nix store. Prefer
            apiKeyFile with a secrets manager such as sops-nix or agenix.
          '';
        };

        apiKeyFile = lib.mkOption {
          type = with lib.types; nullOr path;
          default = null;
          description = ''
            Path to a file containing the API key for the "${name}" provider.
            aiv reads and strips the file contents at runtime.
            Mutually exclusive with apiKey.
          '';
        };

        model = lib.mkOption {
          type = with lib.types; nullOr str;
          default = null;
          description = ''
            Default model for the "${name}" provider. If null, falls back to
            the top-level programs.aiv.model option.
          '';
        };

        maxTokens = lib.mkOption {
          type = with lib.types; nullOr ints.positive;
          default = null;
          description = ''
            Maximum response tokens for the "${name}" provider. If null,
            falls back to the top-level programs.aiv.maxTokens option.
          '';
        };
      };
    };

  # Build a single provider's TOML attrs, omitting unset keys so the tool's
  # own fallback-to-top-level-config logic applies.
  providerToAttrs =
    p:
    lib.filterAttrs (_k: v: v != null) {
      api_key = p.apiKey;
      api_key_file = p.apiKeyFile;
      model = p.model;
      max_tokens = p.maxTokens;
    };

  providersAttrs = lib.mapAttrs (_name: providerToAttrs) cfg.providers;

  # Top-level (legacy/fallback) attribute set; omit optional keys when null so
  # the tool's own defaults (or a matching [providers.<name>] entry) apply.
  # apiKey/apiKeyFile here are now optional — they only need to be set if you
  # want a fallback for providers with no dedicated entry in `providers`, or
  # if you're using aiv with a single provider and never touch `providers` at
  # all (the pre-multi-provider configuration shape).
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
    topLevelAttrs // (lib.optionalAttrs (cfg.providers != { }) { providers = providersAttrs; });

  aivConfigFile = (pkgs.formats.toml { }).generate "aiv-config.toml" aivConfigAttrs;
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
      type = with lib.types; nullOr (enum validProviders);
      default = null;
      description = ''
        The default active provider used when no session_state override is
        present. If null, the tool's own built-in default (anthropic) applies.
        Must be one of: ${lib.concatStringsSep ", " validProviders}.
      '';
    };

    providers = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule providerOpts);
      default = { };
      description = ''
        Per-provider configuration, written as [providers.<name>] tables in
        the aiv config file. Each attribute name must be a valid provider
        (see the assertion below); a provider with no entry here falls back
        to the top-level apiKey/apiKeyFile/model/maxTokens options.
      '';
      example = lib.literalExpression ''
        {
          anthropic.apiKeyFile = config.sops.secrets.anthropic-api-key.path;
          openai.apiKeyFile = config.sops.secrets.openai-api-key.path;
          openai.model = "gpt-4o-mini";
          openai-reasoning.apiKeyFile = config.sops.secrets.openai-api-key.path;
          openai-reasoning.model = "o3-mini";
        }
      '';
    };

    apiKey = lib.mkOption {
      type = with lib.types; nullOr str;
      default = null;
      description = ''
        API key written directly into the top level of the aiv config file.
        Acts as the fallback for any provider in `providers` without its own
        apiKey/apiKeyFile set, or as the sole provider's key if `providers` is
        left empty entirely. Mutually exclusive with apiKeyFile.
        Warning: this value will be written to the Nix store. Prefer apiKeyFile
        with a secrets manager such as sops-nix or agenix.
      '';
    };

    apiKeyFile = lib.mkOption {
      type = with lib.types; nullOr path;
      default = null;
      description = ''
        Path to a file containing the top-level fallback API key. aiv reads
        and strips the file contents at runtime. Use this with sops-nix,
        agenix, or any other secrets manager that delivers secrets as files.
        Mutually exclusive with apiKey.
      '';
    };

    model = lib.mkOption {
      type = lib.types.str;
      default = "claude-sonnet-4-6";
      description = "Top-level fallback default model used by aiv.";
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
        Default system prompt written to the aiv config file.
        If null, the tool's built-in default is used.
      '';
    };

    codePromptSuffix = lib.mkOption {
      type = with lib.types; nullOr lines;
      default = null;
      description = ''
        Prompt suffix to be added to prompts when the mode is "code".
        If null, the tool's built-in default is used.
      '';
    };

    chatPromptSuffix = lib.mkOption {
      type = with lib.types; nullOr lines;
      default = null;
      description = ''
        Prompt suffix to be added to prompts when the mode is "chat".
        If null, the tool's built-in default is used.
      '';
    };

    promptMarker = lib.mkOption {
      type = lib.types.str;
      default = "## prompt:";
      description = ''
        Marker text for the prompt to be extracted from input provided
        to "aiv --extract".
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
        assertion = lib.all (name: lib.elem name validProviders) (lib.attrNames cfg.providers);
        message = ''
          programs.aiv: providers.<name> keys must be one of: ${lib.concatStringsSep ", " validProviders}.
          Got: ${lib.concatStringsSep ", " (lib.attrNames cfg.providers)}
        '';
      }
    ]
    ++ (lib.mapAttrsToList (name: p: {
      assertion = !(p.apiKey != null && p.apiKeyFile != null);
      message = "programs.aiv.providers.${name}: apiKey and apiKeyFile are mutually exclusive.";
    }) cfg.providers);

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
