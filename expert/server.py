
import argparse
import importlib
import importlib.util
import json
import sys
import logging
import logging.handlers
import logging.config
import datetime
import traceback
import gc
import tempfile

from typing import Any, Type, cast, Optional
from pathlib import Path

import tomli

from flask import (
    Flask, session, make_response,
    send_from_directory, request
)

from flask_socketio import SocketIO

import expert as e

from . import experiment, exper, tool, dashboard, templates, user


class BundleLoadError(Exception):
    pass


class App(Flask):

    @property
    def jinja_loader(self):
        loader = getattr(self, '_jinja_loader', None)
        if loader:
            return loader
        self.update_jinja_loader(e.experclass)
        return self._jinja_loader

    def update_jinja_loader(self, experclass: Type[e.Experiment]):
        self._jinja_loader = templates.Loader(
            experclass.templates_path if experclass else None,
            super().jinja_loader)


class Server:

    _args: argparse.Namespace
    cfg: dict[str, Any]
    host: str
    port: int
    bundles_path: Path
    socketio: SocketIO
    dboard: dashboard.Dashboard
    logfile: str
    session_manager: Optional[user.SessionManager] = None

    def __init__(self, args: argparse.Namespace):
        self._args = args
        self.cfg = self._load_config(args.config)

        self.initLogger()
        e.app = App(__name__)
        e.log = e.app.logger
        e.log.info('=== starting EXPERt server ===')
        e.log.info(f'logs saved to {self.logfile}')

        with open(e.expert_path / 'pyproject.toml', 'rb') as f:
            pyproj = tomli.load(f)
        e.ver = pyproj['project']['version']

        e.log.info(f'EXPERt version: {e.ver}')
        e.log.info(f'root path: {e.app.root_path}')
        # sessions aren't enabled until this is set
        # NB: opening the dashboard or displaying a task view
        # doesn't make use of the session
        e.app.secret_key = b'\xe4\xfb\xfd\xff\x80uZL]\xe8B\xcb\x1c\xb3)g'
        e.app.templates_auto_reload = True

        self.host = self.cfg.get('host', '127.0.0.1')
        self.port = self.cfg.get('port', 5000)
        if args.listen:
            if ':' in args.listen:
                h, p = args.listen.split(':')
                self.host = h or self.host
                try:
                    self.port = int(p) if p else self.port
                except ValueError:
                    e.log.warn(f'invalid port; using {self.port}')
            else:
                self.host = args.listen
        e.log.info(f'listening on {self.host}:{self.port}')

        bundles_dir = self.cfg.get('bundles_dir', 'bundles')
        if '..' in bundles_dir:
            sys.exit("config error: '..' not allowed in 'bundles_dir'")
        self.bundles_path = e.expert_path / bundles_dir
        self.bundles_path.mkdir(exist_ok=True)
        e.log.info(f'bundles path: {self.bundles_path}')

        templates.set_server_variables(self)

        self._init_socketio()

        self.dboard = dashboard.Dashboard(self)

        mode = 'new'
        obj = None
        conds = None
        if args.resume:
            mode = 'res'
            obj = args.resume
        elif args.replicate:
            mode = 'rep'
            obj = args.replicate
        else:
            conds = args.conditions.split(',') if args.conditions else None

        self._add_routes()

        if args.exper_path:
            self.load_bundle(args.exper_path, args.tool)
            e.experclass.start(mode, obj, conds)
    
    def initLogger(self):
        self.logfile = self.cfg['logfile'] \
            if self.cfg['logfile'].startswith('/') else e.expert_path / self.cfg['logfile']
        Path(self.logfile).parent.mkdir(parents=True, exist_ok=True)
        config = {
            'version': 1,
            'formatters': {
                'basic': {
                    'format': '%(message)s'
                },
                'extended': {
                    'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
                } 
            },
            'handlers': {
                'wsgi': {
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://flask.logging.wsgi_errors_stream',
                    'formatter': 'basic',
                    'level': 'INFO'
                },
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': self.logfile,
                    'maxBytes': int(self.cfg['logfile_max_size_kib'])*1024,
                    'backupCount': int(self.cfg['logfile_num_backups']),
                    'formatter': 'extended',
                    'level': 'DEBUG'
                },
            },
            'root': {
                'level': 'DEBUG',
                'handlers': ['wsgi', 'file']
            }
        }
        logging.config.dictConfig(config)

    def start(self):
        if self._args.dummy:
            if not e.experclass:
                sys.exit('exper_path must be provided if --dummy is given')
            assert issubclass(e.experclass, exper.Exper)
            e.log.info('performing dummy run')
            e.experclass.dummy_run(self._args.dummy)
        else:
            self.socketio.run(
                e.app, host=self.host, port=self.port) # , log_output=True)

    def _load_config(self, user_cfg_path: str):
        with open(e.expert_path / 'expert_cfg.json') as f:
            cfg = json.load(f)
        if user_cfg_path:
            with open(Path(user_cfg_path).resolve(True)) as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg)
        return cfg

    def _init_socketio(self):
        self.socketio = SocketIO(
            e.app, # logger=True,
            #async_handlers=False,
            #async_mode='eventlet',
            cors_allowed_origins='*')

        @self.socketio.on('connect')
        def sio_connect():
            e.log.info('socket connected')

        @self.socketio.on('disconnect')
        def sio_disconnect():
            e.log.info('socket disconnected')

        @self.socketio.on_error
        def sio_error(err):
            e.log.error(f'socketio error: {err}')

    def _add_routes(self):
        first_request_setup_complete = False

        @e.app.route('/client/<path:subpath>')
        def expert_ts(subpath):
            return send_from_directory(e.expert_path / 'client', subpath)

        @e.app.route(f'/{self.cfg["url_prefix"]}/js/<path:subpath>')
        def js(subpath):
            #if '..' in subpath:
            #    return self.not_found(), 404
            # NB:
            # 1. Can't detect the dashboard by looking at the referrer;
            #    e.g., might be listening on 127.0.0.1, but
            #    referrer is 'localhost'
            # 2. Indirect requests, e.g., dash imports foo.js,
            #    foo.js imports bar.js, have foo.js as the referrer
            #if inst := self.get_inst():
            #    body = inst.task.render(f'js/{subpath}.jinja')
            #else:
                # something other than a task or the dashboard
            #    body = templates.render(f'js/{subpath}.jinja')
            #resp = make_response(body)
            #resp.cache_control.no_store = True
            #resp.content_type = 'application/javascript'
            #return resp
            return send_from_directory(
                e.expert_path / 'expert' / 'static' / 'js', subpath)

        @e.app.route(f'/{self.cfg["url_prefix"]}/audio/<path:subpath>')
        def global_audio(subpath):
            #if '..' in subpath:
            #    return self.not_found(), 404
            return send_from_directory(
                e.expert_path / 'expert' / 'static' / 'audio', subpath)

        @e.app.route(f'/{self.cfg["url_prefix"]}/css/<path:subpath>')
        def global_css(subpath):
            #if '..' in subpath:
            #    return self.not_found(), 404
            return send_from_directory(
                e.expert_path / 'expert' / 'static' / 'css', subpath)

        @e.app.route(f'/{self.cfg["url_prefix"]}/img/<path:subpath>')
        def global_img(subpath):
            #if '..' in subpath:
            #    return self.not_found(), 404
            return send_from_directory(
                e.expert_path / 'expert' / 'static' / 'images', subpath)

        @e.app.route(f'/{self.cfg["url_prefix"]}/login')
        def login():
            return templates.render('login')
        
        @e.app.route(f'/{self.cfg["url_prefix"]}/login_creds', methods=['POST'])
        def login_creds():
            assert self.session_manager
            creds = request.json
            if not creds.get('userid') or not creds.get('password'):
                return {'err': 'login data not provided'}
            try:
                sid = self.session_manager.login(creds['userid'], creds['password'])
                session['sid'] = sid
                return {}
            except user.UserError as exc:
                return {'err': exc.msg}

        @e.app.route('/' + self.cfg['url_prefix'])
        def index():
            nonlocal first_request_setup_complete
            content = None

            if e.experclass:
                if not first_request_setup_complete:
                    self._first_request_setup()
                    first_request_setup_complete = True
                # Even if we aren't running, there may still be completed
                # instances in memory that can serve up completion codes
                sid = session.get('sid')
                if not (isinstance(sid, str) or sid is None):
                    e.log.warn('found SID with invalid type')
                    sid = None
                inst = e.experclass.instances.get(sid)
                if not inst:
                    if e.experclass.running:
                        # XXX But the sid doesn't get stored in the cookie session
                        # until the inst is created, so when we come back here after
                        # a successful login, we just get the form again
                        if self.session_manager and \
                            not (sid and self.session_manager.sessionIsActive(sid)):
                            e.log.info('login required')
                            # Either there is no sid, or it is invalid
                            content = templates.render('login')
                        elif e.experclass.profiles:
                            try:
                                if not self.session_manager:
                                    # Logins are disabled, and any existing sid
                                    # is from a previous run, or a different exper entirely
                                    sid = user.create_sid()
                                    session['sid'] = sid
                                assert sid
                                e.log.info(f'assigning sid {sid}')
                                inst = e.experclass.new_inst(
                                    self._get_ip(), request.args, sid)
                            except:
                                content = self._page_load_error(
                                    traceback.format_exc())
                        else:
                            e.log.info('no profiles available')
                            content = templates.render('full')
                    else:
                        e.log.info('no inst, not running')
                        content = templates.render('norun')
                if not content:
                    try:
                        content = inst.present()
                    except:
                        content = self._page_load_error(traceback.format_exc())
            else:
                e.log.info('no bundle is loaded')
                content = templates.render('norun')

            resp = make_response(content)
            # Caching is disabled entirely to ensure that
            # users always get fresh content
            #resp.cache_control.no_store = True

            return resp

        @e.app.route(f'/{self.cfg["url_prefix"]}/app/<path:subpath>')
        def exper_static(subpath):
            #if '..' in subpath:
            #    return self.not_found(), 404
            return send_from_directory(e.experclass.static_path, subpath)

        @e.app.errorhandler(404)
        def not_found(error):
            e.log.warning(f'NOT FOUND: {request.full_path}')
            return self.not_found(), 404

    def _get_ip(self):
        ip = request.headers.get('X-Real-IP', request.remote_addr)
        if ',' in ip:
            ip = ip.split(',')[0]
        return ip

    def _first_request_setup(self):
        assert e.experclass
        e.app.permanent_session_lifetime = datetime.timedelta(
            hours=e.experclass.cfg['session_lifetime_hours'])
        # session cookie will expire after app.permanent_session_lifetime
        session.permanent = True
        if request.url.startswith('https'):
            e.app.config['SESSION_COOKIE_SECURE'] = True
        else:
            e.app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    def _page_load_error(self, tback: str):
        e.srv.dboard.page_load_error(tback)
        return templates.render('error', {
            'msg': 'System error. Please contact the administrator.'
        })

    def not_found(self):
        return templates.render('error', {
            'msg': '404 Not Found.'
        })

    def load_bundle(self, path: str, tool_mode: bool = False, is_reloading: bool = False):
        bundle_path = Path(path).resolve(True)

        bundle_cfg = self._read_bundle_config(bundle_path)

        if e.experclass:
            self.unload_bundle()

        e.bundle_name = bundle_path.name
        e.bundle_mods = self._bundle_mods(bundle_path)

        try:
            # NB: Tool Mode must get enabled before loading the bundle source
            self.enable_tool_mode(tool_mode or bundle_cfg['tool_mode'])
            e.experclass = self._load_bundle_src(bundle_path, is_reloading)
            e.log.info(f'bundle modules: {" ".join(sorted(e.bundle_mods))}')
            e.experclass.cfg = bundle_cfg
            e.experclass.init(bundle_path, is_reloading)
        except:
            self.unload_bundle()
            raise

        templates.set_bundle_variables(e.experclass)
        e.app.update_jinja_loader(e.experclass)
        if bundle_cfg.get('require_login'):
            self.session_manager = user.SessionManager()
        else:
            self.session_manager = None

    def _bundle_mods(self, path: Path) -> list[str]:
        srcpath = path / 'src'
        return [p.stem for p in srcpath.iterdir()
                if p.suffix == '.py'
                and p.stem != '__init__'
                and not p.stem.startswith('.')]

    def unload_bundle(self):
        for m in e.bundle_mods:
            qualmod = f'{e.bundle_name}.{m}'
            if qualmod in sys.modules:
                e.log.info(f'unloading module {qualmod}')
                del sys.modules[qualmod]
        if e.bundle_name in sys.modules:
            e.log.info(f'unloading module {e.bundle_name}')
            del sys.modules[e.bundle_name]
            # NB: instances is an attribute of BaseExper that experclass
            # mutates
            experiment.BaseExper.instances.clear()
        e.bundle_name = None
        e.bundle_mods = []
        e.experclass = None
        templates.set_bundle_variables(None)
        e.app.update_jinja_loader(None)
        gc.collect()

    def _read_bundle_config(self, bundle_path: Path) -> dict[str, Any]:
        # read default bundle config
        with open(e.expert_path / 'cfg.json') as f:
            cfg = json.load(f)
        bundle_cfg_path = bundle_path / 'cfg.json'
        bundle_cfg = {}
        if bundle_cfg_path.is_file():
            with open(bundle_cfg_path) as f:
                bundle_cfg = json.load(f)

        # bundle_id = bundle_cfg.get('id')
        # cls.id = bundle_id or secrets.token_urlsafe(8)
        # if not bundle_id:
        #     bundle_cfg['id'] = cls.id
        #     with open(bundle_cfg_path, 'w') as f:
        #         json.dump(bundle_cfg, f, indent=2)

        cfg.update(bundle_cfg)
        return cfg

    def _load_bundle_src(self, path: Path, is_reloading=False):
        """Load the bundle in the directory at 'path'.

        NB: The source code for the bundle must be located in
        the 'src' subfolder of the bundle directory.
        E.g., if exper_path == '/foo/bar/my_exper', the source code
        must be located in /foo/bar/my_exper/src.
        """
        #if is_reloading:
            #e.log.info(f'spec: {e.experclass.pkg.__spec__}')
            #pkg = importlib.reload(e.experclass.pkg)
        #    importlib.invalidate_caches()

        e.log.info(f'loading bundle from {path}')
        srcpath = path / 'src'
        #bundle_mods = [p.stem for p in srcpath.iterdir()
        #                    if p.suffix == '.py'
        #                    and p.stem != '__init__'
        #                    and not p.stem.startswith('.')]
        #e.log.info(f'bundle modules: {" ".join(sorted(bundle_mods))}')
        #self._unload_bundle(e.bundle_name, e.bundle_mods)
        init_path = srcpath / '__init__.py'
        spec = importlib.util.spec_from_file_location(path.name, init_path)
        if not spec:
            raise BundleLoadError(
                f'unable to create module spec for bundle \'{path.name}\'')
        try:
            pkg = importlib.util.module_from_spec(spec)
        except:
            raise BundleLoadError(
                f'unable to create module for bundle \'{path.name}\'')
        sys.modules[spec.name] = pkg
        #e.bundle_mods = bundle_mods
        e.log.info(f'bundle package name: {pkg.__name__}')
        try:
            spec.loader.exec_module(pkg)
        except:
            raise BundleLoadError(
                f'unable to exec module for bundle \'{path.name}\'')
        # return the first subclass of Experiment found
        for k, v in pkg.__dict__.items():
            if isinstance(v, type) and issubclass(v, e.Experiment) and \
               v is not e.Experiment:
                return v
        raise BundleLoadError(
            f'no Experiment subclass found in bundle \'{path.name}\'')

    # def get_inst(self):
    #     # NB: session.new seems to be False here even if we do
    #     # in fact have a new, empty session
    #     if 'sid' not in session or not e.experclass:
    #         # New participant
    #         return None
    #     # NB: The presence of an existing sid with no
    #     # instance now simply results in a new sid+inst,
    #     # rather than an error.
    #     return e.experclass.instances.get(cast(str, session['sid']))

    def enable_tool_mode(self, enabled: bool):
        e.tool_mode = enabled
        e.log.info(f'tool mode enabled: {enabled}')
        if e.tool_mode:
            e.Experiment = tool.Tool
        else:
            e.Experiment = exper.Exper
