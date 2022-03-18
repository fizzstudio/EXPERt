
import { elt } from '/expert/static/js/util.js'

export class Task {
    constructor(exper, sid, debug) {
        this.exper = exper
        this.sid = sid
        this.debug = debug
        this.nextBtn = elt('next-btn')
        this.nextBtnWrapper = elt('next-btn-wrapper')
        this.content = elt('task-wrapper')
        // this.onClickNext = null

        this.reset()

        if (sid !== 'None' || debug) {
            let ns = debug ? 'debug' : sid
            this.socket = io(`/${ns}`)
            this.nextBtn.onclick = async () => {
                this.disableNext()
                // let callback = this.onClickNext || (() => location.reload())
                let vars = await this.api('next_page', this.response)
                if (vars['task_type'] === this.vars['task_type']) {
                    this.vars = vars
                    this.reset()
                    this.initFunc(this)
                } else {
                    // moving on to a new task type
                    location.reload()
                }

            }
        }
        // if (disableNext) {
        //     this.disableNext()
        // } else {
        //     this.enableNext()
        // }
    }

    init(f) {
        this.initFunc = f
        this.socket.emit('init_task', vars => {
            this.vars = vars
            f(this)
        })
    }

    reset() {
        this.guide(null)
        this.response = null
        this.content.scrollTo(0, 0)
        window.scrollTo(0, 0)
    }

    async api(func, args = {}) {
        const p = new Promise(resolve => {
            this.socket.emit(func, args, resp => {
                resolve(resp)
            })
        })
        return p
    }

    enableNext() {
        this.nextBtn.disabled = false
        this.guide(this.nextBtnWrapper)
    }

    disableNext() {
        this.nextBtn.disabled = true
        this.guide(null)
    }

    setResponse(response) {
        this.response = response
    }

    guide(guideElt) {
        if (this.guideElt) {
            this.guideElt.classList.remove('guide')
        }
        if (guideElt) {
            guideElt.classList.add('guide')
        }
        this.guideElt = guideElt
    }

    // Pre-load a sound
    loadSound(sound) {
        return new Audio(`/expert/${this.exper}/audio/${sound}.mp3`)
    }
}

export class FSA {
    constructor(task, transitTable) {
        this.task = task
        this.transitTable = transitTable
        this.state = 'q0'
    }

    event(sym) {
        let transits = this.transitTable[this.state]
        if (transits === undefined) {
            return
        }
        let destState = transits[sym]
        // symbols without transitions are treated as loops
        if (destState !== undefined) {
            this.state = destState
            let f = this[this.state]
            if (f !== undefined) {
                f.apply(this)
            }
        }
    }
}

// export const nextBtn = document.getElementById('next-btn')
// nextBtn.disabled = true
