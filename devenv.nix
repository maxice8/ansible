# Workstation tools for Ubuntu bootstrap, Nix deployments and encrypted secret editing.
{ pkgs, ... }:
{
  packages = with pkgs; [
    python3
    pre-commit
    git
    gnumake
    openssh
    curl
    age
    sops
    nixfmt
    nix-output-monitor
    nvd
    ruff
    gitleaks
  ];
}
