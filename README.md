# Pyinfra Deployment Stack

This repository manages the orchestration, configuration, and deployment of containerized services on infrastructure running Fedora CoreOS using pure Python with **Pyinfra**.

## Requirements

### Python & Pyinfra

A `requirements.in` is provided to track dependencies. We use [uv](https://github.com/astral-sh/uv) to manage the virtual environment.

To install dependencies locally:
```bash
uv pip compile requirements.in -o requirements.txt
uv pip sync requirements.txt
```

### Podman (if using Butane)

Podman is required on your local machine to run the Butane configuration compiler container without needing it natively installed in your operating system.

### Age + SOPS

`age` and `sops` are used to manage encrypted secrets files securely. Use your local package manager to install them:

```bash
# Arch Linux
pacman -S age sops

# macOS
brew install age sops
```

### Configuration

We use encrypted `.env` environment files to store variables and secrets. Pyinfra automatically decrypts and processes these natively on execution.

- `group_vars/servers.sops.env` for cluster-wide or group configuration (see `group_vars/example.sops.env`)
- `host_vars/$HOSTNAME.sops.env` for node-specific configuration (see `host_vars/example.sops.env`)
- `$HOSTNAME.env` for initial Butane/Ignition provisioning configuration (see `example.env`)

To bootstrap a new machine target from templates:
```bash
cp group_vars/example.sops.env group_vars/servers.sops.env
cp host_vars/example.sops.env host_vars/ryuu.sops.env
cp example.env ryuu.env
```

### Encrypting Secrets

Both Pyinfra and Butane read from encrypted configuration files. We use an asymmetric key generated with `age` to encrypt/decrypt configuration keys via `sops`.

#### 1. Generate Key

Generate an age key file. **NEVER** commit this file to git. Store it securely in a password manager. If cloning this repository onto a new controller machine, copy this file over manually to restore decryption capabilities.

```bash
age-keygen -o .age-key.txt
```

#### 2. Configure .sops.yaml

Extract your public key by running `grep "public key:" .age-key.txt` and replace the `age` identity key string inside `.sops.yaml` so rules map flawlessly to your key.

#### 3. Encrypt the Configuration

With rules defined, encrypt your staging configuration files in place:

```bash
sops -e -i group_vars/servers.sops.env
sops -e -i host_vars/ryuu.sops.env
sops -e -i ryuu.env
```

*Note: To safely view or modify an encrypted file without leaking secrets to shell histories, always use the native SOPS wraparound instead of native editors like `nano` or `cat`:*
```bash
sops group_vars/servers.sops.env
sops host_vars/ryuu.sops.env
```

## Deploying

Deployments are cleanly split into two individual phases: `butane` (for initial OS provisioning) and `pyinfra` (for state orchestration).

### Phase 1: Butane (OS Initial Provisioning)

 A `Makefile` is provided to generate a Fedora CoreOS system ignition file. It dynamically decrypts your environment secrets, passes them into the Butane blueprint, and outputs a ready-to-flash `.ign` file compatible with `coreos-installer`.

```bash
make ryuu
```

### Phase 2: Pyinfra (Service Orchestration)

Once the machine has successfully booted up from its Ignition image and is accessible via SSH, run the Pyinfra engine stack to compile custom container builds, deploy rootless container networks, load systemd Quadlets, and ensure long-term state idempotency.

```bash
# Execute deployment against host target (e.g., ryuu) with sudo elevation
uv run pyinfra inventory.py deploy.py --sudo --limit ryuu
```

## Code Quality & Static Analysis

We utilize **Ruff** for fast Python linting and code style formatting enforcement.

```bash
# Check for bugs, syntax errors, and unused components
uvx ruff check .

# Automatically apply standard format styling
uvx ruff format .
```