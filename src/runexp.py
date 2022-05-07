
import importlib.util
import datetime
import argparse
import logging
import secrets
import sys
import json

from pathlib import Path

from flask import (
    Flask, render_template, session,
    request, make_response, send_from_directory)
from flask_socketio import SocketIO

from jinja2 import BaseLoader

import expert
from expert import tasks, experiment


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


def read_config(exper_path):
    with open(global_root / 'cfg.json') as f:
        cfg = json.load(f)
    exper_cfg_path = Path(exper_path).resolve(True) / 'cfg.json'
    if exper_cfg_path.is_file():
        with open(exper_cfg_path) as f:
            cfg.update(json.load(f))
    return cfg


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


def monitor(socketio):
    app.logger.info('starting monitor task')
    while True:
        socketio.sleep(cfg['monitor_check_interval'])
        for inst in experclass.instances.values():
            inst.check_for_timeout()


def error(msg):
    return render_template('error' + expert.template_ext,
                           msg=msg, expert_url_prefix=cfg['url_prefix'])


class BadSessionError(Exception): pass


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
                else:
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


def dummy_run(inst_count):
    ip = '127.0.0.1'
    for i in range(inst_count):
        inst = experclass(
            ip, {cfg['prolific_pid_param']: f'DUMMY_{i}'}, dummy=True)
        inst.dummy_run()


app = App(__name__)
expert.app = app
# sessions aren't enabled until this is set
# NB: opening the dashboard or displaying a task view
# doesn't make use of the session
app.secret_key = b'\xe4\xfb\xfd\xff\x80uZL]\xe8B\xcb\x1c\xb3)g'

app.logger.setLevel(logging.INFO)

# the EXPERt folder + '/src'
global_root = Path(app.root_path)

setup_complete = False

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('exper_path', help='path to experiment to run')
    parser.add_argument('-l', '--listen',
                        help='hostname/IP address (:port) for' +
                        ' server to listen on')
    parser.add_argument('-u', '--urlprefix',
                        help='app URL prefix (default: /expert/)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='run in debug mode')
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
    args = parser.parse_args()

    cfg = read_config(args.exper_path)
    expert.cfg = cfg

    cfg['url_prefix'] = args.urlprefix or cfg['url_prefix']
    expert.debug = args.debug

    socketio = SocketIO(
        app, # logger=True,
        #async_handlers=False,
        cors_allowed_origins='*')
    expert.socketio = socketio

    @socketio.on('connect')
    def sio_connect():
        app.logger.info('socket connected')

    @socketio.on('disconnect')
    def sio_disconnect():
        app.logger.info('socket disconnected')

    @socketio.on_error
    def sio_error(e):
        app.logger.info(f'socketio error: {e}')

    conds = None
    if args.resume:
        mode = 'res'
        target = args.resume
    elif args.replicate:
        mode = 'rep'
        target = args.replicate
    else:
        mode = 'new'
        target = None
        conds = args.conditions.split(',') if args.conditions else None

    experclass, experparams = load_exper(args.exper_path)

    if not experclass:
        sys.exit(f'unable to load experiment "{args.exper_path}"')

    experclass.setup(args.exper_path, mode, target, conds)

    expert.template_vars = {
        'expert_debug': args.debug,
        'expert_url_prefix': cfg['url_prefix'],
        'expert_static': cfg['url_prefix'] + '/static',
        'expert_js': cfg['url_prefix'] + '/js',
        'exper': experclass.name,
        'expercss':
            f'/{cfg["url_prefix"]}/{experclass.name}/css/main.css',
        'window_title': experclass.window_title
    }

    monitor_task = socketio.start_background_task(monitor, socketio)

    dashboard_code = secrets.token_urlsafe(16)
    app.logger.info('dashboard code: ' + dashboard_code)

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
        except BadSessionError as e:
            content = error(str(e))

        if content is None:
            content = inst.present(expert.template_vars)

        resp = make_response(content)
        # Caching is disabled entirely to ensure that
        # users always get fresh content
        resp.cache_control.no_store = True

        return resp

    @app.route(f'/{cfg["url_prefix"]}/js/<path:subpath>')
    def js(subpath):
        try:
            inst = get_inst()
        except BadSessionError as e:
            return 'Not Found', 404
        if not inst:
            return 'Not Found', 404

        body = inst.task.render(f'js/{subpath}.jinja', expert.template_vars)
        resp = make_response(body)
        resp.cache_control.no_store = True
        resp.content_type = 'application/javascript'

        return resp

    @app.route(f'/{cfg["url_prefix"]}/dashboard/{dashboard_code}')
    def dashboard():
        return experclass.present_dashboard()

    # NB: trying to name this function 'static' will cause an error
    @app.route(f'/{cfg["url_prefix"]}/static/<path:subpath>')
    def global_static(subpath):
        return send_from_directory(
            global_root / 'expert' / 'static', subpath)

    @app.route(f'/{cfg["url_prefix"]}/{experclass.name}/<path:subpath>')
    def exper_static(subpath):
        return send_from_directory(experclass.static_path, subpath)

    if expert.debug:
        # route for testing task views
        @app.route(f'/{cfg["url_prefix"]}/task/<task>')
        def showtask(task):
            taskvars = {}
            for k, v in request.args.items():
                if v.startswith('params:'):
                    taskvars[k] = getattr(experparams, v[7:])
                else:
                    taskvars[k] = v
            taskvars['_debug'] = True

            t = tasks.Task(None, task, taskvars)

            @socketio.on('init_task', namespace='/debug')
            def sio_init_task():
                return taskvars

            @socketio.on('get_feedback', namespace='/debug')
            def sio_get_feedback(resp):
                return eval(taskvars['fbackval'])

            return t.present()

    @socketio.on('get_instances')
    def sio_get_instances():
        return [inst.status()
                for sid, inst in experclass.instances.items()]

    @socketio.on('soundcheck')
    def sio_soundcheck(resp):
        return resp.strip().lower() == expert.soundcheck_word


    if args.dummy:
        app.logger.info('performing dummy run')
        dummy_run(args.dummy)
    else:
        if args.listen:
            host = '127.0.0.1'
            port = 5000
            if ':' in args.listen:
                h, p = args.listen.split(':')
                host = h or host
                try:
                    port = int(p) if p else port
                except ValueError:
                    app.logger.warn('invalid port; using 5000')
            else:
                host = args.listen
            app.logger.info(f'listening on {host}:{port}')
            socketio.run(app, host=host, port=port) # , log_output=True)
        else:
            app.logger.info('listening on 127.0.0.1:5000')
            socketio.run(app)
