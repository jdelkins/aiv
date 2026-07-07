{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.aiv;

  configTemplateName = "aiv-config";

  # Build the TOML attribute set; omit optional keys when null so the tool's
  # own defaults apply. The api_key value uses the sops placeholder, which is
  # substituted at activation time and never enters the Nix store.
  aivConfigAttrs = {
    api_key = config.sops.placeholder.${cfg.sops.key};
    model = cfg.model;
    max_tokens = cfg.maxTokens;
  }
  // lib.optionalAttrs (cfg.systemPrompt != null) { sys_prompt = cfg.systemPrompt; }
  // lib.optionalAttrs (cfg.codePromptSuffix != null) { mode_code_suffix = cfg.codePromptSuffix; }
  // lib.optionalAttrs (cfg.chatPromptSuffix != null) { mode_chat_suffix = cfg.chatPromptSuffix; };

  aivConfigFile = (pkgs.formats.toml { }).generate "aiv-config.toml" aivConfigAttrs;

  aivExtractPrompt = lib.getExe' cfg.package "aiv-extract-prompt";
in
{
  options.programs.aiv = {
    enable = lib.mkEnableOption "aiv, AI Valve for editor and shell AI workflows";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      description = "The aiv package to install.";
    };

    sops = {
      file = lib.mkOption {
        type = lib.types.path;
        default = ../../secrets/${config.home.username}.yaml;
        example = "/etc/anthropic.yaml";
        description = ''
          Path to the encrypted sops store containing the Anthropic API key.
        '';
      };
      key = lib.mkOption {
        type = lib.types.str;
        example = "anthropic-api-key";
        description = ''
          Name of the sops-nix secret containing the Anthropic API key.

          The generated aiv config uses
          config.sops.placeholder.''${config.programs.aiv.sops.key} inside a
          sops template, so the actual API key is substituted at activation time
          rather than entering the Nix store.
        '';
      };
    };

    model = lib.mkOption {
      type = lib.types.str;
      default = "claude-sonnet-4-6";
      description = "Default Anthropic model used by aiv.";
    };

    maxTokens = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4096;
      description = "Maximum response tokens.";
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
  };

  config = lib.mkIf cfg.enable {
    # sops-nix home-manager module must be imported; verify its options exist.
    assertions = [
      {
        assertion = config ? sops && config.sops ? placeholder && config.sops ? templates;
        message = "programs.aiv requires the sops-nix home-manager module to be imported.";
      }
    ];

    home.packages = [
      cfg.package
      pkgs.glow
    ];

    # Declare the secret by name. The actual sopsFile can still be supplied
    # globally via `sops.defaultSopsFile`, or overridden elsewhere.
    sops.secrets.${cfg.sops.key}.sopsFile = cfg.sops.file;

    # Use the store-path TOML file as the sops template source. sops-nix reads
    # the file, substitutes any placeholders it finds (api_key here), and writes
    # the result to the destination path at activation time.
    sops.templates.${configTemplateName} = {
      file = aivConfigFile;
      path = config.xdg.configHome + "/aiv/config.toml";
    };

    programs.git.ignores = [
      ".aiv-conversation.json" # conversation state
      ".aiv-history" # repl history file
    ];

    programs.helix.settings.keys = (
      let
        aiv = lib.getExe cfg.package;
        keys.space.v = {
          r = ":pipe ${aivExtractPrompt} '%{buffer_name}' '%{selection_line_start}' '%{selection_line_end}'"; # replace selection
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
          ":insert-output printf '## prompt: '"
          "move_char_right"
        ];
      }
    );

    programs.vim.extraConfig = ''
      " ai-prompt-rewrite: pipe selection through aiv-extract-prompt
      xnoremap <leader>vr :!${aivExtractPrompt} '%' line("'<") line("'>")<CR>
      " ai-context: pipe selection to aiv (no output)
      xnoremap <leader>vc :w !aiv -X -c stdin,file=%,range=\%('<):\%('>) <CR>
      " ai-context-reset: pipe selection to aiv (reset conversation, no output)
      xnoremap <leader>vC :w !aiv -X -R -c stdin,file=%,range=\%('<):\%('>)<CR>
      " ai-reset: reset conversation
      nnoremap <leader>vR :!echo ''' \| aiv -X -R<CR>
      " ai-context-file: load current buffer from its file
      nnoremap <leader>vf :execute '!aiv -X -c ' .. shellescape(expand('%:p'))<CR>
      " insert ## prompt: prefix
      inoremap <M-p> ## prompt: 
    '';

    programs.neovim.initLua = ''
      -- ai-prompt-rewrite: pipe selection through aiv-extract-prompt
      vim.keymap.set('x', '<leader>vr', function()
        local file = vim.fn.expand('%:p')
        local firstline = vim.fn.line("'<")
        local lastline = vim.fn.line("'>")
        vim.cmd(firstline .. ',' .. lastline .. '!' .. '${aivExtractPrompt} ' .. vim.fn.shellescape(file) .. ' ' .. firstline .. ' ' .. lastline)
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
      vim.keymap.set('i', '<M-p>', '## prompt: ', { desc = 'ai: insert prompt prefix' })
    '';
  };
}
