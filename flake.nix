{
  description = "AI Valve: Pipes for AI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages.default = pkgs.callPackage ./package.nix { };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            glow
            (python3.withPackages (
              ps: with ps; [
                anthropic
                prompt-toolkit
                rich
                pytest
              ]
            ))
          ];
        };
      }
    );
}
