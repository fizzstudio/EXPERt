
import argparse
import json
import sys
import logging


from typing import Type, Any, Optional
from pathlib import Path

from flask import (
    Flask, session, make_response,
    send_from_directory
)

from flask_socketio import SocketIO

import expert as e

from . import experiment, tool, dashboard, templates


class App(Flask):

    @property
    def jinja_loader(self):
        loader = getattr(self, '_jinja_loader', None)
        if loader:
            return loader
        self.update_jinja_loader(e.experclass)
        return self._jinja_loader

    def update_jinja_loader(self, experclass):
        self._jinja_loader = templates.Loader(
            experclass.templates_path if experclass else None,
            super().jinja_loader)


class Server:

    _args: argparse.Namespace
    cfg: dict[str, Any]
    host: str
    port: int
    socketio: SocketIO
    dboard: dashboard.Dashboard

    def __init__(self, args):
        self._args = args

        e.app = App(__name__)
        e.log = e.app.logger
        # sessions aren't enabled until this is set
        # NB: opening the dashboard or displaying a task view
        # doesn't make use of the session
        e.app.secret_key = b'\xe4\xfb\xfd\xff\x80uZL]\xe8B\xcb\x1c\xb3)g'
        e.app.templates_auto_reload = True

        e.log.setLevel(logging.INFO)
        e.log.info(f'root path: {e.app.root_path}')

        self.cfg = self._load_config(args.config)

        self.host = self.cfg['host']
        self.port = self.cfg['port']
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

        self._add_server_routes()

        if args.exper_path:
            e.experclass = experiment.BaseExper.load(
                args.exper_path, args.tool)
            e.experclass.start(mode, obj, conds)

    def start(self):
        if self._args.dummy:
            if not e.experclass:
                sys.exit('exper_path must be provided if --dummy is given')
            e.log.info('performing dummy run')
            e.experclass.dummy_run(self._args.dummy)
        else:
            self.socketio.run(
                e.app, host=self.host, port=self.port) # , log_output=True)

    def _load_config(self, user_cfg_path):
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
            async_mode='eventlet',
            cors_allowed_origins='*')

        @self.socketio.on('connect')
        def sio_connect():
            e.log.info('socket connected')

        @self.socketio.on('disconnect')
        def sio_disconnect():
            e.log.info('socket disconnected')

        @self.socketio.on_error
        def sio_error(e):
            e.log.info(f'socketio error: {e}')

        @self.socketio.on('soundcheck')
        def sio_soundcheck(resp):
            return resp.strip().lower() == e.soundcheck_word

    def _add_server_routes(self):
        @e.app.route(f'/{self.cfg["url_prefix"]}/js/<path:subpath>')
        def js(subpath):
            # NB:
            # 1. Can't detect the dashboard by looking at the referrer;
            #    e.g., might be listening on 127.0.0.1, but
            #    referrer is 'localhost'
            # 2. Indirect requests, e.g., dash imports foo.js,
            #    foo.js imports bar.js, have foo.js as the referrer
            if inst := self.get_inst():
                body = inst.task.render(f'js/{subpath}.jinja')
            else:
                # probably the dashboard
                body = templates.render(f'js/{subpath}.jinja')
            resp = make_response(body)
            resp.cache_control.no_store = True
            resp.content_type = 'application/javascript'
            return resp

        @e.app.route(f'/{self.cfg["url_prefix"]}/audio/<path:subpath>')
        def global_audio(subpath):
            return send_from_directory(
                e.expert_path / 'expert' / 'static' / 'audio', subpath)

        @e.app.route(f'/{self.cfg["url_prefix"]}/css/<path:subpath>')
        def global_css(subpath):
            return send_from_directory(
                e.expert_path / 'expert' / 'static' / 'css', subpath)

        @e.app.route(f'/{self.cfg["url_prefix"]}/img/<path:subpath>')
        def global_img(subpath):
            return send_from_directory(
                e.expert_path / 'expert' / 'static' / 'images', subpath)

    def get_inst(self):
        # NB: session.new seems to be False here even if we do
        # in fact have a new, empty session
        if 'sid' not in session or not e.experclass:
            # New participant
            return None
        # NB: The presence of an existing sid with no
        # instance now simply results in a new sid+inst,
        # rather than an error.
        return e.experclass.instances.get(session['sid'])

    def enable_tool_mode(self, enabled):
        e.tool_mode = enabled
        if e.tool_mode:
            e.Experiment = tool.Tool
