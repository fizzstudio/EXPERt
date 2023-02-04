
import { Task } from '@fizz/expert-client';

class QnaireTask extends Task {
    ansValid: Map<any, any>;

    constructor(domVars: {[name: string]: string}) {
        super(domVars);

        // Whether mandatory or to-be-validated answers are in fact
        // provided or valid
        this.ansValid = new Map();

        for (const item of this.content.querySelectorAll('.exp-qnaire-item')) {
            //if (item.dataset['optional'] === 'False') {
            const dataset = (item as HTMLElement).dataset;
            const mandatory = dataset['optional'] === 'False';
            if (mandatory) {
                this.ansValid.set(item.id, false);
            }
            // set handlers to enable/disable the next button
            if (dataset['type'] === 'radio') {
                for (const opt of item.querySelectorAll('.exp-qnaire-opt')) {
                    const input = opt.querySelector('input')!;
                    /*
                       this is necessary because the browser may
                       restore values on page reload
                     */
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
            } else if (dataset['type'] === 'checkbox') {
                /*
                   NB: a mandatory checkbox question requires that
                   at least one option be checked
                 */
                let numChecked = 0;
                for (const opt of item.querySelectorAll('.exp-qnaire-opt')) {
                    const input = opt.querySelector('input')!;
                    if (mandatory && input.checked) {
                        this.ansValid.set(item.id, true);
                        numChecked += 1;
                    }
                    input.addEventListener('click', () => {
                        if (mandatory) {
                            numChecked += input.checked ? 1 : -1;
                            this.ansValid.set(item.id,
                                              numChecked ? true : false);
                        }
                        this.checkAnsValid();
                    });
                }
            } else if (['text', 'shorttext'].includes(dataset['type']!)) {
                const elem = ({
                    text: 'textarea',
                    shorttext: 'input'})[dataset['type']!]!;
                const input = item.querySelector(elem) as HTMLInputElement | HTMLTextAreaElement;
                const validator = input.dataset['validate'];
                const validatorRegex = validator ? new RegExp(validator) : null;
                this.ansValid.set(
                    item.id, this._validateText(
                        input.value.trim(), validatorRegex, mandatory));
                input.addEventListener('input', () => {
                    this.ansValid.set(
                        item.id, this._validateText(
                            input.value.trim(), validatorRegex, mandatory));
                    this.checkAnsValid();
                });
            } else {
                console.log('unknown question type: ' + dataset['type']);
            }
            //}
        }
        // browser might restore all mandatory values,
        // making it necessary to enable the Next button
        this.checkAnsValid();
    }

    _validateText(value: string, re: RegExp | null, mand: boolean) {
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
        // NB: .every() is true for an empty array
        if (Array.from(this.ansValid.values()).every(val => val)) {
            const answers = this.collectAnswers();
            this.setResponse(answers);
            this.enableNext();
        } else {
            this.disableNext();
        }
    }

    collectAnswers() {
        const answers: any[] = [];
        for (const item of this.content.querySelectorAll('.exp-qnaire-item')) {
            const dataset = (item as HTMLElement).dataset;
            const itemType = dataset['type']!;
            if (itemType === 'radio') {
                const opts = item.querySelectorAll('.exp-qnaire-opt');
                let selected = -1;
                for (let i = 0; i < opts.length; i++) {
                    const input = opts[i].querySelector('input')!;
                    if (input.checked) {
                        selected = i;
                        break;
                    }
                }
                answers.push(selected);
            } else if (itemType === 'checkbox') {
                const opts = item.querySelectorAll('.exp-qnaire-opt');
                const checked: number[] = [];
                for (let i = 0; i < opts.length; i++) {
                    const input = opts[i].querySelector('input')!;
                    if (input.checked) {
                        checked.push(i);
                    }
                }
                answers.push(checked);
            } else if (['text', 'shorttext'].includes(itemType)) {
                const elem = ({
                    text: 'textarea',
                    shorttext: 'input'})[itemType]!;
                const input = item.querySelector(elem) as HTMLInputElement | HTMLTextAreaElement;
                answers.push(input.value);
            }
        }
        return answers;
    }

}

export { QnaireTask as taskClass };
