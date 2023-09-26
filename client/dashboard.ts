
import { 
    Controller, Overlay, MessageDialog, ConfirmDialog, TracebackDialog,
    elt
} from '@fizz/expert-client';
import { Uploader } from './uploader';
import { InstList } from './instlist';
import { BundlesDialog, RunsDialog } from './dialogs';


export interface Inst {
    sid: string;
    ip: string;
    profile: string;
    state: string;
    task: number;
    time: string;
    elapsed: string;
}

export interface Event {
    tag: string;
    data: Inst | string | number;
}

interface RunInfo {
    run: string | null;
    mode: string | null;
    target: string | null;
}

class APIError extends Error {
}

export class Dashboard extends Controller {

    uploadBtn: HTMLButtonElement;
    loadBtn: HTMLButtonElement;
    newRunBtn: HTMLButtonElement;
    reloadBtn: HTMLButtonElement;
    profilesBtn: HTMLButtonElement;
    downloadBtn: HTMLButtonElement;
    downloadProfBtn: HTMLButtonElement;
    downloadIdBtn: HTMLButtonElement;
    deleteIdBtn: HTMLButtonElement;
    downloadLogBtn: HTMLButtonElement;
    uploader: Uploader;
    bundle: string | null;
    run: string | null;
    completed: number;
    private _didInitViews: boolean;
    tracebackDlg: TracebackDialog;
    uploadingOverlay: Overlay;
    errorOverlay: Overlay;
    bundlesDlg: BundlesDialog;
    runsDlg: RunsDialog;
    confirmDlg: ConfirmDialog;
    msgDlg: MessageDialog;
    vars: {[name: string]: any} | null;
    instList: InstList;

    constructor() {
        super();
        this.uploadBtn = elt('upload-btn') as HTMLButtonElement;
        this.loadBtn = elt('load-btn') as HTMLButtonElement;
        this.newRunBtn = elt('new-run-btn') as HTMLButtonElement;
        this.reloadBtn = elt('reload-btn') as HTMLButtonElement;
        this.profilesBtn = elt('profiles-btn') as HTMLButtonElement;
        this.downloadBtn = elt('download-btn') as HTMLButtonElement;
        this.downloadProfBtn = elt('download-prof-btn') as HTMLButtonElement;
        //this.deleteBtn = elt('delete-btn');
        this.downloadIdBtn = elt('download-id-btn') as HTMLButtonElement;
        this.deleteIdBtn = elt('delete-id-btn') as HTMLButtonElement;
        this.downloadLogBtn = elt('download-log-btn') as HTMLButtonElement;
        this.uploader = new Uploader(this);
        this.bundle = null;
        this.run = null;
        this.completed = 0;
        this._didInitViews = false;
    }
    
    async init(ns: string) {
        return await super.init(ns);
    }

    _initSocket(ns: string) {
        super._initSocket(ns);
        this._socket.on('new_instance',
                        (inst: Inst) => this.instList.addInst(inst));
        this._socket.on('update_instance', (index: number, inst: Inst) => {
            //console.log('got update_instance', index, inst);
            this.instList.setRow(index, inst);
            if (inst.state === 'COMPLETE') {
                this.completed++;
                this.updateRunInfo();
            }
        });
        this._socket.on('update_active_instances', (insts: [number, Inst][]) => {
            for (const [index, inst] of insts) {
                this.instList.setRow(index, inst);
            }
        });
        this._socket.on('run_complete', () => {
            this.instList.addSeparator('end', this.run);
            this.run = null;
            this.completed = 0;
            this.updateRunInfo();
        });
        this._socket.on('page_load_error', (tback: string) => {
            this.instList.addSeparator('error', tback);
        });
        this._socket.on('api_error', (tback: string) => {
            this.instList.addSeparator('error', tback);
        });
    }

    async _initViews() {
        this.tracebackDlg = await new TracebackDialog(this).init();
        this.uploadingOverlay = await new Overlay(this).init();
        this.uploadingOverlay.contentNode.textContent = 'Uploading...';
        this.errorOverlay = await new Overlay(this).init();
        this.errorOverlay.contentNode.textContent =
            'Client-server version mismatch; hit reload';
        this.bundlesDlg = await new BundlesDialog(this).init();
        this.runsDlg = await new RunsDialog(this).init();
        this.confirmDlg = await new ConfirmDialog(this).init();
        this.msgDlg = await new MessageDialog(this).init();
        this.instList = new InstList(this);

        this.uploadBtn.addEventListener('click', async () => {
            const {resp, status} = await this.uploader.upload();
            if (resp === null) {
                await this.msgDlg.show(
                    `Bundle upload request failed; response status: ${status}`);
            } else if (!resp.ok) {
                await this.msgDlg.show(
                    `Error uploading bundle: ${resp.err}`);
            }
        });
        this.loadBtn.addEventListener('click', async () => {
            this.loadBtn.disabled = true;
            await this.loadBundle();
            this.loadBtn.disabled = false;
        });
        this.newRunBtn.addEventListener('click', async () => {
            this.newRunBtn.disabled = true;
            await this.newRun();
            this.newRunBtn.disabled = false;
        });
        this.reloadBtn.addEventListener('click', async () => {
            this.reloadBtn.disabled = true;
            await this.reloadBundle();
            if (this.bundle) {
                this.reloadBtn.disabled = false;
            }
        });
        this.profilesBtn.addEventListener('click', async () => {
            this.profilesBtn.disabled = true;
            await this.rebuildProfiles();
            if (this.bundle) {
                this.profilesBtn.disabled = false;
            }
        });

        this.downloadBtn.addEventListener('click', async () => {
            this.downloadBtn.disabled = true;
            const ok = await this.runsDlg.show(
                'Download Results', 'Download');
            if (ok) {
                this.download('results', this.runsDlg.run);
            }
            this.downloadBtn.disabled = false;
        });
        this.downloadProfBtn.addEventListener('click', async () => {
            this.downloadProfBtn.disabled = true;
            this.download('profiles');
            this.downloadProfBtn.disabled = false;
        });
        /*this.deleteBtn.addEventListener('click', async () => {
        this.deleteBtn.disabled = true;
        if (await this.runsDlg.show(
        'Delete Results', 'Delete', false) &&
        await this.confirmDlg.show(
        `Really delete results for run ${this.runsDlg.run}?`,
        'Cancel', 'Delete')) {
        await callApi(
        this.socket, 'delete_runs', [this.runsDlg.run]);
        }
        this.deleteBtn.disabled = false;
        });*/
        this.downloadIdBtn.addEventListener('click', async () => {
            this.downloadIdBtn.disabled = true;
            const ok = await this.runsDlg.show(
                'Download ID Mapping', 'Download', true, true);
            if (ok) {
                this.download('id_mapping', this.runsDlg.run);
            }
            this.downloadIdBtn.disabled = false;
        });
        this.deleteIdBtn.addEventListener('click', async () => {
            this.deleteIdBtn.disabled = true;
            const ok = await this.runsDlg.show(
                'Delete ID Mapping', 'Delete', false, true);
            if (ok &&
                await this.confirmDlg.show(
                    `Really delete ID mapping for run
                    ${this.runsDlg.run}?`,
                    'Cancel', 'Delete')) {
                await this.api('delete_id_mapping', [this.runsDlg.run]);
            }
            this.deleteIdBtn.disabled = false;
        });
        this.downloadLogBtn.addEventListener('click', async () => {
            console.log('will download log');
            this.download('log');
        });
        this._didInitViews = true;
    }

    async _onSocketConnected() {
        await super._onSocketConnected();
        elt('conn-status')!.textContent = '';
        this.uploadBtn.disabled = false;
        this.loadBtn.disabled = false;
        if (!this._didInitViews) {
            await this._initViews();
        }
        const data: {
            vars: {[name: string]: any}, 
            list_items: Event[], 
            run_info: RunInfo
        } = await this.api('dboard_init');
        if (this.vars &&
            this.vars['exp_version'] !== data.vars['exp_version']) {
            await this.errorOverlay.makeVisible();
        }
        this.vars = data.vars;
        this.bundle = this.vars['exp_app_name'];
        this._onBundleUpdate();
        this.instList.clear();
        this.instList.update(data.list_items);
        this.run = data.run_info.run;
        this.completed = this.vars['exp_completed_profiles'];
        this.updateRunInfo();
        console.log(
            `initializing; bundle: ${this.vars['exp_app_name']};` +
            ` run: ${this.run}`);
    }

    async _onSocketDisconnected() {
        await super._onSocketDisconnected();
        elt('conn-status')!.textContent = 'NOT CONNECTED';
        this.bundle = null;
        this.uploadBtn.disabled = true;
        this.loadBtn.disabled = true;
        this._onBundleUpdate();
    }

    async api(cmd: string, params: any[] = []) {
        try {
            return await super.api(cmd, params);
        } catch (err) {
            // If an error occurs during the API call that happens
            // when the traceback dialog is created, obviously
            // it won't exist yet!
            if (this.tracebackDlg) {
                await this.tracebackDlg.show(err as string);
            }
            throw new APIError(
                `Error in API call '${params[0]}': ${err}`);
        } 
    }

    /**
    Called when a bundle has been loaded or unloaded.
    */
    _onBundleUpdate() {
        if (this.bundle) {
            elt('bundle-name')!.textContent =
                `${this.bundle}
                (${this.vars!['exp_total_profiles']} profiles)`;
            this.newRunBtn.disabled = false;
            this.reloadBtn.disabled = false;
            this.profilesBtn.disabled = false;
            this.downloadBtn.disabled = false;
            this.downloadProfBtn.disabled = false;
            this.downloadIdBtn.disabled = false;
            this.deleteIdBtn.disabled = false;
        } else {
            elt('bundle-name')!.textContent = '<None>';
            this.newRunBtn.disabled = true;
            this.reloadBtn.disabled = true;
            this.profilesBtn.disabled = true;
            this.downloadBtn.disabled = true;
            this.downloadProfBtn.disabled = true;
            this.downloadIdBtn.disabled = true;
            this.deleteIdBtn.disabled = true;
        }
    }

    async loadBundle() {
        const ok = await this.bundlesDlg.show(
            'Load Bundle', 'Load');
        if (ok) {
            if (this.bundlesDlg.bundle === this.bundle) {
                await this.reloadBundle(this.bundlesDlg.toolMode);
            } else {
                if (this.run) {
                    await this.stopRun();
                }
                const {vars, tback} = await this.api(
                    'load_bundle', [this.bundlesDlg.bundle,
                    this.bundlesDlg.toolMode]);
                if (tback) {
                    await this.tracebackDlg.show(tback);
                    if (this.bundle) {
                        this.instList.addSeparator('unload', this.bundle);
                    }
                } else {
                    this.instList.addSeparator(
                        'load', this.bundlesDlg.bundle);
                }
                this.vars = vars;
                this.bundle = vars['exp_app_name'];
                this._onBundleUpdate();
            }
        }
    }

    async newRun() {
        if (this.run === null || await this.confirmDlg.show(
            'Really start a new run?', 'Cancel', 'Start')) {
            if (this.run) {
                await this.stopRun();
            }
            const {info, err} = await this.api('start_new_run');
            if (info) {
                this.run = info.run;
                this.completed = 0;
                this.updateRunInfo();
                this.instList.addSeparator('start', this.run);
            } else {
                await this.tracebackDlg.show(err);
            }
        }
    }

    async stopRun() {
        await this.api('stop_run');
        this.instList.addSeparator('stop', this.run);
        this.run = null;
        this.completed = 0;
        this.updateRunInfo();
    }

    async reloadBundle(toolMode = false) {
        if (await this.confirmDlg.show(
            `Really reload '${this.bundle}'? Any current run will end.`,
            'Cancel', 'Reload')) {
            if (this.run) {
                // NB: this adds a stop separator, not a reload separator
                await this.stopRun();
            }
            const {vars, err} = await this.api('reload_bundle', [toolMode]);
            if (!err) {
                this.instList.addSeparator('reload', this.bundle);
            } else {
                await this.tracebackDlg.show(err);
                this.instList.addSeparator('unload', this.bundle);
                this.bundle = null;
                this._onBundleUpdate();
            }
            this.vars = vars;
        }
    }

    async unloadBundle() {
        // unload_bundle never returns an error
        this.vars = (await this.api('unload_bundle')).vars;
        this.instList.addSeparator('unload', this.bundle);
        this.bundle = null;
        this._onBundleUpdate();
    }

    async rebuildProfiles() {
        if (await this.confirmDlg.show(
            `Really rebuild profiles? Any current run will end.`,
            'Cancel', 'Rebuild')) {
            if (this.run) {
                await this.stopRun();
            }
            const {vars, err} = await this.api('rebuild_profiles');
            if (!err) {
                this.instList.addSeparator('profiles');
            } else {
                await this.tracebackDlg.show(err);
                this.instList.addSeparator('unload', this.bundle);
                this.bundle = null;
                this._onBundleUpdate();
            }
            this.vars = vars;
        }
    }

    download(what: string, run: string | null = null) {
        const anchor = document.createElement('a');
        anchor.href = `${this.vars!['exp_dashboard_path']}/download/${what}`;
        if (run) {
            anchor.href += `/${run}`;
            anchor.download = run;
        }
        anchor.style.display = 'none';
        document.body.append(anchor);
        anchor.click();
        document.body.removeChild(anchor);
    }

    updateRunInfo() {
        const runInfo = elt('run-info')!;
        if (this.run) {
            runInfo.textContent = `${this.run} (${this.completed})`;
        } else {
            runInfo.textContent = '<None>';
        }
        //if (info.mode === 'res') {
        //    runInfo.textContent += ' res';
        //} else if (info.mode === 'rep') {
        //    runInfo.textContent += ' rep ' + info.target;
        //}
    }

}

/*let dboard;
(async () => { 
    dboard = await new Dashboard().init('96Q28aD7JgZ2np2-M7tQQQ');
})();*/

// This statement gets passed through into the output .js,
// and expert_cfg.json is symlinked into build/ so Rollup can find it.
import cfg from './expert_cfg.json';

const dboard = await new Dashboard().init(cfg.dashboard_code);
