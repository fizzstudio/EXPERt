
from expert.tasks import Task


# Abstract base class for all trial tasks types
class TrialTask(Task):

    def __init__(self, inst, variables=None, timeout_secs=None):
        super().__init__(inst, variables=variables, timeout_secs=timeout_secs)


class RatingTask(TrialTask):

    template = 'rating'

    def __init__(
            self, inst, sound, orth, show_prompt=False, timeout_secs=None):
        super().__init__(inst, timeout_secs=timeout_secs)
        self.variables['sound'] = sound
        self.variables['orth'] = orth
        self.variables['show_prompt'] = show_prompt
        # save the sound and orthography in the participant response
        self.resp_extra = f'{sound}:{orth}'
