# Pinned ARM64 image for the maintained Pingvin Share X fork, absent from Nixpkgs.
# Nix verifies both the registry digest and deterministic Docker archive hash.
{ dockerTools }:
dockerTools.pullImage {
  imageName = "smp46/pingvin-share-x";
  imageDigest = "sha256:2d0d6f8388849febf11d2b5b599ac066f4b8fea59eee9b9e22c0ac8798024222";
  hash = "sha256-IIZJgyO3DwojLb4c/LUAi5HCOCm5rKNsFCUa7GSKtak=";
  finalImageName = "smp46/pingvin-share-x";
  finalImageTag = "v1.22.4";
  os = "linux";
  arch = "arm64";
}
