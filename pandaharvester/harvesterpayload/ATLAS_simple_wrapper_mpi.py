#!/usr/bin/env python
import json
import logging
import os
import shutil
import sys
import tarfile
import time
from collections import defaultdict
from datetime import datetime
from glob import glob
from socket import gethostname
from subprocess import call

from mpi4py import MPI

from pilot.jobdescription import JobDescription  # temporary hack
from pilot.util.filehandling import get_json_dictionary as read_json

# from pilot.util.filehandling import read_json
# from pilot.control.payload import parse_jobreport_data  # failed with third party import "import _ssl"

# TODO Safe local copy, with proper exit on failure

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
max_rank = comm.Get_size()

logger = logging.getLogger('Rank {0}'.format(rank))
logger.setLevel(logging.DEBUG)
debug_h = logging.StreamHandler(stream=sys.stdout)
formatter = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s')
debug_h.setFormatter(formatter)
debug_h.setLevel(logging.DEBUG)
error_h = logging.StreamHandler(stream=sys.stderr)
error_h.setFormatter(formatter)
error_h.setLevel(logging.ERROR)
logger.addHandler(error_h)
logger.addHandler(debug_h)

logger.info('HPC Pilot ver. 0.007')


# TODO: loglevel as input parameter

def parse_jobreport_data(job_report):
    work_attributes = {}
    if job_report is None or not any(job_report):
        return work_attributes

    # these are default values for job metrics
    core_count = 16
    work_attributes["nEvents"] = 0
    work_attributes["dbTime"] = ""
    work_attributes["dbData"] = ""

    class DictQuery(dict):
        def get(self, path, dst_dict, dst_key):
            keys = path.split("/")
            if len(keys) == 0:
                return
            last_key = keys.pop()
            v = self
            for key in keys:
                if key in v and isinstance(v[key], dict):
                    v = v[key]
                else:
                    return
            if last_key in v:
                dst_dict[dst_key] = v[last_key]

    if 'ATHENA_PROC_NUMBER' in os.environ:
        work_attributes['core_count'] = os.environ['ATHENA_PROC_NUMBER']
        core_count = int(os.environ['ATHENA_PROC_NUMBER'])

    dq = DictQuery(job_report)
    dq.get("resource/transform/processedEvents", work_attributes, "nEvents")
    dq.get("resource/transform/cpuTimeTotal", work_attributes, "cpuConsumptionTime")
    dq.get("resource/machine/node", work_attributes, "node")
    dq.get("resource/machine/model_name", work_attributes, "cpuConsumptionUnit")
    dq.get("resource/dbTimeTotal", work_attributes, "dbTime")
    dq.get("resource/dbDataTotal", work_attributes, "dbData")
    dq.get("exitCode", work_attributes, "transExitCode")
    dq.get("exitMsg", work_attributes, "exeErrorDiag")
    dq.get("files/output", work_attributes, "outputfiles")

    outputfiles_dict = {}
    if 'outputfiles' in work_attributes.keys():
        for ofs in work_attributes['outputfiles']:
            for of in ofs['subFiles']:
                outputfiles_dict[of['name']] = {'guid': of['file_guid'],
                                                'nentries': of['nentries'],
                                                'size': of['file_size']}
    work_attributes['outputfiles'] = outputfiles_dict

    if 'resource' in job_report and 'executor' in job_report['resource']:
        j = job_report['resource']['executor']
        exc_report = []
        fin_report = defaultdict(int)
        for v in filter(lambda d: 'memory' in d and ('Max' or 'Avg' in d['memory']), j.itervalues()):
            if 'Avg' in v['memory']:
                exc_report.extend(v['memory']['Avg'].items())
            if 'Max' in v['memory']:
                exc_report.extend(v['memory']['Max'].items())
        for x in exc_report:
            fin_report[x[0]] += x[1]
        work_attributes.update(fin_report)

    if 'files' in job_report and 'input' in job_report['files']:
        nInputFiles = 0
        for input_file in job_report['files']['input']:
            if 'subfiles' in input_file:
                nInputFiles += len(job_report['files']['input']['subfiles'])
        work_attributes['nInputFiles'] = nInputFiles

    # workdir_size = get_workdir_size()
    work_attributes['jobMetrics'] = 'coreCount=%s nEvents=%s dbTime=%s dbData=%s' % \
                                    (core_count,
                                     work_attributes["nEvents"],
                                     work_attributes["dbTime"],
                                     work_attributes["dbData"])
    del (work_attributes["dbData"])
    del (work_attributes["dbTime"])

    return work_attributes


def get_setup(job):
    # special setup preparation.

    setup_commands = ['source /ccs/proj/csc108/athena_grid_env/setup.sh',
                      'source $MODULESHOME/init/bash',
                      'tmp_dirname=/tmp/scratch',
                      'tmp_dirname+="/tmp"',
                      'export TEMP=$tmp_dirname',
                      'export TMPDIR=$TEMP',
                      'export TMP=$TEMP',
                      'export LD_LIBRARY_PATH=/ccs/proj/csc108/AtlasReleases/ldpatch:$LD_LIBRARY_PATH',
                      'export ATHENA_PROC_NUMBER=16',
                      'export G4ATLAS_SKIPFILEPEEK=1',
                      'export PANDA_RESOURCE=\"ORNL_Titan_MCORE\"',
                      'export ROOT_TTREECACHE_SIZE=1',
                      'export RUCIO_APPID=\"simul\"',
                      'export RUCIO_ACCOUNT=\"pilot\"',
                      'export CORAL_DBLOOKUP_PATH=/ccs/proj/csc108/AtlasReleases/21.0.15/nfs_db_files',
                      'export CORAL_AUTH_PATH=$SW_INSTALL_AREA/DBRelease/current/XMLConfig',
                      'export DATAPATH=$SW_INSTALL_AREA/DBRelease/current:$DATAPATH',
                      ' ']

    return setup_commands


def timestamp():
    """ return ISO-8601 compliant date/time format. Should be migrated to Pilot 2"""
    tmptz = time.timezone
    sign_str = '+'
    if tmptz > 0:
        sign_str = '-'
    tmptz_hours = int(tmptz / 3600)

    return str("%s%s%02d:%02d" % (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()), sign_str, abs(tmptz_hours),
                                  int(tmptz / 60 - tmptz_hours * 60)))


def main_exit(exit_code, work_report=None, workerAttributesFile="worker_attributes.json"):
    if work_report:
        publish_work_report(work_report, workerAttributesFile)
    sys.exit(exit_code)


def publish_work_report(work_report=None, workerAttributesFile="worker_attributes.json"):
    """Publishing of work report to file"""
    if work_report:
        if work_report.has_key("outputfiles"):
            del (work_report["outputfiles"])
        with open(workerAttributesFile, 'w') as outputfile:
            work_report['timestamp'] = timestamp()
            json.dump(work_report, outputfile)
        logger.debug("Work report published: {0}".format(work_report))
    return 0


def main():
    workerAttributesFile = "worker_attributes.json"
    StageOutnFile = "event_status.dump.json"
    payload_report_file = 'jobReport.json'

    start_g = time.time()
    start_g_str = time.asctime(time.localtime(start_g))
    hostname = gethostname()
    logger.info("Pilot statrted at {0} on {1}".format(start_g_str, hostname))
    starting_point = os.getcwd()
    scratch_path = '/tmp/scratch/'
    cleanup_pathes()

    work_report = {}
    work_report["jobStatus"] = "starting"
    work_report["messageLevel"] = logging.getLevelName(logger.getEffectiveLevel())
    work_report['cpuConversionFactor'] = 1.0
    work_report['node'] = hostname

    # Get a file name with job descriptions
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file = 'worker_pandaids.json'
    try:
        in_file = open(input_file)
        panda_ids = json.load(in_file)
        in_file.close()
    except IOError as (errno, strerror):
        logger.critical("I/O error({0}): {1}".format(errno, strerror))
        logger.critical("Exit from rank")
        main_exit(errno)

    logger.debug("Collected list of jobs")
    # PandaID of the job for the command
    try:
        job_id = panda_ids[rank]
    except ValueError:
        logger.critical("Pilot have no job for rank {0}".format(rank))
        logger.critical("Exit pilot")
        main_exit(1)

    logger.debug("Job [{0}] will be processed".format(job_id))
    os.chdir(str(job_id))
    worker_communication_point = os.getcwd()

    work_report['workdir'] = worker_communication_point
    workerAttributesFile = os.path.join(worker_communication_point, workerAttributesFile)
    trans_job_workdir = os.path.join(scratch_path, str(job_id))

    jobs_dict = read_json("HPCJobs.json")
    job_dict = jobs_dict[str(job_id)]

    job = JobDescription()
    job.load(job_dict)
    # add path to input files in RAM
    for inp_file in job.input_files:
        job.input_files[inp_file]["scratch_path"] = os.path.join(trans_job_workdir, inp_file)

    job.startTime = ""
    job.endTime = ""
    setup_str = "; ".join(get_setup(job))

    job_working_dir = titan_prepare_wd(scratch_path, trans_job_workdir, worker_communication_point, job,
                                       workerAttributesFile)

    my_command = " ".join([job.script, job.script_parameters])
    my_command = titan_command_fix(my_command, job_working_dir)
    my_command = setup_str + my_command
    logger.debug("Going to launch: {0}".format(my_command))
    logger.debug("Current work directory: {0}".format(job_working_dir))
    payloadstdout = open("athena_stdout.txt", "w")
    payloadstderr = open("athena_stderr.txt", "w")

    job.state = 'running'
    work_report["jobStatus"] = job.state
    start_time = time.asctime(time.localtime(time.time()))
    job.startTime = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    publish_work_report(work_report, workerAttributesFile)
    stime = time.time()
    t0 = os.times()
    exit_code = call(my_command, stdout=payloadstdout, stderr=payloadstderr, shell=True)
    t1 = os.times()
    exetime = time.time() - stime
    end_time = time.asctime(time.localtime(time.time()))
    t = map(lambda x, y: x - y, t1, t0)
    t_tot = reduce(lambda x, y: x + y, t[2:3])
    job.endTime = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    payloadstdout.close()
    payloadstderr.close()
    if exit_code == 0:
        job.state = 'finished'
    else:
        job.state = 'failed'
    job.exitcode = exit_code

    work_report["endTime"] = job.endTime
    work_report["jobStatus"] = job.state
    work_report["cpuConsumptionTime"] = t_tot
    work_report["transExitCode"] = job.exitcode

    logger.info("Payload exit code: {0} JobID: {1}".format(exit_code, job_id))
    logger.info("CPU comsumption time: {0}  JobID: {1}".format(t_tot, job_id))
    logger.info("Start time: {0}  JobID: {1}".format(start_time, job_id))
    logger.info("End time: {0}  JobID: {1}".format(end_time, job_id))
    logger.info("Execution time: {0} sec.  JobID: {1}".format(exetime, job_id))
    logger.debug("Job report start time: {0}".format(job.startTime))
    logger.debug("Job report end time: {0}".format(job.endTime))

    if os.path.exists(payload_report_file):
        payload_report = parse_jobreport_data(read_json(payload_report_file))
        work_report.update(payload_report)
        copy_jobreport(job_working_dir, worker_communication_point, payload_report_file, workerAttributesFile)

    titan_postprocess_wd(job_working_dir)

    # log file not produced (yet)
    protectedfiles = job.output_files.keys()
    if job.log_file in protectedfiles:
        protectedfiles.remove(job.log_file)
    else:
        logger.info("Log files was not declared")

    cleanup_strat = time.time()
    logger.info("Cleanup of working directory")
    protectedfiles.extend([workerAttributesFile, StageOutnFile])
    removeRedundantFiles(job_working_dir, protectedfiles)
    cleanup_time = time.time() - cleanup_strat
    logger.info("Cleanup took: {0} sec.".format(cleanup_time))
    res = packlogs(job_working_dir, protectedfiles, job.log_file)
    if res > 0:
        job.state = 'failed'
        work_report['pilotErrorCode'] = 1164  # Let's take this as closed one
        work_report['jobStatus'] = job.state
        main_exit(0, work_report, workerAttributesFile)

    # Copy of output to shared FS for stageout
    if not job_working_dir == worker_communication_point:
        cp_start = time.time()
        for outfile in job.output_files.keys():
            if os.path.exists(outfile):
                shutil.copyfile(os.path.join(job_working_dir, outfile),
                                os.path.join(worker_communication_point, outfile))
        os.chdir(worker_communication_point)
        cp_time = time.time() - cp_start
        logger.info("Copy of outputs took: {0} sec.".format(cp_time))

    logger.info("Declare stage-out")
    out_file_report = {}
    out_file_report[job.job_id] = []

    for outfile in job.output_files.keys():
        logger.debug("File {} will be checked and declared for stage out".format(outfile))
        if os.path.exists(outfile):
            file_desc = {}
            if outfile == job.log_file:
                file_desc['type'] = 'log'
            else:
                file_desc['type'] = 'output'
            file_desc['path'] = os.path.abspath(outfile)
            file_desc['fsize'] = os.path.getsize(outfile)
            if 'guid' in job.output_files[outfile].keys():
                file_desc['guid'] = job.output_files[outfile]['guid']
            elif work_report['outputfiles'] and work_report['outputfiles'][outfile]:
                file_desc['guid'] = work_report['outputfiles'][outfile]['guid']
            out_file_report[job.job_id].append(file_desc)
        else:
            logger.info("Expected output file {0} missed. Job {1} will be failed".format(outfile, job.job_id))
            job.state = 'failed'

    if out_file_report[job.job_id]:
        with open(StageOutnFile, 'w') as stageoutfile:
            json.dump(out_file_report, stageoutfile)
        logger.debug('Stagout declared in: {0}'.format(StageOutnFile))
        logger.debug('Report for stageout: {}'.format(out_file_report))

    logger.info("All done")
    logger.debug("Final report: {0}".format(work_report))
    main_exit(0, work_report, workerAttributesFile)


def copy_jobreport(job_working_dir, worker_communication_point, payload_report_file, workerattributesfile):
    src_file = os.path.join(job_working_dir, payload_report_file)
    dst_file = os.path.join(worker_communication_point, payload_report_file)

    try:
        logger.info(
            "Copy of payload report [{0}] to access point: {1}".format(payload_report_file, worker_communication_point))
        cp_start = time.time()
        # shrink jobReport
        job_report = read_json(src_file)
        if 'executor' in job_report:
            for executor in job_report['executor']:
                if 'logfileReport' in executor:
                    executor['logfileReport'] = {}

        with open(dst_file, 'w') as job_report_outfile:
            json.dump(job_report, job_report_outfile)
        cp_time = time.time() - cp_start
        logger.info("Copy of payload report file took: {0} sec.".format(cp_time))
    except:
        logger.error("Job report copy failed, execution terminated':  \n %s " % (sys.exc_info()[1]))
        work_report = dict()
        work_report["jobStatus"] = "failed"
        work_report["pilotErrorCode"] = 1103  # Should be changed to Pilot2 errors
        work_report["exitMsg"] = str(sys.exc_info()[1])
        main_exit(1103, work_report, workerattributesfile)


def titan_command_fix(command, job_working_dir):
    subs_a = command.split()
    for i in range(len(subs_a)):
        if i > 0:
            if '(' in subs_a[i] and not subs_a[i][0] == '"':
                subs_a[i] = '"' + subs_a[i] + '"'
            if subs_a[i].startswith("--inputEVNTFile"):
                filename = subs_a[i].split("=")[1]
                subs_a[i] = subs_a[i].replace(filename, os.path.join(job_working_dir, filename))

    command = ' '.join(subs_a)
    command = command.strip()
    command = command.replace('--DBRelease="all:current"', '')  # avoid Frontier reading

    return command


def titan_prepare_wd(scratch_path, trans_job_workdir, worker_communication_point, job, workerAttributesFile):
    # ---------
    # Copy Poolcond files to scratch (RAMdisk, ssd, etc) to cope high IO. MOve execution to RAM disk

    dst_db_path = 'sqlite200/'
    dst_db_filename = 'ALLP200.db'
    dst_db_path_2 = 'geomDB/'
    dst_db_filename_2 = 'geomDB_sqlite'
    tmp_path = 'tmp/'
    src_file = '/ccs/proj/csc108/AtlasReleases/21.0.15/DBRelease/current/sqlite200/ALLP200.db'
    src_file_2 = '/ccs/proj/csc108/AtlasReleases/21.0.15/DBRelease/current/geomDB/geomDB_sqlite'
    copy_start = time.time()
    if os.path.exists(scratch_path):
        try:
            if not os.path.exists(scratch_path + tmp_path):
                os.makedirs(scratch_path + tmp_path)
            if not os.path.exists(scratch_path + dst_db_path):
                os.makedirs(scratch_path + dst_db_path)
            shutil.copyfile(src_file, scratch_path + dst_db_path + dst_db_filename)
            if not os.path.exists(scratch_path + dst_db_path_2):
                os.makedirs(scratch_path + dst_db_path_2)
            shutil.copyfile(src_file_2, scratch_path + dst_db_path_2 + dst_db_filename_2)
            if not os.path.exists(trans_job_workdir):
                os.makedirs(trans_job_workdir)
            for inp_file in job.input_files:
                shutil.copyfile(os.path.join(worker_communication_point, inp_file),
                                job.input_files[inp_file]["scratch_path"])
        except IOError as e:
            copy_time = time.time() - copy_start
            logger.info('Special Titan setup failed after: {0}'.format(copy_time))
            logger.error("Copy to scratch failed, execution terminated':  \n %s " % (sys.exc_info()[1]))
            work_report = dict()
            work_report["jobStatus"] = "failed"
            work_report["pilotErrorCode"] = 1103  # Should be changed to Pilot2 errors
            work_report["exitMsg"] = str(sys.exc_info()[1])
            main_exit(1103, work_report, workerAttributesFile)
        except:
            pass
    else:
        logger.info('Scratch directory (%s) dose not exist' % scratch_path)
        return worker_communication_point

    os.chdir(trans_job_workdir)
    logger.debug("Current directory: {0}".format(os.getcwd()))
    true_dir = '/ccs/proj/csc108/AtlasReleases/21.0.15/nfs_db_files'
    pseudo_dir = "./poolcond"
    os.symlink(true_dir, pseudo_dir)
    copy_time = time.time() - copy_start
    logger.info('Special Titan setup took: {0}'.format(copy_time))

    return trans_job_workdir


def titan_postprocess_wd(jobdir):
    pseudo_dir = "poolcond"
    if os.path.exists(pseudo_dir):
        remove(os.path.join(jobdir, pseudo_dir))
    return 0


def removeRedundantFiles(workdir, outputfiles=[]):
    """ Remove redundant files and directories. Should be migrated to Pilot2 """

    logger.info("Removing redundant files prior to log creation")

    workdir = os.path.abspath(workdir)

    dir_list = ["AtlasProduction*",
                "AtlasPoint1",
                "AtlasTier0",
                "buildJob*",
                "CDRelease*",
                "csc*.log",
                "DBRelease*",
                "EvgenJobOptions",
                "external",
                "fort.*",
                "geant4",
                "geomDB",
                "geomDB_sqlite",
                "home",
                "o..pacman..o",
                "pacman-*",
                "python",
                "runAthena*",
                "share",
                "sources.*",
                "sqlite*",
                "sw",
                "tcf_*",
                "triggerDB",
                "trusted.caches",
                "workdir",
                "*.data*",
                "*.events",
                "*.py",
                "*.pyc",
                "*.root*",
                "JEM",
                "tmp*",
                "*.tmp",
                "*.TMP",
                "MC11JobOptions",
                "scratch",
                "jobState-*-test.pickle",
                "*.writing",
                "pwg*",
                "pwhg*",
                "*PROC*",
                "madevent",
                "HPC",
                "objectstore*.json",
                "saga",
                "radical",
                "ckpt*"]

    # remove core and pool.root files from AthenaMP sub directories
    try:
        cleanupAthenaMP(workdir, outputfiles)
    except Exception, e:
        print("Failed to execute cleanupAthenaMP(): %s" % (e))

    # explicitly remove any soft linked archives (.a files) since they will be dereferenced by the tar command (--dereference option)
    matches = []
    import fnmatch
    for root, dirnames, filenames in os.walk(workdir):
        for filename in fnmatch.filter(filenames, '*.a'):
            matches.append(os.path.join(root, filename))
    for root, dirnames, filenames in os.walk(os.path.dirname(workdir)):
        for filename in fnmatch.filter(filenames, 'EventService_premerge_*.tar'):
            matches.append(os.path.join(root, filename))
    if matches != []:
        for f in matches:
            remove(f)
    # else:
    #    print("Found no archive files")

    # note: these should be partitial file/dir names, not containing any wildcards
    exceptions_list = ["runargs", "runwrapper", "jobReport", "log."]

    to_delete = []
    for _dir in dir_list:
        files = glob(os.path.join(workdir, _dir))
        exclude = []

        if files:
            for exc in exceptions_list:
                for f in files:
                    if exc in f:
                        exclude.append(os.path.abspath(f))

            _files = []
            for f in files:
                if not f in exclude:
                    _files.append(os.path.abspath(f))
            to_delete += _files

    exclude_files = []
    for of in outputfiles:
        exclude_files.append(os.path.join(workdir, of))
    for f in to_delete:
        if not f in exclude_files:
            remove(f)

    # run a second pass to clean up any broken links
    broken = []
    for root, dirs, files in os.walk(workdir):
        for filename in files:
            path = os.path.join(root, filename)
            if os.path.islink(path):
                target_path = os.readlink(path)
                # Resolve relative symlinks
                if not os.path.isabs(target_path):
                    target_path = os.path.join(os.path.dirname(path), target_path)
                if not os.path.exists(target_path):
                    broken.append(path)
            else:
                # If it's not a symlink we're not interested.
                continue

    if broken:
        for p in broken:
            remove(p)

    return 0


def cleanupAthenaMP(workdir, outputfiles=[]):
    """ Cleanup AthenaMP sud directories prior to log file creation. ATLAS specific """

    for ampdir in glob('%s/athenaMP-workers-*' % (workdir)):
        for (p, d, f) in os.walk(ampdir):
            for filename in f:
                if 'core' in filename or 'tmp.' in filename:
                    path = os.path.join(p, filename)
                    path = os.path.abspath(path)
                    remove(path)
                for outfile in outputfiles:
                    if outfile in filename:
                        path = os.path.join(p, filename)
                        path = os.path.abspath(path)
                        remove(path)

    return 0


def remove(path):
    "Common function for removing of file. Should migrate to Pilo2"
    try:
        os.unlink(path)
    except OSError as e:
        logger.error("Problem with deletion: %s : %s" % (e.errno, e.strerror))
        return -1
    return 0


def packlogs(wkdir, excludedfiles, logfile_name, attempt=0):
    # logfile_size = 0
    to_pack = []
    pack_start = time.time()
    for path, subdir, files in os.walk(wkdir):
        for file in files:
            if not file in excludedfiles:
                relDir = os.path.relpath(path, wkdir)
                file_rel_path = os.path.join(relDir, file)
                file_path = os.path.join(path, file)
                to_pack.append((file_path, file_rel_path))
    if to_pack:
        try:
            logfile_name = os.path.join(wkdir, logfile_name)
            log_pack = tarfile.open(logfile_name, 'w:gz')
            for f in to_pack:
                log_pack.add(f[0], arcname=f[1])
            log_pack.close()
            # logfile_size = os.path.getsize(logfile_name)
        except IOError as e:
            if attempt == 0:
                safe_delay = 15
                logger.info('I/O error. Will retry in {0} sec.'.format(safe_delay))
                time.sleep(safe_delay)
                packlogs(wkdir, excludedfiles, logfile_name, attempt=1)
            else:
                logger.info("Continues I/O error during packing of logs. Job will be failed")
                return 1

    for f in to_pack:
        remove(f[0])

    del_empty_dirs(wkdir)
    pack_time = time.time() - pack_start
    logger.debug("Pack of logs took: {0} sec.".format(pack_time))
    return 0


def del_empty_dirs(src_dir):
    "Common function for removing of empty directories. Should migrate to Pilo2"

    for dirpath, subdirs, files in os.walk(src_dir, topdown=False):
        if dirpath == src_dir:
            break
        try:
            os.rmdir(dirpath)
        except OSError as ex:
            pass
    return 0


def cleanup_pathes(pathprefix="/lustre/"):
    """"
    Cleanup of PATH, LD_PATH etc from entities, which points to shared file system required to reduce IO from traversing
    of python libraries
    """
    path = os.environ['PATH'].split(':')
    for p in path[:]:
        if p.startswith("/lustre/"):
            path.remove(p)
    ppath = os.environ['PYTHONPATH'].split(':')
    for p in ppath[:]:
        if p.startswith("/lustre/"):
            ppath.remove(p)
    ldpath = os.environ['LD_LIBRARY_PATH'].split(':')
    for p in ldpath[:]:
        if p.startswith("/lustre/"):
            ldpath.remove(p)

    os.environ['PATH'] = ':'.join(path)
    os.putenv('PATH', ':'.join(path))
    os.environ['PYTHONPATH'] = ':'.join(ppath)
    os.putenv('PYTHONPATH', ':'.join(ppath))
    os.environ['LD_LIBRARY_PATH'] = ':'.join(ldpath)
    os.putenv('LD_LIBRARY_PATH', ':'.join(ldpath))

    return 0


if __name__ == "__main__":
    main()
