import { b as elts } from './dialog.js';
import { T as Task } from './task.js';

const dom = elts('exp-consent-agree-box', 'exp-consent-radio1', 'exp-consent-radio2');
class ConsentTask extends Task {
    async reset() {
        await super.reset();
        this.disableNext();
        this.guide(dom['exp-consent-agree-box']);
        dom['exp-consent-radio1'].addEventListener('click', () => {
            this.setResponse('consent_given');
            this.enableNext();
        });
        dom['exp-consent-radio2'].addEventListener('click', () => {
            this.setResponse('consent_declined');
            this.enableNext();
        });
    }
}

export { ConsentTask as taskClass };
//# sourceMappingURL=task_consent.js.map
