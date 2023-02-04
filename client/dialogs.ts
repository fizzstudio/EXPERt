
import { type Controller, Dialog } from '@fizz/expert-client';
import { type Dashboard } from './dashboard';

export class SingleSelectorDialog extends Dialog {
    selectNode: HTMLSelectElement;

    constructor(ctrlr: Controller, template = 'download', id = 'exp-dlg-download') {
        super(ctrlr, template, id);
    }

    async init() {
        await super.init();
        this.selectNode = this.node.querySelector(
            '.exp-dlg-download-select')!;
        return this;
    }

    clearOptions() {
        while (this.selectNode.options.length) {
            this.selectNode.remove(0);
        }
    }

}

export class RunsDialog extends SingleSelectorDialog {
    run: string|null;

    async show(title: string, btnText: string, includeCurrent=true, onlyHasPii=false) {
        this.titlebar = title;
        this.run = null;
        this.selectNode.selectedIndex = 0;
        /* obj with keys:
        'id', 'num_complete', 'num_incomplete', 'has_pii'
        */
        const runs = await this.ctrlr.api('get_runs');
        this.clearOptions();
        this.selectNode.add(new Option('Select a run'));
        for (const run of runs) {
            if ((run.id === (this.ctrlr as Dashboard).run && !includeCurrent) ||
                (!run.has_pii && onlyHasPii)) {
                continue;
            }
            const txt =
                `${run.id} (${run.num_complete}, ${run.num_incomplete})`;
            this.selectNode.add(new Option(txt));
        }
        const selectionChanged = () => {
            this.run = null;
            if (this.selectNode.selectedIndex) {
                const len = this.selectNode.value.split(' ')[0].length;
                this.run = this.selectNode.value.slice(0, len);
            }
            this.setButtonsDisabled({okay: !this.run});
        }
        this.selectNode.addEventListener('change', selectionChanged);
        this.setButtons(
            [{tag: 'cancel', text: 'Cancel'},
             {tag: 'okay', text: btnText, disabled: true}]);
        let tag = await super.makeVisible(() => this.buttons['okay'].node.focus());
        this.selectNode.removeEventListener('change', selectionChanged);
        return tag === 'okay';
    }
}

export class BundlesDialog extends SingleSelectorDialog {
    toolCboxNode: HTMLInputElement;
    run: string|null;
    bundle: string|null;
    toolMode: boolean;

    constructor(ctrlr: Controller) {
        super(ctrlr, 'load_bundle', 'exp-dlg-load');
    }

    async init() {
        await super.init();
        // Can't use elt() here bc we're not added to the document yet
        this.toolCboxNode = this.node.querySelector(
            '#exp-dlg-load-tool-cbox')!;
        return this;
    }

    async show(title: string, btnText: string) {
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
            this.setButtonsDisabled({okay: !this.bundle});
        }
        this.selectNode.addEventListener('change', selectionChanged);
        this.setButtons(
            [{tag: 'cancel', text: 'Cancel'},
             {tag: 'okay', text: btnText, disabled: true}]);
        let tag = await super.makeVisible(() => this.buttons['okay'].node.focus());
        this.selectNode.removeEventListener('change', selectionChanged);
        this.toolMode = this.toolCboxNode.checked;
        return tag === 'okay';
    }
}
