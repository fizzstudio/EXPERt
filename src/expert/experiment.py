
import random
import sys
import time
import importlib
import csv
import hashlib
import secrets

from pathlib import Path
from collections import Counter
from enum import Enum

from flask import render_template, request

import expert
from . import (
    tasks, timestamp
)

import strictyaml


class State(Enum):
    ACTIVE = 0
    CONSENT_DECLINED = 1
    TIMED_OUT = 2
    COMPLETE = 3
    TERMINATED = 4


resp_file_suffixes = {
    State.CONSENT_DECLINED: '-nonconsent',
    State.TIMED_OUT: '-timeout',
    State.TERMINATED: '-terminated'
}


class TaskResponse:

    # args:
    #  response: any
    #  task_name: str
    #  extra: {str:any}
    def __init__(self, response, task_name, **extra):
        self.response = response
        self.task_name = task_name
        # reserved for output files
        for reserved in ['tstamp', 'task', 'resp']:
            assert reserved not in extra
        self.extra = extra
        self.timestamp = timestamp.make_timestamp()


class NoSuchCondError(Exception):
    def __init__(self, condname):
        super().__init__(f'no such condition(s) "{condname}"')


class ExperFullError(Exception):
    def __init__(self):
        super().__init__('no profiles available')


class BadOutputFormatError(Exception):
    def __init__(self, fmt):
        super().__init__(f'unknown output format "{fmt}"')


class Experiment:

    profiles = []
    # sid: <Experiment subclass inst>
    instances = {}

    # Will be True when all profiles have completed the experiment.
    complete = False

    def __init__(self, clientip, urlargs, dummy=False):
        self.sid = secrets.token_hex(16)

        #self.profile = self.choose_profile()
        self.profile = self.profiles.pop(0)
        app.logger.info(f'profile: {self.profile}')

        self.instances[self.sid] = self

        self.start_time = time.monotonic()
        self.end_time = None

        self.start_timestamp = timestamp.make_timestamp()

        # tasks are stored in a linked tree structure
        self.task = None
        self.last_task = None
        # total number of task instances created
        # (not necessarily the number the participant will complete)
        self.num_tasks_created = 0
        #self.num_tasks_completed = 0
        self.task_cursor = 1

        # response returned by current task
        self.response = None
        self.responses = []
        self.pseudo_responses = [
            TaskResponse(self.sid, 'SID'),
        ]
        if expert.cfg['save_ip_hash']:
            self.clientip = clientip
            iphash = hashlib.blake2b(
                bytes(self.clientip, 'ascii'), digest_size=10).hexdigest()
            self.pseudo_responses.append(
                TaskResponse(iphash, 'IPHASH'))
        else:
            self.clientip = 'xxx.xxx.xxx.xxx'
        if expert.cfg['save_user_agent']:
            self.pseudo_responses.append(
                TaskResponse(
                    'DUMMY' if dummy else request.headers.get('User-Agent'),
                    'USER_AGENT'))
        if expert.cfg['prolific_pid_param'] in urlargs:
            self.prolific_pid = urlargs[expert.cfg['prolific_pid_param']]
            app.logger.info(f'PROLIFIC_PID: {self.prolific_pid}')
            self.pseudo_responses.append(
                TaskResponse(self.prolific_pid, 'PROLIFIC_PID'))
        else:
            self.prolific_pid = None

        self.state = State.ACTIVE

        self.inact_timeout_time = \
            self.start_time + expert.cfg['inact_timeout_secs']
        self.global_timeout_time = None

        # template variables shared by all tasks for the experiment
        self.variables = {
            'exp_prolific_pid': self.prolific_pid,
            'exp_sid': self.sid
        }
        if self.prolific_pid:
            self.variables['exp_prolific_completion_url'] = \
                expert.cfg['prolific_completion_url']

        @socketio.on('init_task', namespace=f'/{self.sid}')
        def sio_init_task():
            return self.task.all_vars()

        @socketio.on('next_page', namespace=f'/{self.sid}')
        def sio_next_page(resp):
            if self.task.next_tasks:
                # if we're not here, the user was somehow able
                # to hit 'Next' on the final task screen,
                # which shouldn't be possible ...
                #self.handle_response(resp)
                self.next_task(resp)
            return self.task.all_vars()

        #@socketio.on('debug_fwd', namespace=f'/{self.sid}')
        #def sio_debug_fwd():
        #    if self.task.next_tasks:
        #        self.task_fwd()
        #    return self.task.all_vars()

        @socketio.on('prev_page', namespace=f'/{self.sid}')
        def sio_prev_page():
            if self.task.prev_task:
                self.prev_task()
            return self.task.all_vars()

        @socketio.on('get_feedback', namespace=f'/{self.sid}')
        def sio_get_feedback(resp):
            return self.task.get_feedback(resp)

        @socketio.on_error(f'/{self.sid}')
        def sio_inst_error(e):
            app.logger.info(f'socketio error: {e}')

    @classmethod
    def setup(cls, path, conds):
        global app, socketio
        from . import app as theapp
        from . import socketio as thesocketio
        app, cls.app = theapp, theapp
        socketio = thesocketio
        cls.name = cls.__qualname__.lower()
        cls.setup_paths(path)
        cls.pkg = sys.modules[cls.__module__]
        if conds:
            unknown_conds = [c for c in conds
                             if c not in cls.cond_mod().conds]
            if unknown_conds:
                raise NoSuchCondError(', '.join(unknown_conds))
        # create main experiment directories, if they don't exist
        cls.dir_path.mkdir(exist_ok=True)
        cls.runs_path.mkdir(exist_ok=True)
        cls.profiles_path.mkdir(exist_ok=True)
        cls.conds = conds
        cls.replicate = None
        if expert.mode == 'rep':
            cls.record = Record(cls)
            cls.record.replicate = expert.target
            cls.record.save()
            cls.replicate = Record(cls, expert.target)
        elif expert.mode == 'res':
            cls.record = Record(cls, target)
            if cls.record.replicate:
                cls.replicate = Record(cls, cls.record.replicate)
        else:
            cls.record = Record(cls)
            cls.record.save()
        cls.load_profiles()

    @classmethod
    def setup_paths(cls, path):
        # NB: this is now an absolute path;
        # previously, it was relative to global_root
        cls.dir_path = Path(path).resolve(True)
        cls.static_path = cls.dir_path / expert.cfg['static_dir']
        cls.profiles_path = cls.dir_path / expert.cfg['profiles_dir']
        cls.runs_path = cls.dir_path / expert.cfg['runs_dir']
        cls.templates_path = cls.dir_path / expert.cfg['templates_dir']

    @classmethod
    def read_cond_paths(cls):
        return [p for p in cls.profiles_path.iterdir()
                if p.is_dir() and p.stem[0] != '.']

    @classmethod
    def load_profiles(cls):
        if cls.replicate:
            rep_profs = cls.replicate.completed_profiles()
        else:
            rep_profs = None
        cond_paths = cls.read_cond_paths()
        if not cond_paths:
            cls.make_profiles()
            cond_paths = cls.read_cond_paths()

        app.logger.info('loading profiles')
        cls.profiles.clear()
        for cond_path in cond_paths:
            condname = cond_path.name
            run_cond_path = cls.record.run_path / condname
            for prof_path in cond_path.iterdir():
                profname = prof_path.name
                if profname.startswith('.') or not prof_path.is_file():
                    continue
                if cls.replicate and \
                   f'{condname}/{profname}' not in rep_profs:
                    continue
                #cls.profiles.setdefault(p.cond, {})[profname] = p
                # only load profile if we don't have a result
                # for that profile
                #fullprofname = f'{cond_path.name}/{profname}'
                if not (run_cond_path / profname).is_file():
                    #app.logger.info(
                    #    f'marking profile {fullprofname} as used')
                    #p.use()
                    p = cls.profile_mod().Profile.load(
                        cls, condname, profname)
                    cls.profiles.append(p)
        random.shuffle(cls.profiles)

    @classmethod
    def make_profiles(cls):
        app.logger.info('creating profiles')
        cls.cond_size = round(
            cls.params_mod().n_profiles/len(cls.cond_mod().conds))
        app.logger.info(f'profiles per condition: {cls.cond_size}')
        for cname, c in cls.cond_mod().conds.items():
            app.logger.info(f'creating profiles for condition {cname}')
            (cls.profiles_path / cname).mkdir()
            #cls.profiles[c] = {}
            for i in range(cls.cond_size):
                p = cls.profile_mod().Profile(cls, c)
                #cls.profiles[c][p.subjid] = p
                p.save()

    @classmethod
    def cond_mod(cls):
        return importlib.import_module('.cond', cls.pkg.__package__)

    @classmethod
    def params_mod(cls):
        return importlib.import_module('.params', cls.pkg.__package__)

    @classmethod
    def profile_mod(cls):
        return importlib.import_module('.profile', cls.pkg.__package__)

    @classmethod
    def all_active(cls):
        return [inst for inst in cls.instances.values()
                if inst.state == State.ACTIVE]

    @classmethod
    def start_new_run(cls):
        app.logger.info('--- starting new run ---')
        for inst in cls.all_active():
            inst.terminate()
        #cls.instances.clear()
        cls.load_profiles()
        #for condprofs in cls.profiles.values():
        #    for prof in condprofs.values():
        #        prof.unuse()
        expert.run = timestamp.make_timestamp()
        cls.record = Record(cls)
        if expert.mode == 'rep':
            cls.record.replicate = expert.target
        elif expert.mode == 'res':
            if cls.replicate:
                expert.mode = 'rep'
                cls.record.replicate = expert.target
            else:
                expert.mode = 'new'
        cls.record.save()
        cls.complete = False

    @classmethod
    def complete_run(cls):
        app.logger.info('--- run complete ---')
        cls.complete = True
        socketio.emit('run_complete')

    # def choose_cond(self):
    #     cond_counts = Counter()
    #     # make sure we have a key for each cond
    #     for cname, c in self.cond_mod().conds.items():
    #         if not self.conds or cname in self.conds:
    #             cond_counts[c] = 0

    #     # count currently-active and completed instances in memory
    #     for inst in self.instances.values():
    #         if inst.state in (State.ACTIVE, State.COMPLETE):
    #             cond_counts[inst.profile.cond] += 1
    #     # count completed instances
    #     for fqname in self.record.completed_profiles():
    #         c, prof = fqname.split('/')
    #         cond_counts[self.cond_mod().conds[c]] += 1

    #     return min(cond_counts.keys(), key=lambda k: cond_counts[k])

    # def choose_profile(self):
    #     if self.replicate:
    #         avail = [p for c in self.profiles
    #                  for p in self.profiles[c].values() if not p.used]
    #     else:
    #         # find cond with fewest participants
    #         cond = self.choose_cond()
    #         avail = [p for p in self.profiles[cond].values() if not p.used]

    #     if not avail:
    #         app.logger.warning('no profiles are available')
    #         raise ExperFullError()

    #     p = random.choice(avail)
    #     p.use()
    #     return p

    def will_start(self):
        self.variables['exp_num_tasks'] = self.num_tasks_created
        self.update_vars()

    def present(self, tplt_vars={}):
        return self.task.present(tplt_vars)

    def update_vars(self):
        self.variables['exp_task_cursor'] = self.task_cursor
        self.variables['exp_state'] = self.state.name

    #def task_fwd(self, resp=None):
    #    # XXX currently doesn't handle forking task paths
    #    self.task = self.task.next_task(resp)
    #    self.task_cursor += 1
    #    self.update_cursor()

    def prev_task(self):
        self.task = self.task.prev_task
        self.task_cursor -= 1
        self.update_timeouts()
        self.update_vars()

    def update_timeouts(self):
        now = time.monotonic()
        if self.task.timeout_secs is not None:
            if self.task.timeout_secs >= 0:
                self.global_timeout_time = now + self.task.timeout_secs
            else:
                # negative value disables the timeout
                self.global_timeout_time = None
        self.inact_timeout_time = \
            now + expert.cfg['inact_timeout_secs']

    def next_task(self, resp):
        task_resp = TaskResponse(
            resp, self.task.template_name, **self.task.resp_extra)
        if self.task_cursor > len(self.responses):
            self.responses.append(task_resp)
        else:
            # should only ever do this in tool mode
            self.responses[self.task_cursor - 1] = task_resp
        app.logger.info(
            f'{self.profile} completed "{task_resp.task_name}"' +
            f' ({self.task_cursor})')

        if self.state == State.ACTIVE:

            if isinstance(self.task, tasks.Consent) and \
               resp == 'consent_declined':
                # make sure we didn't time out right before
                app.logger.info(
                    f'consent declined for {self.profile}')
                #self.task.next_tasks = [tasks.Task(self, 'nonconsent')]
                self.task = tasks.NonConsent(self)
                self.end(State.CONSENT_DECLINED)
                # NB: the sid stays in the session so we can keep
                # serving up the consent-declined page
                #self.profile.unuse()
                self.profiles.insert(0, self.profile)
            else:
                # XXX currently doesn't handle forking task paths
                self.task = self.task.next_task(resp)
                self.task_cursor += 1

                self.update_timeouts()

                if not self.task.next_tasks:
                    # This is the final task. It must simply be some sort of
                    # "thank you" page where no data is collected.
                    # When the final task is displayed, the subject's responses
                    # are saved to disk. Their instance remains in memory
                    # so that if they reload the page, they won't lose any,
                    # e.g., mturk completion code that is displayed.
                    self.end(State.COMPLETE)
                    if not self.profiles:
                        self.complete_run()

            self.update_vars()

        #self.num_tasks_completed += 1
        socketio.emit('update_instance', self.status())

    def status(self):
        if self.state == State.ACTIVE:
            elapsed_time = time.monotonic() - self.start_time
        else:
            elapsed_time = self.end_time - self.start_time
        y, mo, d, h, mi, s = self.start_timestamp.split('.')
        return [
            self.sid, self.clientip, str(self.profile),
            self.state.name, self.task_cursor,
            #self.start_timestamp[11:].replace('.', ':'),
            f'{mo}/{d}/{y} {h}:{mi}:{s}',
            f'{elapsed_time/60:.1f}']

    def save_responses(self):
        cond_path = self.record.run_path / str(self.profile.cond)
        resp_path = cond_path / (self.profile.subjid +
                                 resp_file_suffixes.get(self.state, ''))
        # newline='' must be set for the csv module
        with open(resp_path, 'w', newline='') as f:
            if expert.cfg['output_format'] == 'csv':
                writer = csv.writer(f, lineterminator='\n')
                extras = set()
                # collect all extra response field names
                # (NB: skipping pseudo-responses here)
                for r in self.responses:
                    for k in r.extra:
                        extras.add(k)
                # write the header line
                writer.writerow(['tstamp', 'task', 'resp', *extras])
                for r in self.pseudo_responses + self.responses:
                    # NB: None is written as the empty string
                    writer.writerow([r.timestamp, r.task_name, r.response,
                                     *[r.extra[e] for e in extras]])
            elif expert.cfg['output_format'] == 'json':
                import json
                output = []
                for r in self.pseudo_responses + self.responses:
                    item = {'tstamp': r.timestamp, 'task': r.task_name}
                    if r.response is not None:
                        item['resp'] = r.response
                    item.update(r.extra)
                    output.append(item)
                json.dump(output, f, indent=2)
            else:
                # XXX would probably be better to sanity-check this
                # when the program loads
                raise BadOutputFormatError(expert.cfg['output_format'])

    def check_for_timeout(self):
        if self.state != State.ACTIVE:
            return
        if self.global_timeout_time:
            tout_time = min(self.inact_timeout_time,
                            self.global_timeout_time)
        else:
            tout_time = self.inact_timeout_time
        if tout_time and time.monotonic() >= tout_time:
            app.logger.info(f'{self.profile} timed out')
            #self.task.next_tasks = [tasks.Task(self, 'timedout')]
            self.task = tasks.TimedOut(self)
            self.end(State.TIMED_OUT)
            #self.profile.unuse()
            self.profiles.insert(0, self.profile)
        socketio.emit('update_instance', self.status())

    def terminate(self):
        if self.state != State.ACTIVE:
            return
        app.logger.info(f'{self.profile} terminated')
        self.task = tasks.Terminated(self)
        self.end(State.TERMINATED)
        #self.profile.unuse()
        self.profiles.insert(0, self.profile)
        socketio.emit('update_instance', self.status())

    # called for normal completion, timeout, or nonconsent
    def end(self, state):
        self.end_time = time.monotonic()
        self.state = state
        self.save_responses()

    def dummy_run(self):
        while self.state != State.COMPLETE:
            self.next_task(self.task.dummy_resp())


class Record:

    def __init__(self, experclass, fromsaved=None):
        self.experclass = experclass
        fromsaved = fromsaved or expert.run
        saved_path = experclass.runs_path / fromsaved
        md_path = saved_path / 'metadata'
        if md_path.is_file():
            schema = strictyaml.Map({
                'replicate': strictyaml.EmptyNone() | strictyaml.Str(),
            })
            with open(saved_path / 'metadata') as f:
                metadata = strictyaml.load(f.read(), schema).data
                self.start_time = fromsaved
                # folder name of exper run we are replicating
                self.replicate = metadata.get('replicate')
        else:
            self.start_time = fromsaved
            self.replicate = None
        self.run_path = experclass.runs_path / self.start_time

    def completed_profiles(self):
        # list of strings of form 'cond/prof'
        profiles = []
        bad_suffixes = resp_file_suffixes.values()
        for cond_path in self.run_path.iterdir():
            if cond_path.is_dir():
                for prof_path in cond_path.iterdir():
                    prof = prof_path.name
                    if not (prof.startswith('.') or \
                            any(prof.endswith(sfx) for sfx in bad_suffixes)):
                        profiles.append(f'{cond_path.name}/{prof}')
        return profiles

    def save(self):
        # Only the metadata is saved here; the data for each
        # individual subject is saved by the experiment class

        # create run directory (it will already exist if resuming)
        self.run_path.mkdir(exist_ok=True)
        for cname, c in self.experclass.cond_mod().conds.items():
            (self.run_path / cname).mkdir(exist_ok=True)

        md_path = self.run_path / 'metadata'
        with open(md_path, 'w') as f:
            fields = {}
            # if self.time_end:
            #     fields['time_end'] = self.time_end
            fields['replicate'] = self.replicate or ''
            print(strictyaml.as_document(fields).as_yaml(), file=f)
