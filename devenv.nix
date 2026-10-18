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
    kubectl
    kubernetes-helm
    yq-go
    ruff
    gitleaks
  ];
}
