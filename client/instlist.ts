
import { View, type Controller, elt } from '@fizz/expert-client';
import { type Dashboard, type Event, type Inst } from './dashboard';

export class InstList extends View {
    cols: string[];
    cellClasses: string[];
    numRows: number;
    numCols: number;
    private _eventSeps: { [evt: string]: string };
    private _sepText: { [sepType: string]: (...args: any[]) => string };

    constructor(ctrlr: Controller) {
        super(elt('inst-data')!, ctrlr);
        this.cols = [
            'sid', 'ip', 'profile', 'state', 'task', 'time', 'elapsed'];
        this.cellClasses = [
            'dboard-num', 'dboard-id', 'dboard-clientip',
            'dboard-profile', 'dboard-state', 'dboard-task',
            'dboard-started', 'dboard-elapsed'];
        this.numRows = 0;
        this.numCols = this.cellClasses.length;
        //this.errors = [];
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
                //this.errors.push(tback);
                //div.dataset.error = this.errors.length - 1;
                div.addEventListener('click', async () =>
                    await (this.ctrlr as Dashboard).tracebackDlg.show(tback));
                return 'Error';
            }
        };
    }

    newRow(): HTMLDivElement[] {
        const divs: HTMLDivElement[] = [];
        for (let i = 0; i < this.numCols; i++) {
            divs.push(document.createElement('div'));
            this.node.append(divs[i]);
            divs[i].classList.add(this.cellClasses[i], 'dboard-item');
        }
        divs[0].textContent = `${this.numRows + 1}`;
        divs[1].dataset.index = `${this.numRows++}`;
        return divs;
    }

    getRow(index: number): HTMLDivElement[] {
        const indexDiv: HTMLDivElement | null = this.node.querySelector(
            `div[data-index="${index}"]`);
        if (indexDiv) {
            const divs = [indexDiv];
            for (let i=2; i<this.numCols; i++) {
                divs.push(divs.at(-1)!.nextElementSibling! as HTMLDivElement);
            }
            return divs;
        }
        return [];
    }

    setRow(index: number, fields: Inst) { // , start=0, end=null) {
        const vals = this.cols.map(name => (fields as {[idx: string]: any})[name]);
        // NB: if end is set, it must be non-negative
        //if (end === null) {
        //    end = this.numCols - 1;
        //}
        const divs = this.getRow(index);
        //for (let i=start; i<end; i++) {
        //    divs[i].innerHTML = vals[i - start];
        //}
        for (const [k, v] of Object.entries(fields)) {
            const i = this.cols.indexOf(k);
            divs[i].textContent = v;
        }
    }

    addInst(inst: Inst) {
        this.newRow();
        this.setRow(this.numRows - 1, inst);
    }

    addSeparator(sepType: string, data?: any) {
        const div = document.createElement('div');
        div.textContent = this._sepText[sepType](data, div);
        div.className = `dboard-${sepType}-sep`;
        this.node.append(div);
    }

    clear() {
        this.node.replaceChildren();
        this.numRows = 0;
        //this.errors = [];
    }

    update(items: Event[]) {
        //console.log('items', items);
        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.tag === 'inst') {
                //if (i === this.numRows) {
                    this.newRow();
                //}
                this.setRow(this.numRows - 1, item.data as Inst);
            } else {
                const sepType = this._eventSeps[item.tag];
                if (sepType) {
                    this.addSeparator(sepType, item.data);
                } else {
                    this.addSeparator('unknown', 'UNKNOWN EVENT');
                }
            }
        }
    }

}
