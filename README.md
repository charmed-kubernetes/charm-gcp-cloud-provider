# gcp-cloud-provider

## Description

This subordinate charm manages the cloud controller-manager components for gcp.

## Requirements
* these polices are defined as [prerequisites](https://cloud-provider-gcp.sigs.k8s.io/prerequisites/)
* the primary unit, the gcp-integrator application must have access to create IAM Policies

## Usage

The charm requires gcp credentials and connection information, which
can be provided the `gcp-integration` relation to the [GCP Integrator charm](https://charmhub.io/gcp-integrator).

## Deployment

### Quickstart
The GCP Cloud Provider subordinate charm can be deployed alongside Charmed Kubernetes using the overlay provided in the [Charmed Kubernetes bundle repository](https://github.com/charmed-kubernetes/bundle/blob/main/overlays/gcp-overlay.yaml):

```bash
juju deploy charmed-kubernetes --overlay gcp-cloud-overlay.yaml
```

### The full process

```bash
juju deploy charmed-kubernetes
juju deploy gcp-integrator --trust
juju deploy gcp-cloud-provider

juju relate gcp-cloud-provider:certificates            easyrsa
juju relate gcp-cloud-provider:kube-control            kubernetes-control-plane
juju relate gcp-cloud-provider:external-cloud-provider kubernetes-control-plane
juju relate gcp-cloud-provider:gcp-integration         gcp-integrator

##  wait for the gcp controller daemonset to be running
# the cloud-controller will set the node's ProviderID
kubectl describe nodes |egrep "Taints:|Name:|Provider"
```

### Storage
* to access Native GCP storage, see the [GCP Storage charm](https://charmhub.io/gcp-k8s-storage).

### Details

* Requires a `charmed-kubernetes` deployment on a gcp cloud launched by juju with the `allow-privileged` flag enabled.
* Deploy the `gcp-integrator` charm into the model using `--trust` so juju provided vsphere credentials
* Deploy the `gcp-cloud-provider` charm in the model relating to the integrator and to charmed-kubernetes components
* Once the model is active/idle, the cloud-provider charm will have successfully deployed the gcp controller-manager
  in the kube-system namespace
* Taint the existing nodes so the controller will apply the correct provider id to those nodes. 
* Confirm the `ProviderID` is set on each node
* For the controller to operate, the gcp-integrator charm will apply the appropriate IAM policies and standardize the cluster-tag
* the Kubernetes-Worker and Kuberenetes-Control-Plane charms start their binaries with `--external-provider` rather than the
  in-tree switch `--cloud-provider=gcp` which has been removed starting in kubernetes 1.27


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines
on enhancements to this charm following best practice guidelines, and
[CONTRIBUTING.md](https://github.com/canonical/gcp-cloud-provider/blob/main/CONTRIBUTING.md)
for developer guidance.
