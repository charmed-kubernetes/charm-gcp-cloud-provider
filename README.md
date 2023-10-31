# aws-cloud-provider

## Description

This subordinate charm manages the cloud controller-manager components for aws.

## Requirements
* these polices are defined as [prerequisites](https://cloud-provider-aws.sigs.k8s.io/prerequisites/)
* the primary unit, the aws-integrator application must have access to create IAM Policies

## Usage

The charm requires aws credentials and connection information, which
can be provided the `aws-integration` relation to the [AWS Integrator charm](https://charmhub.io/aws-integrator).

## Deployment

### Quickstart
The AWS Cloud Provider subordinate charm can be deployed alongside Charmed Kubernetes using the overlay provided in the [Charmed Kubernetes bundle repository](https://github.com/charmed-kubernetes/bundle/blob/main/overlays/aws-overlay.yaml):

```bash
juju deploy charmed-kubernetes --overlay aws-cloud-overlay.yaml
```

### The full process

```bash
juju deploy charmed-kubernetes
juju deploy aws-integrator --trust
juju deploy aws-cloud-provider

juju relate aws-cloud-provider:certificates            easyrsa
juju relate aws-cloud-provider:kube-control            kubernetes-control-plane
juju relate aws-cloud-provider:external-cloud-provider kubernetes-control-plane
juju relate aws-cloud-provider:aws-integration         aws-integrator

##  wait for the aws controller daemonset to be running
# the cloud-controller will set the node's ProviderID
kubectl describe nodes |egrep "Taints:|Name:|Provider"
```

### Storage
* to access Native AWS storage, see the [AWS Storage charm](https://charmhub.io/aws-k8s-storage).

### Details

* Requires a `charmed-kubernetes` deployment on a aws cloud launched by juju with the `allow-privileged` flag enabled.
* Deploy the `aws-integrator` charm into the model using `--trust` so juju provided vsphere credentials
* Deploy the `aws-cloud-provider` charm in the model relating to the integrator and to charmed-kubernetes components
* Once the model is active/idle, the cloud-provider charm will have successfully deployed the aws controller-manager
  in the kube-system namespace
* Taint the existing nodes so the controller will apply the correct provider id to those nodes. 
* Confirm the `ProviderID` is set on each node
* For the controller to operate, the aws-integrator charm will apply the appropriate IAM policies and standardize the cluster-tag
* the Kubernetes-Worker and Kuberenetes-Control-Plane charms start their binaries with `--external-provider` rather than the
  in-tree switch `--cloud-provider=aws` which has been removed starting in kubernetes 1.27


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines
on enhancements to this charm following best practice guidelines, and
[CONTRIBUTING.md](https://github.com/canonical/aws-cloud-provider/blob/main/CONTRIBUTING.md)
for developer guidance.
