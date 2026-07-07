{
  lib,
  python3Packages,
  glow,
  git,
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
  ];

  # glow is a Go binary, not a Python package
  nativeBuildInputs = [
    glow
    git
  ];

  nativeCheckInputs = with python3Packages; [ pytest ];

  doCheck = true;

  checkPhase = ''
    runHook preCheck
    pytest tests/
    runHook postCheck
  '';

  meta = {
    description = "AI Valve: Pipes for AI";
    license = lib.licenses.mit;
    maintainers = [ ];
    mainProgram = "aiv";
  };
}
