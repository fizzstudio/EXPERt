
import { elt } from '/expert/static/js/util.js'

const pficBtn = elt('pfic-redir-btn')

export function initTask(task) {
    task.disableNext()
    if (pficBtn) {
        pficBtn.addEventListener('click', () => {
            location = task.vars['prolific_completion_url']
        })
    }
}
