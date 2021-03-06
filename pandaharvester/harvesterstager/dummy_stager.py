from pandaharvester.harvestercore import core_utils
from .base_stager import BaseStager

# logger
_logger = core_utils.setup_logger('dummy_stager')


# dummy plugin for stager
class DummyStager(BaseStager):
    # constructor
    def __init__(self, **kwarg):
        BaseStager.__init__(self, **kwarg)

    # check status
    def check_status(self, jobspec):
        """Check the status of stage-out procedure. If staging-out is done synchronously in trigger_stage_out
        this method should always return True.
        Output files are available through jobspec.get_outfile_specs(skip_done=False) which gives
        a list of FileSpecs not yet done.
        FileSpec.attemptNr shows how many times the transfer was checked for the file.
        If the file was successfully transferred, status should be set to 'finished'.
        Or 'failed', if the file failed to be transferred. Once files are set to 'finished' or 'failed',
        jobspec.get_outfile_specs(skip_done=False) ignores them.

        :param jobspec: job specifications
        :type jobspec: JobSpec
        :return: A tuple of return code (True: transfer success, False: fatal transfer failure,
                 None: on-going or temporary failure) and error dialog
        :rtype: (bool, string)
        """
        for fileSpec in jobspec.get_output_file_specs(skip_done=True):
            fileSpec.status = 'finished'
        return True, ''

    # trigger stage out
    def trigger_stage_out(self, jobspec):
        """Trigger the stage-out procedure for the job.
        Output files are available through jobspec.get_outfile_specs(skip_done=False) which gives
        a list of FileSpecs not yet done.
        FileSpec.attemptNr shows how many times transfer was tried for the file so far.

        :param jobspec: job specifications
        :type jobspec: JobSpec
        :return: A tuple of return code (True: success, False: fatal failure, None: temporary failure)
                 and error dialog
        :rtype: (bool, string)
        """
        for fileSpec in jobspec.get_output_file_specs(skip_done=True):
            # fileSpec.objstoreID = 123
            # fileSpec.fileAttributes['guid']
            pass
        return True, ''

    # zip output files
    def zip_output(self, jobspec):
        """Zip output files. This method loops over jobspec.get_output_file_specs(skip_done=False) to make a zip
        file for each outFileSpec from FileSpec.associatedFiles which is a list of toZipFileSpec to be zipped.
        The file path is available in toZipFileSpec. One zip files are made, their toZipFileSpec.path,
        toZipFileSpec.fsize, and toZipFileSpec.chksum need to be set.

        :param jobspec: job specifications
        :type jobspec: JobSpec
        :return: A tuple of return code (True for success, False otherwise) and error dialog
        :rtype: (bool, string)
        """
        # make logger
        tmpLog = self.make_logger(_logger, 'PandaID={0}'.format(jobspec.PandaID),
                                  method_name='zip_output')
        return self.simple_zip_output(jobspec, tmpLog)
