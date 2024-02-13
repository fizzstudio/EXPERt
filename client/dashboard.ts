
import { 
    Controller, Overlay, MessageDialog, ConfirmDialog, TracebackDialog,
    elt
} from '@fizz/expert-client';
import { InstList } from './instlist';
import { BundlesDialog, RunsDialog } from './dialogs';
import { Uploader } from './uploader';


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

interface ButtonInfo {
    element: HTMLButtonElement;
    listener: () => Promise<void | boolean>;
}

export class Dashboard extends Controller {

    toolbarBtns: {[key: string]: ButtonInfo} = {};
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
    private uploader = new Uploader(this);

    constructor() {
        super();
        const btns = {
            'upload': () => this.uploader.show(), 
            'load': async () => await this.loadBundle(), 
            'new-run': async () => await this.newRun(), 
            'reload': async () => await this.reloadBundle(), 
            'profiles': async () => await this.rebuildProfiles(), 
            'download': async () => {
                const ok = await this.runsDlg.show(
                    'Download Results', 'Download');
                if (ok) {
                    this.download('results', this.runsDlg.run);
                }
            }, 
            'download-prof': async () => this.download('profiles'), 
            'download-id': async () => {
                const ok = await this.runsDlg.show(
                    'Download ID Mapping', 'Download', true, true);
                if (ok) {
                    this.download('id_mapping', this.runsDlg.run);
                }
            }, 
            'delete-id': async () => {
                const ok = await this.runsDlg.show(
                    'Delete ID Mapping', 'Delete', false, true);
                if (ok &&
                    await this.confirmDlg.show(
                        `Really delete ID mapping for run
                        ${this.runsDlg.run}?`,
                        'Cancel', 'Delete')) {
                    await this.api('delete_id_mapping', [this.runsDlg.run]);
                }
            }, 
            'download-log': async () => this.download('log')
        };
        for (const [name, listener] of Object.entries(btns)) {
            this.toolbarBtns[name] = {
                element: elt(name + '-btn') as HTMLButtonElement,
                listener
            };
        }
        this.bundle = null;
        this.run = null;
        this.completed = 0;
        this._didInitViews = false;
    }
    
    async init(ns: string) {
        await this.uploader.init(ns);
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

        for (const [name, info] of Object.entries(this.toolbarBtns)) {
            info.element.addEventListener('click', async () => {
                info.element.disabled = true;
                //console.log('will run listener');
                if (!await info.listener()) {
                    //console.log('did run listener');
                    info.element.disabled = false;
                }
                //console.log('done');
            });
        }

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
        this._didInitViews = true;
    }

    async _onSocketConnected() {
        await super._onSocketConnected();
        elt('conn-status')!.textContent = '';
        this.toolbarBtns['upload'].element.disabled = false;
        this.toolbarBtns['load'].element.disabled = false;
        this.toolbarBtns['download-log'].element.disabled = false;
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
        this.toolbarBtns['upload'].element.disabled = true;
        this.toolbarBtns['load'].element.disabled = true;
        this.toolbarBtns['download-log'].element.disabled = true;
        this._onBundleUpdate();
    }

    async api(cmd: string, params: any[] = [], showTraceback=true) {
        try {
            return await super.api(cmd, params);
        } catch (err) {
            // If an error occurs during the API call that happens
            // when the traceback dialog is created, obviously
            // it won't exist yet!
            if (showTraceback && this.tracebackDlg) {
                await this.tracebackDlg.show(err as string);
            }
            throw new APIError(`Error in API call '${params[0]}': ${err}`);
        } 
    }

    /**
    Called when a bundle has been loaded or unloaded.
    */
    _onBundleUpdate() {
        const btns = [
            'new-run', 'reload', 'profiles', 'download',
            'download-prof', 'download-id', 'delete-id'
        ];
        if (this.bundle) {
            elt('bundle-name')!.textContent =
                `${this.bundle}
                (${this.vars!['exp_total_profiles']} profiles)`;
            btns.forEach(name => {
                this.toolbarBtns[name].element.disabled = false;
            });
        } else {
            elt('bundle-name')!.textContent = '<None>';
            btns.forEach(name => {
                this.toolbarBtns[name].element.disabled = true;
            });
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
                    'load_bundle', [this.bundlesDlg.bundle, this.bundlesDlg.toolMode]);
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
        if (!this.bundle) {
            return true;
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
        if (!this.bundle) {
            return true;
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
