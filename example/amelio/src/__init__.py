
import secrets
import random

from expert.experiment import Experiment, TaskResponse

from expert.tasks import Task, Consent, Soundcheck, TaskDesc

from expert import socketio

from . import params

from .trialtasks import RatingTask


# Your experiment class must be a subclass of expert.experiment.Experiment,
# but can have any name

class Amelio(Experiment):

    # Title for experiment browser window
    window_title = 'Nonsense word experiment'

    turk_codes = set()

    def __init__(self, *args):
        super().__init__(*args)

        # Example of generating a secure Mechanical Turk code
        # and storing it in the participant's responses

        while True:
            self.turk_code = secrets.token_urlsafe(16)
            if self.turk_code not in self.turk_codes:
                self.turk_codes.add(self.turk_code)
                break
        self.responses.append(
            TaskResponse(self.turk_code, 'TURK_CODE', ''))

        # The first task is created as an instance of the
        # Task class, and assigned to self.task;
        # the first argument is the participant's session ID,
        # and the second is the name of the template to display.
        # Subsequent tasks are added by chaining calls
        # to the .then() method.

        # .then() creates a new instance of the Task class
        # using the arguments it is given. Optionally, the first
        # argument may be a custom sublcass of Task.
        self.task = Task(self.sid, 'welcome')
        # Use built-in Consent class with custom 'consent' template
        (self.task.then(Consent, 'consent')
         #.then(Soundcheck)
         # Use Task class with custom template
         .then('instruct_qnaire')
         # 'qnaire' template receives 'questions' variable containing
         # questionnaire questions
         .then('qnaire', {'questions': params.qnaire_quests})
         .then('instruct_training')
         # Insert sequence of tasks
         .then_all(self.training_tasks()[:4])
         .then('instruct_main')
         .then_all(self.main_tasks()[:4])
         .then('exit_qnaire', {'questions': params.exit_qnaire_quests},
               # Disable main section timeout (set below)
               timeout_secs=-1)
         .then('thankyou', {'turk_code': self.turk_code}))

    def training_tasks(self):
        sounds = []
        with open(self.dir_path / 'stims-training.txt') as f:
            for line in f:
                sound, orth = line.rstrip().split('  ')  # 2 spaces
                sounds.append((sound, orth))
        random.shuffle(sounds)
        tasks = [TaskDesc([RatingTask, sound, orth])
                 for sound, orth in sounds]
        # Set show_prompt=True for first task
        tasks[0].kwargs['show_prompt'] = True
        return tasks

    def main_tasks(self):
        tasks = [TaskDesc([RatingTask, self.profile.stim_sounds[stim], stim])
                 for stim in self.profile.stims]
        # Set timeout for main experiment section
        tasks[0].kwargs['timeout_secs'] = params.timeout_secs
        return tasks
