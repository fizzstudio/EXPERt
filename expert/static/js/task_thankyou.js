import { e as elt } from './dialog.js';
import { T as Task } from './task.js';

const pficBtn = elt('exp-pfic-redir-btn');
class ThankYouTask extends Task {
    constructor(domVars) {
        super(domVars);
        this.disableNext();
        if (pficBtn) {
            pficBtn.addEventListener('click', () => {
                location = this.vars['exp_prolific_completion_url'];
            });
        }
    }
}

export { ThankYouTask as taskClass };
