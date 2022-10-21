
import hashlib
import time

from typing import cast, ClassVar, Optional

from flask import request

import expert as e
from .experiment import BaseExper, State, TaskResponse, Record
from . import tasks, timestamp


def _monitor():
    e.log.info('starting monitor task')
    while e.experclass:
        e.srv.socketio.sleep(e.srv.cfg['monitor_check_interval'])
        for inst in e.experclass.instances.values():
            inst = cast(Exper, inst)
            if not inst.check_for_timeout():
                # Exper.end() sends the update if the inst has timed out
                e.srv.socketio.emit('update_instance', inst.status())


class Exper(BaseExper):

    # Will be True when all profiles have completed the experiment.
    complete: ClassVar[bool] = False

    end_time: float
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
            self.variables['exp_prolific_completion_url'] = \
                self.cfg['prolific_completion_url']

        self.inact_timeout_time = \
            self.start_time + self.cfg['inact_timeout_secs']
        self.global_timeout_time = None

    @classmethod
    def _setup(cls, *args):
        super()._setup(*args)
        cls.monitor_task = e.srv.socketio.start_background_task(
            _monitor)

    @classmethod
    def all_active(cls):
        return [cast(Exper, inst) for inst in cls.instances.values()
                if inst.state == State.ACTIVE]

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
            e.srv.socketio.emit('run_complete')

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

    def terminate(self):
        if self.state != State.ACTIVE:
            return
        e.log.info(f'sid {self.sid[:4]} terminated')
        self.task.replace_next_task(tasks.Terminated(self))
        self.end(State.TERMINATED)
        if self.profile:
            self.profiles.insert(0, self.profile)

    def end(self, state):
        # called for normal completion, timeout, nonconsent, or termination
        self.end_time = time.monotonic()
        self.state = state
        e.srv.socketio.emit('update_instance', self.status())
        if self.profile:
            e.log.info(f'saving responses for sid {self.sid[:4]}')
            self._save_responses()

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
            e.srv.socketio.emit('update_instance', self.status())

    def _elapsed_time(self):
        if self.state == State.ACTIVE:
            return super()._elapsed_time()
        else:
            return self.end_time - self.start_time

    def _dummy_do_tasks(self):
        while self.state != State.COMPLETE:
            self._next_task(self.task.dummy_resp())
