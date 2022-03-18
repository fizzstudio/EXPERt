
# **************************************************
# Profile
#
# Contains ordered stimuli to be presented to a
# single subject as they progress through the
# experiment.
# **************************************************

import random

from expert import profile


class Profile(profile.Profile):

    def __init__(self, expercls, condition):
        super().__init__(expercls, condition)
        self.load_stim_sounds()
        self.stims = list(self.stim_sounds.keys())
        random.shuffle(self.stims)

    @classmethod
    def load(cls, expercls, cond_str, subjid):
        inst = super().load(expercls, cond_str, subjid)
        with open(expercls.profiles_path / cond_str / subjid) as f:
            inst.stims = [line.rstrip() for line in f]
            inst.load_stim_sounds()
        return inst

    def load_stim_sounds(self):
        self.stim_sounds = {}
        # 'D' stims are the distractors, shared by conds A and B
        for fname in [self.cond.group.name, 'D']:
            with open(self.expercls.dir_path / f'stims-{fname}.txt') as f:
                for line in f:
                    sound, orth = line.rstrip().split('  ')  # 2 spaces
                    self.stim_sounds[orth] = sound

    def save(self):
        fname = self.expercls.profiles_path / str(self.cond) / self.subjid
        with open(fname, 'w') as f:
            for s in self.stims:
                print(s, file=f)
