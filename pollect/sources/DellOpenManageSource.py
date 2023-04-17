from __future__ import annotations

import os
from typing import Optional

import requests

from pollect.core.ValueSet import ValueSet, Value
from pollect.libs.dell.openmanage import DellOpenManage
from pollect.sources.Source import Source


class DellOpenManageSource(Source):
    value: Optional[int] = None

    def __init__(self, config):
        super().__init__(config)

        ome_endpoint = config['ome_endpoint']
        ome_username_env = config['ome_username_env_var']
        ome_username = os.environ.get(ome_username_env)
        ome_password_env = config['ome_password_env_var']
        ome_password = os.environ.get(ome_password_env)
        worker_threads = config.get("worker_threads", 8)

        self.scrape_policy = config.get("scrape_policy", "auto")

        if self.scrape_policy == 'manual':
            self.targets = config["targets"]
        if self.scrape_policy == 'auto':
            self.targets = self._get_targets()

        self.energy_api_endpoint = config["energy_api_endpoint"]
        self.ome = DellOpenManage(endpoint=ome_endpoint, username=ome_username, password=ome_password, logger=self.log,
                                  worker_threads=min(worker_threads, len(self.targets)))

    def _get_targets(self):
        resp = requests.get(self.energy_api_endpoint + "/get_hosts_to_monitor")
        if resp.status_code != 200:
            self.log.error("Energy API returned status code %s", resp.status_code)
            return []
        return resp.json()["hosts"]

    def _probe(self):

        data = ValueSet(labels=["host"])
        if self.scrape_policy == 'all':
            result = self.ome.query_all_hosts()
        else:
            result = self.ome.query_hosts(self.targets)

        for host in result:
            if host is None:
                self.log.warning("OME: No data found for host")
                continue
            data.add(Value(host["power"], label_values=[host["name"]], name="power"))
            data.add(Value(host["request_ts"], label_values=[host["name"]], name="request_ts"))

        return data
