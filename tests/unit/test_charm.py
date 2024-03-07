# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest.mock as mock
from ipaddress import ip_network
from pathlib import Path

import ops.testing
import pytest
import yaml
from ops.model import BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import GcpCloudProviderCharm

ops.testing.SIMULATE_CAN_CONNECT = True


@pytest.fixture
def harness():
    harness = Harness(GcpCloudProviderCharm)
    try:
        yield harness
    finally:
        harness.cleanup()


@pytest.fixture(autouse=True)
def mock_ca_cert(tmpdir):
    ca_cert = Path(tmpdir) / "ca.crt"
    with mock.patch.object(GcpCloudProviderCharm, "CA_CERT_PATH", ca_cert):
        yield ca_cert


@pytest.fixture()
def certificates():
    with mock.patch("charm.CertificatesRequires") as mocked:
        certificates = mocked.return_value
        certificates.ca = "abcd"
        certificates.evaluate_relation.return_value = None
        yield certificates


@pytest.fixture()
def kube_control():
    with mock.patch("charm.KubeControlRequirer") as mocked:
        kube_control = mocked.return_value
        kube_control.evaluate_relation.return_value = None
        kube_control.get_registry_location.return_value = "rocks.canonical.com/cdk"
        kube_control.get_controller_taints.return_value = []
        kube_control.get_controller_labels.return_value = []
        kube_control.get_cluster_tag.return_value = "kubernetes-4ypskxahbu3rnfgsds3pksvwe3uh0lxt"
        kube_control.get_cluster_cidr.return_value = ip_network("192.168.0.0/16")
        kube_control.relation.app.name = "kubernetes-control-plane"
        kube_control.relation.units = [f"kubernetes-control-plane/{_}" for _ in range(2)]
        yield kube_control


@pytest.fixture(autouse=True)
def gcp_integration():
    with mock.patch("charm.GCPIntegrationRequires") as mocked:
        integration = mocked.return_value
        integration.credentials = "{}"
        integration.is_ready = False
        yield integration


def test_waits_for_certificates(harness):
    harness.begin_with_initial_hooks()
    charm = harness.charm
    assert isinstance(charm.unit.status, BlockedStatus)
    assert charm.unit.status.message == "Missing required certificates"

    # Test adding the certificates relation
    rel_cls = type(charm.certificates)
    rel_cls.relation = property(rel_cls.relation.func)
    rel_cls._data = property(rel_cls._data.func)
    rel_cls._raw_data = property(rel_cls._raw_data.func)
    rel_id = harness.add_relation("certificates", "easyrsa")
    assert isinstance(charm.unit.status, WaitingStatus)
    assert charm.unit.status.message == "Waiting for certificates"
    harness.add_relation_unit(rel_id, "easyrsa/0")
    assert isinstance(charm.unit.status, WaitingStatus)
    assert charm.unit.status.message == "Waiting for certificates"
    harness.update_relation_data(
        rel_id,
        "easyrsa/0",
        yaml.safe_load(Path("tests/data/certificates_data.yaml").read_text()),
    )
    assert isinstance(charm.unit.status, BlockedStatus)
    assert charm.unit.status.message == "Missing required kube-control relation"


@mock.patch("ops.interface_kube_control.KubeControlRequirer.create_kubeconfig")
@pytest.mark.usefixtures("certificates")
def test_waits_for_kube_control(mock_create_kubeconfig, harness):
    harness.begin_with_initial_hooks()
    charm = harness.charm
    assert isinstance(charm.unit.status, BlockedStatus)
    assert charm.unit.status.message == "Missing required kube-control relation"

    # Add the kube-control relation
    rel_cls = type(charm.kube_control)
    rel_cls.relation = property(rel_cls.relation.func)
    rel_cls._data = property(rel_cls._data.func)
    rel_id = harness.add_relation("kube-control", "kubernetes-control-plane")
    assert isinstance(charm.unit.status, WaitingStatus)
    assert charm.unit.status.message == "Waiting for kube-control relation"

    harness.add_relation_unit(rel_id, "kubernetes-control-plane/0")
    assert isinstance(charm.unit.status, WaitingStatus)
    assert charm.unit.status.message == "Waiting for kube-control relation"
    mock_create_kubeconfig.assert_not_called()

    harness.update_relation_data(
        rel_id,
        "kubernetes-control-plane/0",
        yaml.safe_load(Path("tests/data/kube_control_data.yaml").read_text()),
    )
    mock_create_kubeconfig.assert_has_calls(
        [
            mock.call(charm.CA_CERT_PATH, "/root/.kube/config", "root", charm.unit.name),
            mock.call(charm.CA_CERT_PATH, "/home/ubuntu/.kube/config", "ubuntu", charm.unit.name),
        ]
    )
    assert isinstance(charm.unit.status, BlockedStatus)
    assert charm.unit.status.message == "Provider manifests waiting for definition of gcp-creds"


@pytest.mark.usefixtures("certificates", "kube_control")
def test_waits_for_config(harness: Harness, lk_client, caplog, gcp_integration):
    gcp_integration.is_ready = True
    harness.begin_with_initial_hooks()
    with mock.patch.object(lk_client, "list") as mock_list:
        mock_list.return_value = [mock.Mock(**{"metadata.annotations": {}})]
        caplog.clear()
        harness.update_config(
            {
                "control-node-selector": "something.io/my-control-node=",
            }
        )

        provider_messages = {r.message for r in caplog.records if "provider" in r.filename}

        assert provider_messages == {
            "Adding provider tolerations from control-plane",
            "Adjusting container arguments",
            "Adjusting container cloud-config secret",
            'Applying provider Control Node Selector as something.io/my-control-node: ""',
            "Encoding secret data for cloud-controller.",
            "Encode cloud-config for cloud-controller.",
            "Skip Loadbalancer RBAC Rule adjustments.",
        }

        caplog.clear()
        harness.update_config({"control-node-selector": ""})
        provider_messages = {r.message for r in caplog.records if "provider" in r.filename}

        assert provider_messages == {
            "Adding provider tolerations from control-plane",
            "Adjusting container arguments",
            "Adjusting container cloud-config secret",
            'Applying provider Control Node Selector as juju-application: "kubernetes-control-plane"',
            "Encoding secret data for cloud-controller.",
            "Encode cloud-config for cloud-controller.",
            "Skip Loadbalancer RBAC Rule adjustments.",
        }


def test_install_or_upgrade_apierror(harness: Harness, lk_client, api_error_klass):
    lk_client.apply.side_effect = [mock.MagicMock(), api_error_klass]
    harness.begin_with_initial_hooks()
    charm = harness.charm
    charm.stored.config_hash = "mock_hash"
    mock_event = mock.MagicMock()
    charm._install_or_upgrade(mock_event)
    mock_event.defer.assert_called_once()
    assert isinstance(charm.unit.status, WaitingStatus)
