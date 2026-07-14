{
  lib,
  python3Packages,
  git,
  bash,
  gnused,
  makeWrapper,
}:

let
  pyproject = lib.importTOML ./pyproject.toml;
in

python3Packages.buildPythonApplication {
  pname = "aiv";
  version = pyproject.project.version;
  format = "pyproject";

  src = ./.;

  build-system = with python3Packages; [
    setuptools
  ];

  dependencies = with python3Packages; [
    anthropic
    prompt-toolkit
    rich
    filelock
  ];

  nativeBuildInputs = [
    git
    makeWrapper
  ];

  nativeCheckInputs = with python3Packages; [ pytest ];

  doCheck = true;

  checkPhase = ''
    runHook preCheck
    pytest tests/
    runHook postCheck
  '';

  postInstall = ''
    install -Dm755 scripts/aiv-extract-prompt $out/bin/aiv-extract-prompt
    wrapProgram $out/bin/aiv-extract-prompt \
      --prefix PATH : ${
        lib.makeBinPath [
          bash
          gnused
          git
        ]
      }:$out/bin
  '';

  meta = {
    description = "AI Valve: Pipes for AI";
    license = lib.licenses.mit;
    maintainers = [ ];
    mainProgram = "aiv";
  };
}
