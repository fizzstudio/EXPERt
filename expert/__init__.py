
import argparse
import json
import logging
import sys

from pathlib import Path
from typing import Type, Any, Optional

from flask import (
    Flask, session, make_response,
    send_from_directory
)

from flask_socketio import SocketIO

from . import experiment, exper, tool, dashboard, templates


Experiment: Type[exper.Exper]|Type[tool.Tool] = exper.Exper

app: Flask
log: logging.Logger
socketio: SocketIO

args: argparse.Namespace

cfg: dict[str, Any]

tool_mode = False
soundcheck_word = 'singapore'

experclass: Optional[Type[Experiment]] = None

# path to the EXPERt directory (remove 'expert/')
expert_path = Path(__file__).parent.parent.absolute()


class App(Flask):

    @property
    def jinja_loader(self):
        loader = getattr(self, '_jinja_loader', None)
        if loader:
            return loader
        self._jinja_loader = templates.Loader(
            experclass.templates_path if experclass else None,
            super().jinja_loader)
        return self._jinja_loader


def init_server():
    global app, log, args, cfg, host, port

    args = _parse_args()

    app = App(__name__)
    log = app.logger
    # sessions aren't enabled until this is set
    # NB: opening the dashboard or displaying a task view
    # doesn't make use of the session
    app.secret_key = b'\xe4\xfb\xfd\xff\x80uZL]\xe8B\xcb\x1c\xb3)g'
    app.templates_auto_reload = True

    app.logger.setLevel(logging.INFO)
    app.logger.info(f'root path: {app.root_path}')

    with open(expert_path / 'expert_cfg.json') as f:
        cfg = json.load(f)
    if args.config:
        with open(Path(args.config).resolve(True)) as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)
    host = cfg['host']
    port = cfg['port']

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

    templates.set_server_variables()

    _init_socketio()

    dboard = dashboard.Dashboard()

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

    _add_server_routes()

    if args.exper_path:
        experiment.BaseExper.load(args.exper_path, conds, args.tool)
        experiment.BaseExper.start(mode, obj)

    if args.dummy:
        if not experclass:
            sys.exit('exper_path must be provided if --dummy is given')
        app.logger.info('performing dummy run')
        experclass.dummy_run(args.dummy)
    else:
        socketio.run(app, host=host, port=port) # , log_output=True)


def _parse_args():
    allargs = [
        [['-e', '--exper_path'], {'help': 'path to experiment bundle folder'}],
        [['-f', '--config'], {'help': 'path to server config file'}],
        [['-l', '--listen'], {
            'help': 'hostname/IP address (:port) for server to listen on'}],
        (
            [['-t', '--tool'], {
                'action': 'store_true',
                'help': 'run in tool mode'}],
            [['-D', '--dummy'], {
                'type': int,
                'help': 'perform a dummy run with the given instance count'}]
        ),
        (
            [['-r', '--resume'], {
                'help': 'timestamp of experiment run to resume'}],
            [['-p', '--replicate'], {
                'help': 'timestamp of experiment run to replicate'}],
            [['-c', '--conditions'], {
                'help': 'comma-separated (no spaces) list of' +
                ' conditions from which to choose all profiles'}]
        )
    ]
    parser = argparse.ArgumentParser()
    for arg in allargs:
        if isinstance(arg, list):
            parser.add_argument(*arg[0], **arg[1])
        else:
            mutexgrp = parser.add_mutually_exclusive_group()
            for mutex_arg in arg:
                mutexgrp.add_argument(*mutex_arg[0], **mutex_arg[1])
    return parser.parse_args()


def enable_tool_mode(enabled):
    global tool_mode, Experiment
    tool_mode = enabled
    if tool_mode:
        Experiment = tool.Tool


def _init_socketio():
    global socketio
    socketio = SocketIO(
        app, # logger=True,
        #async_handlers=False,
        async_mode='eventlet',
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

    @socketio.on('soundcheck')
    def sio_soundcheck(resp):
        return resp.strip().lower() == soundcheck_word


def _add_server_routes():
    @app.route(f'/{cfg["url_prefix"]}/js/<path:subpath>')
    def js(subpath):
        # NB:
        # 1. Can't detect the dashboard by looking at the referrer;
        #    e.g., might be listening on 127.0.0.1, but
        #    referrer is 'localhost'
        # 2. Indirect requests, e.g., dash imports foo.js,
        #    foo.js imports bar.js, have foo.js as the referrer
        if inst := get_inst():
            body = inst.task.render(f'js/{subpath}.jinja')
        else:
            # probably the dashboard
            body = templates.render(f'js/{subpath}.jinja')
        resp = make_response(body)
        resp.cache_control.no_store = True
        resp.content_type = 'application/javascript'
        return resp

    @app.route(f'/{cfg["url_prefix"]}/audio/<path:subpath>')
    def global_audio(subpath):
        return send_from_directory(
            expert_path / 'expert' / 'static' / 'audio', subpath)

    @app.route(f'/{cfg["url_prefix"]}/css/<path:subpath>')
    def global_css(subpath):
        return send_from_directory(
            expert_path / 'expert' / 'static' / 'css', subpath)

    @app.route(f'/{cfg["url_prefix"]}/img/<path:subpath>')
    def global_img(subpath):
        return send_from_directory(
            expert_path / 'expert' / 'static' / 'images', subpath)

def get_inst():
    # NB: session.new seems to be False here even if we do
    # in fact have a new, empty session
    if 'sid' not in session:
        # New participant
        return None
    # NB: The presence of an existing sid with no
    # instance now simply results in a new sid+inst,
    # rather than an error.
    return experclass.instances.get(session['sid'])
