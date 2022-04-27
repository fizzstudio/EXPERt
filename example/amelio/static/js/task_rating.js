
import { elt } from '/expert/js/util.js'

let prompt = elt('prompt')
let showPromptBtn = elt('show-prompt')
let playBtn = elt('play-btn-wrapper').querySelector('button')
let starSetWrapper = elt('star-set-wrapper')
let orth = elt('orth')

let stars = []
let starWrappers = []
for (let i = 0; i < 5; i++) {
    let starWrapper = elt('star-wrapper' + (i + 1))
    let star = starWrapper.querySelector('img')
    stars.push(star)
    starWrappers.push(starWrapper)
}

let starsEnabled = false

function showPrompt(show) {
    if (show) {
        prompt.style.display = 'block'
        showPromptBtn.style.display = 'none'
    } else {
        prompt.style.display = 'none'
        showPromptBtn.style.display = 'block'
    }
}

showPromptBtn.onclick = () => showPrompt(true)

function enableStars() {
    starsEnabled = true
    starSetWrapper.classList.add('enabled')
}

function disableStars() {
    starsEnabled = false
    starSetWrapper.classList.remove('enabled')
    for (let j = 0; j < 5; j++) {
        stars[j].src = '/expert/amelio/img/star_empty.svg'
    }
}

function initPlayer(task, sound) {
    let player = task.loadSound(sound)
    player.ontimeupdate = () => {
        let pct = 100*player.currentTime/player.duration
        // default button background is set in the stylesheet
        playBtn.style.background =
            `linear-gradient(to right, lightgreen ${pct}%, #e1e1e1 ${pct + 1}%, #e1e1e1)`
    }
    player.onended = () => {
        playBtn.style.background = null // '#e1e1e1'
        if (!starsEnabled) {
            enableStars()
            task.guide(starSetWrapper)
        }
    }
    player.autoplay = true
    playBtn.onclick = () => player.play()
    return player
}

export function initTask(task) {
    task.disableNext()

    showPrompt(task.vars['show_prompt'])

    disableStars()

    task.guide(playBtn)

    let player = initPlayer(task, task.vars['sound'])

    orth.innerHTML = `&ldquo;the ${task.vars['orth']}&rdquo;`

    for (let i = 0; i < 5; i++) {
        starWrappers[i].onclick = () => {
            if (!starsEnabled)
                return
            for (let j = 0; j < 5; j++) {
                let sfx = j <= i ? '' : '_empty'
                stars[j].src = `/expert/amelio/img/star${sfx}.svg`
            }
            task.setResponse(i + 1)
            task.enableNext()
        }
    }
}
