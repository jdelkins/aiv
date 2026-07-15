{
  lib,
  python3Packages,
  git,
}:

let
  pyproject = lib.importTOML ./pyproject.toml;
  nameOverrides = { };

  parseName = dep: builtins.head (builtins.match "([A-Za-z0-9_.-]+).*" dep);

  pyDeps = map (
    dep:
    let
      name = parseName dep;
    in
    python3Packages.${nameOverrides.${name} or name}
  ) pyproject.project.dependencies;
in

python3Packages.buildPythonApplication {
  pname = "aiv";
  version = pyproject.project.version;
  format = "pyproject";

  src = ./.;

  build-system = with python3Packages; [
    setuptools
  ];

  dependencies = pyDeps;

  nativeBuildInputs = [
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
