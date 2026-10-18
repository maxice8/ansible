# Workstation tools for Ubuntu bootstrap, Nix deployments and encrypted secret editing.
{ pkgs, ... }:
{
  languages.python = {
    enable = true;
    venv = {
      enable = true;
      requirements = ./requirements.txt;
    };
  };

  packages = with pkgs; [
    uv
    git
    gnumake
    openssh
    curl
    age
    sops
    nix-prefetch-docker
    ruff
    gitleaks
  ];
}
