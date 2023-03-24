from __future__ import annotations

import os
from typing import Optional

from pollect.core.ValueSet import ValueSet, Value
from pollect.sources.Source import Source
from pollect.libs.vmware.vsphere import Vsphere


class VSphereSource(Source):
    value: Optional[int] = None

    def __init__(self, config):
        super().__init__(config)

        vsphere_endpoint = config['vsphere_endpoint']
        vsphere_username_env = config['vsphere_username_env_var']
        vsphere_username = os.environ.get(vsphere_username_env)
        vsphere_password_env = config['vsphere_password_env_var']
        vsphere_password = os.environ.get(vsphere_password_env)
        worker_threads = config.get("worker_threads", 8)

        self.scrape_all_hosts = config.get("scrape_all_hosts", False)
        self.targets = config["targets"]
        self.vsphere = Vsphere(endpoint=vsphere_endpoint, username=vsphere_username, password=vsphere_password,
                               logger=self.log, worker_threads=min(worker_threads, len(self.targets)))

    def _probe(self):

        data = ValueSet(labels=["type", "host", "vm"])
        if self.scrape_all_hosts:
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
