
import random

from functools import cached_property

from . import globalparams


class Profile:

    def __init__(self, expercls, condition):
        self.expercls = expercls
        self.cond = condition
        self.subjid = self.make_subjid()
        self._used = False

    @property
    def used(self):
        return self._used

    @cached_property
    def fqname(self):
        return f'{self.cond}/{self.subjid}'

    def __str__(self):
        return self.fqname

    # abstract; subclass customizes inst with data
    # loaded from file
    @classmethod
    def load(cls, expercls, cond_str, subjid):
        inst = super().__new__(cls)
        inst.expercls = expercls
        inst.subjid = subjid
        inst.cond = expercls.cond_mod().conds[cond_str]
        inst._used = False
        return inst

    def save(self):
        pass

    def use(self):
        self._used = True

    def unuse(self):
        self._used = False

    def make_subjid(self):
        while True:
            subjid = ''
            for _ in range(globalparams.subjid_length):
                subjid += random.choice(globalparams.subjid_symbols)
            subjid_exists = False
            for c, profiles in self.expercls.profiles.items():
                if subjid in profiles:
                    subjid_exists = True
                    break
            if not subjid_exists:
                return subjid
