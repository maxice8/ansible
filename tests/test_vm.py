"""Small offline checks for cache planning and ownership of VM shutdown."""

import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import deploy
from tests.vm import NixVM


def main():
    source = Path("/tmp/source")
    drv = "/nix/store/" + "a" * 32 + "-probe.drv"
    for system, needed in [("aarch64-linux", True), ("x86_64-linux", False)]:
        with (
            patch.object(
                deploy.subprocess,
                "run",
                return_value=SimpleNamespace(
                    stderr=f"this derivation will be built:\n  {drv}\n"
                ),
            ),
            patch.object(
                deploy.subprocess,
                "check_output",
                return_value=json.dumps({"derivations": {drv: {"system": system}}}),
            ),
        ):
            assert deploy.needs_arm_builder(source, "probe") is needed
    with (
        patch.object(deploy.subprocess, "run", return_value=SimpleNamespace(stderr="")),
        patch.object(deploy.subprocess, "check_output") as graph,
    ):
        assert not deploy.needs_arm_builder(source, "cached")
        graph.assert_not_called()
    with tempfile.TemporaryDirectory() as directory:
        vm = NixVM(Path(directory))
        with (
            patch.object(
                deploy,
                "needs_arm_builder",
                side_effect=subprocess.CalledProcessError(1, ["nix"]),
            ),
            patch.object(vm, "prepare") as start,
        ):
            try:
                deploy.build(source, "broken", "auto", vm)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("Evaluation failure was suppressed")
            start.assert_not_called()
        with patch.object(vm, "stop") as stop:
            with vm:
                pass
            stop.assert_not_called()
            try:
                with vm:
                    vm.started = True
                    raise RuntimeError("synthetic build failure")
            except RuntimeError:
                pass
            stop.assert_called_once()
        runtime = vm.directory / "runtime"
        runtime.mkdir()
        (runtime / "store.img").write_text("disposable boot image")
        with patch.object(vm, "pid", return_value=None):
            vm.stop()
        assert not runtime.exists()
        with (
            patch.object(vm, "pid", side_effect=[123, None]),
            patch.object(
                vm,
                "ssh",
                side_effect=[
                    subprocess.CalledProcessError(255, ["ssh"]),
                    SimpleNamespace(stdout="mashu-test\n"),
                ],
            ),
            patch(
                "tests.vm.subprocess.run", return_value=SimpleNamespace(returncode=0)
            ),
            patch("tests.vm.time.sleep") as wait,
        ):
            vm.stop()
            wait.assert_called_once_with(3)
        vm.__exit__(None, None, None)
    print(
        "PASS cache planning, evaluation errors, shutdown ownership and startup retry"
    )


if __name__ == "__main__":
    main()
