# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Config Management for the gcp-cloud-provider charm."""

import logging
from typing import Mapping, Optional

log = logging.getLogger(__name__)


class CharmConfig:
    """Representation of the charm configuration."""

    def __init__(self, charm):
        """Creates a CharmConfig object from the configuration data."""
        self.charm = charm

    @property
    def control_node_selector(self) -> Optional[Mapping[str, str]]:
        """Parse charm config for node selector into a dict."""
        value = self.charm.config.get("control-node-selector")
        if value:
            object_value = {}
            for label in value.split(" "):
                key, value = label.split("=")
                object_value[key] = value
            return object_value
        return None

    @property
    def controller_extra_args(self) -> Mapping[str, str]:
        """Parse charm config for controller extra args into a dict."""
        elements = self.charm.config.get("controller-extra-args", "").split()
        args = {}
        for element in elements:
            if "=" in element:
                key, _, value = element.partition("=")
                args[key] = value
            else:
                args[element] = "true"
        return args

    @property
    def safe_control_node_selector(self) -> Optional[Mapping[str, str]]:
        """Parse charm config for node selector into a dict, return None on failure."""
        try:
            return self.control_node_selector
        except ValueError:
            return None

    def evaluate(self) -> Optional[str]:
        """Determine if configuration is valid."""
        try:
            self.control_node_selector
        except ValueError:
            return "Config control-node-selector is invalid."
        return None

    @property
    def available_data(self):
        """Parse valid charm config into a dict, drop keys if unset."""
        data = {}
        for key, value in self.charm.config.items():
            if key == "control-node-selector":
                value = self.safe_control_node_selector
            if key == "controller-extra-args":
                value = self.controller_extra_args
            data[key] = value

        for key, value in dict(**data).items():
            if value == "" or value is None:
                del data[key]

        return data
