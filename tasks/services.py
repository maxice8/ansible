from pyinfra.operations import systemd

for service in ("rpcbind.socket", "rpcbind.service"):
    systemd.service(
        name=f"Disable {service}",
        service=service,
        running=False,
        enabled=False,
    )
