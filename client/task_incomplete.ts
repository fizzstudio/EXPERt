
import { Task } from '@fizz/expert-client';

class IncompleteTask extends Task {

    constructor(domVars: {[name: string]: string}) {
        super(domVars);
        this.disableNext();
    }
}

export { IncompleteTask as taskClass };
