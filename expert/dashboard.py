
import secrets
import json
import zipfile
import shutil

from pathlib import Path

from flask import send_file

import expert
from . import templates, experiment


_code: str
_path: str
_url: str


def init():
    global _code, _path, _url
    cfg_code = expert.cfg.get('dashboard_code')
    _code = cfg_code or secrets.token_urlsafe(16)
    if not cfg_code:
        expert.cfg['dashboard_code'] = _code
        with open(expert.expert_path / 'expert_cfg.json', 'w') as f:
            json.dump(expert.cfg, f, indent=2)

    _path = '/' + expert.cfg["url_prefix"] + f'/dashboard/{_code}'
    _url = f'http://{expert.cfg["host"]}:{expert.cfg["port"]}' + _path
    expert.log.info('dashboard URL: ' + _url)
    _add_routes()
    _add_sio_commands()


def _add_routes():
    @expert.app.route(_path)
    def dashboard():
        return templates.render('dashboard' + templates.html_ext, {
            'dashboard_path': _path,
            'num_profiles': expert.experclass.num_profiles,
            'exp_window_title': 'EXPERt Dashboard',
            'exp_favicon': expert.cfg['dashboard_favicon']
        })

    @expert.app.route(f'{_path}/download/<path:subpath>/results')
    def dashboard_dl_results(subpath):
        dl_name = f'exp_{expert.experclass.name}_{subpath}_results.zip'
        expert.log.info(f'download request for {dl_name}')
        _zip_results(subpath, dl_name)
        return _download(dl_name)

    @expert.app.route(f'{_path}/download/<path:subpath>/id_mapping')
    def dashboard_dl_id_map(subpath):
        dl_name = f'exp_{expert.experclass.name}_{subpath}_id_map.zip'
        expert.log.info(f'download request for {dl_name}')
        _zip_id_mapping(subpath, dl_name)
        return _download(dl_name)


def _add_sio_commands():
    @expert.socketio.on('dboard_init')
    def sio_dboard_init():
        return {
            'insts': [inst.status()
                      for sid, inst in expert.experclass.instances.items()],
            'runInfo': _run_info()
        }

    @expert.socketio.on('get_runs')
    def sio_get_runs():
        runs = []
        for run in expert.experclass.runs_path.iterdir():
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

    @expert.socketio.on('start_new_run')
    def sio_start_new_run():
        expert.experclass.start_new_run()
        return _run_info()

    # @socketio.on('delete_results')
    # def sio_delete_results(runs):
    #     for run in runs:
    #         app.logger.info(f'deleting results for run {run}')
    #         shutil.rmtree(experclass.runs_path / run)

    @expert.socketio.on('delete_id_mappings')
    def sio_delete_id_mappings(runs):
        for run in runs:
            expert.log.info(f'deleting id mapping for run {run}')
            shutil.rmtree(expert.experclass.runs_path / run / 'id-mapping')

    @expert.socketio.on('terminate_inst')
    def sio_terminate_inst(sid):
        pass


def _run_info():
    return {
        'run': expert.experclass.run,
        'mode': expert.experclass.mode,
        'target': expert.experclass.target
    }


def _zip_results(run_id, zip_name):
    expert.log.info('building zip file')
    run_path = expert.experclass.runs_path / run_id
    root = Path(zip_name).stem
    with zipfile.ZipFile(expert.experclass.dls_path / zip_name, 'w',
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


def _zip_id_mapping(run_id, zip_name):
    expert.log.info('building zip file')
    id_map_path = expert.experclass.runs_path / run_id / 'id-mapping'
    root = Path(zip_name).stem
    with zipfile.ZipFile(expert.experclass.dls_path / zip_name, 'w',
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for fpath in id_map_path.iterdir():
            if fpath.stem[0] == '.' or not fpath.is_file():
                continue
            zf.write(str(fpath), root + '/' + fpath.name)


def _download(dl_name):
    #if not dl_path.is_file():
    return send_file(
        expert.experclass.dls_path / dl_name,
        as_attachment=True, download_name=dl_name)
