#!/usr/bin/env python

"""
Uses openstack cli to collect usage and limits from projects

Written by: @biancalana
"""

from subprocess import Popen, PIPE
import json
import graphitesend
import logging
import logging.handlers
from multiprocessing import Pool
import os
import re
import signal, os
import time
import yaml

def get_project_id():

    logger.debug("Getting my project id")
    p = Popen(["openstack", "project",  "list", "-f", "json"], stdout=PIPE, stderr=PIPE)

    (stdout, stderr) = p.communicate()

    if p.returncode != 0:
        raise RuntimeError("%r failed, %r" % ("openstack", stderr))

    try:
        project = json.loads(stdout)
    except ValueError:
        raise RuntimeError("Decoding JSON")

    return project[0]['ID']


def get_token():

    logger.debug("Getting access token")
    p = Popen(["openstack", "token",  "issue", "-c", "id", "-f", "value"], stdout=PIPE, stderr=PIPE)

    (stdout, stderr) = p.communicate()

    if p.returncode != 0:
        raise RuntimeError("%r failed, %r" % ("openstack", stderr))

    try:
        token = stdout.rstrip()
    except ValueError:
        raise RuntimeError("Decoding JSON")

    return token.rstrip()


def get_project_limits(project):

    time_start = time.time()
    p = Popen(["openstack", "limits",  "show", "--project", project['ID'], "--absolute", "-f", "json"], stdout=PIPE, stderr=PIPE)

    (stdout, stderr) = p.communicate()

    if p.returncode != 0:
        logger.warning("Failure getting project(%s) limits, %r", project['ID'], stderr)
        return
        #raise RuntimeError("%r failed, %r" % ("openstack", stderr))

    try:
        limits = json.loads(stdout)
    except ValueError:
        raise RuntimeError("Decoding JSON")

    time_end = time.time()
    time_took = time_end-time_start

    logger.debug("Get project(%s) limits took %.02f seconds", project['ID'], time_took)

    project_name = re.sub(r'[\s\.]+', '_', project['Name'])
    project_name = re.sub(r'[\(\)\[\]\*\s]+', '', project_name)

    for metric in limits:
        g.send("%s_%s.%s" % (project_name, project['ID'], metric['Name']),  metric['Value'])

    return limits


def list_projects():

    logger.debug("Listing all projects")

    time_start = time.time()
    p = Popen(["openstack", "project", "list", "-f", "json"], stdout=PIPE, stderr=PIPE)

    (stdout, stderr) = p.communicate()

    if p.returncode != 0:
        raise RuntimeError("%r failed, %r" % ( "openstack", stderr))

    try:
        projects = json.loads(stdout)
        time_end = time.time()
        time_took = time_end-time_start

        logger.debug("List projects took %.02f seconds", time_took)
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

def handler(signum, frame):
    logger.info('Signal received, exit scheduled...')
    keep_running=0


if __name__ == '__main__':

    keep_running = 1

    # load config file
    SystemConfig = LoadConfig('etc/system.conf')

    # Setup logging
    logger = logging.getLogger('os_projects_collector')
    logger.setLevel(logging.INFO)

    log_handler = logging.handlers.TimedRotatingFileHandler('logs/stdout.log',
            when='midnight', interval=1, backupCount=10)

    log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(process)d %(funcName)s: %(message)s'))
    logger.addHandler(log_handler)

    os.environ['OS_AUTH_URL']   = SystemConfig['openstack']['url']
    os.environ['OS_USERNAME']   = SystemConfig['openstack']['username']
    os.environ['OS_PASSWORD']   = SystemConfig['openstack']['password']

    # Set user project so it's possible to query all projects
    os.environ['OS_PROJECT_ID'] = get_project_id()

    # Re-use issued token
    os.environ['OS_TOKEN'] = get_token()
    if os.environ['OS_TOKEN'] is not None:
        logger.info("Using token for next requests")
        os.environ['OS_AUTH_TYPE'] = 'token'
        del(os.environ['OS_USERNAME'])
        del(os.environ['OS_PASSWORD'])

    graphite_host       = SystemConfig['graphite']['host']
    graphite_prefix     = SystemConfig['graphite']['prefix']
    collect_interval    = SystemConfig['collection']['interval']
    collect_processes   = SystemConfig['collection']['processes']

    logger.info("Reporting metrics Using prefix(%s) to graphite host(%s)", graphite_prefix, graphite_host)
    g = graphitesend.init(graphite_server=graphite_host, prefix=graphite_prefix, system_name='')

    pool = Pool(processes=collect_processes)

    signal.signal(signal.SIGTERM, handler)

    while keep_running:

        logger.info("Starting collection")

        time_start = time.time()
        totals = {}
        projects = list_projects()
        tenants = 0

        multiple_results = [pool.apply_async(get_project_limits, (project,)) for project in projects]

        for res in multiple_results:
            if keep_running <= 0:
                pool.close()
                break

            tenants += 1
            try:
                for metric in res.get():
                    if not metric['Name'] in totals:
                        totals[metric['Name']] = metric['Value']
                    else:
                        totals[metric['Name']] += metric['Value']
            except Exception as e:
                print "Error fetching data, %s" % (e.strerror)
                raise

        for metric in totals:
            g.send("_Root.%s" % metric,  totals[metric])

        g.send("_Root.tenants", tenants)

        time_end = time.time()
        time_took = time_end-time_start

        toSleep = (collect_interval - time_took)

        logger.info("Collection done in %.02f seconds" % time_took)

        if toSleep < 0:
            logger.warning("Collection is taking too long, collection internal of %d seconds cannot be keeped !!" % collect_interval)
            toSleep=10

        logger.info("Sleeping for %d seconds" % toSleep)

        time.sleep(toSleep)

    logger.info("Exiting..." % toSleep)
