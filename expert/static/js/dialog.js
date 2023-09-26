function elt(id) {
    return document.getElementById(id);
}
function elts(...ids) {
    const dom = {};
    for (const id of ids) {
        dom[id] = document.getElementById(id);
    }
    return dom;
}
async function callApi(socket, cmd, params = []) {
    const p = new Promise((resolve, reject) => {
        socket.emit('call_api', cmd, ...params, (resp) => {
            if (Object.hasOwn(resp, 'val')) {
                resolve(resp.val);
            }
            else {
                reject(resp.err);
            }
        });
    });
    return p;
}

class Controller {
    _socket;
    async init(ns) {
        this._initSocket(ns);
        return this;
    }
    _initSocket(ns) {
        this._socket = io(`/${ns}`);
        this._socket.on('connect', async () => await this._onSocketConnected());
        this._socket.on('disconnect', async () => await this._onSocketDisconnected());
        this._socket.on('connect_error', async () => await this._onSocketConnectError());
    }
    async _onSocketConnected() {
        console.log("socket connected");
    }
    async _onSocketDisconnected() {
        console.log("socket disconnected");
    }
    async _onSocketConnectError() {
        console.log("socket connection error");
    }
    async api(cmd, params = []) {
        return await callApi(this._socket, cmd, params);
    }
}

class View {
    node;
    ctrlr;
    constructor(node, ctrlr) {
        this.node = node;
        this.ctrlr = ctrlr;
    }
}

class Overlay extends View {
    template;
    visible;
    contentNode;
    _resolve;
    constructor(ctrlr, template = 'overlay', id) {
        const div = document.createElement('div');
        super(div, ctrlr);
        if (id !== undefined) {
            div.id = id;
        }
        div.classList.add('exp-overlay');
        this.template = template;
        this.visible = false;
    }
    async init() {
        const content = await this.ctrlr.api('load_template', [this.template]);
        this.node.innerHTML = content;
        this.contentNode = this.node.querySelector('.exp-overlay-content');
        return this;
    }
    makeVisible(afterFunc) {
        document.querySelector('body').lastChild.after(this.node);
        this.visible = true;
        return new Promise(resolve => {
            this._resolve = resolve;
            if (afterFunc) {
                afterFunc();
            }
        });
    }
    close(value = 'exp_no_tag') {
        this.node.remove();
        this.visible = false;
        this._resolve(value);
    }
}
class Dialog extends Overlay {
    titlebarNode;
    btnsWrapper;
    buttons;
    oldOnkeydown;
    keymap;
    constructor(ctrlr, template, id) {
        super(ctrlr, `${template}_dialog`, id);
        this.node.classList.add('exp-dlg');
        this.buttons = {};
        this.keymap = {};
        this.visible = false;
    }
    async init() {
        await super.init();
        this.titlebarNode = this.node.querySelector('.exp-dlg-title');
        this.btnsWrapper = this.node.querySelector('.exp-dlg-buttons');
        return this;
    }
    set titlebar(t) {
        this.titlebarNode.textContent = t;
    }
    setButtons(buttons) {
        this.buttons = {};
        while (this.btnsWrapper.firstChild) {
            this.btnsWrapper.removeChild(this.btnsWrapper.firstChild);
        }
        for (const { tag, text, hook, disabled } of buttons) {
            const btn = document.createElement('button');
            btn.append(text);
            if (disabled) {
                btn.disabled = true;
            }
            this.btnsWrapper.append(btn);
            this.buttons[tag] = { node: btn, hook, disabled: !!disabled };
        }
    }
    getButtonsDisabled() {
        const state = {};
        for (const [tag, { node, hook, disabled }] of Object.entries(this.buttons)) {
            state[tag] = node.disabled;
        }
        return state;
    }
    setButtonsDisabled(state) {
        if (state) {
            for (const [tag, disabled] of Object.entries(state)) {
                this.buttons[tag].node.disabled = disabled;
            }
        }
        else {
            const curState = this.getButtonsDisabled();
            for (const [tag, { node, hook, disabled }] of Object.entries(this.buttons)) {
                node.disabled = true;
            }
            return curState;
        }
    }
    makeVisible(afterFunc) {
        for (const [tag, { node, hook, disabled }] of Object.entries(this.buttons)) {
            node.disabled = disabled;
        }
        return super.makeVisible(() => {
            if (afterFunc) {
                afterFunc();
            }
            for (const [tag, { node, hook }] of Object.entries(this.buttons)) {
                node.addEventListener('click', async () => {
                    const btnState = this.setButtonsDisabled();
                    const shouldClose = hook ? await hook(tag) : true;
                    if (shouldClose) {
                        this.close(tag);
                    }
                    this.setButtonsDisabled(btnState);
                });
            }
            this.oldOnkeydown = document.onkeydown;
            document.onkeydown = async (ev) => {
                if (ev.code === 'Escape' && this.buttons.cancel) {
                    const hook = this.buttons.cancel.hook;
                    const shouldClose = hook ? await hook('cancel') : true;
                    if (shouldClose) {
                        this.close('cancel');
                    }
                }
                else {
                    const handler = this.keymap[ev.code];
                    if (handler) {
                        handler();
                    }
                }
            };
        });
    }
    close(tag) {
        document.onkeydown = this.oldOnkeydown;
        super.close(tag);
    }
}
class MessageDialog extends Dialog {
    messageNode;
    constructor(ctrlr, template = 'confirm', id) {
        super(ctrlr, template, id);
    }
    async init(btnText = 'Okay') {
        await super.init();
        this.titlebar = 'Message';
        this.messageNode = this.node.querySelector('.exp-dlg-message');
        this.setButtons([{ tag: 'cancel', text: btnText }]);
        return this;
    }
    async show(text) {
        this.messageNode.textContent = text;
        await super.makeVisible(() => this.buttons['cancel'].node.focus());
    }
}
class ConfirmDialog extends Dialog {
    messageNode;
    constructor(ctrlr, template = 'confirm', id) {
        super(ctrlr, template, id);
    }
    async init() {
        await super.init();
        this.titlebar = 'Confirm';
        this.messageNode = this.node.querySelector('.exp-dlg-message');
        return this;
    }
    async show(text, cancelLabel, okayLabel) {
        this.messageNode.innerHTML = text;
        this.setButtons([{ tag: 'cancel', text: cancelLabel },
            { tag: 'okay', text: okayLabel }]);
        let tag = await super.makeVisible(() => this.buttons['okay'].node.focus());
        return tag === 'okay';
    }
}
class TracebackDialog extends MessageDialog {
    tracebackNode;
    constructor(ctrlr, id) {
        super(ctrlr, 'traceback', id);
    }
    async init() {
        await super.init('Close');
        this.titlebar = 'Server Error';
        this.tracebackNode = this.node.querySelector('.exp-dlg-traceback-text');
        return this;
    }
    async show(text) {
        this.tracebackNode.textContent = text;
        await super.show('Error received from server:');
    }
}

export { Controller as C, Dialog as D, MessageDialog as M, Overlay as O, TracebackDialog as T, View as V, ConfirmDialog as a, elts as b, elt as e };
//# sourceMappingURL=dialog.js.map
