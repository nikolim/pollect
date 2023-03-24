import logging
from concurrent.futures import ThreadPoolExecutor
from time import time

import requests

# ignore warning for self signed host
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class DellOpenManage:
    """
    Wrapper for Dell Open Manage API
    """

    def __init__(self, endpoint: str, username: str, password: str, logger: logging.Logger, worker_threads: int = 8):
        """
        Create a session key for OME
        """
        self.logger = logger
        self.endpoint = endpoint

        session_url = f"{self.endpoint}/api/SessionService/Sessions"
        user = {"UserName": username, "Password": password}
        session_response = requests.post(session_url, json=user, verify=False)
        if session_response.status_code == 201:
            self.logger.info("Created session key for OME")
        else:
            self.logger.info("Could not create session key for OME")
        self.session_key = session_response.headers['X-Auth-Token']

        self.executor = ThreadPoolExecutor(max_workers=worker_threads)
        self.id_dict = self.create_name_to_id_dict()

    def create_name_to_id_dict(self):
        device_url = f"{self.endpoint}/api/DeviceService/Devices?$skip=0&$top=500"
        response = requests.get(
            device_url, headers={'X-Auth-Token': self.session_key}, verify=False, timeout=10)

        if response.status_code != 200:
            self.logger.warning(response.json())
            return

        id_dict = {}
        for device in response.json()['value']:
            id_dict[device['DeviceName']] = device['Id']
        return id_dict

    def get_id_for_name(self, device_name: str) -> int:
        """
        Get the id for a device name
        :param device_name:
        :return: id
        """
        # hosts in OME are extended with mp before the first dot
        first_dot_index = device_name.find(".")
        target_host_name = device_name[:first_dot_index] + "mp" + device_name[first_dot_index:]

        # check if the global variable id_dict is set
        return self.id_dict.get(target_host_name, None)

    def query(self, device_name: str, request_ts: time) -> dict | None:
        """
        Get power stats for a server
        :param request_ts: time when the request was triggered
        :param device_name: provide either device_id or device_name
        """
        device_id = self.get_id_for_name(device_name)
        if not device_id:
            self.logger.warning(f"Could not find ID for target: {device_name}")
            return

        power_url = f'{self.endpoint}/api/DeviceService/Devices({device_id})/Power'
        try:
            response = requests.get(
                power_url, headers={'X-Auth-Token': self.session_key}, verify=False, timeout=10)
        except requests.exceptions.Timeout:
            self.logger.warning(f"Timeout for OME request: {power_url} after 10 seconds")
            return

        response_ts = time()

        if response.status_code != 200:
            self.logger.warning(response.json())
            return

        data = response.json()
        new_data = {'name': device_name,
                    'request_ts': request_ts,
                    'response_ts': response_ts,
                    'power': data['power'],
                    'systemEnergyConsumption': data['systemEnergyConsumption'],
                    'systemEnergyConsumptionTimestamp': data['systemEnergyConsumptionTimeStamp']}

        return new_data

    def query_hosts(self, hosts: list[str], request_ts: time = time()) -> list[dict]:
        """
        Query performance metrics for a given list of hosts in parallel using a thread pool
        :param hosts: list of hostnames
        :param request_ts:
        :return: list of dicts with the result for each host
        """
        futures = [self.executor.submit(self.query, device_name=host, request_ts=request_ts)
                   for host in hosts]
        return [future.result(timeout=15) for future in futures]

    def query_all_hosts(self, request_ts: time = time()) -> list[dict]:
        """
        Query performance metrics for all available hosts in parallel using a thread pool
        :param request_ts:
        :return: list of dicts with the result for each host
        """
        device_url = f"{self.endpoint}/api/DeviceService/Devices?top=500"
        response = requests.get(
            device_url, headers={'X-Auth-Token': self.session_key}, verify=False, timeout=10)

        if response.status_code == 200:
            hosts = response.json()["value"]
            host_names = [host["DeviceName"] for host in hosts]
        else:
            self.logger.error(f"Failed to get hosts. Status code: {response.status_code}")
            return []

        self.query_hosts(hosts=host_names, request_ts=request_ts)
