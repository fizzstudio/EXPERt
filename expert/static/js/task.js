import { C as Controller, e as elt, O as Overlay, a as ConfirmDialog } from './dialog.js';

class APIError extends Error {
}
class Task extends Controller {
    prevBtn;
    nextBtn;
    nextBtnWrapper;
    taskCursor;
    navSelect;
    content;
    returnBtn;
    _nextHook;
    response;
    confirmDlg;
    errorOverlay;
    vars;
    domVars;
    progbar;
    sidebar;
    sidebarContent;
    guideElt;
    constructor(domVars) {
        super();
        this.domVars = domVars;
        this.progbar = elt('exp-progbar');
        this.sidebar = elt('exp-sidebar');
        this.sidebarContent = elt('exp-sidebar-content');
        this.prevBtn = elt('exp-prev-btn');
        this.nextBtn = elt('exp-next-btn');
        this.nextBtnWrapper = elt('exp-next-btn-wrapper');
        this.taskCursor = elt('exp-task-cursor');
        this.navSelect = elt('exp-nav-menu-select');
        this.content = elt('exp-task-wrapper');
        this.returnBtn = elt('exp-return-btn');
        if (this.domVars.exp_progbar_enabled === 'True') {
            elt('exp-progbar').classList.remove('exp-hidden');
        }
        document.addEventListener('keydown', async (ev) => {
            if (ev.code === 'Enter' && !this.nextBtn.disabled) {
                this.nextBtn.click();
                ev.preventDefault();
                ev.stopPropagation();
            }
        }, true);
        this.nextBtn.addEventListener('click', async () => {
            if (this._nextHook) {
                await this._nextHook();
            }
            this.disableNext();
            await this._nav('next_page', this.response);
        });
        if (this.returnBtn) {
            this.returnBtn.addEventListener('click', async () => {
                if (await this.confirmDlg.show(`Really withdraw your participation in this survey?
                <br><strong>WARNING: This cannot be undone!</strong>`, 'No, continue participating', 'Yes, withdraw participation')) {
                    await this.api('return_survey');
                    location.reload();
                }
            });
        }
        if (this.domVars.exp_tool_mode === 'True') {
            this.prevBtn.addEventListener('click', async () => {
                this.prevBtn.disabled = true;
                await this._nav('prev_page', this.response);
                this.prevBtn.disabled = false;
            });
            this.navSelect.addEventListener('change', async () => {
                const idx = this.navSelect.selectedIndex;
                if (idx) {
                    await this._nav('goto', this.vars['exp_nav_items'][idx - 1], this.response);
                }
            });
        }
    }
    get nextHook() {
        return this._nextHook;
    }
    set nextHook(h) {
        this._nextHook = h;
    }
    async api(cmd, ...params) {
        const { val, err } = await super.api(cmd, ...params);
        if (err) {
            if (this.errorOverlay) {
                this.errorOverlay.makeVisible();
            }
            throw new APIError(`Error in API call '${params[0]}': ${err}`);
        }
        else {
            return val;
        }
    }
    _updateProgress() {
        const cursor = this.vars['exp_task_cursor'];
        const num_tasks = this.vars['exp_num_tasks'];
        const progress_pct = 100 * cursor / num_tasks;
        this.progbar.firstElementChild.style.width = `${progress_pct}%`;
        if (this.domVars.exp_tool_mode === 'True') {
            if (this.domVars.exp_tool_display_total_tasks === 'True') {
                this.taskCursor.textContent = `${cursor}/${num_tasks}`;
            }
            else {
                this.taskCursor.textContent = cursor;
            }
            this.prevBtn.disabled = cursor < 2;
            this.nextBtn.disabled = cursor === num_tasks;
        }
    }
    async _nav(cmd, ...params) {
        let vars = await this.api(cmd, ...params);
        if (vars['task_type'] === this.vars['task_type'] &&
            vars['task_script'] === this.vars['task_script']) {
            this.vars = vars;
            await this.reset();
        }
        else {
            location.reload();
        }
    }
    async init(ns) {
        await super.init(ns);
        this.errorOverlay = await new Overlay(this).init();
        this.errorOverlay.contentNode.textContent =
            'System error. Please contact the administrator.';
        this.confirmDlg = await new ConfirmDialog(this).init();
        this.vars = await this.api('init_task');
        return this;
    }
    defaultResponse() {
        return null;
    }
    async reset() {
        this.guide(null);
        this.response = this.defaultResponse();
        this.content.scrollTo(0, 0);
        window.scrollTo(0, 0);
        this._updateProgress();
    }
    enableNext() {
        this.nextBtn.disabled = false;
        this.guide(this.nextBtn);
    }
    disableNext() {
        if (this.domVars.exp_tool_mode === 'False') {
            this.nextBtn.disabled = true;
        }
        if (this.guideElt === this.nextBtn) {
            this.guide(null);
        }
    }
    setResponse(response) {
        this.response = response;
    }
    guide(guideElt) {
        if (this.guideElt) {
            this.guideElt.classList.remove('exp-guide');
        }
        if (guideElt) {
            guideElt.classList.add('exp-guide');
        }
        this.guideElt = guideElt;
    }
    loadSound(sound) {
        return new Audio(`${this.domVars.exp_app_static}/audio/${sound}.mp3`);
    }
    showSidebar(visible = true) {
        if (visible) {
            this.sidebar.classList.remove('exp-hidden');
        }
        else {
            this.sidebar.classList.add('exp-hidden');
        }
    }
    setSidebarContent(content) {
        this.sidebarContent.innerHTML = content;
    }
}

export { Task as T };
