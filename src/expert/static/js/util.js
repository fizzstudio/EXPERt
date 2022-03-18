
'use strict'

export function elt(id) {
    return document.getElementById(id)
}

export function aPlay(sound) {
    return new Promise((resolve, reject) => {
        sound.onended = () => resolve()
        sound.play()
    })
}

export function aSleep(ms) {
    return new Promise((resolve, reject) => {
        setTimeout(resolve, ms)
    })
}
