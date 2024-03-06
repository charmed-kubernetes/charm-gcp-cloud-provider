# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Implementation of gcp specific details of the kubernetes manifests."""
import base64
import logging
import pickle
from hashlib import md5
from typing import Dict, Optional

from lightkube.codecs import AnyResource, from_dict
from lightkube.models.core_v1 import (
    ConfigMapVolumeSource,
    EnvVar,
    SecretVolumeSource,
    Toleration,
    Volume,
    VolumeMount,
)
from lightkube.models.rbac_v1 import PolicyRule
from ops.manifests import Addition, ManifestLabel, Manifests, Patch

log = logging.getLogger(__file__)
NAMESPACE = "kube-system"
SECRET_NAME = "gcp-cloud-secret"
SECRET_DATA = "gcp-creds"
GCP_CONFIG_NAME = "cloudconfig"
GCP_CONFIG_DATA = "cloud.config"


class CreateSecret(Addition):
    """Create secret for the deployment."""

    def __call__(self) -> Optional[AnyResource]:
        """Craft the secrets object for the deployment."""
        creds: Optional[str] = self.manifests.config.get(SECRET_DATA)
        if not creds:
            log.error("secret data item is Unavailable")
            return None

        b64_creds = base64.b64encode(creds.encode()).decode()
        secret_config = {SECRET_DATA: b64_creds}

        log.info("Encoding secret data for cloud-controller.")
        return from_dict(
            dict(
                apiVersion="v1",
                kind="Secret",
                type="Opaque",
                metadata=dict(name=SECRET_NAME, namespace=NAMESPACE),
                data=secret_config,
            )
        )


class CreateCloudConfig(Addition):
    """Create cloud-config for the deployment."""

    def __call__(self) -> Optional[AnyResource]:
        """Craft the ConfigMap object for the deployment."""
        log.info("Encode cloud-config for cloud-controller.")
        return from_dict(
            dict(
                apiVersion="v1",
                kind="ConfigMap",
                metadata=dict(name=GCP_CONFIG_NAME, namespace=NAMESPACE),
                data={GCP_CONFIG_DATA: "[Global]\ntoken-url = nil\nmultizone = true"},
            )
        )


class UpdateControllerDaemonSet(Patch):
    """Update the Controller DaemonSet object to target juju control plane."""

    def __call__(self, obj):
        """Update the DaemonSet object in the deployment."""
        if not (obj.kind == "DaemonSet" and obj.metadata.name == "cloud-controller-manager"):
            return
        node_selector = self.manifests.config.get("control-node-selector")
        if not isinstance(node_selector, dict):
            log.error(
                f"provider control-node-selector was an unexpected type: {type(node_selector)}"
            )
            return
        obj.spec.template.spec.nodeSelector = node_selector
        node_selector_text = " ".join('{0}: "{1}"'.format(*t) for t in node_selector.items())
        log.info(f"Applying provider Control Node Selector as {node_selector_text}")

        current_keys = {toleration.key for toleration in obj.spec.template.spec.tolerations}
        missing_tolerations = [
            Toleration(
                key=taint.key,
                value=taint.value,
                effect=taint.effect,
            )
            for taint in self.manifests.config.get("control-node-taints", [])
            if taint.key not in current_keys
        ]
        obj.spec.template.spec.tolerations += missing_tolerations
        log.info("Adding provider tolerations from control-plane")

        args = [
            ("cloud-provider", "gce"),
            ("cloud-config", f"/etc/kubernetes/config/{GCP_CONFIG_DATA}"),
            ("controllers", "*"),
            ("controllers", "-nodeipam"),
            ("v", 4),
            ("configure-cloud-routes", "false"),
            ("allocate-node-cidrs", "false"),
            ("cluster-name", self.manifests.config.get("cluster-name")),
        ]
        args += list(self.manifests.config.get("controller-extra-args").items())
        containers = obj.spec.template.spec.containers
        containers[0].args = [f"--{name}={value}" for name, value in args]
        containers[0].command = ["/usr/local/bin/cloud-controller-manager"]
        containers[0].env = [
            EnvVar("GOOGLE_APPLICATION_CREDENTIALS", f"/etc/kubernetes/creds/{SECRET_DATA}")
        ]
        containers[0].volumeMounts = [
            VolumeMount("/etc/kubernetes/config", GCP_CONFIG_NAME, readOnly=True),
            VolumeMount("/etc/kubernetes/creds", SECRET_NAME, readOnly=True),
        ]
        log.info("Adjusting container arguments")

        obj.spec.template.spec.volumes = [
            Volume(name=GCP_CONFIG_NAME, configMap=ConfigMapVolumeSource(name=GCP_CONFIG_NAME)),
            Volume(name=SECRET_NAME, secret=SecretVolumeSource(secretName=SECRET_NAME)),
        ]
        log.info("Adjusting container cloud-config secret")


class LoadBalancerSupport(Patch):
    """Update cluster role bindings to support creating Public LoadBalancers."""

    def __call__(self, obj):
        """Update the ClusterRole resource."""
        if not (
            obj.kind == "ClusterRole" and obj.metadata.name == "system:cloud-controller-manager"
        ):
            return

        if not self.manifests.config.get("enable-loadbalancers"):
            log.info("Skip Loadbalancer RBAC Rule adjustments.")
            return

        obj.rules += [
            PolicyRule(
                apiGroups=[""], verbs=["list", "patch", "update", "watch"], resources=["services"]
            ),
            PolicyRule(
                apiGroups=[""],
                verbs=["list", "patch", "update", "watch"],
                resources=["services/status"],
            ),
            PolicyRule(
                apiGroups=[""],
                verbs=["create", "list", "patch", "update", "watch"],
                resources=["configmaps"],
            ),
        ]
        log.info("Adjust Loadbalancer RBAC Rules.")


class GCPProviderManifests(Manifests):
    """Deployment Specific details for cloud-provider-gcp."""

    def __init__(self, charm, charm_config, integrator, kube_control):
        manipulations = [
            CreateCloudConfig(self),
            CreateSecret(self),
            ManifestLabel(self),
            UpdateControllerDaemonSet(self),
            LoadBalancerSupport(self),
        ]
        super().__init__(
            "cloud-provider-gcp", charm.model, "upstream/cloud_provider", manipulations
        )
        self.charm_config = charm_config
        self.integrator = integrator
        self.kube_control = kube_control

    @property
    def config(self) -> Dict:
        """Returns current config available from charm config and joined relations."""
        config = {}
        if self.integrator.is_ready:
            config[SECRET_DATA] = self.integrator.credentials
        if self.kube_control.is_ready:
            config["image-registry"] = self.kube_control.get_registry_location()
            config["control-node-taints"] = self.kube_control.get_controller_taints() or [
                Toleration("NoSchedule", "node-role.kubernetes.io/control-plane"),
                Toleration("NoSchedule", "node.cloudprovider.kubernetes.io/uninitialized", "true"),
            ]  # by default
            config["control-node-selector"] = {
                label.key: label.value for label in self.kube_control.get_controller_labels()
            } or {"juju-application": self.kube_control.relation.app.name}
            config["cluster-name"] = self.kube_control.get_cluster_tag()

        config.update(**self.charm_config.available_data)

        for key, value in dict(**config).items():
            if value == "" or value is None:
                del config[key]

        config["release"] = config.pop("provider-release", None)

        return config

    def hash(self) -> int:
        """Calculate a hash of the current configuration."""
        return int(md5(pickle.dumps(self.config)).hexdigest(), 16)

    def evaluate(self) -> Optional[str]:
        """Determine if manifest_config can be applied to manifests."""
        props = ["control-node-selector", "cluster-name", SECRET_DATA]
        for prop in props:
            value = self.config.get(prop)
            if not value:
                return f"Provider manifests waiting for definition of {prop}"
        return None
