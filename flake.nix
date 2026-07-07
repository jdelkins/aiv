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
    # homeManagerModules is not system-specific so it lives outside eachDefaultSystem
    {
      homeManagerModules.default = import ./module.nix;
    }
    // flake-utils.lib.eachDefaultSystem (
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
