from __future__ import annotations

import os
from typing import Optional

import requests

from pollect.core.ValueSet import ValueSet, Value
from pollect.sources.Source import Source
from pollect.libs.vmware.vsphere import Vsphere


class VSphereSource(Source):
    value: Optional[int] = None

    def __init__(self, config):
        super().__init__(config)

        self.vsphere_endpoint = config['vsphere_endpoint']
        vsphere_username_env = config['vsphere_username_env_var']
        self.vsphere_username = os.environ.get(vsphere_username_env)
        vsphere_password_env = config['vsphere_password_env_var']
        self.vsphere_password = os.environ.get(vsphere_password_env)
        self.worker_threads = config.get("worker_threads", 8)

        self.scrape_policy = config.get("scrape_policy", "auto")

        if self.scrape_policy == 'manual':
            self.targets = config["targets"]
        if self.scrape_policy == 'auto':
            self.targets = self._get_targets()

        self.energy_api_endpoint = config["energy_api_endpoint"]

        self.vsphere = Vsphere(endpoint=self.vsphere_endpoint, username=self.vsphere_username,
                               password=self.vsphere_password,
                               logger=self.log, worker_threads=min(self.worker_threads, len(self.targets)))

    def _get_targets(self):
        resp = requests.get(self.energy_api_endpoint + "/get_hosts_to_monitor")
        if resp.status_code != 200:
            self.log.error("Energy API returned status code %s", resp.status_code)
            return []
        return resp.json()["hosts"]

    def _probe(self):

        if not self.vsphere.is_connected():
            self.vsphere = Vsphere(endpoint=self.vsphere_endpoint, username=self.vsphere_username,
                                   password=self.vsphere_password,
                                   logger=self.log, worker_threads=min(self.worker_threads, len(self.targets)))

        data = ValueSet(labels=["type", "host", "vm"])
        if self.scrape_policy == 'all':
            result = self.vsphere.query_all_hosts()
        else:
            result = self.vsphere.query_hosts(self.targets)

        excluded_metrics = ["name", "vms"]

        for host in result:
            if host is None:
                self.log.warning("VSphere: No data found for host")
                continue
            # add host metrics
            for metric in host.keys():
                if metric not in excluded_metrics:
                    data.add(Value(host[metric], label_values=["host", host["name"], ""], name=metric))

            # add vm metrics
            for vm in host["vms"]:
                if vm is None:
                    self.log.warning("VSphere: No data found for host")
                    continue
                for metric in vm.keys():
                    if metric not in excluded_metrics:
                        data.add(Value(vm[metric], label_values=["vm", host["name"], vm["name"]], name=metric))

        return data
