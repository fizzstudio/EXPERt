
from __future__ import annotations

from typing import Any

from flask import render_template
from jinja2 import BaseLoader

import expert


html_ext = '.html.jinja'
js_ext = '.js.jinja'
variables: dict[str, Any]


class Loader(BaseLoader):

    def __init__(self, path, chain_loader):
        self.path = path
        self.chain_loader = chain_loader

    def get_source(self, environment, template):
        if not self.path or not (path := self.path / template).is_file():
            return self.chain_loader.get_source(environment, template)
        mtime = path.stat().st_mtime
        with open(path) as f:
            source = f.read()
        return source, path, lambda: mtime == path.stat().st_mtime


def set_server_variables():
    global variables
    # All predefined vars are prefixed with 'exp_'
    # to avoid clashing with vars defined by experiments.
    pfx = expert.cfg['url_prefix']
    variables = {
        'exp_tool_mode': expert.tool_mode,
        'exp_url_prefix': pfx
    }
    variables['exp_audio'] = f'/{pfx}/audio'
    variables['exp_img'] = f'/{pfx}/img'
    variables['exp_css'] = f'/{pfx}/css'
    variables['exp_js'] = f'/{pfx}/js'


def set_bundle_variables():
    pfx = expert.cfg['url_prefix']
    cls = expert.experclass
    variables['exp_app_name'] = cls.name
    variables['exp_app_id'] = cls.id
    variables['exp_app_static'] = f'/{pfx}/app/{variables["exp_app_id"]}'
    variables['exp_app_img'] = f'{variables["exp_app_static"]}/img'
    variables['exp_app_css'] = f'{variables["exp_app_static"]}/css'
    variables['exp_app_js'] = f'{variables["exp_app_static"]}/js'
    variables['exp_window_title'] = cls.window_title
    variables['exp_favicon'] = cls.cfg['favicon']
    variables['exp_progbar_enabled'] = cls.cfg['progbar_enabled']
    if expert.tool_mode:
        variables['exp_tool_display_total_tasks'] = \
            cls.cfg['tool_display_total_tasks']


def render(tplt, other_vars={}):
    all_vars = variables.copy()
    all_vars.update(other_vars)
    return render_template(tplt, **all_vars)
