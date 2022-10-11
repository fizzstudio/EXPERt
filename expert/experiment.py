
from __future__ import annotations

import random
import sys
import traceback
import time
import datetime
import importlib
import importlib.util
import csv
import json
import secrets

from pathlib import Path
from enum import Enum
from functools import reduce
from typing import ClassVar, Optional, Any
from click.core import Option

from flask import session, request, make_response, send_from_directory

import expert
from . import (
    tasks, timestamp, profile, templates
)

import strictyaml


class State(Enum):
    ACTIVE = 0
    CONSENT_DECLINED = 1
    TIMED_OUT = 2
    COMPLETE = 3
    TERMINATED = 4


resp_file_suffixes = {
    # NB: CONSENT_DECLINED insts never have their results saved
    State.TIMED_OUT: '-timeout',
    State.TERMINATED: '-terminated'
}


class TaskResponse:
    response: Any
    task_name: str
    timestamp: str
    sid: Optional[str]
    cond: Optional[str]
    extra: dict[str, Any]
    def __init__(self, response, task_name,
                 ts=None, sid=None, cond=None, **extra):
        self.response = response
        self.task_name = task_name
        self.timestamp = ts or timestamp.make_timestamp()
        self.sid = sid
        self.cond = cond
        # reserved for output files
        for reserved in ['tstamp', 'task', 'resp']:
            assert reserved not in extra
        self.extra = extra


class NoSuchCondError(Exception):
    def __init__(self, condname):
        super().__init__(f'no such condition(s) "{condname}"')


class BadOutputFormatError(Exception):
    def __init__(self, fmt):
        super().__init__(f'unknown output format "{fmt}"')


class BaseExper:

    dir_path: ClassVar[Path]
    static_path: ClassVar[Path]
    profiles_path: ClassVar[Path]
    runs_path: ClassVar[Path]
    templates_path: ClassVar[Path]
    dls_path: ClassVar[Path]
    mode: ClassVar[str]
    target: ClassVar[Optional[str]]
    run: ClassVar[str]
    record: ClassVar[Record]
    replicate: ClassVar[Optional[Record]]
    name: ClassVar[str]
    profiles: ClassVar[list[profile.Profile]] = []
    # sid: <Experiment subclass inst>
    instances: ClassVar[dict[str, BaseExper]] = {}

    ## instance vars
    sid: str
    profile: Optional[profile.Profile]
    start_time: float
    start_timestamp: str
    task: tasks.Task
    last_task: tasks.Task
    tasks_by_id: dict[int, tasks.Task]

    def __init__(self, clientip, urlargs):
        self.sid = secrets.token_hex(16)
        self.urlargs = urlargs

        self.profile = None

        self.instances[self.sid] = self
        self.start_time = time.monotonic()
        self.start_timestamp = timestamp.make_timestamp()

        # tasks are stored in a linked tree structure
        #self.task = None
        # None if there are forking paths through the experiment
        #self.last_task = None
        # total number of task instances created
        # (not necessarily the number the participant will complete)
        self.num_tasks_created = 0
        self.tasks_by_id = {}
        #self.num_tasks_completed = 0
        self.task_cursor = 1
        # gets set to True if a Consent task is created
        self.has_consent_task = False

        # response returned by current task
        self.response = None
        # {task.id: TaskResponse}
        self.responses = {}
        self.pseudo_responses = [
            TaskResponse(self.sid, 'SID'),
        ]

        self.clientip = clientip
        self.prolific_pid = None

        self.state = State.ACTIVE

        # template variables shared by all tasks for the experiment
        self.variables = {
            'exp_prolific_pid': self.prolific_pid,
            'exp_sid': self.sid
        }

        @socketio.on('init_task', namespace=f'/{self.sid}')
        def sio_init_task():
            return self.task.all_vars()

        @socketio.on('next_page', namespace=f'/{self.sid}')
        def sio_next_page(resp):
            if self.task.next_tasks or isinstance(self.task, tasks.Consent):
                # if we're not here, the user was somehow able
                # to hit 'Next' on the final task screen,
                # which shouldn't be possible ...
                #self.handle_response(resp)
                self._next_task(resp)
            return self.task.all_vars()

        @socketio.on('get_feedback', namespace=f'/{self.sid}')
        def sio_get_feedback(resp):
            return self.task.get_feedback(resp)

        @socketio.on('load_template', namespace=f'/{self.sid}')
        def sio_load_template(tplt, tplt_vars={}):
            return templates.render(f'{tplt}{templates.html_ext}', tplt_vars)

        @socketio.on_error(f'/{self.sid}')
        def sio_inst_error(e):
            expert.log.info(f'socketio error:\n{traceback.format_exc()}')

    @classmethod
    def start(cls, path, mode, obj, conds=None, tool_mode=False):
        cls.dir_path = Path(path).resolve(True)

        cls._read_config()

        cls.mode = mode
        cls.target = None
        if mode == 'res':
            cls.run = obj
        elif mode == 'rep':
            cls.target = obj
            cls.run = timestamp.make_timestamp()
        else:
            cls.run = timestamp.make_timestamp()

        expert.enable_tool_mode(tool_mode or cls.cfg['tool_mode'])

        expert.experclass = cls._load()
        if expert.experclass is None:
            sys.exit(f'unable to load experiment "{cls.dir_path}"')

        expert.experclass._setup(path, conds)
        expert.experclass._add_routes()

        templates.set_variables()

        cls.running = True

    @classmethod
    def reload(cls):
        expert.log.info('*** reloading experiment bundle ***')
        # XXX Should this be allowed if there are active instances?
        # In experiment mode, I'm inclined to say no, since even
        # if the nstance code remains the same (the instance object
        # doesn't get replaced), resources might change.Might be
        # desirable in tool mode, though.
        cls._read_config()
        # NB: Reloading does NOT start a new run.
        # Reloading implies the bundle has changed, so
        # allowing resuming seems counter-intuitive. But,
        # it's possible a bug might need fixing mid-run,
        # so it might be useful.
        expert.experclass = cls._load()

    @classmethod
    def _add_routes(cls):
        first_request_setup_complete = False

        @expert.app.route('/' + expert.cfg['url_prefix'])
        def index():
            nonlocal first_request_setup_complete
            if not first_request_setup_complete:
                cls._first_request_setup()
                first_request_setup_complete = True
            content = None
            inst = expert.get_inst()
            if not inst:
                if not expert.tool_mode and not cls.running:
                    content = templates.render('norun' + templates.html_ext)
                else:
                    ip = request.headers.get('X-Real-IP', request.remote_addr)
                    if ',' in ip:
                        ip = ip.split(',')[0]
                    if cls.profiles:
                        # not full yet
                        inst = cls(ip, request.args)
                        session['sid'] = inst.sid
                        expert.log.info(f'new instance for sid {inst.sid[:4]}')
                        socketio.emit('new_instance', inst.status())
                        inst._will_start()
                    else:
                        content = templates.render('full' + templates.html_ext)

            if content is None:
                content = inst._present()

            resp = make_response(content)
            # Caching is disabled entirely to ensure that
            # users always get fresh content
            resp.cache_control.no_store = True

            return resp

        @expert.app.route(f'/{expert.cfg["url_prefix"]}/app/{cls.id}/<path:subpath>')
        def exper_static(subpath):
            return send_from_directory(cls.static_path, subpath)

    @classmethod
    def _first_request_setup(cls):
        # session will expire after 24 hours
        expert.app.permanent_session_lifetime = datetime.timedelta(hours=24)
        # session cookie will expire after app.permanent_session_lifetime
        session.permanent = True
        if request.url.startswith('https'):
            expert.app.config['SESSION_COOKIE_SECURE'] = True
        else:
            expert.app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    @classmethod
    def _read_config(cls):
        with open(expert.expert_path / 'cfg.json') as f:
            cls.cfg = json.load(f)
        exper_cfg_path = cls.dir_path / 'cfg.json'
        exper_cfg = {}
        if exper_cfg_path.is_file():
            with open(exper_cfg_path) as f:
                exper_cfg = json.load(f)

        exper_id = exper_cfg.get('id')
        cls.id = exper_id or secrets.token_urlsafe(8)
        if not exper_id:
            exper_cfg['id'] = cls.id
            with open(exper_cfg_path, 'w') as f:
                json.dump(exper_cfg, f, indent=2)

        cls.cfg.update(exper_cfg)

    @classmethod
    def _load(cls):
        """Load the experiment in the directory at cls.dir_path.

        NB: The source code for the experiment must be located in
        the 'src' subfolder of the experiment bundle directory.
        E.g., if exper_path == '/foo/bar/my_exper', the source code
        must be located in /foo/bar/my_exper/src.
        """
        #exper_path = Path(exper_path).resolve(True)
        expert.log.info(f'loading experiment from {cls.dir_path}')
        init_path = cls.dir_path / 'src' / '__init__.py'
        spec = importlib.util.spec_from_file_location('src', init_path)
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = pkg
        expert.log.info(f'experiment package name: {pkg.__name__}')
        spec.loader.exec_module(pkg)
        ##params = importlib.import_module('.params', pkg)
        #params = __import__('src.params', fromlist=['params'])
        # return the first subclass of Experiment found
        for k, v in pkg.__dict__.items():
            if isinstance(v, type) and issubclass(v, expert.Experiment) and \
               v is not expert.Experiment:
                return v
        return None

    @classmethod
    def _setup(cls, path, conds):
        global socketio
        from . import socketio as thesocketio
        socketio = thesocketio
        cls.name = cls.__qualname__.lower()
        cls._setup_paths()
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
        cls.dls_path.mkdir(exist_ok=True)
        cls.conds = conds
        cls.replicate = None
        cls.record = Record(cls)
        if cls.mode == 'rep':
            cls.record.replicate = cls.target
            cls.record.save()
            cls.replicate = Record(cls, cls.target)
        elif cls.mode == 'res':
            if cls.record.replicate:
                cls.replicate = Record(cls, cls.record.replicate)
        else:
            cls.record.save()
        cls._load_profiles()

    @classmethod
    def _setup_paths(cls):
        expert.log.info(f'bundle path: {cls.dir_path}')
        cls.static_path = cls.dir_path / cls.cfg['static_dir']
        cls.profiles_path = cls.dir_path / cls.cfg['profiles_dir']
        cls.runs_path = cls.dir_path / cls.cfg['runs_dir']
        cls.templates_path = cls.dir_path / cls.cfg['templates_dir']
        cls.dls_path = cls.dir_path / cls.cfg['dls_dir']

    @classmethod
    def _read_cond_paths(cls):
        return [p for p in cls.profiles_path.iterdir()
                if p.is_dir() and p.stem[0] != '.']

    @classmethod
    def _load_profiles(cls):
        if cls.replicate:
            rep_profs = cls.replicate.completed_profiles()
        else:
            rep_profs = None
        cond_paths = cls._read_cond_paths()
        if not cond_paths:
            cls._make_profiles()
            cond_paths = cls._read_cond_paths()

        expert.log.info('loading profiles')
        cls.profiles.clear()
        for cond_path in cond_paths:
            condname = cond_path.name
            if cls.conds and condname not in cls.conds:
                continue
            run_cond_path = cls.record.run_path / condname
            for prof_path in cond_path.iterdir():
                profname = prof_path.name
                if profname.startswith('.') or not prof_path.is_file():
                    continue
                if cls.replicate and \
                   f'{condname}/{profname}' not in rep_profs:
                    continue
                # only load profile if we don't have a result
                # for that profile
                #fullprofname = f'{cond_path.name}/{profname}'
                if not (run_cond_path / profname).is_file():
                    p = cls.profile_mod().Profile.load(
                        condname, profname)
                    cls.profiles.append(p)
        random.shuffle(cls.profiles)
        # the actual list of profiles will shrink
        # as the experiment progresses
        cls.num_profiles = len(cls.profiles)

    @classmethod
    def _make_profiles(cls):
        expert.log.info('creating profiles')
        cls.cond_size = round(
            cls.params_mod().n_profiles/len(cls.cond_mod().conds))
        expert.log.info(f'profiles per condition: {cls.cond_size}')
        for cname, c in cls.cond_mod().conds.items():
            expert.log.info(f'creating profiles for condition {cname}')
            (cls.profiles_path / cname).mkdir()
            for i in range(cls.cond_size):
                p = cls.profile_mod().Profile(c)
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
    def collect_responses(cls, run):
        run_path = cls.runs_path / run
        by_cond = {}
        for cond in run_path.iterdir():
            if cond.name == 'id-mapping' or not cond.is_dir():
                continue
            by_cond[cond.name] = {}
            for respath in cond.iterdir():
                if respath.stem[0] == '.':
                    continue
                if cls.cfg['output_format'] == 'csv':
                    with open(respath, newline='') as f:
                        reader = csv.reader(f, lineterminator='\n')
                        rows = list(reader)
                        headers = rows[0]
                        sid = rows[1][2]
                        by_cond[cond.name][sid] = []
                        # skip header row
                        for row in rows[1:]:
                            by_cond[cond.name][sid].append(TaskResponse(
                                row[2], row[1], row[0], sid, cond.name,
                                **dict(zip(headers[3:], row[3:]))))
                elif cls.cfg['output_format'] == 'json':
                    # 'tstamp', 'task', 'resp', + extra fields
                    with open(respath) as f:
                        items = json.load(f)
                    sid = items[0]['resp']
                    by_cond[cond.name][sid] = []
                    for item in items:
                        extras = item.copy()
                        extras.pop('tstamp')
                        extras.pop('task')
                        extras.pop('resp', None)
                        by_cond[cond.name][sid].append(TaskResponse(
                            item.get('resp'), item['task'], item['tstamp'],
                            sid, cond.name, **extras))
                else:
                    # XXX would probably be better to sanity-check this
                    # when the program loads
                    raise BadOutputFormatError(cls.cfg['output_format'])
        return sum([by_cond[c][s]
                    for c in sorted(by_cond.keys())
                    for s in sorted(by_cond[c].keys())], [])

    @classmethod
    def write_responses(cls, resps, dest_path):
        if resps[0].sid:
            all_sids = set(r.sid for r in resps)
            min_uniq_len = 0
            while len(set(sid[:(min_uniq_len := min_uniq_len + 1)]
                          for sid in all_sids)) < len(all_sids):
                pass
            min_uniq_len = max(min_uniq_len, 4)

        # newline='' must be set for the csv module
        with open(dest_path, 'w', newline='') as f:
            if cls.cfg['output_format'] == 'csv':
                writer = csv.writer(f, lineterminator='\n')
                extras = set()
                # collect all extra response field names
                for r in resps:
                    for k in r.extra:
                        extras.add(k)
                headers = ['time', 'task', 'resp', *extras]
                if resps[0].sid:
                    headers = ['sid', 'cond'] + headers
                writer.writerow(headers)
                for r in resps:
                    # NB: None is written as the empty string
                    data = [r.timestamp, r.task_name, r.response,
                            *[r.extra.get(e) for e in extras]]
                    if r.sid:
                        data = [r.sid[:min_uniq_len], r.cond] + data
                    writer.writerow(data)
            elif cls.cfg['output_format'] == 'json':
                output = []
                for r in resps:
                    item = {'time': r.timestamp, 'task': r.task_name}
                    if r.response is not None:
                        item['resp'] = r.response
                    item.update(r.extra)
                    if r.sid:
                        item['sid'] = r.sid[:min_uniq_len]
                        item['cond'] = r.cond
                    output.append(item)
                json.dump(output, f, indent=2)
            else:
                # XXX would probably be better to sanity-check this
                # when the program loads
                raise BadOutputFormatError(cls.cfg['output_format'])

    def create_tasks(self):
        """Overridden by the bundle class to create post-consent tasks."""
        pass

    def nav_items(self):
        """May be overridden by the bundle class to add nav menu items."""
        if self.last_task:
            return [('First', self.first_task), ('Last', self.last_task)]
        else:
            return []

    def status(self):
        y, mo, d, h, mi, s = self.start_timestamp.split('.')
        return [
            self.sid, self.clientip,
            str(self.profile) if self.profile else 'unassigned',
            self.state.name, self.task_cursor,
            #self.start_timestamp[11:].replace('.', ':'),
            f'{mo}/{d}/{y} {h}:{mi}:{s}',
            f'{self._elapsed_time()/60:.1f}']

    def assign_profile(self):
        self.profile = self.profiles.pop(0)
        expert.log.info(
            f'sid {self.sid[:4]} assigned profile: {self.profile}')
        self.create_tasks()
        self.variables['exp_num_tasks'] = self.num_tasks_created

    def _will_start(self):
        self.first_task = self.task
        if not self.has_consent_task:
            self.assign_profile()
        self.variables['exp_num_tasks'] = self.num_tasks_created
        self._update_vars()

    def _next_task(self, resp):
        pass

    def _present(self, tplt_vars={}):
        return self.task.present(tplt_vars)

    def _update_vars(self):
        self.variables['exp_task_cursor'] = self.task_cursor
        self.variables['exp_state'] = self.state.name

    def _store_resp(self, resp):
        task_resp = TaskResponse(
            resp, self.task.template_name, **self.task.resp_extra)
        self.responses[self.task.id] = task_resp
        #self.task.did_store_resp(resp)

    def _elapsed_time(self):
        return time.monotonic() - self.start_time

    def _save_pii(self, pii):
        # dir might exist if resuming
        self.record.id_mapping_path.mkdir(exist_ok=True)
        pii_path = self.record.id_mapping_path / self.sid
        output = [{'key': 'SESSION_ID', 'val': self.sid}]
        for item in pii:
            record = {'key': item.task_name, 'val': item.response}
            output.append(record)
        with open(pii_path, 'w') as f:
            json.dump(output, f, indent=2)

    def _save_responses(self):
        cond_path = self.record.run_path / str(self.profile.cond)
        resp_path = cond_path / (self.profile.subjid +
                                 resp_file_suffixes.get(self.state, ''))
        actual_resps = [self.responses[tid]
                        for tid in sorted(self.responses.keys())]
        all_resps = self.pseudo_responses + actual_resps
        def splitter(pii_resps, resp):
            if resp.task_name in self.cfg['pii']:
                pii_resps[0].append(resp)
            else:
                pii_resps[1].append(resp)
            return pii_resps
        pii, resps = reduce(splitter, all_resps, [[], []])
        if pii:
            self._save_pii(pii)
        self.write_responses(resps, resp_path)


class Record:

    def __init__(self, experclass, fromsaved=None):
        self.experclass = experclass
        fromsaved = fromsaved or experclass.run
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
        self.id_mapping_path = self.run_path / 'id-mapping'

    def completed_profiles(self) -> list[str]:
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

