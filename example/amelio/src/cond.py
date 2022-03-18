

from dataclasses import dataclass
from functools import cached_property
from enum import Enum


class Group(Enum):
    A = 0
    B = 1


@dataclass(frozen=True)
class Cond:
    group: Group

    @cached_property
    def name(self):
        return f'{self.group.name}'

    def __str__(self):
        return self.name


conds = {}
for g in Group:
    c = Cond(g)
    conds[c.name] = c
del c
