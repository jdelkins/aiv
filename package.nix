{ lib, python3Packages }:

python3Packages.buildPythonApplication {
  pname = "aiv";
  version = "0.2.0";
  format = "other";

  src = ./.;

  dependencies = with python3Packages; [
    anthropic
  ];

  installPhase = ''
    install -Dm755 aiv.py $out/bin/aiv
  '';

  meta = {
    description = "AI Valve: Pipes for AI";
    license = lib.licenses.mit;
    maintainers = [ ];
    mainProgram = "aiv";
  };
}
