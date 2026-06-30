{
  lib,
  python3Packages,
  glow,
}:

python3Packages.buildPythonApplication {
  pname = "aiv";
  version = "0.3.0";
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
  nativeBuildInputs = [ glow ];

  meta = {
    description = "AI Valve: Pipes for AI";
    license = lib.licenses.mit;
    maintainers = [ ];
    # aiv is the primary entry point; aiv-repl is also installed
    mainProgram = "aiv";
  };
}
