
import { Task } from '@fizz/expert-client';

document.getElementById('exp-task-wrapper')!.scrollTo(0, 0);
window.scrollTo(0, 0);

const vars = document.getElementById('exp-vars')!.dataset as {[name: string]: string};

const sid = vars.exp_sid;

let task: Task;
if ('task_script' in vars) {
    let jspath: string, taskScript = vars.task_script!;
    if (vars.task_script!.startsWith('_')) {
        jspath = vars.exp_js!;
        taskScript = taskScript.slice(1);
    } else {
        jspath = vars.exp_app_js!;
    }
    try {
        const mod = await import(`${ jspath }/task_${ taskScript }.js`);
        task = new mod.taskClass(vars);
    } catch (error) {
        console.log('error importing script:', error);
    }
} else {
    task = new class extends Task {
        async reset() {
            super.reset();
            this.enableNext();
        }
    }(vars);
}
await task!.init(sid);
await task!.reset();
