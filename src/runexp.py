
import importlib.util
import datetime
import argparse
import logging
import sys
import json
import zipfile
import shutil

from pathlib import Path

from flask import (
    Flask, session,
    request, make_response,
    send_file, send_from_directory)
from flask_socketio import SocketIO

from jinja2 import BaseLoader

import expert
from expert import tasks, experiment, timestamp


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
    return expert.render('error' + expert.template_ext, {'msg': msg})


class BadSessionError(Exception): pass


def get_inst():
    # NB: session.new seems to be False here even if we do
    # in fact have a new, empty session
    if 'sid' not in session:
        # New participant
        return None
    inst = experclass.instances.get(session['sid'])
    if inst:
        return inst
    elif expert.tool_mode:
        return None
    else:
        raise BadSessionError('Unrecognized user')


def dummy_run(inst_count):
    ip = '127.0.0.1'
    for i in range(inst_count):
        inst = experclass(
            ip, {cfg['prolific_pid_param']: f'DUMMY_{i}'}, dummy=True)
        inst.dummy_run()


def run_info():
    return {
        'run': expert.run,
        'mode': expert.mode,
        'target': expert.target
    }


def zip_results(run_id, zip_name):
    app.logger.info('building zip file')
    run_path = experclass.runs_path / run_id
    root = Path(zip_name).stem
    with zipfile.ZipFile(experclass.dls_path / zip_name, 'w',
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for condit in run_path.iterdir():
            if condit.name == 'id-mapping' or not condit.is_dir():
                continue
            for respath in condit.iterdir():
                if respath.stem[0] == '.':
                    continue
                zf.write(
                    str(respath),
                    root + '/' + str(respath.relative_to(run_path)))


def zip_id_mapping(run_id, zip_name):
    app.logger.info('building zip file')
    id_map_path = experclass.runs_path / run_id / 'id-mapping'
    root = Path(zip_name).stem
    with zipfile.ZipFile(experclass.dls_path / zip_name, 'w',
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for fpath in id_map_path.iterdir():
            if fpath.stem[0] == '.' or not fpath.is_file():
                continue
            zf.write(str(fpath), root + '/' + fpath.name)


def download(dl_name):
    #if not dl_path.is_file():
    return send_file(
        experclass.dls_path / dl_name,
        as_attachment=True, download_name=dl_name)


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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('exper_path', help='path to experiment to run')
    parser.add_argument('-l', '--listen',
                        help='hostname/IP address (:port) for' +
                        ' server to listen on')
    parser.add_argument('-u', '--urlprefix',
                        help='app URL prefix (default: /expert/)')
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


if __name__ == '__main__':
    args = parse_args()

    cfg = read_config(args.exper_path)
    expert.cfg = cfg

    cfg['url_prefix'] = args.urlprefix or cfg['url_prefix']
    expert.tool_mode = args.tool
    experiment.Experiment = experiment.Tool \
        if expert.tool_mode else experiment.Exper

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
        expert.mode = 'res'
        expert.target = None
        expert.run = args.resume
    elif args.replicate:
        expert.mode = 'rep'
        expert.target = args.replicate
        expert.run = timestamp.make_timestamp()
    else:
        expert.mode = 'new'
        expert.target = None
        expert.run = timestamp.make_timestamp()
        conds = args.conditions.split(',') if args.conditions else None

    if args.listen:
        if ':' in args.listen:
            h, p = args.listen.split(':')
            cfg['host'] = h or cfg['host']
            try:
                cfg['port'] = int(p) if p else cfg['port']
            except ValueError:
                app.logger.warn(f'invalid port; using {cfg["port"]}')
        else:
            cfg['host'] = args.listen
    app.logger.info(f'listening on {cfg["host"]}:{cfg["port"]}')

    experclass, experparams = load_exper(args.exper_path)

    if not experclass:
        sys.exit(f'unable to load experiment "{args.exper_path}"')

    experclass.setup(args.exper_path, conds)

    expert.template_vars = {
        'exp_tool_mode': args.tool,
        'exp_url_prefix': cfg['url_prefix'],
        'exp_static': cfg['url_prefix'] + '/static',
        'exp_js': cfg['url_prefix'] + '/js',
        'exp_exper': experclass.name,
        'exp_expercss':
            f'/{cfg["url_prefix"]}/{experclass.name}/css/main.css',
        'exp_experimg': f'/{cfg["url_prefix"]}/{experclass.name}/img',
        'exp_window_title': experclass.window_title,
        'exp_favicon': cfg['favicon'],
        'exp_progbar_enabled': cfg['progbar_enabled']
    }
    if expert.tool_mode:
        expert.template_vars['exp_tool_display_total_tasks'] = \
            cfg['tool_display_total_tasks']
        app.templates_auto_reload = True
    else:
        monitor_task = socketio.start_background_task(monitor, socketio)

    #dashboard_code = secrets.token_urlsafe(16)
    dashboard_code = cfg.get('dashboard_code')
    dashboard_path = f'/{cfg["url_prefix"]}/dashboard'
    if dashboard_code:
        dashboard_path += f'/{dashboard_code}'
    dashboard_url = f'http://{cfg["host"]}:{cfg["port"]}' + dashboard_path

    app.logger.info('dashboard URL: ' + dashboard_url)

    @app.route('/' + cfg['url_prefix'])
    def index():
        if not setup_complete:
            setup()
        content = None
        try:
            inst = get_inst()
            if not inst:
                if not expert.tool_mode and experclass.complete:
                    content = expert.render('norun' + expert.template_ext)
                else:
                    ip = request.headers.get('X-Real-IP', request.remote_addr)
                    if ',' in ip:
                        ip = ip.split(',')[0]
                    if experclass.profiles:
                        # not full yet
                        inst = experclass(ip, request.args)
                        session['sid'] = inst.sid
                        #session['exper'] = experclass.name
                        #session['run'] = experclass.record.start_time
                        #session['profile'] = inst.profile.fqname
                        app.logger.info(f'new instance for sid {inst.sid[:4]}')
                        socketio.emit('new_instance', inst.status())
                        inst.will_start()
                    else:
                        content = expert.render('full' + expert.template_ext)
        except BadSessionError as e:
            content = error(str(e))

        if content is None:
            content = inst.present()

        resp = make_response(content)
        # Caching is disabled entirely to ensure that
        # users always get fresh content
        resp.cache_control.no_store = True

        return resp

    @app.route(f'/{cfg["url_prefix"]}/js/<path:subpath>')
    def js(subpath):
        # NB:
        # 1. Can't detect the dashboard by looking at the referrer;
        #    e.g., might be listening on 127.0.0.1, but
        #    referrer is 'localhost'
        # 2. Indirect requests, e.g., dash imports foo.js,
        #    foo.js imports bar.js, have foo.js as the referrer
        try:
            inst = get_inst()
        except BadSessionError as e:
            #return 'Not Found', 404
            inst = None
        if inst:
            body = inst.task.render(f'js/{subpath}.jinja')
        else:
            # probably the dashboard
            body = expert.render(f'js/{subpath}.jinja')
        resp = make_response(body)
        resp.cache_control.no_store = True
        resp.content_type = 'application/javascript'

        return resp

    @app.route(dashboard_path)
    def dashboard():
        return expert.render('dashboard' + expert.template_ext, {
            'dashboard_path': dashboard_path,
            'num_profiles': experclass.num_profiles
        })

    @app.route(f'{dashboard_path}/download/<path:subpath>/results')
    def dashboard_dl_results(subpath):
        dl_name = f'exp_{experclass.name}_{subpath}_results.zip'
        app.logger.info(f'download request for {dl_name}')
        zip_results(subpath, dl_name)
        return download(dl_name)

    @app.route(f'{dashboard_path}/download/<path:subpath>/id_mapping')
    def dashboard_dl_id_map(subpath):
        dl_name = f'exp_{experclass.name}_{subpath}_id_map.zip'
        app.logger.info(f'download request for {dl_name}')
        zip_id_mapping(subpath, dl_name)
        return download(dl_name)

    # NB: trying to name this function 'static' will cause an error
    @app.route(f'/{cfg["url_prefix"]}/static/<path:subpath>')
    def global_static(subpath):
        return send_from_directory(
            global_root / 'expert' / 'static', subpath)

    @app.route(f'/{cfg["url_prefix"]}/{experclass.name}/<path:subpath>')
    def exper_static(subpath):
        return send_from_directory(experclass.static_path, subpath)

    # if expert.debug:
    #     # route for testing task views
    #     @app.route(f'/{cfg["url_prefix"]}/task/<task>')
    #     def showtask(task):
    #         taskvars = {}
    #         for k, v in request.args.items():
    #             if v.startswith('params:'):
    #                 taskvars[k] = getattr(experparams, v[7:])
    #             else:
    #                 taskvars[k] = v
    #         taskvars['_debug'] = True

    #         t = tasks.Task(None, task, taskvars)

    #         @socketio.on('init_task', namespace='/debug')
    #         def sio_init_task():
    #             return taskvars

    #         @socketio.on('get_feedback', namespace='/debug')
    #         def sio_get_feedback(resp):
    #             return eval(taskvars['fbackval'])

    #         return t.present()

    @socketio.on('dboard_init')
    def sio_dboard_init():
        return {
            'insts': [inst.status()
                      for sid, inst in experclass.instances.items()],
            'runInfo': run_info()
        }

    @socketio.on('get_runs')
    def sio_get_runs():
        runs = []
        for run in experclass.runs_path.iterdir():
            if not run.is_dir() or run.stem[0] == '.':
                continue
            runs.append({
                'id': run.name,
                'num_complete': 0,
                'num_incomplete': 0,
                'has_pii': False
            })
            for cond in run.iterdir():
                if cond.name == 'id-mapping' or \
                   not cond.is_dir() or cond.stem[0] == '.':
                    continue
                for resp in cond.iterdir():
                    if not resp.is_file() or resp.stem[0] == '.':
                        continue
                    if any(resp.name.endswith(sfx)
                           for sfx in experiment.resp_file_suffixes.values()):
                        runs[-1]['num_incomplete'] += 1
                    else:
                        runs[-1]['num_complete'] += 1
            if (run / 'id-mapping').is_dir():
                runs[-1]['has_pii'] = True
        return sorted(runs, key=lambda r: r['id'], reverse=True)

    # @socketio.on('delete_results')
    # def sio_delete_results(runs):
    #     for run in runs:
    #         app.logger.info(f'deleting results for run {run}')
    #         shutil.rmtree(experclass.runs_path / run)

    @socketio.on('delete_id_mappings')
    def sio_delete_id_mappings(runs):
        for run in runs:
            app.logger.info(f'deleting id mapping for run {run}')
            shutil.rmtree(experclass.runs_path / run / 'id-mapping')

    @socketio.on('start_new_run')
    def sio_start_new_run():
        experclass.start_new_run()
        return run_info()

    @socketio.on('terminate_inst')
    def sio_terminate_inst(sid):
        pass

    @socketio.on('soundcheck')
    def sio_soundcheck(resp):
        return resp.strip().lower() == expert.soundcheck_word


    if args.dummy:
        app.logger.info('performing dummy run')
        dummy_run(args.dummy)
    else:
        socketio.run(app, host=cfg['host'], port=cfg['port']) # , log_output=True)
