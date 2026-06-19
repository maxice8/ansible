# Pyinfra Deployment Stack

This repository manages the orchestration, configuration, and deployment of containerized services on infrastructure running Fedora CoreOS using pure Python with [Pyinfra](https://github.com/pyinfra-dev/pyinfra).

## Requirements

### Python & Pyinfra

Use our `requirements.txt` to install the required python packages. I recommend [uv](https://github.com/astral-sh/uv).

```bash
uv pip sync requirements.txt
```

### Podman (if using Butane)

Podman is required to configure the Ignition file with Butane.

### Age + SOPS

[age](https://github.com/filosottile/age) and [sops](https://github.com/getsops/sops) are used to manage encrypted secrets files securely. To install using pacman in Arch Linux:

```bash
pacman -S age sops
```

### Configuration

Sops-encrypted `.env` files are used to store variables and secrets. Pyinfra automatically decrypts and processes these natively on execution.

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

Both Pyinfra and Butane read from encrypted configuration files. Use `age` to encrypt/decrypt configuration keys via `sops`.

#### 1. Generate Key

Generate an age key file. **NEVER** commit this file to git. Store it securely in a password manager. If cloning this repository onto a new machine, copy the file over manually to restore decryption capabilities.

```bash
age-keygen -o .age-key.txt
```

#### 2. Configure .sops.yaml

Extract the public key by running `grep "public key:" .age-key.txt` and replace the `age` identity key string inside `.sops.yaml` so rules map flawlessly to your key.

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

Deployments are split into `butane` (for initial OS provisioning) and `pyinfra` (for state orchestration).

### Butane

 A `Makefile` is provided to generate a Fedora CoreOS system ignition file. It dynamically decrypts your environment secrets, passes them into the Butane blueprint, and outputs a ready-to-flash `.ign` file compatible with `coreos-installer`.

```bash
make ryuu
```

### Pyinfra

Use pyinfra to deploy the services.

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