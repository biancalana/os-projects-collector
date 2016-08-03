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


if __name__ == '__main__':

    os.environ['OS_AUTH_URL'] = 'https://keystone.br-sp1.openstack.uolcloud.com.br:5000/v2.0'
    os.environ['OS_USERNAME'] = 'graphite'
    os.environ['OS_PASSWORD'] = 'https://keystone.br-sp1.openstack.uolcloud.com.br:5000/v2.0'

    graphite_host       = 'd3-zcarbon1.host.intranet'
    graphite_prefix     = 'prod.openstack.GT.D4-UCOS.projects'
    collect_interval    = 900
    collect_processes   = 4

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
