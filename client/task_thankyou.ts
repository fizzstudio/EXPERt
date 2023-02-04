
import { Task, elt } from '@fizz/expert-client';

const pficBtn = elt('exp-pfic-redir-btn');

class ThankYouTask extends Task {
    constructor(domVars: {[name: string]: string}) {
        super(domVars);
        this.disableNext();
        if (pficBtn) {
            pficBtn.addEventListener('click', () => {
                location = this.vars!['exp_prolific_completion_url'];
            });
        }
    }
}

export { ThankYouTask as taskClass };
