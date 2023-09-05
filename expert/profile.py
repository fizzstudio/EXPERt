
import random

from functools import cached_property

import expert as e


class Profile:
    subjid: str

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
    def load(cls, cond_str: str, subjid: str):
        inst = super().__new__(cls)
        inst.subjid = subjid
        inst.cond = e.experclass.cond_mod().conds[cond_str]
        return inst

    def save(self):
        pass

    def make_subjid(self) -> str:
        while True:
            subjid = ''
            for _ in range(e.experclass.cfg['subjid_length']):
                subjid += random.choice(e.experclass.cfg['subjid_symbols'])
            if subjid not in [p.subjid for p in e.experclass.profiles]:
                return subjid
