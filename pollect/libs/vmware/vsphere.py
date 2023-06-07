import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_EXCEPTION
from time import time
from datetime import datetime

from pyVmomi import vim
from pyVim import connect


class Vsphere:
    """
    Wrapper for pyvmomi vSphere library
    """

    def __init__(self, endpoint: str, username: str, password: str, logger: logging.Logger, worker_threads: int = 8):
        """
        Connect to vSphere
        """
        self.logger = logger
        self.si = connect.SmartConnect(host=endpoint, user=username, port=443, pwd=password,
                                       disableSslCertValidation=True)
        self.content = self.si.RetrieveContent()
        self.perf_manager = self.content.perfManager
        self.counter_info = self.create_counter_info_dict()
        self.executor = ThreadPoolExecutor(max_workers=worker_threads)

    def is_connected(self):
        """
        Check if the connection is still alive
        """
        try:
            self.si.CurrentTime()
            return True
        except:
            return False

    def create_counter_info_dict(self) -> dict:
        """
        Create a with the name of the counter as key and the counter id as value
        """
        counter_info = {}
        for counter in self.perf_manager.perfCounter:
            full_name = counter.groupInfo.key + "." + counter.nameInfo.key + "." + counter.rollupType
            counter_info[full_name] = counter.key
        return counter_info

    def get_available_counter_ids(self, entity: vim.HostSystem | vim.VirtualMachine) -> list[int]:
        """
        Get all available counter ids for a given entity
        :param entity:
        :return: list of counter ids
        """
        counter_ids = [m.counterId for m in self.perf_manager.QueryAvailablePerfMetric(entity=entity)]

        # add the power.power.average counter which is not added by default
        power_counter = self.counter_info['power.power.average']
        if power_counter not in counter_ids:
            counter_ids.append(power_counter)

        return counter_ids

    def get_perf_metrics(self, target_obj: vim.HostSystem | vim.VirtualMachine, request_ts: time,
                         counter_ids: list[int] = None) -> dict:
        """
        Get performance metrics for a given entity
        :param target_obj: object to get metrics for
        :param request_ts: timestamp of the request
        :param counter_ids: optional list of counter ids
        :return: dict with the counter name as key and the value as value
        """
        counter_ids = counter_ids if counter_ids else self.get_available_counter_ids(target_obj)
        metric_ids = [vim.PerformanceManager.MetricId(counterId=c, instance="*") for c in counter_ids]
        spec = vim.PerformanceManager.QuerySpec(intervalId=20,
                                                entity=target_obj,
                                                metricId=metric_ids)

        result_stats = self.perf_manager.QueryStats(querySpec=[spec])

        try:
            sample_ts = datetime.timestamp(result_stats[0].sampleInfo[0].timestamp)
        except IndexError:
            sample_ts = -1

        result = {'request_ts': request_ts,
                  'sample_ts': sample_ts}
        for _ in result_stats:
            for val in result_stats[0].value:
                counter_key = list(self.counter_info.keys())[list(self.counter_info.values()).index(val.id.counterId)]
                if val.id.instance == '':
                    result[str(counter_key)] = val.value[0]

        return result

    def query(self, device_name: str, request_ts: time = time(), counter_ids: list[int] = None) -> dict:
        """
        Query performance metrics for a given host and all VMs on that host
        :param device_name: hostname of the target
        :param request_ts: optional timestamp of the request, defaults to current time
        :param counter_ids: optional list of counter ids
        """
        host_object = self.content.searchIndex.FindByDnsName(None, device_name, False)
        if not host_object:
            self.logger.warning(f"Target not found: {device_name}")
            return {}

        host_result = self.get_perf_metrics(target_obj=host_object, request_ts=request_ts, counter_ids=counter_ids)
        host_result["name"] = device_name

        host_result['vms'] = []
        for vm_object in host_object.vm:
            vm_result = self.get_perf_metrics(target_obj=vm_object, request_ts=request_ts, counter_ids=counter_ids)
            vm_result["name"] = vm_object.name
            host_result['vms'].append(vm_result)

        return host_result

    def query_hosts(self, hosts: list[str], request_ts: time = time(), counter_ids: list[int] = None) -> list[dict]:
        """
        Query performance metrics for a given list of hosts in parallel using a thread pool
        :param hosts: list of hostnames
        :param request_ts:
        :param counter_ids: optional list of counter ids
        :return: list of dicts with the result for each host
        """
        futures = [self.executor.submit(self.query, device_name=host, request_ts=request_ts, counter_ids=counter_ids)
                   for host in hosts]

        result = []
        done, futures = wait(futures, timeout=60, return_when=FIRST_EXCEPTION)
        for future in done:
            result.append(future.result())
        return result

    def query_all_hosts(self, request_ts: time = time(), counter_ids: list[int] = None) -> list[dict]:
        """
        Query performance metrics for all available hosts in parallel using a thread pool
        :param request_ts:
        :param counter_ids: optional list of counter ids
        :return: list of dicts with the result for each host
        """
        container = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.HostSystem], True)
        host_names = []
        for host in container.view:
            host_names.append(host.name)
        return self.query_hosts(hosts=host_names, request_ts=request_ts, counter_ids=counter_ids)
