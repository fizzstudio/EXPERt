
import argparse
import json
import secrets
import sys
import datetime
import zipfile
import logging
import importlib.util

from pathlib import Path

from flask import (
    Flask, session, request, make_response, render_template,
    send_file, send_from_directory
)
from jinja2 import BaseLoader

from flask_socketio import SocketIO

from . import experiment, timestamp

socketio = None

args = None
# per-experiment config settings
cfg = None
dashboard_code = None
dashboard_path = None
dashboard_url = None

mode = None
run = None
target = None

tool_mode = False
setup_complete = False

template_ext = '.html.jinja'
soundcheck_word = 'singapore'

monitor_task = None
experclass = None
template_vars = None

# path to the EXPERt directory (remove 'expert/')
expert_path = Path( __file__ ).parent.parent.absolute()


class TemplateLoader(BaseLoader):

    def __init__(self, path, chain_loader):
        self.path = path
        self.chain_loader = chain_loader

    def get_source(self, environment, template):
        path = self.path / template
        if not path.is_file():
            return self.chain_loader.get_source(environment, template)
        mtime = path.stat().st_mtime
        with open(path) as f:
            source = f.read()
        return source, path, lambda: mtime == path.stat().st_mtime


class App(Flask):

    @property
    def jinja_loader(self):
        loader = getattr(self, '_jinja_loader', None)
        if loader:
            return loader
        self._jinja_loader = TemplateLoader(
            experclass.templates_path, super().jinja_loader)
        return self._jinja_loader


class BadSessionError(Exception): pass


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('exper_path', help='path to experiment to run')
    parser.add_argument('-l', '--listen',
                        help='hostname/IP address (:port) for' +
                        ' server to listen on')
    #parser.add_argument('-u', '--urlprefix',
    #                    help='app URL prefix (default: /expert/)')
    parser.add_argument('-t', '--tool', action='store_true',
                        help='run in tool mode')
    parser.add_argument('-D', '--dummy', type=int,
                        help='perform a dummy run with the given instance count')
    mutexgrp = parser.add_mutually_exclusive_group()
    mutexgrp.add_argument('-r', '--resume',
                          help='timestamp of experiment run to resume')
    mutexgrp.add_argument('-p', '--replicate',
                          help='timestamp of experiment run to replicate')
    mutexgrp.add_argument('-c', '--conditions',
                          help='comma-separated (no spaces) list of' +
                          ' conditions from which to choose all profiles')
    return parser.parse_args()


def init_socketio():
    global socketio
    socketio = SocketIO(
        app, # logger=True,
        #async_handlers=False,
        cors_allowed_origins='*')

    @socketio.on('connect')
    def sio_connect():
        app.logger.info('socket connected')

    @socketio.on('disconnect')
    def sio_disconnect():
        app.logger.info('socket disconnected')

    @socketio.on_error
    def sio_error(e):
        app.logger.info(f'socketio error: {e}')

    @socketio.on('dboard_init')
    def sio_dboard_init():
        return {
            'insts': [inst.status()
                      for sid, inst in experclass.instances.items()],
            'runInfo': run_info()
        }

    @socketio.on('get_runs')
    def sio_get_runs():
        return sorted([x.name for x in experclass.runs_path.iterdir()
                       if x.is_dir() and x.stem[0] != '.'], reverse=True)

    @socketio.on('start_new_run')
    def sio_start_new_run():
        experclass.start_new_run()
        return run_info()

    @socketio.on('terminate_inst')
    def sio_terminate_inst(sid):
        pass

    @socketio.on('soundcheck')
    def sio_soundcheck(resp):
        return resp.strip().lower() == soundcheck_word


def run_info():
    return {
        'run': run,
        'mode': mode,
        'target': target
    }


def init_server():
    global app, args, main_cfg, host, port, \
        dashboard_code, dashboard_path, dashboard_url

    args = parse_args()

    app = App(__name__)
    # sessions aren't enabled until this is set
    # NB: opening the dashboard or displaying a task view
    # doesn't make use of the session
    app.secret_key = b'\xe4\xfb\xfd\xff\x80uZL]\xe8B\xcb\x1c\xb3)g'

    app.logger.setLevel(logging.INFO)
    app.logger.info(f'root path: {app.root_path}')


    with open(expert_path / 'expert_cfg.json') as f:
        main_cfg = json.load(f)
    host = main_cfg['host']
    port = main_cfg['port']

    if args.listen:
        if ':' in args.listen:
            h, p = args.listen.split(':')
            host = h or host
            try:
                port = int(p) if p else port
            except ValueError:
                app.logger.warn(f'invalid port; using {port}')
        else:
            host = args.listen
    app.logger.info(f'listening on {host}:{port}')

    dashboard_code = main_cfg.get('dashboard_code')
    if not dashboard_code:
        dashboard_code = secrets.token_urlsafe(16)
        main_cfg['dashboard_code'] = dashboard_code
        with open(expert_path / 'expert_cfg.json', 'w') as f:
            json.dump(main_cfg, f, indent=2)

    dashboard_path = '/' + main_cfg["url_prefix"] + \
        f'/dashboard/{dashboard_code}'
    dashboard_url = f'http://{main_cfg["host"]}:{main_cfg["port"]}' + \
        dashboard_path
    app.logger.info('dashboard URL: ' + dashboard_url)

    init_socketio()

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

    if args.exper_path:
        start_exper(args.exper_path, mode, obj, conds)

    @app.route(f'/{main_cfg["url_prefix"]}/js/<path:subpath>')
    def js(subpath):
        # NB:
        # 1. Can't detect the dashboard by looking at the referrer;
        #    e.g., might be listening on 127.0.0.1, but
        #    referrer is 'localhost'
        # 2. Indirect requests, e.g., dash imports foo.js,
        #    foo.js imports bar.js, have foo.js as the referrer
        try:
            inst = get_inst()
        except BadSessionError:
            return 'Not Found', 404
        if inst:
            body = inst.task.render(f'js/{subpath}.jinja')
        else:
            # probably the dashboard
            body = render(f'js/{subpath}.jinja')
        resp = make_response(body)
        resp.cache_control.no_store = True
        resp.content_type = 'application/javascript'

        return resp

    @app.route(dashboard_path)
    def dashboard():
        return render('dashboard' + template_ext, {
            'dashboard_path': dashboard_path
        })

    @app.route(f'{dashboard_path}/download/<path:subpath>')
    def dashboard_dl(subpath):
        dl_name = f'exp_{experclass.name}_{subpath}.zip'
        app.logger.info(f'download request for {dl_name}')
        dls_path = experclass.dir_path / 'dl'
        dls_path.mkdir(exist_ok=True)
        dl_path = dls_path / dl_name
        #if not dl_path.is_file():
        app.logger.info('building zip file')
        run_path = experclass.runs_path / subpath
        with zipfile.ZipFile(dl_path, 'w',
                             compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            for condit in run_path.iterdir():
                if not condit.is_dir():
                    continue
                for respath in condit.iterdir():
                    if respath.stem[0] == '.':
                        continue
                    zf.write(
                        str(respath),
                        str(respath.relative_to(experclass.runs_path)))
        return send_file(
            dl_path, as_attachment=True, download_name=dl_name)

    # NB: trying to name this function 'static' will cause an error
    @app.route(f'/{main_cfg["url_prefix"]}/static/<path:subpath>')
    def global_static(subpath):
        return send_from_directory(
            expert_path / 'expert' / 'static', subpath)

    if args.dummy:
        app.logger.info('performing dummy run')
        dummy_run(args.dummy)
    else:
        socketio.run(
            app, host=host, port=port) # , log_output=True)


def read_config(exper_path):
    with open(expert_path / 'cfg.json') as f:
        cfg = json.load(f)
    exper_cfg_path = Path(exper_path).resolve(True) / 'cfg.json'
    if exper_cfg_path.is_file():
        with open(exper_cfg_path) as f:
            cfg.update(json.load(f))
    return cfg


def load_exper(exper_path):
    """Load the experiment in the directory at exper_path.

    NB: The source code for the experiment must be located in
    the 'src' subfolder of the experiment directory.
    E.g., if exper_path == '/foo/bar/my_exper', the source code
    must be located in /foo/bar/my_exper/src.
    """
    exper_path = Path(exper_path).resolve(True)
    app.logger.info(f'loading experiment from {exper_path}')
    init_path = exper_path / 'src' / '__init__.py'
    spec = importlib.util.spec_from_file_location('src', init_path)
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = pkg
    app.logger.info(f'experiment package name: {pkg.__name__}')
    spec.loader.exec_module(pkg)

    #params = importlib.import_module('.params', pkg)
    params = __import__('src.params', fromlist=['params'])
    # return the first subclass of Experiment found
    for k, v in pkg.__dict__.items():
        if isinstance(v, type) and issubclass(v, experiment.Experiment) \
           and v is not experiment.Experiment:
            return v, params
    return None, None


# perform any setup after the first request
def setup():
    global setup_complete
    # session will expire after 24 hours
    app.permanent_session_lifetime = datetime.timedelta(hours=24)
    # session cookie will expire after app.permanent_session_lifetime
    session.permanent = True
    if request.url.startswith('https'):
        app.config['SESSION_COOKIE_SECURE'] = True
    else:
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    setup_complete = True


def monitor():
    app.logger.info('starting monitor task')
    while experclass:
        socketio.sleep(main_cfg['monitor_check_interval'])
        for inst in experclass.instances.values():
            inst.check_for_timeout()
    app.logger.info('monitor task stopping')


def render(tplt, other_vars={}):
    all_vars = template_vars.copy()
    all_vars.update(other_vars)
    return render_template(tplt, **all_vars)


def get_inst():
    required = ['sid', 'exper', 'run', 'profile']
    # NB: session.new seems to be False here even if we do
    # in fact have a new, empty session
    if not any(key in session for key in required):
        # New participant
        return None

    if not all(key in session for key in required):
        app.logger.info('missing some session keys')
        print(session, session.new)
        raise BadSessionError('Invalid session')

    if session['exper'] == experclass.name:
        try:
            return experclass.instances[session['sid']]
        except KeyError:
            if session['run'] == experclass.record.start_time:
                # We have a sid for this run, but no instance
                results_file = (experclass.record.run_path /
                                session['profile'])
                if results_file.is_file():
                    # Experiment was probably resumed
                    raise BadSessionError(
                        'You have already participated in this experiment')
                app.logger.info(
                    f'no inst for profile {session["profile"]}')
                raise BadSessionError('Invalid session')
            else:
                # Session ID is for a different run of this experiment
                raise BadSessionError(
                    'You have already participated in this experiment')
    else:
        # Possible participant from different experiment
        app.logger.info(f'exper name mismatch: {session["exper"]}')
        raise BadSessionError('Invalid session')


def error(msg):
    return render('error' + template_ext, {'msg': msg})


def start_exper(path, exper_mode, obj, conds=None):
    global cfg, mode, run, target, \
        tool_mode, experclass, template_vars, monitor_task


    mode = exper_mode
    if mode == 'res':
        run = obj
    elif mode == 'rep':
        target = obj
        run = timestamp.make_timestamp()
    else:
        run = timestamp.make_timestamp()

    cfg = read_config(path)
    tool_mode = args.tool or cfg['tool_mode']

    experclass, experparams = load_exper(path)

    if not experclass:
        sys.exit(f'unable to load experiment "{path}"')

    experclass.setup(path, conds)

    # All predefined vars are prefixed with 'exp_'
    # to avoid clashing with vars defined by experiments.
    template_vars = {
        'exp_tool_mode': tool_mode,
        'exp_url_prefix': main_cfg['url_prefix'],
        'exp_bundle_url_prefix': cfg['url_prefix'],
        'exp_static': main_cfg['url_prefix'] + '/static',
        'exp_js': main_cfg['url_prefix'] + '/js',
        'exp_exper': experclass.name,
        'exp_expercss':
            f'/{cfg["url_prefix"]}/{experclass.name}/css/main.css',
        'exp_experimg': f'/{cfg["url_prefix"]}/{experclass.name}/img',
        'exp_window_title': experclass.window_title,
        'exp_favicon': cfg['favicon'],
        'exp_progbar_enabled': cfg['progbar_enabled']
    }

    if tool_mode:
        template_vars['exp_tool_display_total_tasks'] = \
            cfg['tool_display_total_tasks']

    monitor_task = socketio.start_background_task(monitor)


    @app.route('/' + cfg['url_prefix'])
    def index():
        if not setup_complete:
            setup()
        content = None
        try:
            inst = get_inst()
            if not inst:
                ip = request.headers.get('X-Real-IP', request.remote_addr)
                if ',' in ip:
                    ip = ip.split(',')[0]
                try:
                    inst = experclass(ip, request.args)
                except experiment.ExperFullError:
                    return error('No participant profiles are available')
                session['sid'] = inst.sid
                session['exper'] = experclass.name
                session['run'] = experclass.record.start_time
                session['profile'] = inst.profile.fqname
                app.logger.info(f'new instance for SID {inst.sid}')
                socketio.emit('new_instance', inst.status())
                inst.will_start()
        except BadSessionError as e:
            content = error(str(e))

        if content is None:
            content = inst.present()

        resp = make_response(content)
        # Caching is disabled entirely to ensure that
        # users always get fresh content
        resp.cache_control.no_store = True

        return resp

    @app.route(f'/{cfg["url_prefix"]}/{experclass.name}/<path:subpath>')
    def exper_static(subpath):
        return send_from_directory(experclass.static_path, subpath)


def dummy_run(inst_count):
    ip = '127.0.0.1'
    for i in range(inst_count):
        inst = experclass(
            ip, {cfg['prolific_pid_param']: f'DUMMY_{i}'}, dummy=True)
        inst.dummy_run()
