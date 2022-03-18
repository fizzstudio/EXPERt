
import { elt } from '/expert/static/js/util.js'

let agreeBox = elt('consent-agree-box')
let radio1 = elt('radio1')
let radio2 = elt('radio2')

export function initTask(task) {
    task.disableNext()

    task.guide(agreeBox)

    radio1.onclick = () => {
        task.setResponse('consent_given')
        task.enableNext()
    }
    radio2.onclick = () => {
        task.setResponse('consent_declined')
        task.enableNext()
    }
}
