
function collectAnswers(task) {
    let answers = []
    for (let item of task.content.querySelectorAll('.qnaire-item')) {
        let itemType = item.dataset['type']
        if (itemType === 'radio') {
            let opts = item.querySelectorAll('.qnaire-opt')
            let selected = -1
            for (let i = 0; i < opts.length; i++) {
                let input = opts[i].querySelector('input')
                if (input.checked) {
                    selected = i
                    break
                }
            }
            answers.push(selected)
        } else if (itemType === 'checkbox') {
            let opts = item.querySelectorAll('.qnaire-opt')
            let checked = []
            for (let i = 0; i < opts.length; i++) {
                let input = opts[i].querySelector('input')
                if (input.checked) {
                    checked.push(i)
                }
            }
            answers.push(checked)
        } else if (['text', 'shorttext'].includes(itemType)) {
            let elem = ({
                text: 'textarea',
                shorttext: 'input'})[itemType]
            let input = item.querySelector(elem)
            answers.push(input.value)
        }
    }
    return answers
}

// indicates whether a mandatory item has been set or not
let mandatory = new Map()

function checkMandatories(task) {
    if (Array.from(mandatory.values()).every(val => val)) {
        let answers = collectAnswers(task)
        task.setResponse(answers)
        task.enableNext()
    } else {
        task.disableNext()
    }
}

export function initTask(task) {
    task.disableNext()

    for (let item of task.content.querySelectorAll('.qnaire-item')) {
        if (item.dataset['optional'] === 'False') {
            mandatory.set(item.id, false)
            // set handlers to enable/disable the next button
            if (item.dataset['type'] === 'radio') {
                for (let opt of item.querySelectorAll('.qnaire-opt')) {
                    let input = opt.querySelector('input')
                    /*
                      this is necessary because the browser may
                      restore values on page reload
                    */
                    if (input.checked)
                        mandatory.set(item.id, true)
                    input.onclick = () => {
                        mandatory.set(item.id, true)
                        checkMandatories(task)
                    }
                }
            } else if (item.dataset['type'] === 'checkbox') {
                /*
                  NB: a mandatory checkbox question requires that
                  at least one option be checked
                */
                let numChecked = 0
                for (let opt of item.querySelectorAll('.qnaire-opt')) {
                    let input = opt.querySelector('input')
                    if (input.checked) {
                        mandatory.set(item.id, true)
                        numChecked += 1
                    }
                    input.onclick = () => {
                        numChecked += input.checked? 1 : -1
                        mandatory.set(item.id, numChecked? true : false)
                        checkMandatories(task)
                    }
                }
            } else if (['text', 'shorttext'].includes(item.dataset['type'])) {
                let elem = ({
                    text: 'textarea',
                    shorttext: 'input'})[item.dataset['type']]
                let input = item.querySelector(elem)
                mandatory.set(item.id, Boolean(input.value))
                input.oninput = () => {
                    mandatory.set(item.id, Boolean(input.value))
                    checkMandatories(task)
                }
            } else {
                console.log('unknown question type: ' + item.dataset['type'])
            }
        }
    }

    /* let prompt = task.elt('prompt')
       prompt.style.display = 'block' */

    /* browser might restore all mandatory values,
       making it necessary to enable the Next button */
    checkMandatories(task)
}
