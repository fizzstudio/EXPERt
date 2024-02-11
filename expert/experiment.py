
from __future__ import annotations

import random
import sys
import traceback
import time
import importlib
import importlib.util
import csv
import json

from pathlib import Path
from enum import Enum
from functools import reduce
from typing import ClassVar, Optional, Any, Type, TypedDict, Union, cast, Literal

from werkzeug.datastructures import MultiDict

import expert as e
from . import (
    tasks, profile, templates
)

import strictyaml

ExperMode = Literal['new', 'res', 'rep']

class State(Enum):
    ACTIVE = 0
    CONSENT_DECLINED = 1
    TIMED_OUT = 2
    COMPLETE = 3
    TERMINATED = 4
    RETURNED = 5


resp_file_suffixes = {
    # NB: CONSENT_DECLINED insts never have their results saved
    State.TIMED_OUT: '-timeout',
    State.TERMINATED: '-terminated',
    State.RETURNED: '-returned'
}


class TaskResponse:
    response: Any
    task_name: str
    timestamp: int
    sid: Optional[str]
    cond: Optional[str]
    prof: Optional[str]
    extra: dict[str, Any]
    def __init__(self, response: Any, task_name: str,
                 ts: Optional[int] = None, sid: Optional[str] = None, 
                 cond: Optional[str] = None, prof: Optional[str] = None, 
                 **extra: dict[str, Any]):
        self.response = response
        self.task_name = task_name
        self.timestamp = ts or int(time.time())*1000 # msec since start of epoch
        self.sid = sid
        self.cond = cond
        self.prof = prof
        # reserved for output files
        for reserved in ['time', 'task', 'resp', 'sid', 'cond', 'prof']:
            assert reserved not in extra
        self.extra = extra


class NoSuchCondError(Exception):
    def __init__(self, condname: str):
        super().__init__(f'no such condition(s) "{condname}"')


class BadOutputFormatError(Exception):
    def __init__(self, fmt: str):
        super().__init__(f'unknown output format "{fmt}"')


class API:

    def __init__(self, inst: BaseExper):
        self._inst = inst

    def soundcheck(self, resp: str) -> bool:
        return resp.strip().lower() == e.soundcheck_word

    def init_task(self):
        return self._inst.all_vars()

    def next_page(self, resp: Any):
        if self._inst.task.next_tasks or \
           isinstance(self._inst.task, tasks.Consent):
            # if we're not here, the user was somehow able
            # to hit 'Next' on the final task screen,
            # which shouldn't be possible ...
            #self.handle_response(resp)
            self._inst.next_task(resp)
        return self._inst.all_vars()

    def get_feedback(self, resp: Any):
        return self._inst.task.get_feedback(resp)

    def load_template(self, tplt: str, tplt_vars: dict[str, Any] = {}):
        return templates.render(tplt, tplt_vars)


class BaseExper:

    # Initialized immediately after bundle is loaded, so 
    # not typed as Optional
    name: ClassVar[str]
    cfg: ClassVar[dict[str, Any]]
    dir_path: ClassVar[Path]
    static_path: ClassVar[Path]
    profiles_path: ClassVar[Path]
    runs_path: ClassVar[Path]
    templates_path: ClassVar[Path]
    dls_path: ClassVar[Path]
    temp_path: ClassVar[Path]
    running: ClassVar[bool]
    _cond_paths: ClassVar[list[Path]]

    conds: ClassVar[Optional[list[str]]] = None
    temp_run_path: ClassVar[Optional[Path]] = None
    mode: ClassVar[Optional[ExperMode]] = None  # set on subclass
    target: ClassVar[Optional[str]] = None      # set on subclass
    run: ClassVar[Optional[str]] = None         # set on subclass
    record: ClassVar[Optional[Record]] = None   # set on subclass
    replicate: ClassVar[Optional[Record]] = None
    profiles: ClassVar[list[profile.Profile]] = [] # mutated by subclass
    num_profiles: ClassVar[int]                 # set on subclass
    # sid: <Experiment subclass inst>
    instances: ClassVar[dict[str, BaseExper]] = {} # mutated by subclass
    api_class: ClassVar[Type[API]] = API

    ## instance vars
    sid: str
    temp_work_path: Path
    urlargs: MultiDict[str, str]
    profile: Optional[profile.Profile]
    start_time: float
    start_timestamp: int
    end_time: float
    task: tasks.Task
    last_task: Optional[tasks.Task]
    tasks_by_id: dict[int, tasks.Task]
    state: State
    responses: dict[int, TaskResponse]
    variables: dict[str, Any]

    def __init__(self, clientip: str, urlargs: MultiDict[str, str], sid: str):
        assert self.temp_run_path is not None
        self.sid = sid 
        self.temp_work_path = self.temp_run_path / self.sid
        self.temp_work_path.mkdir(exist_ok=self.mode == 'res')
        self.urlargs = urlargs

        self.profile = None

        self.start_time = time.monotonic()
        self.start_timestamp = int(time.time())*1000

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

        self._api = self.api_class(self)

        @e.srv.socketio.on('connect', namespace=f'/{self.sid}')
        def sio_connect():
            e.log.info(f'sid {self.sid[:4]} socket connected')
        @e.srv.socketio.on('disconnect', namespace=f'/{self.sid}')
        def sio_disconnect():
            e.log.info(f'sid {self.sid[:4]} socket disconnected')
        @e.srv.socketio.on_error(namespace=f'/{self.sid}')
        def sio_error(err):
            e.log.error(f'sid {self.sid[:4]} socket error: {err}\n{traceback.format_exc()}')
        @e.srv.socketio.on('call_api', namespace=f'/{self.sid}')
        def sio_call(cmd: str, *args:list[Any]):
            try:
                f = getattr(self._api, cmd)
                val = f(*args)
            except:
                tback = traceback.format_exc()
                e.log.error(f'SID {self.sid[:4]} API \'{cmd}\' error: {tback}')
                e.srv.dboard.api_error(tback)
                return {'err': tback}
            return {'val': val}

    @classmethod
    def make_run_timestamp(cls):
        # Pad numbers with leading zeros to a fixed width
        def pad(n: int, width: int):
            return format(n, f'0{width}')
        precise_time = time.time()
        seconds = int(precise_time)
        ltime = time.localtime(seconds)
        ymd = '.'.join([str(ltime.tm_year), pad(ltime.tm_mon, 2), pad(ltime.tm_mday, 2)])
        same_day_runs = [r for r in cls.runs_path.iterdir() if r.name.startswith(ymd)]
        if len(same_day_runs):
            ymd += f'-{len(same_day_runs) + 1}'
        return ymd

    @classmethod
    def init(cls, path: Path, is_reloading: bool):
        cls.name = cls.__qualname__.lower()
        e.log.info(f'initializing class {cls.__qualname__}')
        cls.dir_path = path
        cls.pkg = sys.modules[cls.__module__]
        cls._setup_paths()
        # create main experiment directories, if they don't exist
        cls.dir_path.mkdir(exist_ok=True)
        cls.runs_path.mkdir(exist_ok=True)
        cls.profiles_path.mkdir(exist_ok=True)
        cls.dls_path.mkdir(exist_ok=True)
        cls.temp_path.mkdir(exist_ok=True)

        cls._cond_paths = cls._read_cond_paths()
        conds = cls.cond_mod().conds
        e.log.info('conditions: ' + ', '.join([f"'{k}'" for k in conds.keys()]))
        cls.cond_size = round(cls.params_mod().n_profiles/len(conds))
        # We set this early (rather than when they get loaded) so that
        # the dashboard can have this information.
        # NB! This is the total number, not how many get loaded
        # (which may vary due to resumption)
        cls.num_profiles = len(conds)*cls.cond_size
        e.log.info(f'profiles per condition: {cls.cond_size}')
        e.log.info(f'total profiles: {cls.num_profiles}')
        if not cls._cond_paths:
            cls.make_profiles()
            cls._cond_paths = cls._read_cond_paths()
        else:
            e.log.info('found existing profiles; not creating')
        cls.running = False
        cls._setup(is_reloading)

    @classmethod
    def start(cls, mode: ExperMode, obj: Optional[str] = None, 
              conds: Optional[list[str]] = None):
        cls.instances.clear()
        if conds:
            unknown_conds = [c for c in conds
                             if c not in cls.cond_mod().conds]
            if unknown_conds:
                raise NoSuchCondError(', '.join(unknown_conds))
        cls.conds = conds

        cls.mode = mode
        cls.target = None
        if mode == 'res':
            cls.run = obj
        elif mode == 'rep':
            cls.target = obj
            cls.run = cls.make_run_timestamp()
        else:
            cls.run = cls.make_run_timestamp()

        cls.replicate = None
        cls.record = Record(cls)
        if cls.mode == 'rep':
            cls.record.replicate = cls.target
            #cls.record.save()
            cls.replicate = Record(cls, cls.target)
        elif cls.mode == 'res':
            cls.record.set_resumed()
            if cls.record.replicate:
                cls.replicate = Record(cls, cls.record.replicate)
        #else:
            #cls.record.save()

        cls.temp_run_path = cls.temp_path / cast(str, cls.run)
        cls.temp_run_path.mkdir(exist_ok=True)

        cls._load_profiles()

        cls.running = True
        e.log.info(f'--- starting new run {cls.run} ---')

    @classmethod
    def stop(cls):
        e.log.info(f'--- stopping run {cls.run} ---')
        cls.mode = None
        cls.target = None
        cls.run = None
        cls.replicate = None
        cls.record = None
        cls.running = False

    @classmethod
    def _setup(cls, is_reloading: bool):
        """Overridden by bundle class"""
        pass

    @classmethod
    def _setup_paths(cls):
        e.log.info(f'bundle path: {cls.dir_path}')
        cls.static_path = cls.dir_path / cls.cfg['static_dir']
        cls.profiles_path = cls.dir_path / cls.cfg['profiles_dir']
        cls.runs_path = cls.dir_path / cls.cfg['runs_dir']
        cls.templates_path = cls.dir_path / cls.cfg['templates_dir']
        cls.dls_path = cls.dir_path / cls.cfg['dls_dir']
        cls.temp_path = cls.dir_path / cls.cfg['temp_dir']

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

        e.log.info('loading profiles')
        cls.profiles.clear()
        assert cls.record
        for cond_path in cls._cond_paths:
            condname = cond_path.name
            if cls.conds and condname not in cls.conds:
                e.log.info(f'skipping unknown cond dir \'{condname}\'')
                continue
            run_cond_path = cls.record.run_path / condname
            for prof_path in cond_path.iterdir():
                profname = prof_path.name
                if cls.cfg.get('enabled_profiles') and \
                   profname not in cls.cfg['enabled_profiles']:
                    continue
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
                else:
                    e.log.info(f'results file exists for profile \'{condname}/{profname}\'; not loading')
        random.shuffle(cls.profiles)
        # the actual list of profiles will shrink
        # as the experiment progresses
        cls.num_profiles = len(cls.profiles)
        e.log.info(f'loaded {cls.num_profiles} profiles')

    @classmethod
    def make_profiles(cls):
        e.log.info('creating all profiles')
        cls.profiles_path.mkdir(exist_ok=True)
        for cname, c in cls.cond_mod().conds.items():
            e.log.info(f'creating {cls.cond_size} profiles for condition \'{cname}\'')
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
        imported = importlib.import_module('.profile', cls.pkg.__package__)
        return imported

    @classmethod
    def all_active(cls):
        return [inst for inst in cls.instances.values()
                if inst.state == State.ACTIVE]

    @classmethod
    def new_inst(cls, ip: str, args: MultiDict[str, str], sid: str, userid: Optional[str] = None):
        assert cls.record
        inst = cls(ip, args, sid)
        inst._will_start()
        cls.instances[inst.sid] = inst
        e.log.info(f'new instance for sid {inst.sid[:4]}')
        e.srv.dboard.inst_created(inst)
        if cls.mode != 'res':
            cls.record.init_inst(inst, userid)
        return inst

    @classmethod
    def collect_responses(cls, run: str):
        run_path = cls.runs_path / run
        by_cond: dict[str, dict[str, list[TaskResponse]]] = {}
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
                            by_cond[cond.name][sid].append(
                                TaskResponse(
                                    row[2], row[1], row[0],
                                    sid, cond.name, respath.stem,
                                    **dict(zip(headers[3:], row[3:]))))
                elif cls.cfg['output_format'] == 'json':
                    # 'time', 'task', 'resp', + extra fields
                    with open(respath) as f:
                        items = json.load(f)
                    sid = items[0]['resp']
                    by_cond[cond.name][sid] = []
                    for item in items:
                        extras = item.copy()
                        extras.pop('time')
                        extras.pop('task')
                        extras.pop('resp', None)
                        by_cond[cond.name][sid].append(
                            TaskResponse(
                                item.get('resp'), item['task'], item['time'],
                                sid, cond.name, respath.stem, **extras))
                else:
                    # XXX would probably be better to sanity-check this
                    # when the program loads
                    raise BadOutputFormatError(cls.cfg['output_format'])
        return sum([by_cond[c][s]
                    for c in sorted(by_cond.keys())
                    for s in sorted(by_cond[c].keys())], [])

    def _write_response(self, resp: TaskResponse, task_id: int):
        dest_path = self.temp_work_path / f'{task_id}.json'
        with open(dest_path, 'w') as f:
            item = {'time': resp.timestamp, 'task': resp.task_name}
            if resp.response is not None:
                item['resp'] = resp.response
            item.update(resp.extra)
            json.dump(item, f, indent=2)

    def _load_response(self, task_id: int):
        load_path = self.temp_work_path / f'{task_id}.json'
        # 'time', 'task', 'resp', + extra fields
        with open(load_path) as f:
            item = json.load(f)
        extras = item.copy()
        extras.pop('time')
        extras.pop('task')
        extras.pop('resp', None)
        return TaskResponse(
            item.get('resp'), item['task'], item['time'], **extras)

    @classmethod
    def write_responses(cls, resps: list[TaskResponse], dest_path: Path):
        if resps[0].sid:
            all_sids = set(cast(str, r.sid) for r in resps)
            min_uniq_len = 0
            while len(set(sid[:(min_uniq_len := min_uniq_len + 1)]
                          for sid in all_sids)) < len(all_sids):
                pass
            min_uniq_len = max(min_uniq_len, 4)

        # newline='' must be set for the csv module
        with open(dest_path, 'w', newline='') as f:
            if cls.cfg['output_format'] == 'csv':
                writer = csv.writer(f, lineterminator='\n')
                extras: set[str] = set()
                # collect all extra response field names
                for r in resps:
                    for k in r.extra:
                        extras.add(k)
                headers = ['time', 'task', 'resp', *extras]
                if resps[0].sid:
                    headers = ['sid', 'cond', 'prof'] + headers
                writer.writerow(headers)
                for r in resps:
                    # NB: None is written as the empty string
                    data = [r.timestamp, r.task_name, r.response,
                            *[r.extra.get(e) for e in extras]]
                    if r.sid:
                        data = [r.sid[:min_uniq_len], r.cond, r.prof] + data
                    writer.writerow(data)
            elif cls.cfg['output_format'] == 'json':
                output: list[dict[str, Any]] = []
                for r in resps:
                    item = {'time': r.timestamp, 'task': r.task_name}
                    if r.response is not None:
                        item['resp'] = r.response
                    item.update(r.extra)
                    if r.sid:
                        item['sid'] = r.sid[:min_uniq_len]
                        item['cond'] = r.cond
                        item['prof'] = r.prof
                    output.append(item)
                json.dump(output, f, indent=2)
            else:
                # XXX would probably be better to sanity-check this
                # when the program loads
                raise BadOutputFormatError(cls.cfg['output_format'])

    def create_tasks(self):
        """Overridden by the bundle class to create post-consent tasks."""
        pass

    def nav_items(self) -> list[tuple[str, tasks.Task]]:
        """May be overridden by the bundle class to add nav menu items."""
        if self.last_task:
            return [('First', self.first_task), ('Last', self.last_task)]
        else:
            return []

    def status(self):
        elapsed = self._elapsed_time()
        elapsed_min = int(elapsed//60)
        elapsed_sec = int(elapsed) % 60
        return {
            'profile': str(self.profile) if self.profile else 'unassigned',
            'task': self.task_cursor,
            'elapsed': f'{elapsed_min:02}:{elapsed_sec:02}'
        }

    def assign_profile(self):
        self.profile = self.profiles.pop(0)
        e.log.info(
            f'sid {self.sid[:4]} assigned profile: {self.profile}')
        self.create_tasks()
        self.variables['exp_num_tasks'] = self.num_tasks_created

    def _will_start(self):
        assert self.record
        self.first_task = self.task
        if not self.has_consent_task:
            self.assign_profile()
        self.variables['exp_num_tasks'] = self.num_tasks_created
        if self.mode == 'res':
            # The sid was either retrieved from the record by logging in,
            # or was retained in a session cookie (or may be new, in which
            # case there won't be any inst_data)
            inst_data = self.record.get_inst_data(self.sid)
            if inst_data:
                for fname in self.temp_work_path.iterdir():
                    task_id = int(fname.stem)
                    self.responses[task_id] = self._load_response(task_id)
                self.state = State[inst_data['state']]
                self.task = self.tasks_by_id[inst_data['curr_task_id']]
                self.task_cursor = self.task.id
                if self.state == State.ACTIVE:
                    e.srv.dboard.inst_updated(self)
        self._update_vars()

    def _nav(self, resp: Any, dest_task: tasks.Task):
        assert self.record
        self._store_resp(resp)
        self.task = dest_task
        self.task_cursor = dest_task.id
        self._update_vars()
        #self._save_responses()
        if self.state == State.ACTIVE:
            e.srv.dboard.inst_updated(self)
        self.record.update_inst(self)

    def next_task(self, resp: Any):
        self._nav(resp, self.task.next_task(resp))

    def present(self, tplt_vars={}):
        return self.task.present(tplt_vars)

    def all_vars(self):
        all_vars = templates.variables.copy()
        all_vars.update(self.variables)
        all_vars.update(self.task.variables)
        return all_vars

    def _update_vars(self):
        self.variables['exp_task_cursor'] = self.task_cursor
        self.variables['exp_state'] = self.state.name

    def _store_resp(self, resp: Any):
        task_resp = TaskResponse(
            resp, self.task.template_name, **self.task.resp_extra)
        self.responses[self.task.id] = task_resp
        self._write_response(task_resp, self.task.id)
        #self.task.did_store_resp(resp)

    def _elapsed_time(self):
        if self.state == State.ACTIVE:
            return time.monotonic() - self.start_time
        else:
            return self.end_time - self.start_time

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

    def _response_save_path(self):
        if self.profile:
            cond_path = cast(Record, self.record).run_path / str(self.profile.cond)
            return cond_path / (self.profile.subjid 
                + resp_file_suffixes.get(self.state, ''))
        else:
            # XXX this relies on cfg['output_format'] being set to a valid value
            return cast(Record, self.record).run_path.with_suffix(
                '.' + self.cfg['output_format'])

    def _save_responses(self):
        resp_path = self._response_save_path()
        actual_resps = [self.responses[tid]
                        for tid in sorted(self.responses.keys())]
        all_resps = self.pseudo_responses + actual_resps
        def splitter(pii_resps, resp: TaskResponse):
            if resp.task_name in self.cfg['pii']:
                pii_resps[0].append(resp)
            else:
                pii_resps[1].append(resp)
            return pii_resps
        pii, resps = reduce(splitter, all_resps, [[], []])
        if pii:
            self._save_pii(pii)
        self.write_responses(resps, resp_path)

    def terminate(self):
        if self.state != State.ACTIVE:
            return
        e.log.info(f'sid {self.sid[:4]} terminated')
        self.task.replace_next_task(tasks.Terminated(self))
        self.end(State.TERMINATED)
        if self.profile:
            self.profiles.insert(0, self.profile)

    def end(self, state: State):
        # called for normal completion, timeout, nonconsent, or termination
        self.end_time = time.monotonic()
        self.state = state
        e.srv.dboard.inst_updated(self)
        if self.profile:
            e.log.info(f'saving responses for sid {self.sid[:4]}')
            self._save_responses()


class InstData(TypedDict):
    state: str
    curr_task_id: int
    userid: Optional[str]


class Record:
    # folder name of exper run we are replicating
    replicate: Optional[str]
    run_path: Path
    id_mapping_path: Path
    _experclass: BaseExper
    _run: str
    _md_path: Path
    _inst_data: dict[str, InstData]
    _resume_times: list[int]

    def __init__(self, experclass: BaseExper, fromsaved: Optional[str] = None):
        assert experclass.run
        self._experclass = experclass
        self._run = fromsaved or experclass.run
        self.run_path = experclass.runs_path / self._run
        # create run directory (it will already exist if resuming)
        self.run_path.mkdir(exist_ok=True)
        self.id_mapping_path = self.run_path / 'id-mapping'
        for cname, c in self._experclass.cond_mod().conds.items():
            (self.run_path / cname).mkdir(exist_ok=True)
        self._md_path = self.run_path / 'metadata.json'
        if self._md_path.is_file():
            self.load()
        else:
            self.replicate = None
            self._inst_data = {}
            self._resume_times = []

    def set_resumed(self):
        self._resume_times.append(int(time.time())*1000)

    def completed_profiles(self) -> list[str]:
        # list of strings of form 'cond/prof'
        profiles: list[str] = []
        bad_suffixes = resp_file_suffixes.values()
        for cond_path in self.run_path.iterdir():
            if cond_path.is_dir():
                for prof_path in cond_path.iterdir():
                    prof = prof_path.name
                    if not (prof.startswith('.') or \
                            any(prof.endswith(sfx) for sfx in bad_suffixes)):
                        profiles.append(f'{cond_path.name}/{prof}')
        return profiles

    def init_inst(self, inst: BaseExper, userid: Optional[str] = None):
        inst_data: InstData = {
            'state': inst.state.name,
            'curr_task_id': inst.task.id, 
            'userid': userid
        }
        self._inst_data[inst.sid] = inst_data
        self.save()

    def update_inst(self, inst: BaseExper):
        self._inst_data[inst.sid]['state'] = inst.state.name
        self._inst_data[inst.sid]['curr_task_id'] = inst.task.id
        self.save()

    def lookup_user_sid(self, userid: str) -> str | None:
        for sid, inst_data in self._inst_data.items():
            if inst_data['userid'] == userid:
                return sid
            
    def get_inst_data(self, sid: str) -> InstData | None:
        return self._inst_data.get(sid)
            
    def load(self):
        with open(self._md_path) as f:
            fields = json.load(f)
            self.replicate = fields['replicate']
            self._inst_data = fields['participants']
            self._resume_times = fields['resume_times']

    def save(self):
        # Only the metadata is saved here; the data for each
        # individual participant is saved by the experiment class
        with open(self._md_path, 'w') as f:
            fields = {}
            fields['replicate'] = self.replicate
            fields['participants'] = self._inst_data
            fields['resume_times'] = self._resume_times
            json.dump(fields, f, indent=2)
            #print(strictyaml.as_document(fields).as_yaml(), file=f)

