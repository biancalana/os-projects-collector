# coding=utf-8

"""
Uses openstack cli to collect usage and limits from projects

Written by: @biancalana
"""

from subprocess import Popen, PIPE
import json
import pprint
import graphitesend
from multiprocessing import Pool
import os
import re
import time
import yaml

def get_project_limits(project):

    p = Popen(["openstack", "limits",  "show", "--project", project['ID'], "--absolute", "-f", "json"], stdout=PIPE, stderr=PIPE)

    (stdout, stderr) = p.communicate()

    if p.returncode != 0:
        raise RuntimeError("%r failed, %r" % ("openstack", stderr))

    try:
        limits = json.loads(stdout)
    except ValueError:
        raise RuntimeError("Decoding JSON")

    project_name = re.sub(r'[\s\.]+', '_', project['Name'])
    project_name = re.sub(r'[\(\)\[\]\*\s]+', '', project_name)

    for metric in limits:
        g.send("%s_%s.%s" % (project_name, project['ID'], metric['Name']),  metric['Value'])

    return limits


def list_projects():
    p = Popen(["openstack", "project", "list", "-f", "json"], stdout=PIPE, stderr=PIPE)

    (stdout, stderr) = p.communicate()

    if p.returncode != 0:
        raise RuntimeError("%r failed, %r" % ( "openstack", stderr))

    try:
        projects = json.loads(stdout)
        return projects

    except ValueError:
        raise RuntimeError("Decoding JSON")


def LoadConfig(config_file):
    try:
        fd = open(config_file, 'r')
        cfg = yaml.load(fd)

        return cfg

    except IOError as e:
        print "Error reading configuration file (%s), %s" % (config_file, e.strerror)
        raise


if __name__ == '__main__':

    # load config file
    SystemConfig = LoadConfig('etc/system.conf')

    os.environ['OS_AUTH_URL'] = SystemConfig['openstack']['url']
    os.environ['OS_USERNAME'] = SystemConfig['openstack']['username']
    os.environ['OS_PASSWORD'] = SystemConfig['openstack']['password']

    graphite_host       = SystemConfig['graphite']['host']
    graphite_prefix     = SystemConfig['graphite']['prefix']
    collect_interval    = SystemConfig['collection']['interval']
    collect_processes   = SystemConfig['collection']['processes']

    g = graphitesend.init(graphite_server=graphite_host, prefix=graphite_prefix, system_name='')

    pool = Pool(processes=collect_processes)

    while True:

        time_start = time.time()
        totals = {}
        projects = list_projects()

        multiple_results = [pool.apply_async(get_project_limits, (project,)) for project in projects]

        for res in multiple_results:
            for metric in res.get():
                if not metric['Name'] in totals:
                    totals[metric['Name']] = metric['Value']
                else:
                    totals[metric['Name']] += metric['Value']

            for metric in totals:
                g.send("_Root.%s" % metric,  totals[metric])

        time_end = time.time()
        time_took = time_end-time_start

        toSleep = (collect_interval - time_took)

        print "Collection done in %s seconds" % time_took
        print "Sleeping for %s" % toSleep

        time.sleep(toSleep)
