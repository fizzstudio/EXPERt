import { T as Task } from './task.js';
import './dialog.js';

class IncompleteTask extends Task {
    constructor(domVars) {
        super(domVars);
        this.disableNext();
    }
}

export { IncompleteTask as taskClass };
//# sourceMappingURL=task_incomplete.js.map
