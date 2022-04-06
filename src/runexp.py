
import importlib.util
import datetime
import argparse
import logging
import secrets
import sys

from pathlib import Path

from flask import (
    Flask, render_template, session,
    request, make_response, send_from_directory)
from flask_socketio import SocketIO

from jinja2 import BaseLoader

import expert
from expert import cfg, tasks, experiment


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
        socketio.sleep(cfg.monitor_check_interval)
        for inst in experclass.instances.values():
            inst.check_for_timeout()


def error(msg):
    return render_template('error.html.jinja', msg=msg)


app = App(__name__)
expert.app = app
# sessions aren't enabled until this is set
# NB: opening the dashboard or displaying a task view
# doesn't make use of the session
app.secret_key = b'\xe4\xfb\xfd\xff\x80uZL]\xe8B\xcb\x1c\xb3)g'

app.logger.setLevel(logging.INFO)

# the experiment folder + '/src'
global_root = Path(app.root_path)

setup_complete = False

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('exper_path', help='path to experiment to run')
    parser.add_argument('-l', '--listen',
                        help='hostname/IP address (:port) for' +
                        ' server to listen on')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='run in debug mode')
    mutexgrp = parser.add_mutually_exclusive_group()
    mutexgrp.add_argument('-r', '--resume',
                          help='timestamp of experiment run to resume')
    mutexgrp.add_argument('-p', '--replicate',
                          help='timestamp of experiment run to replicate')
    mutexgrp.add_argument('-c', '--conditions',
                          help='comma-separated (no spaces) list of' +
                          ' conditions from which to choose all profiles')
    args = parser.parse_args()

    cfg.debug = args.debug

    socketio = SocketIO(
        app, # logger=True,
        async_handlers=False,
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

    tasks.Task.experclass = experclass

    experclass.setup(args.exper_path, mode, target, conds)

    monitor_task = socketio.start_background_task(monitor, socketio)

    dashboard_code = secrets.token_urlsafe(16)
    app.logger.info('dashboard code: ' + dashboard_code)

    @app.route('/expert')
    def index():
        if not setup_complete:
            setup()
        content = None
        if (sid := session.get('sid')) and \
           session.get('exper') == experclass.name:
            inst = experclass.instances.get(sid)
            if inst is None:
                if session.get('run') == experclass.record.start_time:
                    # A session ID is present for this run, but
                    # no instance is found
                    results_file = (experclass.record.run_path /
                                    session.get('profile'))
                    if results_file.is_file():
                        # Experiment was probably resumed
                        content = error(
                            'You have already participated in this experiment')
                    else:
                        content = error(f'Unknown session ID {sid}')
                else:
                    # Session ID is for a different run of this experiment
                    content = error(
                        'You have already participated in this experiment')
        else:
            ip = request.headers.get('X-Real-IP', request.remote_addr)
            if ',' in ip:
                ip = ip.split(',')[0]
            try:
                inst = experclass(socketio, ip)
            except experiment.ExperFullError:
                return error('No participant profiles are available')
            session['sid'] = inst.sid
            session['exper'] = experclass.name
            session['run'] = experclass.record.start_time
            session['profile'] = inst.profile.fqname
            app.logger.info(f'new instance for SID {inst.sid}')
            socketio.emit('new_instance', inst.status())

        if content is None:
            content = inst.present({'expert_debug': args.debug})
        resp = make_response(content)
        # Caching is disabled entirely to ensure that
        # users always get fresh content.
        resp.cache_control.no_store = True

        return resp

    @app.route('/expert/dashboard/' + dashboard_code)
    def dashboard():
        return experclass.present_dashboard()

    # NB: trying to name this function 'static' will cause an error
    @app.route('/expert/static/<path:subpath>')
    def global_static(subpath):
        return send_from_directory(
            global_root / 'expert' / 'static', subpath)

    @app.route(f'/expert/{experclass.name}/<path:subpath>')
    def exper_static(subpath):
        return send_from_directory(experclass.static_path, subpath)

    # route for testing task views
    @app.route('/expert/task/<task>')
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
        return resp.strip().lower() == cfg.soundcheck_word

    if args.listen:
        host, port = args.listen.split(':')
        assert host and port
        app.logger.info(f'listening on {host}:{port}')
        socketio.run(app, host=host, port=int(port)) # , log_output=True)
    else:
        app.logger.info('listening on 127.0.0.1:5000')
        socketio.run(app)
