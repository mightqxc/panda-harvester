import Queue
import datetime
from pandaharvester.harvesterconfig import harvester_config
from communicator import Communicator
import core_utils

# logger
_logger = core_utils.setup_logger()


# method wrapper
class CommunicatorMethod:
    # constructor
    def __init__(self, method_name, pool):
        self.methodName = method_name
        self.pool = pool

    # method emulation
    def __call__(self, *args, **kwargs):
        tmpLog = core_utils.make_logger(_logger, 'method={0}'.format(self.methodName))
        try:
            # get connection
            con = self.pool.get()
            tmpLog.debug('got lock. qsize={0}'.format(self.pool.qsize()))
            startTime = datetime.datetime.utcnow()
            # get function
            func = getattr(con, self.methodName)
            # exec
            return apply(func, args, kwargs)
        finally:
            diff = datetime.datetime.utcnow() - startTime
            tmpLog.debug('release lock : took {0}.{0} sec'.format(diff.seconds,
                                                                  diff.microseconds/1000))
            self.pool.put(con)


# connection class
class CommunicatorPool(object):
    # constructor
    def __init__(self):
        # install members
        object.__setattr__(self, 'pool', None)
        # connection pool
        self.pool = Queue.Queue(harvester_config.pandacon.nConnections)
        for i in range(harvester_config.pandacon.nConnections):
            con = Communicator()
            self.pool.put(con)

    # override __getattribute__
    def __getattribute__(self, name):
        try:
            return object.__getattribute__(self, name)
        except:
            pass
        # method object
        tmpO = CommunicatorMethod(name, self.pool)
        object.__setattr__(self, name, tmpO)
        return tmpO
