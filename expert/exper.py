
import hashlib
import time

from typing import cast, ClassVar, Optional, Type

from flask import request

import expert as e
from .experiment import State, TaskResponse, API, BaseExper
from . import tasks


def _monitor():
    e.log.info('starting monitor task')
    while True:
        e.srv.socketio.sleep(e.srv.cfg['monitor_check_interval'])
        if e.experclass:
            insts = []
            for inst in e.experclass.all_active():
                if not (isinstance(inst, Exper) and inst.check_for_timeout()):
                    insts.append(inst)
            # Exper.end() sends separate updates if any inst has timed out
            e.srv.dboard.monitor_updated(insts)
        else:
            e.log.info('monitor task shutting down')
            break


class ExperAPI(API):

    def return_survey(self):
        self._inst.return_survey()


class Exper(BaseExper):

    api_class: ClassVar[Type[API]] = ExperAPI

    # Will be True when all profiles have completed the experiment.
    complete: ClassVar[bool] = False

    global_timeout_time: Optional[float]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.cfg['save_user_agent']:
            self.pseudo_responses.append(
                TaskResponse(
                    'DUMMY' if kwargs.get('dummy')
                    else request.headers.get('User-Agent'),
                    'USER_AGENT'))
        if self.cfg['save_ip_hash']:
            iphash = hashlib.blake2b(
                bytes(self.clientip, 'ascii'), digest_size=10).hexdigest()
            self.pseudo_responses.append(
                TaskResponse(iphash, 'IPHASH'))
        if self.cfg['prolific_pid_param'] in self.urlargs:
            self.prolific_pid = self.urlargs[self.cfg['prolific_pid_param']]
            #app.logger.info(f'PROLIFIC_PID: {self.prolific_pid}')
            self.pseudo_responses.append(
                TaskResponse(self.prolific_pid, 'PROLIFIC_PID'))

        if self.prolific_pid:
            self.variables['exp_prolific_pid'] = self.prolific_pid
            self.variables['exp_prolific_completion_url'] = \
                self.cfg['prolific_completion_url']

        self.inact_timeout_time = \
            self.start_time + self.cfg['inact_timeout_secs']
        self.global_timeout_time = None

    @classmethod
    def _setup(cls, is_reloading):
        super()._setup(is_reloading)
        if not is_reloading:
            cls.monitor_task = e.srv.socketio.start_background_task(_monitor)

    # @classmethod
    # def start_new_run(cls):
    #     e.log.info('--- starting new run ---')
    #     for inst in cls.all_active():
    #         inst.terminate()
    #     #cls.instances.clear()
    #     cls._load_profiles()
    #     cls.run = timestamp.make_timestamp()
    #     cls.record = Record(cls)
    #     if cls.mode == 'rep':
    #         cls.record.replicate = cls.target
    #     elif cls.mode == 'res':
    #         if cls.replicate:
    #             cls.mode = 'rep'
    #             cls.record.replicate = cls.target
    #         else:
    #             cls.mode = 'new'
    #     cls.record.save()
    #     cls.running = True

    @classmethod
    def dummy_run(cls, inst_count):
        ip = '127.0.0.1'
        for i in range(inst_count):
            inst = cls(
                ip, {cls.cfg['prolific_pid_param']: f'DUMMY_{i}'}, dummy=True)
            inst._dummy_do_tasks()

    @classmethod
    def check_for_run_complete(cls):
        if not cls.profiles and \
           not any(i.state == State.ACTIVE for i in cls.instances.values()):
            e.log.info('--- run complete ---')
            cls.running = False
            e.srv.dboard.run_complete(cls.run)

    def check_for_complete(self):
        if not self.task.next_tasks and self.profile:
            # (The Consent task initially has no next_tasks,
            # because the profile hasn't been assigned yet.)
            # We have moved onto the final task. This will
            # typically be some sort of "thank you" page
            # that returns the participant to mturk or wherever.
            # No response is collected from this task.
            # When the final task is displayed, the subject's responses
            # are saved to disk. Their instance remains in memory
            # so that if they reload the page, they won't lose any,
            # e.g., mturk completion code that is displayed.
            self.end(State.COMPLETE)
            self.check_for_run_complete()

    def update_timeouts(self):
        now = time.monotonic()
        if self.task.timeout_secs is not None:
            if self.task.timeout_secs >= 0:
                self.global_timeout_time = now + self.task.timeout_secs
            else:
                # negative value disables the timeout
                self.global_timeout_time = None
        self.inact_timeout_time = \
            now + self.cfg['inact_timeout_secs']

    def check_for_timeout(self):
        if self.state != State.ACTIVE:
            return False
        if self.global_timeout_time:
            tout_time = min(self.inact_timeout_time,
                            self.global_timeout_time)
        else:
            tout_time = self.inact_timeout_time
        if tout_time and time.monotonic() >= tout_time:
            e.log.info(f'sid {self.sid[:4]} timed out')
            self.task.replace_next_task(tasks.TimedOut(self))
            self.end(State.TIMED_OUT)
            if self.profile:
                self.profiles.insert(0, self.profile)
            return True
        return False

    def return_survey(self):
        e.log.info(f'sid {self.sid[:4]} returned their survey')
        self.task = tasks.ReturnedSurvey(self)
        self.end(State.RETURNED)
        if self.profile:
            self.profiles.insert(0, self.profile)

    def _next_task(self, resp):
        self._store_resp(resp)
        e.log.info(
            f'sid {self.sid[:4]} completed "{self.task.template_name}"' +
            f' ({self.task.id})')
        self.task = self.task.next_task(resp)
        self.task_cursor = self.task.id
        if isinstance(self.task, tasks.NonConsent):
            self.end(State.CONSENT_DECLINED)
        if self.state == State.ACTIVE:
            self.update_timeouts()
            # may change self.state
            self.check_for_complete()
        self._update_vars()
        if self.state == State.ACTIVE:
            e.srv.dboard.inst_updated(self)

    def _dummy_do_tasks(self):
        while self.state != State.COMPLETE:
            self._next_task(self.task.dummy_resp())
