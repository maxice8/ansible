# Workload enforcement plan

Do not apply this plan as one change. Use Kubernetes Pod Security Admission (PSA). Pin all policy versions to `v1.36`.

Tick an action after you complete it. Tick a workload after you complete all its actions. Tick a namespace after you complete all its workloads.

## Rollout method

- [x] Add `audit=restricted` and `warn=restricted` only to namespaces that enforce `baseline` or `restricted`.
- [x] Run the server-side dry-run for each namespace.
- [x] Change the listed workloads.
- [x] Test each changed workload.
- [x] Add `enforce=restricted` or `enforce=baseline` only when the dry-run has no warning.
- [x] Set enforce, audit, and warn to `privileged` for homelab system and host-access namespaces.
- [x] Change `backrest`, `forgejo-runner`, and `netbird` from restricted audit and warn to privileged audit and warn.
- [x] Set the K3s Pod Security admission defaults to `restricted` at version `v1.36`.
- [x] Configure the Rancher v2.15 namespace exemptions in the K3s Pod Security admission configuration.
- [x] Set `service-account-extend-token-expiration=false` for the K3s API server.
- [x] Restart K3s and verify the Rancher, Fleet, certificate, ingress, and compliance workloads.

Use this command before each baseline or restricted enforcement change:

```sh
kubectl label namespace NAMESPACE \
  pod-security.kubernetes.io/enforce=LEVEL \
  pod-security.kubernetes.io/enforce-version=v1.36 \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/audit-version=v1.36 \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/warn-version=v1.36 \
  --overwrite --dry-run=server
```

Use this command for a homelab privileged namespace:

```sh
kubectl label namespace NAMESPACE \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/enforce-version=v1.36 \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/audit-version=v1.36 \
  pod-security.kubernetes.io/warn=privileged \
  pod-security.kubernetes.io/warn-version=v1.36 \
  --overwrite --dry-run=server
```

Rancher system exemptions belong in the K3s Pod Security admission configuration and must not use PSA namespace labels.

## Application namespaces

- [x] `argus`: target `restricted`.
  - [x] Deployment `argus`:
    - [x] Add `runAsNonRoot: true` to the pod security context.
    - [x] Keep UID and GID `911`.
    - [x] Run the update dry-run.
    - [x] Test the dashboard and its WebSocket connection.
- [x] `asf`: target `restricted`.
  - [x] Deployment `asf`:
    - [x] Add `runAsNonRoot: true` to the pod security context.
    - [x] Keep UID and GID `976`.
    - [x] Run the update dry-run.
    - [x] Test login and Steam connectivity.
- [x] `whoami`: target `restricted`.
  - [x] Deployment `whoami`:
    - [x] Do not change the pod.
    - [x] Add the restricted namespace labels.
    - [x] Test the HTTPS route.
- [x] `pomerium`: target `restricted`.
  - [x] Deployment `pomerium`:
    - [x] Set a fixed non-root UID and GID.
    - [x] Add `runAsNonRoot: true`.
    - [x] Keep all capabilities dropped.
    - [x] Test all protected routes before enforcement.
- [x] `pingvin-share`: target `baseline` first, then `restricted`.
  - [x] Deployment `pingvin-share`:
    - [x] Add the baseline namespace labels first.
    - [x] Select a fixed non-root UID and GID.
    - [x] Verify the PVC ownership and change it during a planned stop if needed.
    - [x] Remove `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID`, and `SETUID`.
    - [x] Add `runAsNonRoot: true` and `seccompProfile: RuntimeDefault`.
    - [x] Test uploads, downloads, and image changes.
    - [x] Change enforcement from baseline to restricted.
- [x] `pocket-id`: target `baseline` first, then `restricted`.
  - [x] Deployment `pocket-id`:
    - [x] Add the baseline namespace labels first.
    - [x] Select a fixed non-root UID and GID.
    - [x] Verify the data PVC ownership; stop Pocket ID before changing it if needed.
    - [x] Remove `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID`, and `SETUID`.
    - [x] Add `runAsNonRoot: true` and `seccompProfile: RuntimeDefault`.
    - [x] Start one replica and test login.
    - [x] Change enforcement from baseline to restricted.
- [x] `syncthing`: target `baseline` first, then `restricted`.
  - [x] Deployment `syncthing`:
    - [x] Replace pod `hostPort` fields with a K3s `LoadBalancer` Service for TCP 22000, UDP 22000, and UDP 21027.
    - [x] Keep the web UI on its ClusterIP Service.
    - [x] Add the baseline namespace labels.
    - [x] Verify the data PVC ownership; stop Syncthing before changing it if needed.
    - [x] Remove `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID`, and `SETUID`.
    - [x] Add `runAsNonRoot: true`, `runAsUser: 977`, and `runAsGroup: 977`.
    - [x] Test local discovery, TCP sync, QUIC sync, and file writes.
    - [x] Change enforcement from baseline to restricted.
- [x] `forgejo`: target `restricted`.
  - [x] Deployment `forgejo`:
    - [x] Replace the SSH `hostPort` with a K3s `LoadBalancer` Service on port 23.
    - [x] Keep HTTP on the current ClusterIP Service and HTTPRoute.
    - [x] Keep the current non-root security context.
    - [x] Test Git over HTTPS and SSH.
  - [x] Deployment `forgejo-runner`:
    - [x] Move the runner, its ConfigMap, and its Secret to `forgejo-runner`.
- [x] `forgejo-runner`: keep `privileged`.
- [x] `netbird`: keep `privileged`.
- [x] `netbird-dashboard`: keep `baseline`.
  - [x] Deployment `netbird-dashboard`:
    - [x] Add the baseline namespace labels first.
    - [x] Keep the upstream-supported root NGINX runtime.
    - [x] Keep restricted audit and warning labels for future hardening.
    - [x] Test the dashboard and API calls.
- [x] `backrest`: keep `privileged`.

## Platform namespaces

- [x] `argocd`: target `restricted`.
  - [x] Argo CD workloads:
    - [x] Do not change the workloads.
    - [x] Add the restricted namespace labels.
    - [x] Sync a test application.
- [x] `gateway-system`: target `restricted`.
  - [x] Gateway and certificate resources:
    - [x] Do not change the resources.
    - [x] Add the restricted namespace labels.
    - [x] Test staging and production certificates.
- [x] `sops-secrets-operator`: target `restricted`.
  - [x] Deployment `sops-secrets-operator`:
    - [x] Do not change the workload.
    - [x] Add the restricted namespace labels.
    - [x] Decrypt a test secret.
- [x] `cert-manager`: keep `privileged` as a Rancher system exemption.
- [x] `traefik`: keep `privileged`.
- [x] `netdata`: keep `privileged`.
- [x] `compliance-operator-system`: keep `privileged`.
- [x] `default`: target `restricted`.
  - [x] Namespace:
    - [x] Keep the namespace empty.
    - [x] Inherit the restricted K3s admission defaults without namespace labels.

## Rancher and Kubernetes namespaces

- [x] `calico-apiserver`, `calico-system`, `cattle-alerting`, `cattle-capi-system`, `cattle-csp-adapter-system`, `cattle-elemental-system`, `cattle-epinio-system`, `cattle-externalip-system`, `cattle-fleet-local-system`, `cattle-fleet-system`, `cattle-gatekeeper-system`, `cattle-global-data`, `cattle-global-nt`, `cattle-impersonation-system`, `cattle-istio`, `cattle-istio-system`, `cattle-logging`, `cattle-logging-system`, `cattle-monitoring-system`, `cattle-neuvector-system`, `cattle-prometheus`, `cattle-provisioning-capi-system`, `cattle-resources-system`, `cattle-sriov-system`, `cattle-system`, `cattle-turtles-system`, `cattle-ui-plugin-system`, `cattle-windows-gmsa-system`, `cert-manager`, `cis-operator-system`, `compliance-operator-system`, `fleet-default`, `fleet-local`, `istio-system`, `kube-node-lease`, `kube-public`, `kube-system`, `longhorn-system`, `rancher-alerting-drivers`, `rancher-compliance-system`, `security-scan`, `sr-operator-system`, `tigera-operator`, and `traefik`: use the Rancher v2.15 Pod Security admission exemptions without PSA namespace labels.
- [x] Rancher-generated `local`, `p-*`, and `user-*` namespaces:
  - [x] Rancher resources:
    - [x] Do not manage these namespaces with Argo CD.
    - [x] Do not change their labels by hand.
    - [x] Inherit the restricted workload policy in each namespace that Rancher creates inside a project.

## Completion checks

- [x] Run `kubectl get namespaces --show-labels` and record each policy level.
- [x] Run `kubectl get events -A --field-selector reason=FailedCreate` after each enforcement change.
- [x] Run `kubectl get pods -A` and confirm that all pods are ready.
- [x] Run the Rancher Compliance scan again.
- [x] Record each accepted exception and its reason.
