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
    age
    sops
    kubectl
    yq-go
    ruff
    gitleaks
  ];
}
