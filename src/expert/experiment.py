
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

from . import (
    cfg,
    tasks, timestamp
)

import strictyaml


class State(Enum):
    ACTIVE = 0
    CONSENT_DECLINED = 1
    TIMED_OUT = 2
    COMPLETE = 3


class TaskResponse:

    # args:
    #  response: any
    #  task_name: str
    #  extra: any
    def __init__(self, response, task_name, extra=None):
        self.response = response
        self.task_name = task_name
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

    # cond: {profname: Profile}
    profiles = {}
    # sid: <Experiment subclass inst>
    instances = {}

    def __init__(self, socketio, clientip):
        self.sid = secrets.token_hex(16)

        self.clientip = clientip
        self.iphash = hashlib.blake2b(
            bytes(self.clientip, 'ascii'), digest_size=10).hexdigest()

        self.profile = self.choose_profile()
        app.logger.info(f'profile: {self.profile}')

        self.socketio = socketio

        self.instances[self.sid] = self

        self.start_time = time.monotonic()
        self.end_time = None

        self.start_timestamp = timestamp.make_timestamp()

        # tasks are stored in a linked list
        self.task = None
        self.last_task = None
        self.num_tasks_completed = 0

        # response returned by current task
        self.response = None
        # all saved task responses, plus some other metadata
        self.responses = [
            TaskResponse(self.sid, 'SID'),
            TaskResponse(self.iphash, 'IPHASH'),
            TaskResponse(request.headers.get('User-Agent'), 'USER_AGENT')]

        self.state = State.ACTIVE

        self.inact_timeout_time = \
            self.start_time + cfg.inact_timeout_secs
        self.global_timeout_time = None

        @socketio.on('init_task', namespace=f'/{self.sid}')
        def sio_init_task():
            return self.task.variables

        @socketio.on('next_page', namespace=f'/{self.sid}')
        def sio_next_page(resp):
            if self.task.next_tasks:
                # if we're not here, the user was somehow able
                # to hit 'Next' on the final task screen,
                # which shouldn't be possible ...
                self.handle_response(resp)
                self.next_task()
            return self.task.variables

        @socketio.on('debug_fwd', namespace=f'/{self.sid}')
        def sio_debug_fwd():
            if self.task.next_tasks:
                self.task_fwd()
            return self.task.variables

        @socketio.on('debug_back', namespace=f'/{self.sid}')
        def sio_debug_back():
            if self.task.prev_task:
                self.task_back()
            return self.task.variables

        @socketio.on('get_feedback', namespace=f'/{self.sid}')
        def sio_get_feedback(resp):
            return self.task.get_feedback(resp)

    @classmethod
    def setup(cls, path, mode, target, conds):
        global app
        from . import app as theapp
        app, cls.app = theapp, theapp
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
        if mode == 'rep':
            cls.record = Record(cls)
            cls.record.replicate = target
            cls.record.save()
            cls.replicate = Record(cls, target)
        elif mode == 'res':
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
        cls.static_path = cls.dir_path / cfg.static_dir
        cls.profiles_path = cls.dir_path / cfg.profiles_dir
        cls.runs_path = cls.dir_path / cfg.runs_dir
        cls.templates_path = cls.dir_path / cfg.templates_dir

    @classmethod
    def load_profiles(cls):
        if cls.replicate:
            rep_profs = cls.replicate.completed_profiles()
        else:
            rep_profs = None
        cond_paths = [p for p in cls.profiles_path.iterdir() if p.is_dir()]
        if cond_paths:
            app.logger.info('loading profiles')
            for cond_path in cond_paths:
                condname = cond_path.name
                run_cond_path = cls.record.run_path / condname
                for profile_path in cond_path.iterdir():
                    profname = profile_path.name
                    if profname.startswith('.'):
                        continue
                    if cls.replicate and \
                       f'{condname}/{profname}' not in rep_profs:
                        continue
                    p = cls.profile_mod().Profile.load(
                        cls, condname, profname)
                    cls.profiles.setdefault(p.cond, {})[profname] = p
                    # mark profile as used if we have a result
                    # for that profile
                    fullprofname = f'{cond_path.name}/{profname}'
                    if (run_cond_path / profname).is_file():
                        app.logger.info(
                            f'marking profile {fullprofname} as used')
                        p.use()
        else:
            cls.make_profiles()

    @classmethod
    def make_profiles(cls):
        app.logger.info('creating profiles')
        items_per_cond = round(
            cls.params_mod().n_profiles/len(cls.cond_mod().conds))
        app.logger.info(f'profiles per condition: {items_per_cond}')
        for cname, c in cls.cond_mod().conds.items():
            app.logger.info(f'creating profiles for condition {cname}')
            (cls.profiles_path / cname).mkdir()
            cls.profiles[c] = {}
            for i in range(items_per_cond):
                p = cls.profile_mod().Profile(cls, c)
                cls.profiles[c][p.subjid] = p
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
    def present_dashboard(cls):
        variables = {'exper': cls.name,
                     'expercss': f'/expert/{cls.name}/css/main.css',
                     'window_title': cls.window_title}
        return render_template('dashboard.j2.html', **variables)

    def choose_cond(self):
        cond_counts = Counter()
        # make sure we have a key for each cond
        for cname, c in self.cond_mod().conds.items():
            if not self.conds or cname in self.conds:
                cond_counts[c] = 0

        # count currently-active and completed instances in memory
        for inst in self.instances.values():
            if inst.state in (State.ACTIVE, State.COMPLETE):
                cond_counts[inst.profile.cond] += 1
        # count completed instances
        for fqname in self.record.completed_profiles():
            c, prof = fqname.split('/')
            cond_counts[self.cond_mod().conds[c]] += 1

        return min(cond_counts.keys(), key=lambda k: cond_counts[k])

    def choose_profile(self):
        if self.replicate:
            avail = [p for c in self.profiles
                     for p in self.profiles[c].values() if not p.used]
        else:
            # find cond with fewest participants
            cond = self.choose_cond()
            avail = [p for p in self.profiles[cond].values() if not p.used]

        if not avail:
            app.logger.warning('no profiles are available')
            raise ExperFullError()

        p = random.choice(avail)
        p.use()
        return p

    def present(self, tplt_vars={}):
        return self.task.present(tplt_vars)

    # Called by sio_next_page immediately before next_task()
    def handle_response(self, resp):
        self.response = TaskResponse(
            resp, self.task.template_name, self.task.resp_extra)
        app.logger.info(
            f'{self.profile} completed "{self.response.task_name}"'
            f' ({self.num_tasks_completed + 1})')
        if isinstance(self.task, tasks.Consent) and resp == 'consent_declined':
            # make sure we didn't time out right before
            if self.state == State.ACTIVE:
                app.logger.info(
                    f'consent declined for profile {self.profile}')
                self.task.next_tasks = [tasks.Task(self.sid, 'nonconsent')]
                self.state = State.CONSENT_DECLINED
                self.end()
                self.save_responses()
                # NB: the sid stays in the session so we can keep
                # serving up the consent-declined page
                self.profile.unuse()

    def task_fwd(self, resp=None):
        # XXX currently doesn't handle forking task paths
        self.task = self.task.next_task(resp)

    def task_back(self):
        self.task = self.task.prev_task

    # Called by sio_next_page immediately after handle_response()
    def next_task(self):
        self.task_fwd(self.response)

        if self.state == State.ACTIVE:
            now = time.monotonic()
            if self.task.timeout_secs is not None:
                if self.task.timeout_secs >= 0:
                    self.global_timeout_time = now + self.task.timeout_secs
                else:
                    # negative value disables the timeout
                    self.global_timeout_time = None
            self.inact_timeout_time = \
                now + cfg.inact_timeout_secs

            if self.response is None:
                # previous task did not send a response
                self.responses.append(TaskResponse(
                    None, self.task.prev_task.template_name,
                    self.task.prev_task.resp_extra))
            else:
                self.responses.append(self.response)
            self.response = None

            if not self.task.next_tasks:
                # This is the final task. It must simply be some sort of
                # "thank you" page where no data is collected.
                # When the final task is displayed, the subject's responses
                # are saved to disk. Their instance remains in memory
                # so that if they reload the page, they won't lose any,
                # e.g., mturk completion code that is displayed.
                self.state = State.COMPLETE
                self.end()
                self.save_responses()

        self.num_tasks_completed += 1
        self.socketio.emit('update_instance', self.status())

    def status(self):
        if self.state == State.ACTIVE:
            elapsed_time = time.monotonic() - self.start_time
        else:
            elapsed_time = self.end_time - self.start_time
        return [
            f'{self.sid[:6]}...', self.clientip, str(self.profile),
            self.state.name, self.num_tasks_completed,
            self.start_timestamp[11:].replace('.', ':'),
            f'{elapsed_time/60:.1f}']

    def save_responses(self):
        cond_path = self.record.run_path / str(self.profile.cond)
        if self.state == State.TIMED_OUT:
            resp_path = cond_path / (self.profile.subjid + '-timeout')
        else:
            resp_path = cond_path / self.profile.subjid
        # newline='' must be set for the csv module
        with open(resp_path, 'w', newline='') as f:
            if cfg.output_format == 'csv':
                writer = csv.writer(f, lineterminator='\n')
                # write the header line
                writer.writerow(['tstamp', 'taskname', 'resp', 'extra'])
                for r in self.responses:
                    # NB: None is written as the empty string
                    writer.writerow([r.timestamp, r.task_name,
                                     r.response, r.extra])
            elif cfg.output_format == 'json':
                import json
                output = []
                for r in self.responses:
                    item = {'timestamp': r.timestamp, 'task': r.task_name}
                    if r.response is not None:
                        item['response'] = r.response
                    if r.extra is not None:
                        item['extra'] = r.extra
                    output.append(item)
                json.dump(output, f, indent=2)
            else:
                # XXX would probably be better to sanity-check this
                # when the program loads
                raise BadOutputFormatError(cfg.output_format)

    def check_for_timeout(self):
        if self.state != State.ACTIVE:
            return
        if self.global_timeout_time:
            tout_time = min(self.inact_timeout_time,
                            self.global_timeout_time)
        else:
            tout_time = self.inact_timeout_time
        if tout_time and time.monotonic() >= tout_time:
            app.logger.info(f'profile {self.profile} timed out')
            self.state = State.TIMED_OUT
            self.task.next_tasks = [tasks.Task(self.sid, 'timedout')]
            self.end()
            self.profile.unuse()
            self.save_responses()
        self.socketio.emit('update_instance', self.status())

    # called for normal completion, timeout, or nonconsent
    def end(self):
        self.end_time = time.monotonic()


class Record:

    def __init__(self, experclass, fromsaved=None):
        self.experclass = experclass
        if fromsaved:
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
        else:
            self.start_time = timestamp.make_timestamp()
            self.replicate = None
        self.run_path = experclass.runs_path / self.start_time

    def completed_profiles(self):
        # list of strings of form 'cond/prof'
        profiles = []
        for cond_path in self.run_path.iterdir():
            if cond_path.is_dir():
                for prof_path in cond_path.iterdir():
                    prof = prof_path.name
                    if not (prof.startswith('.') or prof.endswith('-timeout')):
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
