
import secrets
import json
import zipfile
import shutil
import importlib
import time
import traceback
import weakref

from pathlib import Path
from typing import Any

from flask import send_file, request, make_response

import expert as e
from . import templates, experiment, view


# def authn_check(fn):
#     def wrapped(code, *args):
#         if code == _code:
#             return e.OK(fn(*args))
#         else:
#             return e.ERR('authentication failed')


class Event:

    time: float
    tag: str
    data: Any

    def __init__(self, tag, data=None, ts=None):
        self.tag = tag
        self.data = data
        self.time = ts or time.monotonic()

    def to_client(self):
        d = {'tag': self.tag}
        if self.tag == 'inst':
        #if isinstance(self.data, experiment.BaseExper):
            d['data'] = self.data().status() if self.data() else {
                'sid': '---', 'ip': '---', 'profile': '---', 'state': '---',
                'task': '---', 'time': '---', 'elapsed': '---'
            }
        else:
            d['data'] = self.data
        return d


class APIBadArgumentError(Exception):
    def __init__(self, cmd, value):
        super().__init__(f'{cmd}: bad argument value \'{value}\'')


class API:

    def __init__(self, dboard):
        self._dboard = dboard

    def dboard_init(self):
        list_items = [item.to_client()
                      for item in self._dboard._events]
        return {
            'vars': self._dboard.all_vars(),
            'list_items': list_items,
            'run_info': self._dboard._run_info()
        }

    def get_bundles(self):
        return sorted(bundle.name for bundle in e.srv.bundles_path.iterdir()
                      if bundle.is_dir() and bundle.stem[0] != '.')

    def get_runs(self):
        runs = []
        for run in e.experclass.runs_path.iterdir():
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

    def start_new_run(self):
        try:
            e.experclass.start('new')
        except:
            err = traceback.format_exc()
            e.log.error(f'error starting run: {err}')
            return {'err': err}
        self._dboard._events.append(Event('new_run', e.experclass.run))
        templates.variables['exp_app_is_running'] = True
        return {'info': self._dboard._run_info()}

    def stop_run(self):
        self._dboard._events.append(Event('run_stop', e.experclass.run))
        self._dboard._stop_run()

    # @socketio.on('delete_results')
    # def sio_delete_results(runs):
    #     for run in runs:
    #         app.logger.info(f'deleting results for run {run}')
    #         shutil.rmtree(experclass.runs_path / run)

    def delete_id_mapping(self, run):
        if '..' in run:
            e.log.error(f'attempt to delete run \'{run}\'')
            raise APIBadArgumentError('delete_id_mapping', run)
        e.log.info(f'deleting id mapping for run \'{run}\'')
        shutil.rmtree(e.experclass.runs_path / run / 'id-mapping')

    def terminate_inst(self, sid):
        pass

    def load_bundle(self, name, tool_mode):
        if '..' in name:
            e.log.error(f'attempt to load bundle \'{name}\'')
            raise APIBadArgumentError('load_bundle', name)
        e.log.info(f'loading in tool mode: {tool_mode}')
        path = e.srv.bundles_path / name
        #importlib.invalidate_caches()
        try:
            e.srv.load_bundle(path, tool_mode=tool_mode)
        except:
            tback = traceback.format_exc()
            e.log.error(f'error loading bundle \'{name}\': {tback}')
            return {
                'tback': tback,
                'vars': self._dboard.all_vars()
            }
        self._dboard._events.append(Event('bundle_load', name))
        self._dboard.update_vars()
        return {'vars': self._dboard.all_vars()}

    def reload_bundle(self):
        e.log.info('*** reloading bundle ***')
        try:
            e.srv.load_bundle(
                e.experclass.dir_path, e.tool_mode, is_reloading=True)
        except:
            return {
                'err': traceback.format_exc(),
                'vars': self._dboard.all_vars()
            }
        self._dboard._events.append(Event('bundle_reload', e.bundle_name))
        # NB: Reloading does NOT start a new run.
        # Reloading implies the bundle has changed, so
        # allowing resuming seems counter-intuitive. But,
        # it's possible a bug might need fixing mid-run,
        # so it might be useful.
        return {'vars': self._dboard.all_vars()}

    def unload_bundle(self):
        e.log.info('*** unloading bundle ***')
        self._dboard._events.append(Event('bundle_unload', e.bundle_name))
        e.srv.unload_bundle()
        return {'vars': self._dboard.all_vars()}

    def rebuild_profiles(self):
        e.log.info('rebuilding profiles')
        try:
            shutil.rmtree(e.experclass.profiles_path)
            e.experclass.make_profiles()
        except:
            err = traceback.format_exc()
            e.log.error(f'error rebuilding profiles: {err}')
            e.srv.unload_bundle()
            return {
                'err': err,
                'vars': self._dboard.all_vars()
            }
        self._dboard.update_vars()
        self._dboard._events.append(Event('profiles_rebuild'))
        return {'vars': self._dboard.all_vars()}

    def load_template(self, tplt, tplt_vars={}):
        return templates.render(f'{tplt}{templates.html_ext}', tplt_vars)


class Dashboard(view.View):

    _path: str
    code: str
    _url: str

    def __init__(self, srv):
        super().__init__(template='dashboard')

        cfg_code = srv.cfg.get('dashboard_code')
        self.code = cfg_code or secrets.token_urlsafe(16)
        if not cfg_code:
            srv.cfg['dashboard_code'] = self.code
            with open(e.expert_path / 'expert_cfg.json', 'w') as f:
                json.dump(srv.cfg, f, indent=2)

        self._path = '/' + srv.cfg["url_prefix"] + f'/dashboard/{self.code}'
        # In order that controller.js.jinja can have access to the
        # 'authn_code' variable, it needs to be rendered via the
        # Dashboard instamce. However, as far as I can tell, there's
        # no way to reliably and with absolute certainty tell that
        # a request for a JS file is in fact coming from the dashboard,
        # other than to use a separate URL for it from the one used
        # for tasks. To ensure that scripts directly loaded from
        # the dashboard as well as scripts indirectly loaded by other
        # scripts (templates) use this special path, we have to
        # override the 'exp_js' variable.
        self._js_path = f'{self._path}/js'
        self.variables['exp_js'] = self._js_path

        self._url = f'http://{srv.cfg["host"]}:{srv.cfg["port"]}' + self._path
        e.log.info('dashboard URL: ' + self._url)
        self._add_routes()
        self._add_sio_commands(srv)
        self._api = API(self)

        # NB: these variables are prefixed because they are
        # looked for by layout.html.jinja, and therefore bundle
        # vars could conflict with them (well, the path, at least).
        self.variables['exp_dashboard_path'] = self._path
        self.variables['exp_authn_code'] = self.code
        self.variables['exp_window_title'] = 'EXPERt Dashboard'
        self.variables['exp_favicon'] = srv.cfg['dashboard_favicon']
        # XXX what about resuming?
        self.variables['exp_completed_profiles'] = 0
        self.update_vars()

        self._events = []

    def update_vars(self):
        # NB: This is the total number, not affected by resuming
        self.variables['exp_total_profiles'] = \
            e.experclass.num_profiles if e.experclass else 0

    def all_vars(self):
        all_vars = templates.variables.copy()
        all_vars.update(self.variables)
        return all_vars

    def _add_routes(self):
        @e.app.route(self._path)
        def dashboard():
            return self.present()

        @e.app.route(f'{self._js_path}/<path:subpath>')
        def dashboard_js(subpath):
            #if '..' in subpath:
            #    return e.srv.not_found(), 404
            body = self.render(f'js/{subpath}.jinja')
            resp = make_response(body)
            resp.cache_control.no_store = True
            resp.content_type = 'application/javascript'
            return resp

        @e.app.route(f'{self._path}/download/<path:subpath>/results')
        def dashboard_dl_results(subpath):
            #if '..' in subpath:
            #    return e.srv.not_found(), 404
            dl_name = f'exp_{e.bundle_name}_{subpath}_results.zip'
            e.log.info(f'download request for {dl_name}')
            self._zip_results(subpath, dl_name)
            return self._download(dl_name)

        @e.app.route(f'{self._path}/download/<path:subpath>/id_mapping')
        def dashboard_dl_id_map(subpath):
            #if '..' in subpath:
            #    return e.srv.not_found(), 404
            dl_name = f'exp_{e.bundle_name}_{subpath}_id_map.zip'
            e.log.info(f'download request for {dl_name}')
            self._zip_id_mapping(subpath, dl_name)
            return self._download(dl_name)

        @e.app.route(f'{self._path}/upload_bundle', methods=['POST'])
        def dashboard_ul_bundle():
            bundles_path = e.expert_path / 'bundles'
            bundle_name = next(iter(request.files)).split('/')[0]

            if '..' in bundle_name:
                return {'ok': False, 'err': 'Bundle name cannot contain ".."'}
            for relpath, f in request.files.items():
                if '..' in relpath:
                    return {'ok': False, 'err': 'Filenames cannot contain ".."'}

            if e.experclass and bundle_name == e.bundle_name:
                self._stop_run()

            bundle_path = bundles_path / bundle_name
            try:
                bundle_path.mkdir(exist_ok=True)
            except FileExistsError:
                # bundle_path already exists as a non-directory
                err = 'Unable to create bundle directory'
                e.log.error(f'error uploading bundle \'{bundle_name}\': {err}')
                return {'ok': False, 'err': err}
            for relpath, f in request.files.items():
                path = bundles_path / relpath
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                except FileExistsError:
                    err = f'Unable to write file \'{relpath}\''
                    e.log.error(
                        f'error uploading bundle \'{bundle_name}\': {err}')
                    return {'ok': False, 'err': err}
                f.save(path)
            importlib.invalidate_caches()
            e.log.info(f'installed bundle \'{bundle_name}\'')
            return {'ok':True, 'err': None}

    def _add_sio_commands(self, srv):
        @srv.socketio.on('call_api', namespace=f'/{self.code}')
        def sio_call(cmd, *args):
            try:
                f = getattr(self._api, cmd)
                val = f(*args)
            except:
                err = traceback.format_exc()
                e.log.error(f'dashboard API \'{cmd}\' error: {err}')
                return {'err': err}
            return {'val': val}

    def _run_info(self):
        if e.experclass and e.experclass.running:
            return {
                'run': e.experclass.run,
                'mode': e.experclass.mode,
                'target': e.experclass.target
            }
        else:
            return {
                'run': None,
                'mode': None,
                'target': None
            }

    def _stop_run(self):
        if not e.experclass.running:
            return
        e.log.info('--- stopping current run ---')
        active = e.experclass.all_active()
        if active:
            for inst in active:
                inst.terminate()
        e.experclass.stop()
        templates.variables['exp_app_is_running'] = False

    def _zip_results(self, run_id, zip_name):
        e.log.info('building zip file')
        # run_path = expert.experclass.runs_path / run_id
        root = Path(zip_name).stem
        resps = e.experclass.collect_responses(run_id)
        resps_ext = e.experclass.cfg['output_format']
        resps_name = root + '.' + resps_ext
        resps_path = e.experclass.dls_path / resps_name
        e.experclass.write_responses(resps, resps_path)
        with zipfile.ZipFile(e.experclass.dls_path / zip_name, 'w',
                             compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            zf.write(resps_path, resps_name)
            # for cond in run_path.iterdir():
            #     if cond.name == 'id-mapping' or not cond.is_dir():
            #         continue
            #     for respath in cond.iterdir():
            #         if respath.stem[0] == '.':
            #             continue
            #         zf.write(
            #             str(respath),
            #             root + '/' + str(respath.relative_to(run_path)))

    def _zip_id_mapping(self, run_id, zip_name):
        e.log.info('building zip file')
        id_map_path = e.experclass.runs_path / run_id / 'id-mapping'
        root = Path(zip_name).stem
        with zipfile.ZipFile(e.experclass.dls_path / zip_name, 'w',
                             compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            for fpath in id_map_path.iterdir():
                if fpath.stem[0] == '.' or not fpath.is_file():
                    continue
                zf.write(str(fpath), root + '/' + fpath.name)

    def _download(self, dl_name):
        #if not dl_path.is_file():
        return send_file(
            e.experclass.dls_path / dl_name,
            as_attachment=True, download_name=dl_name)

    def inst_created(self, inst):
        self._events.append(Event('inst', weakref.ref(inst), inst.start_time))
        e.srv.socketio.emit('new_instance', inst.status(),
                            namespace=f'/{self.code}')

    def inst_updated(self, inst):
        i = None
        num_other = 0
        for i in range(len(self._events)):
            ev = self._events[i]
            if ev.tag != 'inst':
                num_other += 1
            elif ev.data == inst:
                break
        if inst.state == experiment.State.COMPLETE:
            self.variables['exp_completed_profiles'] += 1
        # NB: tuple for multiple args
        e.srv.socketio.emit('update_instance', (i - num_other, inst.status()),
                            namespace=f'/{self.code}')

    def run_complete(self, run):
        self._events.append(Event('run_complete', run))
        e.srv.socketio.emit('run_complete',
                            namespace=f'/{self.code}')

    def page_load_error(self, tback):
        self._events.append(Event('page_load_error', tback))
        e.srv.socketio.emit('page_load_error', tback,
                            namespace=f'/{self.code}')

    def api_error(self, tback):
        self._events.append(Event('api_error', tback))
        e.srv.socketio.emit('api_error', tback,
                            namespace=f'/{self.code}')
