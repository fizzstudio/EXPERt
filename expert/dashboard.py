
import secrets
import json
import zipfile
import shutil
import importlib

from pathlib import Path

from flask import send_file, request, make_response

import expert as e
from . import templates, experiment, view


# def authn_check(fn):
#     def wrapped(code, *args):
#         if code == _code:
#             return e.OK(fn(*args))
#         else:
#             return e.ERR('authentication failed')


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

        self.variables['dashboard_path'] = self._path
        self.variables['authn_code'] = self.code
        #self.variables['num_profiles'] = e.experclass.num_profiles \
        #    if e.experclass else 0
        self.variables['exp_window_title'] = 'EXPERt Dashboard'
        self.variables['exp_favicon'] = srv.cfg['dashboard_favicon']

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
            body = self.render(f'js/{subpath}.jinja')
            resp = make_response(body)
            resp.cache_control.no_store = True
            resp.content_type = 'application/javascript'
            return resp

        @e.app.route(f'{self._path}/download/<path:subpath>/results')
        def dashboard_dl_results(subpath):
            dl_name = f'exp_{e.experclass.name}_{subpath}_results.zip'
            e.log.info(f'download request for {dl_name}')
            self._zip_results(subpath, dl_name)
            return self._download(dl_name)

        @e.app.route(f'{self._path}/download/<path:subpath>/id_mapping')
        def dashboard_dl_id_map(subpath):
            dl_name = f'exp_{e.experclass.name}_{subpath}_id_map.zip'
            e.log.info(f'download request for {dl_name}')
            self._zip_id_mapping(subpath, dl_name)
            return self._download(dl_name)

        @e.app.route(f'{self._path}/upload_bundle', methods=['POST'])
        def dashboard_ul_bundle():
            bundles_path = e.expert_path / 'bundles'
            bundle_name = next(iter(request.files)).split('/')[0]
            bundle_path = bundles_path / bundle_name
            try:
                bundle_path.mkdir(exist_ok=True)
            except FileExistsError:
                return {'ok': False, 'err': 'Unable to write file'}
            for relpath, f in request.files.items():
                path = bundles_path / relpath
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                except FileExistsError:
                    return {'ok': False, 'err': 'Unable to write file'}
                f.save(path)
            importlib.invalidate_caches()
            e.log.info(f'installed bundle \'{bundle_name}\'')
            return {'ok':True, 'err': None}

    def _add_sio_commands(self, srv):
        @srv.socketio.on('dboard_init', namespace=f'/{self.code}')
        def sio_dboard_init():
            insts = []
            if e.experclass:
                insts = [inst.status()
                         for sid, inst in e.experclass.instances.items()]
            return {
                'vars': self.all_vars(),
                'insts': insts,
                'run_info': self._run_info()
            }

        @srv.socketio.on('get_bundles', namespace=f'/{self.code}')
        def sio_get_bundles():
            bundles_path = e.expert_path / 'bundles'
            return sorted(bundle.name for bundle in bundles_path.iterdir()
                          if bundle.is_dir() and bundle.stem[0] != '.')

        @srv.socketio.on('get_runs', namespace=f'/{self.code}')
        def sio_get_runs():
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

        @srv.socketio.on('start_new_run', namespace=f'/{self.code}')
        def sio_start_new_run():
            e.log.info('--- starting new run ---')
            for inst in e.experclass.all_active():
                inst.terminate()
            e.experclass.start('new')
            return self._run_info()

        # @socketio.on('delete_results')
        # def sio_delete_results(runs):
        #     for run in runs:
        #         app.logger.info(f'deleting results for run {run}')
        #         shutil.rmtree(experclass.runs_path / run)

        @srv.socketio.on('delete_id_mappings', namespace=f'/{self.code}')
        def sio_delete_id_mappings(runs):
            for run in runs:
                e.log.info(f'deleting id mapping for run {run}')
                shutil.rmtree(e.experclass.runs_path / run / 'id-mapping')

        @srv.socketio.on('terminate_inst', namespace=f'/{self.code}')
        def sio_terminate_inst(sid):
            pass

        @srv.socketio.on('load_bundle', namespace=f'/{self.code}')
        def sio_load_bundle(name, tool_mode):
            e.log.info(f'loading in tool mode: {tool_mode}')
            path = e.expert_path / 'bundles' / name
            e.srv.load_bundle(path, tool_mode=tool_mode)
            #self.variables['num_profiles'] = e.experclass.num_profiles
            return self.all_vars()

        @srv.socketio.on('reload_exper', namespace=f'/{self.code}')
        def sio_reload_exper():
            e.log.info('*** reloading bundle ***')
            for inst in e.experclass.all_active():
                inst.terminate()
            e.srv.load_bundle(
                e.experclass.dir_path, e.tool_mode, is_reloading=True)
            # NB: Reloading does NOT start a new run.
            # Reloading implies the bundle has changed, so
            # allowing resuming seems counter-intuitive. But,
            # it's possible a bug might need fixing mid-run,
            # so it might be useful.

        @srv.socketio.on('load_template', namespace=f'/{self.code}')
        def sio_load_template(tplt, tplt_vars={}):
            return templates.render(f'{tplt}{templates.html_ext}', tplt_vars)

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
