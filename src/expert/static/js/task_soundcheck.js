
import { FSA } from '/expert/static/js/task.js'
import { elt } from '/expert/static/js/util.js'

let player = elt('soundcheck-player')

let responseWrapper = elt('soundcheck-response-wrapper')
let submitButton = elt('soundcheck-submit-btn')
let responseField = elt('soundcheck-response')
let correctMsg = elt('soundcheck-correct-msg')

// global socket
const socket = io()
socket.on('connect', () => {
    console.log("socket connected")
})

class MyFSA extends FSA {
    q1() {
        this.task.guide(responseWrapper)
        let submitHandler = () => {
            let enteredText = responseField.value
            socket.emit('soundcheck', enteredText, ok => {
                if (ok) {
                    this.event('response_correct')
                } else {
                    // clear text field
                    responseField.value = ''
                    alert(
                        'That did not match the audio clip. Please try again.')
                }
            })
        }
        submitButton.disabled = false
        submitButton.onclick = submitHandler
        responseField.disabled = false
        responseField.onkeydown = async (e) => {
            if (e.code === 'Enter')
                await submitHandler()
        }
    }
    q2() {
        this.task.enableNext()
        correctMsg.style.display = 'block'
        submitButton.disabled = true
        responseField.disabled = true
    }
}

export function initTask(task) {
    task.disableNext()

    if (player.canPlayType('audio/mp3')) {
        let playerWrapper = elt('soundcheck-player-wrapper')
        task.guide(playerWrapper)
        let fsa = new MyFSA(task, {
            q0: {play_clicked: 'q1'},
            q1: {response_correct: 'q2'}
        })
        player.onended = () => {
            fsa.event('play_clicked')
        }
    } else {
        let formatError = elt('soundcheck-format-error')
        let controlsWrapper = elt('soundcheck-controls')
        controlsWrapper.style.display = 'none'
        formatError.style.display = 'block'
     }
}
