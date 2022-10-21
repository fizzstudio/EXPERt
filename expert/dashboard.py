
import secrets
import json
import zipfile
import shutil

from pathlib import Path

from flask import send_file

import expert as e
from . import templates, experiment, view


class Dashboard(view.View):

    _code: str
    _path: str
    _url: str

    def __init__(self, srv):
        super().__init__(template='dashboard')

        cfg_code = srv.cfg.get('dashboard_code')
        self._code = cfg_code or secrets.token_urlsafe(16)
        if not cfg_code:
            srv.cfg['dashboard_code'] = self._code
            with open(e.expert_path / 'expert_cfg.json', 'w') as f:
                json.dump(srv.cfg, f, indent=2)

        self._path = '/' + srv.cfg["url_prefix"] + f'/dashboard/{self._code}'
        self._url = f'http://{srv.cfg["host"]}:{srv.cfg["port"]}' + self._path
        e.log.info('dashboard URL: ' + self._url)
        self._add_routes()
        self._add_sio_commands(srv)

        self.variables['dashboard_path'] = self._path
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

    def _add_sio_commands(self, srv):
        @srv.socketio.on('dboard_init')
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

        @srv.socketio.on('get_bundles')
        def sio_get_bundles():
            bundles_path = e.expert_path / 'bundles'
            return sorted(bundle.name for bundle in bundles_path.iterdir()
                          if bundle.is_dir() and bundle.stem[0] != '.')

        @srv.socketio.on('get_runs')
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

        @srv.socketio.on('start_new_run')
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

        @srv.socketio.on('delete_id_mappings')
        def sio_delete_id_mappings(runs):
            for run in runs:
                e.log.info(f'deleting id mapping for run {run}')
                shutil.rmtree(e.experclass.runs_path / run / 'id-mapping')

        @srv.socketio.on('terminate_inst')
        def sio_terminate_inst(sid):
            pass

        @srv.socketio.on('load_exper')
        def sio_load_exper(name):
            e.experclass = experiment.BaseExper.load(
                e.expert_path / 'bundles' / name)
            #self.variables['num_profiles'] = e.experclass.num_profiles
            return self.all_vars()

        @srv.socketio.on('reload_exper')
        def sio_reload_exper():
            e.experclass.reload()

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
