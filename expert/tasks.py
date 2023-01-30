
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Any, Optional

from flask import current_app as app

import expert as e

from . import view

# A Task represents a single page with some activity to be
# performed. Examples range from reading
# a page of text and clicking Next, to responding to a question
# during a trial.

# Every Task has a list of Tasks that may follow it.
# If this list has more than one item, by default,
# the next task to move to is selected by taking the response
# from the previous task as an index into the next_tasks list.

@dataclass(frozen=True)
class TaskDesc:
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)


class Task(view.View):

    template: ClassVar[str] = ''

    inst: e.Experiment
    template_name: str
    variables: dict[str, Any]
    prev_task: Optional[Task]
    next_tasks: list[Task]
    timeout_secs: Optional[int]
    resp_extra: dict[str, Any]
    id: int

    @classmethod
    def new(cls, inst, *posargs, **kwargs):
        if isinstance(posargs[0], type) and issubclass(posargs[0], Task):
            cls = posargs[0]
            posargs = posargs[1:]
        else:
            cls = Task
        return cls(inst, *posargs, **kwargs)

    @classmethod
    def reify(cls, inst, desc):
        return cls.new(inst, *desc.args, **desc.kwargs)

    def __init__(self, inst, template=None, variables=None, timeout_secs=None):
        super().__init__(template=template, variables=variables)
        self.inst = inst
        self.sid = inst.sid
        self.variables['task_type'] = self.template_name
        self.prev_task = None
        self.next_tasks = []
        self.timeout_secs = timeout_secs
        # extra fields to be added to each participant response
        self.resp_extra = {}
        self.inst.num_tasks_created += 1
        # default ID for the very first task;
        # will get changed if this task becomes one of
        # 'next_tasks' for another task;
        # the ID determines the order task results are saved
        self.id = self.inst.num_tasks_created
        self.inst.tasks_by_id[self.id] = self

    def get_feedback(self, response):
        pass

    def template_filename(self):
        return 'task_' + super().template_filename()

    def render_vars(self):
        all_vars = self.inst.variables.copy()
        all_vars.update(super().render_vars())
        return all_vars

    def then(self, *posargs, **kwargs):
        if isinstance(posargs[0], Task):
            task = posargs[0]
        else:
            task = self.new(self.inst, *posargs, **kwargs)
        task.prev_task = self
        self.next_tasks.append(task)
        if len(self.next_tasks) > 1:
            self.inst.last_task = None
        else:
            self.inst.last_task = task
        task.was_added()
        return task

    def then_all(self, task_descriptors):
        cursor = self
        for task in task_descriptors:
            #if isinstance(task, (list, tuple)):
            if isinstance(task, TaskDesc):
                cursor = cursor.then(*task.args, **task.kwargs)
                #if isinstance(task[-1], dict):
                #    cursor = cursor.then(*task[:-1], **task[-1])
                #else:
                #    cursor = cursor.then(*task)
            else:
                cursor = cursor.then(task)
        return cursor

    def was_added(self):
        pass

    def next_task(self, response=None):
        if len(self.next_tasks) > 1:
            # response is an instance of experiment.TaskResponse
            # response.response is by default treated as an index
            return self.next_tasks[response.response]
        elif len(self.next_tasks) == 0:
            return None
        else:
            return self.next_tasks[0]

    def replace_next_task(self, task):
        self.next_tasks[:] = [task]

    def dummy_resp(self):
        return None


class NoProgbarTask(Task):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.variables['exp_progbar_enabled'] = False


class NoReturnTask(Task):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.variables['exp_no_return_task'] = True


class IncompleteTask(NoProgbarTask, NoReturnTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class Welcome(NoProgbarTask):
    pass


class Consent(NoProgbarTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inst.has_consent_task = True

    def next_task(self, resp):
        if resp == 'consent_declined':
            app.logger.info(f'sid {self.inst.sid[:4]} declined consent')
            return NonConsent(self.inst)
        else:
            self.inst.assign_profile()
            return self.next_tasks[0]


class Soundcheck(Task):
    template = 'soundcheck'


class Thankyou(NoReturnTask):
    template = 'thankyou'


class TimedOut(IncompleteTask):
    template = 'timedout'


class ReturnedSurvey(IncompleteTask):
    template = 'returned'


class Terminated(IncompleteTask):
    template = 'terminated'


class NonConsent(IncompleteTask):
    template = 'nonconsent'
