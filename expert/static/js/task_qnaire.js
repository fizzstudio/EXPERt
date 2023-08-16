import { T as Task } from './task.js';
import './dialog.js';

class QnaireTask extends Task {
    ansValid;
    constructor(domVars) {
        super(domVars);
        this.ansValid = new Map();
        for (const item of this.content.querySelectorAll('.exp-qnaire-item')) {
            const dataset = item.dataset;
            const mandatory = dataset['optional'] === 'False';
            if (mandatory) {
                this.ansValid.set(item.id, false);
            }
            if (dataset['type'] === 'radio') {
                for (const opt of item.querySelectorAll('.exp-qnaire-opt')) {
                    const input = opt.querySelector('input');
                    if (mandatory && input.checked) {
                        this.ansValid.set(item.id, true);
                    }
                    input.addEventListener('click', () => {
                        if (mandatory) {
                            this.ansValid.set(item.id, true);
                        }
                        this.checkAnsValid();
                    });
                }
            }
            else if (dataset['type'] === 'checkbox') {
                let numChecked = 0;
                for (const opt of item.querySelectorAll('.exp-qnaire-opt')) {
                    const input = opt.querySelector('input');
                    if (mandatory && input.checked) {
                        this.ansValid.set(item.id, true);
                        numChecked += 1;
                    }
                    input.addEventListener('click', () => {
                        if (mandatory) {
                            numChecked += input.checked ? 1 : -1;
                            this.ansValid.set(item.id, numChecked ? true : false);
                        }
                        this.checkAnsValid();
                    });
                }
            }
            else if (['text', 'shorttext'].includes(dataset['type'])) {
                const elem = ({
                    text: 'textarea',
                    shorttext: 'input'
                })[dataset['type']];
                const input = item.querySelector(elem);
                const validator = input.dataset['validate'];
                const validatorRegex = validator ? new RegExp(validator) : null;
                this.ansValid.set(item.id, this._validateText(input.value.trim(), validatorRegex, mandatory));
                input.addEventListener('input', () => {
                    this.ansValid.set(item.id, this._validateText(input.value.trim(), validatorRegex, mandatory));
                    this.checkAnsValid();
                });
            }
            else {
                console.log('unknown question type: ' + dataset['type']);
            }
        }
        this.checkAnsValid();
    }
    _validateText(value, re, mand) {
        let valid = true;
        if (mand) {
            valid = Boolean(value);
        }
        if (re) {
            valid &&= re.test(value);
        }
        return valid;
    }
    defaultResponse() {
        return this.collectAnswers();
    }
    checkAnsValid() {
        if (Array.from(this.ansValid.values()).every(val => val)) {
            const answers = this.collectAnswers();
            this.setResponse(answers);
            this.enableNext();
        }
        else {
            this.disableNext();
        }
    }
    collectAnswers() {
        const answers = [];
        for (const item of this.content.querySelectorAll('.exp-qnaire-item')) {
            const dataset = item.dataset;
            const itemType = dataset['type'];
            if (itemType === 'radio') {
                const opts = item.querySelectorAll('.exp-qnaire-opt');
                let selected = -1;
                for (let i = 0; i < opts.length; i++) {
                    const input = opts[i].querySelector('input');
                    if (input.checked) {
                        selected = i;
                        break;
                    }
                }
                answers.push(selected);
            }
            else if (itemType === 'checkbox') {
                const opts = item.querySelectorAll('.exp-qnaire-opt');
                const checked = [];
                for (let i = 0; i < opts.length; i++) {
                    const input = opts[i].querySelector('input');
                    if (input.checked) {
                        checked.push(i);
                    }
                }
                answers.push(checked);
            }
            else if (['text', 'shorttext'].includes(itemType)) {
                const elem = ({
                    text: 'textarea',
                    shorttext: 'input'
                })[itemType];
                const input = item.querySelector(elem);
                answers.push(input.value);
            }
        }
        return answers;
    }
}

export { QnaireTask as taskClass };
//# sourceMappingURL=task_qnaire.js.map
