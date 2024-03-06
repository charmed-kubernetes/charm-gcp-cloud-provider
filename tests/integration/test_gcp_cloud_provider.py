# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import shlex
import urllib.request
from pathlib import Path

import pytest
from lightkube.codecs import load_all_yaml
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import Node, Service

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
    charm = next(Path(".").glob("gcp-cloud-provider*.charm"), None)
    if not charm:
        log.info("Build Charm...")
        charm = await ops_test.build_charm(".")

    overlays = [
        ops_test.Bundle("kubernetes-core", channel="edge"),
        Path("tests/data/charm.yaml"),
    ]

    bundle, *overlays = await ops_test.async_render_bundles(*overlays, charm=charm.resolve())

    log.info("Deploy Charm...")
    model = ops_test.model_full_name
    cmd = f"juju deploy -m {model} {bundle} " + " ".join(
        f"--overlay={f} --trust" for f in overlays
    )
    rc, stdout, stderr = await ops_test.run(*shlex.split(cmd))
    assert rc == 0, f"Bundle deploy failed: {(stderr or stdout).strip()}"

    log.info(stdout)
    await ops_test.model.block_until(
        lambda: "gcp-cloud-provider" in ops_test.model.applications, timeout=60
    )

    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)


async def test_provider_ids(kubernetes):
    async for node in kubernetes.list(Node):
        assert node.spec.providerID.startswith("gce://")


async def test_loadbalancer(kubernetes):
    log.info("Starting hello-world on port=8080.")
    lb_yaml = Path("tests/data/lb-test.yaml")
    lb_content = load_all_yaml(lb_yaml.open())
    try:
        for obj in lb_content:
            await kubernetes.create(obj, obj.metadata.name)
        await kubernetes.wait(Deployment, "hello", for_conditions=["Available"])
        async for _, dep in kubernetes.watch(Service, fields={"metadata.name": "hello"}):
            if dep.status.loadBalancer.ingress:
                break
        assert dep.status.loadBalancer.ingress[0].ip
        with urllib.request.urlopen(
            f"http://{dep.status.loadBalancer.ingress[0].ip}:8080"
        ) as resp:
            assert b"Hello Kubernetes!" in resp.read()
    finally:
        for obj in lb_content:
            await kubernetes.delete(type(obj), obj.metadata.name)
