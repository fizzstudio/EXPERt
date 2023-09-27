import { V as View, e as elt, D as Dialog, C as Controller, a as ConfirmDialog, M as MessageDialog, T as TracebackDialog, O as Overlay } from './dialog.js';

class InstList extends View {
    cols;
    cellClasses;
    numRows;
    numCols;
    _eventSeps;
    _sepText;
    constructor(ctrlr) {
        super(elt('inst-data'), ctrlr);
        this.cols = [
            'sid', 'ip', 'profile', 'state', 'task', 'time', 'elapsed'
        ];
        this.cellClasses = [
            'dboard-num', 'dboard-id', 'dboard-clientip',
            'dboard-profile', 'dboard-state', 'dboard-task',
            'dboard-started', 'dboard-elapsed'
        ];
        this.numRows = 0;
        this.numCols = this.cellClasses.length;
        this._eventSeps = {
            new_run: 'start',
            run_stop: 'stop',
            run_complete: 'end',
            bundle_load: 'load',
            bundle_reload: 'reload',
            bundle_unload: 'unload',
            profiles_rebuild: 'profiles',
            page_load_error: 'error',
            api_error: 'error'
        };
        this._sepText = {
            start: run => `Started new run '${run}'`,
            stop: run => `Run '${run}' stopped`,
            end: run => `Run '${run}' complete`,
            load: bundle => `Bundle '${bundle}' loaded`,
            reload: bundle => `Bundle '${bundle}' reloaded`,
            profiles: () => 'Profiles rebuilt',
            unload: bundle => `Bundle '${bundle}' unloaded`,
            error: (tback, div) => {
                div.addEventListener('click', async () => await this.ctrlr.tracebackDlg.show(tback));
                return 'Error';
            }
        };
    }
    newRow() {
        const divs = [];
        for (let i = 0; i < this.numCols; i++) {
            divs.push(document.createElement('div'));
            this.node.append(divs[i]);
            divs[i].classList.add(this.cellClasses[i], 'dboard-item');
        }
        divs[0].textContent = `${this.numRows + 1}`;
        divs[1].dataset.index = `${this.numRows++}`;
        return divs;
    }
    getRow(index) {
        const indexDiv = this.node.querySelector(`div[data-index="${index}"]`);
        if (indexDiv) {
            const divs = [indexDiv];
            for (let i = 2; i < this.numCols; i++) {
                divs.push(divs.at(-1).nextElementSibling);
            }
            return divs;
        }
        return [];
    }
    setRow(index, fields) {
        this.cols.map(name => fields[name]);
        const divs = this.getRow(index);
        for (const [k, v] of Object.entries(fields)) {
            const i = this.cols.indexOf(k);
            divs[i].textContent = v;
        }
    }
    addInst(inst) {
        this.newRow();
        this.setRow(this.numRows - 1, inst);
    }
    addSeparator(sepType, data) {
        const div = document.createElement('div');
        div.textContent = this._sepText[sepType](data, div);
        div.className = `dboard-${sepType}-sep`;
        this.node.append(div);
    }
    clear() {
        this.node.replaceChildren();
        this.numRows = 0;
    }
    update(items) {
        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.tag === 'inst') {
                this.newRow();
                this.setRow(this.numRows - 1, item.data);
            }
            else {
                const sepType = this._eventSeps[item.tag];
                if (sepType) {
                    this.addSeparator(sepType, item.data);
                }
                else {
                    this.addSeparator('unknown', 'UNKNOWN EVENT');
                }
            }
        }
    }
}

class UploadDialog extends Dialog {
    inputNode;
    uploadBtn;
    constructor(ctrlr, template = 'upload', id = 'exp-dlg-upload') {
        super(ctrlr, template, id);
    }
    async init() {
        await super.init();
        this.titlebar = 'Upload Bundle';
        this.inputNode = this.node.querySelector('.exp-dlg-upload-input');
        this.uploadBtn = this.node.querySelector('.exp-dlg-upload-btn');
        this.inputNode.addEventListener('change', () => this.ctrlr.didSelectFiles(this.inputNode.files));
        this.uploadBtn.addEventListener('click', async () => await this.ctrlr.upload());
        return this;
    }
    async show() {
        this.setButtons([{ tag: 'cancel', text: 'Close' }]);
        return await super.makeVisible();
    }
    enableButton() {
        this.uploadBtn.disabled = false;
    }
    disableButton() {
        this.uploadBtn.disabled = true;
    }
}
class SingleSelectorDialog extends Dialog {
    selectNode;
    constructor(ctrlr, template = 'download', id = 'exp-dlg-download') {
        super(ctrlr, template, id);
    }
    async init() {
        await super.init();
        this.selectNode = this.node.querySelector('.exp-dlg-download-select');
        return this;
    }
    clearOptions() {
        while (this.selectNode.options.length) {
            this.selectNode.remove(0);
        }
    }
}
class RunsDialog extends SingleSelectorDialog {
    run;
    async show(title, btnText, includeCurrent = true, onlyHasPii = false) {
        this.titlebar = title;
        this.run = null;
        this.selectNode.selectedIndex = 0;
        const runs = await this.ctrlr.api('get_runs');
        this.clearOptions();
        this.selectNode.add(new Option('Select a run'));
        for (const run of runs) {
            if ((run.id === this.ctrlr.run && !includeCurrent) ||
                (!run.has_pii && onlyHasPii)) {
                continue;
            }
            const txt = `${run.id} (${run.num_complete}, ${run.num_incomplete})`;
            this.selectNode.add(new Option(txt));
        }
        const selectionChanged = () => {
            this.run = null;
            if (this.selectNode.selectedIndex) {
                const len = this.selectNode.value.split(' ')[0].length;
                this.run = this.selectNode.value.slice(0, len);
            }
            this.setButtonsDisabled({ okay: !this.run });
        };
        this.selectNode.addEventListener('change', selectionChanged);
        this.setButtons([{ tag: 'cancel', text: 'Cancel' },
            { tag: 'okay', text: btnText, disabled: true }]);
        let tag = await super.makeVisible(() => this.buttons['okay'].node.focus());
        this.selectNode.removeEventListener('change', selectionChanged);
        return tag === 'okay';
    }
}
class BundlesDialog extends SingleSelectorDialog {
    toolCboxNode;
    run;
    bundle;
    toolMode;
    constructor(ctrlr) {
        super(ctrlr, 'load_bundle', 'exp-dlg-load');
    }
    async init() {
        await super.init();
        this.toolCboxNode = this.node.querySelector('#exp-dlg-load-tool-cbox');
        return this;
    }
    async show(title, btnText) {
        this.titlebar = title;
        this.run = null;
        this.selectNode.selectedIndex = 0;
        const bundles = await this.ctrlr.api('get_bundles');
        this.clearOptions();
        this.selectNode.add(new Option('Select a bundle'));
        for (const bundle of bundles) {
            this.selectNode.add(new Option(bundle));
        }
        const selectionChanged = () => {
            this.bundle = null;
            if (this.selectNode.selectedIndex) {
                this.bundle = this.selectNode.value;
            }
            this.setButtonsDisabled({ okay: !this.bundle });
        };
        this.selectNode.addEventListener('change', selectionChanged);
        this.setButtons([{ tag: 'cancel', text: 'Cancel' },
            { tag: 'okay', text: btnText, disabled: true }]);
        let tag = await super.makeVisible(() => this.buttons['okay'].node.focus());
        this.selectNode.removeEventListener('change', selectionChanged);
        this.toolMode = this.toolCboxNode.checked;
        return tag === 'okay';
    }
}

class Uploader extends Controller {
    dboard;
    uploadDlg = new UploadDialog(this);
    confirmDlg = new ConfirmDialog(this);
    messageDlg = new MessageDialog(this);
    include = ['cfg.json', 'user_info.json', 'src/', 'static/', 'templates/'];
    deny = ['profiles/', 'runs/'];
    files = null;
    constructor(dboard) {
        super();
        this.dboard = dboard;
    }
    async show() {
        await this.uploadDlg.init();
        await this.confirmDlg.init();
        await this.messageDlg.init();
        this.dboard.uploadBtn.disabled = true;
        await this.uploadDlg.show();
        this.dboard.uploadBtn.disabled = false;
    }
    didSelectFiles(files) {
        console.log(`selected ${files.length} files`);
        this.files = files;
        this.uploadDlg.enableButton();
    }
    async upload() {
        this.uploadDlg.disableButton();
        const bundleName = this.files[0].webkitRelativePath.split('/')[0];
        console.log('upload bundle name:', bundleName);
        const bundles = await this.dboard.api('get_bundles');
        if (bundles.includes(bundleName)) {
            console.log('bundle already exists');
            let msg = `Really overwrite bundle '${bundleName}'?`;
            let unload = false;
            let stopRun = false;
            if (bundleName === this.dboard.bundle) {
                unload = true;
                if (this.dboard.run) {
                    msg += ' Current run will end.';
                    stopRun = true;
                }
            }
            if (await this.confirmDlg.show(msg, 'Cancel', 'Overwrite')) {
                if (stopRun) {
                    await this.dboard.stopRun();
                }
                if (unload) {
                    await this.dboard.unloadBundle();
                }
            }
            else {
                console.log('upload canceled');
                this.uploadDlg.enableButton();
                return;
            }
        }
        this.dboard.uploadingOverlay.makeVisible();
        const fileChunks = await this.getFileChunks(bundleName);
        if (fileChunks.length === 0) {
            this.dboard.uploadingOverlay.close();
            await this.messageDlg.show('Error: no valid files selected');
            return;
        }
        const chunkUploads = this.dboard.vars['exp_simultaneous_chunk_uploads'];
        for (let i = 0; i < Math.ceil(fileChunks.length / chunkUploads); i++) {
            const chunkSet = fileChunks.slice(i * chunkUploads, (i + 1) * chunkUploads);
            await Promise.all(chunkSet.map(c => this.dboard.api('upload_bundle_chunk', [c], false)));
        }
        await this.dboard.api('save_bundle_chunks');
        this.files = null;
        this.dboard.uploadingOverlay.close();
    }
    aread(f) {
        return new Promise(resolve => {
            const reader = new FileReader();
            const listener = () => {
                reader.removeEventListener('load', listener);
                resolve(reader.result);
            };
            reader.addEventListener('load', listener);
            reader.readAsText(f);
        });
    }
    async loadManifest(f) {
        const manifest = await this.aread(f);
        return manifest
            .split('\n')
            .map(x => x.trim())
            .filter(x => x.length &&
            !this.deny.find(y => x.toLowerCase() === y) &&
            !this.include.find(y => x.toLowerCase() === y));
    }
    async getFileChunks(bundleName) {
        let manifestF = null;
        for (const file of this.files) {
            const parts = file.webkitRelativePath.split('/');
            if (parts[1] === 'exp_manifest.txt') {
                manifestF = file;
                break;
            }
        }
        let include = this.include;
        if (manifestF) {
            include = include.concat(await this.loadManifest(manifestF));
        }
        const blockDirs = ['__pycache__'];
        const blockFiles = ['.DS_Store'];
        const files = [];
        let skipped = 0;
        for (const file of this.files) {
            if (blockFiles.some(name => file.webkitRelativePath.endsWith(name)) ||
                blockDirs.some(name => file.webkitRelativePath.match(`/${name}/`))) {
                skipped++;
                continue;
            }
            for (const item of include) {
                const itemPath = `${bundleName}/${item}`;
                if (item[item.length - 1] === '/') {
                    if (file.webkitRelativePath.startsWith(itemPath)) {
                        files.push(file);
                    }
                }
                else {
                    if (file.webkitRelativePath === itemPath) {
                        files.push(file);
                        break;
                    }
                }
            }
        }
        console.log(`will upload ${files.length} files; skipping ${skipped}`);
        const chunks = [];
        const chunkSize = 1024 * this.dboard.vars['exp_upload_chunk_size_kib'];
        for (const file of files) {
            const nChunks = Math.ceil(file.size / chunkSize);
            for (let i = 0; i < nChunks; i++) {
                const start = i * chunkSize;
                const end = i === nChunks - 1 ? file.size : start + chunkSize;
                chunks.push({
                    name: file.webkitRelativePath,
                    idx: i,
                    nChunks,
                    lastMod: file.lastModified,
                    data: file.slice(i * chunkSize, end)
                });
            }
        }
        console.log(`${chunks.length} chunks, ${chunks.reduce((total, c) => total + c.data.size, 0)} bytes`);
        return chunks;
    }
}

var host = "127.0.0.1";
var port = 5000;
var url_prefix = "survey";
var bundles_dir = "bundles";
var monitor_check_interval = 10;
var dashboard_code = "96Q28aD7JgZ2np2-M7tQQQ";
var dashboard_favicon = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect width=%22100%22 height=%22100%22 fill=%22green%22/><text y=%22.9em%22 font-size=%2290%22>🧪</text></svg>";
var upload_chunk_size_kib = 128;
var simultaneous_chunk_uploads = 50;
var cfg = {
	host: host,
	port: port,
	url_prefix: url_prefix,
	bundles_dir: bundles_dir,
	monitor_check_interval: monitor_check_interval,
	dashboard_code: dashboard_code,
	dashboard_favicon: dashboard_favicon,
	upload_chunk_size_kib: upload_chunk_size_kib,
	simultaneous_chunk_uploads: simultaneous_chunk_uploads
};

class APIError extends Error {
}
class Dashboard extends Controller {
    uploadBtn;
    loadBtn;
    newRunBtn;
    reloadBtn;
    profilesBtn;
    downloadBtn;
    downloadProfBtn;
    downloadIdBtn;
    deleteIdBtn;
    downloadLogBtn;
    bundle;
    run;
    completed;
    _didInitViews;
    tracebackDlg;
    uploadingOverlay;
    errorOverlay;
    bundlesDlg;
    runsDlg;
    confirmDlg;
    msgDlg;
    vars;
    instList;
    uploader = new Uploader(this);
    constructor() {
        super();
        this.uploadBtn = elt('upload-btn');
        this.loadBtn = elt('load-btn');
        this.newRunBtn = elt('new-run-btn');
        this.reloadBtn = elt('reload-btn');
        this.profilesBtn = elt('profiles-btn');
        this.downloadBtn = elt('download-btn');
        this.downloadProfBtn = elt('download-prof-btn');
        this.downloadIdBtn = elt('download-id-btn');
        this.deleteIdBtn = elt('delete-id-btn');
        this.downloadLogBtn = elt('download-log-btn');
        this.bundle = null;
        this.run = null;
        this.completed = 0;
        this._didInitViews = false;
    }
    async init(ns) {
        await this.uploader.init(ns);
        return await super.init(ns);
    }
    _initSocket(ns) {
        super._initSocket(ns);
        this._socket.on('new_instance', (inst) => this.instList.addInst(inst));
        this._socket.on('update_instance', (index, inst) => {
            this.instList.setRow(index, inst);
            if (inst.state === 'COMPLETE') {
                this.completed++;
                this.updateRunInfo();
            }
        });
        this._socket.on('update_active_instances', (insts) => {
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
        this._socket.on('page_load_error', (tback) => {
            this.instList.addSeparator('error', tback);
        });
        this._socket.on('api_error', (tback) => {
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
            this.uploadBtn.disabled = true;
            await this.uploader.show();
            this.uploadBtn.disabled = false;
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
            const ok = await this.runsDlg.show('Download Results', 'Download');
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
        this.downloadIdBtn.addEventListener('click', async () => {
            this.downloadIdBtn.disabled = true;
            const ok = await this.runsDlg.show('Download ID Mapping', 'Download', true, true);
            if (ok) {
                this.download('id_mapping', this.runsDlg.run);
            }
            this.downloadIdBtn.disabled = false;
        });
        this.deleteIdBtn.addEventListener('click', async () => {
            this.deleteIdBtn.disabled = true;
            const ok = await this.runsDlg.show('Delete ID Mapping', 'Delete', false, true);
            if (ok &&
                await this.confirmDlg.show(`Really delete ID mapping for run
                    ${this.runsDlg.run}?`, 'Cancel', 'Delete')) {
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
        elt('conn-status').textContent = '';
        this.uploadBtn.disabled = false;
        this.loadBtn.disabled = false;
        if (!this._didInitViews) {
            await this._initViews();
        }
        const data = await this.api('dboard_init');
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
        console.log(`initializing; bundle: ${this.vars['exp_app_name']};` +
            ` run: ${this.run}`);
    }
    async _onSocketDisconnected() {
        await super._onSocketDisconnected();
        elt('conn-status').textContent = 'NOT CONNECTED';
        this.bundle = null;
        this.uploadBtn.disabled = true;
        this.loadBtn.disabled = true;
        this._onBundleUpdate();
    }
    async api(cmd, params = [], showTraceback = true) {
        try {
            return await super.api(cmd, params);
        }
        catch (err) {
            if (showTraceback && this.tracebackDlg) {
                await this.tracebackDlg.show(err);
            }
            throw new APIError(`Error in API call '${params[0]}': ${err}`);
        }
    }
    _onBundleUpdate() {
        if (this.bundle) {
            elt('bundle-name').textContent =
                `${this.bundle}
                (${this.vars['exp_total_profiles']} profiles)`;
            this.newRunBtn.disabled = false;
            this.reloadBtn.disabled = false;
            this.profilesBtn.disabled = false;
            this.downloadBtn.disabled = false;
            this.downloadProfBtn.disabled = false;
            this.downloadIdBtn.disabled = false;
            this.deleteIdBtn.disabled = false;
        }
        else {
            elt('bundle-name').textContent = '<None>';
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
        const ok = await this.bundlesDlg.show('Load Bundle', 'Load');
        if (ok) {
            if (this.bundlesDlg.bundle === this.bundle) {
                await this.reloadBundle(this.bundlesDlg.toolMode);
            }
            else {
                if (this.run) {
                    await this.stopRun();
                }
                const { vars, tback } = await this.api('load_bundle', [this.bundlesDlg.bundle, this.bundlesDlg.toolMode]);
                if (tback) {
                    await this.tracebackDlg.show(tback);
                    if (this.bundle) {
                        this.instList.addSeparator('unload', this.bundle);
                    }
                }
                else {
                    this.instList.addSeparator('load', this.bundlesDlg.bundle);
                }
                this.vars = vars;
                this.bundle = vars['exp_app_name'];
                this._onBundleUpdate();
            }
        }
    }
    async newRun() {
        if (this.run === null || await this.confirmDlg.show('Really start a new run?', 'Cancel', 'Start')) {
            if (this.run) {
                await this.stopRun();
            }
            const { info, err } = await this.api('start_new_run');
            if (info) {
                this.run = info.run;
                this.completed = 0;
                this.updateRunInfo();
                this.instList.addSeparator('start', this.run);
            }
            else {
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
        if (await this.confirmDlg.show(`Really reload '${this.bundle}'? Any current run will end.`, 'Cancel', 'Reload')) {
            if (this.run) {
                await this.stopRun();
            }
            const { vars, err } = await this.api('reload_bundle', [toolMode]);
            if (!err) {
                this.instList.addSeparator('reload', this.bundle);
            }
            else {
                await this.tracebackDlg.show(err);
                this.instList.addSeparator('unload', this.bundle);
                this.bundle = null;
                this._onBundleUpdate();
            }
            this.vars = vars;
        }
    }
    async unloadBundle() {
        this.vars = (await this.api('unload_bundle')).vars;
        this.instList.addSeparator('unload', this.bundle);
        this.bundle = null;
        this._onBundleUpdate();
    }
    async rebuildProfiles() {
        if (await this.confirmDlg.show(`Really rebuild profiles? Any current run will end.`, 'Cancel', 'Rebuild')) {
            if (this.run) {
                await this.stopRun();
            }
            const { vars, err } = await this.api('rebuild_profiles');
            if (!err) {
                this.instList.addSeparator('profiles');
            }
            else {
                await this.tracebackDlg.show(err);
                this.instList.addSeparator('unload', this.bundle);
                this.bundle = null;
                this._onBundleUpdate();
            }
            this.vars = vars;
        }
    }
    download(what, run = null) {
        const anchor = document.createElement('a');
        anchor.href = `${this.vars['exp_dashboard_path']}/download/${what}`;
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
        const runInfo = elt('run-info');
        if (this.run) {
            runInfo.textContent = `${this.run} (${this.completed})`;
        }
        else {
            runInfo.textContent = '<None>';
        }
    }
}
await new Dashboard().init(cfg.dashboard_code);

export { Dashboard };
//# sourceMappingURL=dashboard.js.map
