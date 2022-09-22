
import random

from functools import cached_property

import expert


class Profile:

    def __init__(self, condition):
        self.cond = condition
        self.subjid = self.make_subjid()

    @cached_property
    def fqname(self):
        return f'{self.cond}/{self.subjid}'

    def __str__(self):
        return self.fqname

    # abstract; subclass customizes inst with data
    # loaded from file
    @classmethod
    def load(cls, cond_str, subjid):
        inst = super().__new__(cls)
        inst.subjid = subjid
        inst.cond = expert.experclass.cond_mod().conds[cond_str]
        return inst

    def save(self):
        pass

    def make_subjid(self):
        while True:
            subjid = ''
            for _ in range(expert.experclass.cfg['subjid_length']):
                subjid += random.choice(expert.experclass.cfg['subjid_symbols'])
            if subjid not in [p.subjid for p in expert.experclass.profiles]:
                return subjid
