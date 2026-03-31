# Ansible playbook

## Requirements

### Ansible

A `requirements.txt` is provided to install dependencies, we recommend [uv](https://github.com/astral-sh/uv).

```
uv pip install -r requirements.txt
```

### Podman (if using Butane)

We use podman to run a butane container instead of having it in system, so podman is required if using Butane config.

### Age + SOPS

Age and Sops are used to encrypt configuration files, use your system package manager to install them.

```
# Arch Linux
pacman -S age sops
```

### Configuration

We use hostname-namespaced configuration files in the following formats:

- `vars/settings.$HOSTNAME.yaml` for Ansible configuration (see `vars/settings.example.yaml`)
- `$HOSTNAME.env` for Butane configuration (see `example.env`)

```
cp vars/settings.example.yaml vars/settings.ryuu.yaml
cp example.env ryuu.env
```

### Encrypting

Ansible and Butane read from encrypted files instead of local configuration so we need to generate a key with `age` and then encrypt them with `sops`

#### Generate key

Generate a key file, this file should **NEVER** be commited to git, save it to a secure password manager, if you clone this repo on a new machine copy it over so you can decrypt the configuration you encrypted.

```
age-keygen -o .age-key.txt
```

#### Configure .sops.yml

Replace the `age` section in `.sops.yaml` so it encrypts with your public key, you can get the public key after generating your key with `grep "public key:" .age-key.txt`.

#### Encrypt the files

With all setup you can encrypt both files

```
sops -e -i vars/settings.ryuu.yaml
sops -e -i ryuu.env
```

*Note: If you need to edit these files in the future, do not use `cat` or `nano` directly. Instead, use SOPS to decrypt and open them in your default editor on the fly:*
`sops vars/settings.ryuu.yaml`

### Deploying

There are 2 separate deployments, `butane`, and `ansible`.

#### Butane

A `Makefile` is provided that generates an ignition file by decrypting the configuration, replacing it in the template butane and then converting the butane configuration to an ignition file that can then be with `coreos-installer` to install Fedora CoreOS on a machine.

```
make ryuu
```

#### Ansible

The Ansible deployment is done after a machine can be accessed through SSH (normally by doing the Butane deployment first) to make the deployment of all the apps/services.

```
# Deploy to 'ryuu' with diffs (-D) enabled
uv run ansible-playbook -i inventory.yaml server.yaml -D -l ryuu
```