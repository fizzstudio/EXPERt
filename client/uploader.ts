
import { Controller, Overlay, ConfirmDialog, MessageDialog,
    elt
} from '@fizz/expert-client';
import { UploadDialog } from './dialogs';

import { type Dashboard } from './dashboard';

export interface UploadResp {
    ok: boolean;
    err?: string;
}

export interface UploadResult {
    resp: UploadResp | null;
    status?: string;
}

interface FileChunk {
    name: string;
    idx: number;
    nChunks: number;
    lastMod: number;
    data: Blob;
}

export class Uploader extends Controller {
    private uploadDlg = new UploadDialog(this);
    private confirmDlg = new ConfirmDialog(this);
    private messageDlg = new MessageDialog(this);

    // The manifest can list extra items to be uploaded in addition
    // to what is included by default. Denied items are removed
    // from the manifest before it is added to the include list.
    private include = ['cfg.json', 'user_info.json', 'src/', 'static/', 'templates/'];
    private deny = ['profiles/', 'runs/'];
    private files: FileList | null = null;

    constructor(private dboard: Dashboard) {
        super();
    }

    async show() {
        await this.uploadDlg.init();
        await this.confirmDlg.init();
        await this.messageDlg.init();
        this.dboard.uploadBtn.disabled = true;
        await this.uploadDlg.show();
        this.dboard.uploadBtn.disabled = false;
    }

    didSelectFiles(files: FileList) {
        console.log(`selected ${files.length} files`);
        this.files = files;
        this.uploadDlg.enableButton();
    }

    async upload() {
        // NB: Doesn't get re-enabled after successful upload
        this.uploadDlg.disableButton();
        const bundleName = this.files![0].webkitRelativePath.split('/')[0];
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
            } else {
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
        const chunkUploads = this.dboard.vars!['exp_simultaneous_chunk_uploads'] as number;
        for (let i = 0; i < Math.ceil(fileChunks.length/chunkUploads); i++) {
            const chunkSet = fileChunks.slice(i*chunkUploads, (i + 1)*chunkUploads);
            await Promise.all(chunkSet.map(
                c => this.dboard.api('upload_bundle_chunk', [c], false)));
        } 
        await this.dboard.api('save_bundle_chunks');
        this.files = null;
        this.dboard.uploadingOverlay.close();
    }

    private aread(f: File): Promise<string> {
        return new Promise(resolve => {
            const reader = new FileReader();
            const listener = () => {
                reader.removeEventListener('load', listener);
                resolve(reader.result as string);
            };
            reader.addEventListener('load', listener);
            reader.readAsText(f);
        });
    }

    private async loadManifest(f: File) {
        const manifest = await this.aread(f);
        return manifest
            .split('\n')
            .map(x => x.trim())
            .filter(
                x => x.length &&
                   !this.deny.find(y => x.toLowerCase() === y) &&
                   // Skip anything already on the include list
                   !this.include.find(y => x.toLowerCase() === y));
    }

    private async getFileChunks(bundleName: string) {
        let manifestF: File | null = null;
        for (const file of this.files!) {
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
        // Can be used to match dotfiles or file types by extension
        const blockFiles = ['.DS_Store'];
        const files: File[] = [];
        let skipped = 0;
        for (const file of this.files!) {
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
                } else {
                    if (file.webkitRelativePath === itemPath) {
                        files.push(file);
                        break;
                    }
                }
            }
        }
        console.log(`will upload ${files.length} files; skipping ${skipped}`);
        const chunks: FileChunk[] = [];
        const chunkSize = 1024*this.dboard.vars!['exp_upload_chunk_size_kib'] as number;
        for (const file of files) {
            const nChunks = Math.ceil(file.size/chunkSize);
            for (let i = 0; i < nChunks; i++) {
                const start = i*chunkSize;
                const end = i === nChunks - 1 ? file.size : start + chunkSize;
                chunks.push({
                    name: file.webkitRelativePath,
                    idx: i,
                    nChunks,
                    lastMod: file.lastModified,
                    data: file.slice(i*chunkSize, end)
                });
            }
        }
        console.log(`${chunks.length} chunks, ${chunks.reduce((total, c) => total + c.data.size, 0)} bytes`);
        return chunks;
    }

}
