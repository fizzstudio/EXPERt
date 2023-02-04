
import { Task, FSA, FSAStates, elts } from '@fizz/expert-client';


const dom = elts(
    'play-btn', 'player-wrapper',
    'response-wrapper',
    'submit-btn', 'response-input',
    'correct-msg',
    'format-error', 'controls'
);


class States extends FSAStates {
    responseInput: HTMLInputElement;
    submitBtn: HTMLButtonElement;

    constructor(task: Task) {
        super(task);
        this.transits = {
            q0: {sound_ended: 'q1'},
            q1: {response_correct: 'q2'}
        };
        this.responseInput = dom['response-input'] as HTMLInputElement;
        this.submitBtn = dom['submit-btn'] as HTMLButtonElement;
        this.funcs = {
            q0: () => {
                const playerWrapper = dom['player-wrapper'];
                this.task.guide(playerWrapper);
            },
            q1: () => {
                this.task.disableNext();
                this.task.guide(dom['response-wrapper']);
                const submitHandler = async () => {
                    const enteredText = this.responseInput.value;
                    const ok = await this.task.api('soundcheck', enteredText);
                    if (ok) {
                        this.fsa.event('response_correct');
                    } else {
                        // clear text field
                        this.responseInput.value = '';
                        alert(
                            'That did not match the audio clip. Please try again.');
                    }
                };
                this.submitBtn.disabled = false;
                this.submitBtn.addEventListener('click', submitHandler);
                this.responseInput.disabled = false;
                this.responseInput.focus();
                this.responseInput.addEventListener('keydown', async e => {
                    if (e.code === 'Enter') {
                        await submitHandler();
                    }
                });
            },
        
        };
    }



    q2() {
        dom['play-btn'].disabled = true;
        this.task.enableNext();
        dom['correct-msg'].style.display = 'block';
        this.submitBtn.disabled = true;
        this.responseInput.disabled = true;
    }

}

class Soundcheck extends Task {

    async reset() {
        await super.reset();

        //const player = dom['soundcheck-player'];
        const player = this.initPlayer(
            () => this.fsa.event('sound_ended'));
        if (player) {
            dom['play-btn'].addEventListener('click', () => player.play());
            const states = new States(this);
            this.fsa = new FSA(states);
            this.fsa.enter('q0');
        } else {
            dom['soundcheck-controls'].style.display = 'none';
            dom['soundcheck-format-error'].style.display = 'block';
        }
    }

    initPlayer(onended) {
        //const player = this.loadSound(sound);
        const player = new Audio(
            `{{ exp_audio }}/_soundcheck.mp3`);
        if (player.canPlayType('audio/mp3')) {
            player.addEventListener('play', () => {
                dom['play-btn'].disabled = true;
            });
            player.addEventListener('ended', () => {
                dom['play-btn'].disabled = false;
                if (onended) {
                    onended();
                }
            });
            return player;
        } else {
            return null;
        }
    }
}

export { Soundcheck as taskClass };
