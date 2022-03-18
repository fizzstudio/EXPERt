
import { elt } from '/expert/static/js/util.js'

let sounds = ['x05', 'x03', 'x02', 'x01', 'x04']
let playBtns = elt('rating-examples').querySelectorAll('.play-btn')

export function initTask(task) {
    task.enableNext()

    for (let i=0; i<sounds.length; i++) {
        let player = task.loadSound(sounds[i])
        player.ontimeupdate = () => {
            let pct = 100*player.currentTime/player.duration
            // default button background is set in the stylesheet
            playBtns[i].style.background =
                `linear-gradient(to right, lightgreen ${pct}%, #e1e1e1 ${pct + 1}%, #e1e1e1)`
        }
        player.onended = () => {
            playBtns[i].style.background = null // '#e1e1e1'
        }
        playBtns[i].onclick = () => player.play()
    }
}
