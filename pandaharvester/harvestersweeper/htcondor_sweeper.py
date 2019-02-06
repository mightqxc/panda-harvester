
#=== Imports ==================================================

from pandaharvester.harvestersweeper.base_sweeper import BaseSweeper
from pandaharvester.harvestercore import core_utils

import os
import shutil
try:
    import subprocess32 as subprocess
except Exception:
    import subprocess

#==============================================================

#=== Definitions ==============================================

## Logger
baseLogger = core_utils.setup_logger('htcondor_sweeper')

#==============================================================

#=== Functions ================================================

def _runShell(cmd):
    cmd = str(cmd)
    p = subprocess.Popen(cmd.split(), shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdOut, stdErr = p.communicate()
    retCode = p.returncode
    return (retCode, stdOut, stdErr)

#==============================================================

#=== Classes ==================================================

# sweeper for HTCONDOR batch system
class HTCondorSweeper(BaseSweeper):
    # constructor
    def __init__(self, **kwarg):
        BaseSweeper.__init__(self, **kwarg)


    # kill a worker
    def kill_worker(self, workspec):
        ## Make logger
        tmpLog = self.make_logger(baseLogger, 'workerID={0}'.format(workspec.workerID),
                                  method_name='kill_worker')

        ## Skip batch operation for workers without batchID
        if workspec.batchID is None:
            tmpLog.info('Found workerID={0} has submissionHost={1} batchID={2} . Cannot kill. Skipped '.format(
                            workspec.workerID, workspec.submissionHost, workspec.batchID))
            return True, ''

        ## Parse condor remote options
        name_opt, pool_opt = '', ''
        if workspec.submissionHost is None or workspec.submissionHost == 'LOCAL':
            pass
        else:
            try:
                condor_schedd, condor_pool = workspec.submissionHost.split(',')[0:2]
            except ValueError:
                errStr = 'Invalid submissionHost: {0} . Skipped'.format(workspec.submissionHost)
                tmpLog.error(errStr)
                return False, errStr
            name_opt = '-name {0}'.format(condor_schedd) if condor_schedd else ''
            pool_opt = '-pool {0}'.format(condor_pool) if condor_pool else ''

        ## Kill command
        comStr = 'condor_rm {name_opt} {pool_opt} {batchID}'.format(name_opt=name_opt,
                                                                    pool_opt=pool_opt,
                                                                    batchID=workspec.batchID)
        (retCode, stdOut, stdErr) = _runShell(comStr)
        if retCode != 0:
            comStr = 'condor_q -l {name_opt} {pool_opt} {batchID}'.format(name_opt=name_opt,
                                                                        pool_opt=pool_opt,
                                                                        batchID=workspec.batchID)
            (retCode, stdOut, stdErr) = _runShell(comStr)
            if ('ClusterId = {0}'.format(workspec.batchID) in str(stdOut) \
                and 'JobStatus = 3' not in str(stdOut)) or retCode != 0:
                ## Force to cancel if batch job not terminated first time
                comStr = 'condor_rm -forcex {name_opt} {pool_opt} {batchID}'.format(name_opt=name_opt,
                                                                            pool_opt=pool_opt,
                                                                            batchID=workspec.batchID)
                (retCode, stdOut, stdErr) = _runShell(comStr)
                if retCode != 0:
                    ## Command failed to kill
                    errStr = 'command "{0}" failed, retCode={1}, error: {2} {3}'.format(comStr, retCode, stdOut, stdErr)
                    tmpLog.error(errStr)
                    return False, errStr
            ## Found already killed
            tmpLog.info('Found workerID={0} submissionHost={1} batchID={2} already killed'.format(
                            workspec.workerID, workspec.submissionHost, workspec.batchID))
        else:
            tmpLog.info('Succeeded to kill workerID={0} submissionHost={1} batchID={2}'.format(
                            workspec.workerID, workspec.submissionHost, workspec.batchID))
        ## Return
        return True, ''


    # kill workers
    def kill_workers(self, workspec_list):
        ## Make logger
        tmpLog = self.make_logger(baseLogger, method_name='kill_workers')

        ret_list = []
        for workspec in workspec_list:
            ## Skip batch operation for workers without batchID
            if workspec.batchID is None:
                tmpLog.info('Found workerID={0} has submissionHost={1} batchID={2} . Cannot kill. Skipped '.format(
                                workspec.workerID, workspec.submissionHost, workspec.batchID))
                ret_list.append((True, ''))

            ## Parse condor remote options
            name_opt, pool_opt = '', ''
            if workspec.submissionHost is None or workspec.submissionHost == 'LOCAL':
                pass
            else:
                try:
                    condor_schedd, condor_pool = workspec.submissionHost.split(',')[0:2]
                except ValueError:
                    errStr = 'Invalid submissionHost: {0} . Skipped'.format(workspec.submissionHost)
                    tmpLog.error(errStr)
                    ret_list.append((False, errStr))
                name_opt = '-name {0}'.format(condor_schedd) if condor_schedd else ''
                pool_opt = '-pool {0}'.format(condor_pool) if condor_pool else ''

            ## Kill command
            comStr = 'condor_rm {name_opt} {pool_opt} {batchID}'.format(name_opt=name_opt,
                                                                        pool_opt=pool_opt,
                                                                        batchID=workspec.batchID)
            (retCode, stdOut, stdErr) = _runShell(comStr)
            if retCode != 0:
                comStr = 'condor_q -l {name_opt} {pool_opt} {batchID}'.format(name_opt=name_opt,
                                                                            pool_opt=pool_opt,
                                                                            batchID=workspec.batchID)
                (retCode, stdOut, stdErr) = _runShell(comStr)
                if ('ClusterId = {0}'.format(workspec.batchID) in str(stdOut) \
                    and 'JobStatus = 3' not in str(stdOut)) or retCode != 0:
                    ## Force to cancel if batch job not terminated first time
                    comStr = 'condor_rm -forcex {name_opt} {pool_opt} {batchID}'.format(name_opt=name_opt,
                                                                                pool_opt=pool_opt,
                                                                                batchID=workspec.batchID)
                    (retCode, stdOut, stdErr) = _runShell(comStr)
                    if retCode != 0:
                        ## Command failed to kill
                        errStr = 'command "{0}" failed, retCode={1}, error: {2} {3}'.format(comStr, retCode, stdOut, stdErr)
                        tmpLog.error(errStr)
                        ret_list.append((False, errStr))
                ## Found already killed
                tmpLog.info('Found workerID={0} submissionHost={1} batchID={2} already killed'.format(
                                workspec.workerID, workspec.submissionHost, workspec.batchID))
            else:
                tmpLog.info('Succeeded to kill workerID={0} submissionHost={1} batchID={2}'.format(
                                workspec.workerID, workspec.submissionHost, workspec.batchID))
        ## Return
        return ret_list


    # cleanup for a worker
    def sweep_worker(self, workspec):
        ## Make logger
        tmpLog = self.make_logger(baseLogger, 'workerID={0}'.format(workspec.workerID),
                                  method_name='sweep_worker')

        ## Make sure batch job is terminated
        self.kill_worker(workspec)

        ## Clean up preparator base directory (staged-in files)
        try:
            preparatorBasePath = self.preparatorBasePath
        except AttributeError:
            tmpLog.debug('No preparator base directory is configured. Skipped cleaning up preparator directory')
            pass
        else:
            if os.path.isdir(preparatorBasePath):
                if not workspec.get_jobspec_list():
                    tmpLog.warning('No job PandaID found relate to workerID={0}. Skipped cleaning up preparator directory'.format(workspec.workerID))
                else:
                    for jobspec in workspec.get_jobspec_list():
                        preparator_dir_for_cleanup = os.path.join(preparatorBasePath, str(jobspec.PandaID))
                        if os.path.isdir(preparator_dir_for_cleanup) and preparator_dir_for_cleanup != preparatorBasePath:
                            try:
                                shutil.rmtree(preparator_dir_for_cleanup)
                            except OSError as _err:
                                if 'No such file or directory' in _err.strerror:
                                    tmpLog.debug('Found that {0} was already removed'.format(_err.filename))
                                pass
                            tmpLog.info('Succeeded to clean up preparator directory: Removed {0}'.format(preparator_dir_for_cleanup))
                        else:
                            errStr = 'Failed to clean up preparator directory: {0} does not exist or invalid to be cleaned up'.format(preparator_dir_for_cleanup)
                            tmpLog.error(errStr)
                            return False, errStr
            else:
                errStr = 'Configuration error: Preparator base directory {0} does not exist'.format(preparatorBasePath)
                tmpLog.error(errStr)
                return False, errStr

        tmpLog.info('Succeeded to clean up everything about workerID={0}'.format(workspec.workerID))

        ## Return
        return True, ''

#==============================================================
