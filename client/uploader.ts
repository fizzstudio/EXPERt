
import { type Dashboard } from './dashboard';
import { elt } from '@fizz/expert-client';

export interface UploadResp {
    ok: boolean;
    err?: string;
}

export class Uploader {

    ctrlr: Dashboard;
    input: HTMLInputElement;
    allow: string[];
    deny: string[];

    constructor(ctrlr: Dashboard) {
        this.ctrlr = ctrlr;
        this.input = elt('file-input') as HTMLInputElement;
        // The manifest can list extra items to be uploaded in addition
        // to what is allowed. Denied items are removed
        // from the manifest before it is added to the allow list.
        this.allow = ['cfg.json', 'src/', 'static/', 'templates/'];
        this.deny = ['profiles/', 'runs/'];
    }

    _aread(f: File): Promise<string> {
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

    async _loadManifest(f: File) {
        const manifest = await this._aread(f);
        return manifest
            .split('\n')
            .map(x => x.trim())
            .filter(
                x => x.length &&
                   !this.deny.find(
                       y => x.toLowerCase() === y) &&
                   // Skip anything already on the allow list
                   !this.allow.find(
                       y => x.toLowerCase() === y));
    }

    async _getFiles(bundleName: string) {
        let manifestF: File | null = null;
        // Guaranteed to be a FileList since the input element is of type "file"
        const fileList = this.input.files as FileList;
        for (const file of fileList) {
            const parts = file.webkitRelativePath.split('/');
            if (parts[1] === 'exp_manifest.txt') {
                manifestF = file;
                break;
            }
        }
        let allow = this.allow;
        if (manifestF) {
            allow = allow.concat(await this._loadManifest(manifestF));
        }
        const files: File[] = [];
        for (const item of allow) {
            const itemPath = `${bundleName}/${item}`;
            for (const file of fileList) {
                // XXX should exclude files in __pycache__ directories,
                // .DS_Store, etc.
                if (item[item.length - 1] === '/') {
                    if (file.webkitRelativePath.startsWith(
                        itemPath)) {
                        //console.log(
                        //'will upload', file.webkitRelativePath);
                        files.push(file);
                    }
                } else {
                    if (file.webkitRelativePath === itemPath) {
                        //console.log(
                        //'will upload', file.webkitRelativePath);
                        files.push(file);
                        break;
                    }
                }
            }
        }
        console.log(`will upload ${files.length} files`);
        return files;
    }

    _sendRequest(formData: FormData, resolve: (value: UploadResp) => void) {
        const url = `${this.ctrlr.vars!['exp_dashboard_path']}/upload_bundle`;
        const xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', e => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded*100)/e.total);
                console.log('pct', pct);
            }
        }, false);
        xhr.upload.addEventListener('load', e => {
            console.log('upload complete');
        }, false);
        xhr.addEventListener('readystatechange', e => {
            if (xhr.readyState === 4) {
                console.log('response:', xhr.response);
                resolve(xhr.response);
                this.ctrlr.uploadBtn.disabled = false;
                this.ctrlr.uploadingOverlay.close();
            }
        }, false);
        xhr.open('POST', url);
        xhr.responseType = 'json';
        xhr.overrideMimeType('multipart/form-data');
        console.log('sending upload request');
        xhr.send(formData);
    }

    upload(): Promise<UploadResp> {
        return new Promise(resolve => {
            const listener = async () => {
                console.log('upload files selected');
                this.ctrlr.uploadBtn.disabled = true;
                this.input.removeEventListener('change', listener, false);
                const bundleName = this.input.files![0]
                                       .webkitRelativePath.split('/')[0];
                console.log('upload bundle name', bundleName);
                const bundles = await this.ctrlr.api('get_bundles');
                if (bundles.includes(bundleName)) {
                    console.log('bundle already exists');
                    let msg = `Really overwrite bundle '${bundleName}'?`;
                    let unload = false;
                    let stopRun = false;
                    if (bundleName === this.ctrlr.bundle) {
                        unload = true;
                        if (this.ctrlr.run) {
                            msg += ' Current run will end.';
                            stopRun = true;
                        }
                    }
                    if (await this.ctrlr.confirmDlg.show(
                        msg, 'Cancel', 'Overwrite')) {
                        if (stopRun) {
                            await this.ctrlr.stopRun();
                        }
                        if (unload) {
                            await this.ctrlr.unloadBundle();
                        }
                    } else {
                        console.log('upload canceled');
                        resolve({ok: true});
                        this.ctrlr.uploadBtn.disabled = false;
                        return;
                    }
                }

                const formData = new FormData();
                this.ctrlr.uploadingOverlay.makeVisible();
                const files = await this._getFiles(bundleName);
                console.log('got upload files');
                for (const file of files) {
                    formData.set(file.webkitRelativePath, file);
                }
                this._sendRequest(formData, resolve);
            };
            this.input.addEventListener('change', listener, false);
            this.input.click();
        });
    }

}
