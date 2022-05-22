
from dataclasses import dataclass, field

from flask import render_template, current_app as app

import expert

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


class Task:

    template = ''

    def __init__(self, inst, template=None, variables=None, timeout_secs=None):
        self.inst = inst
        self.sid = inst.sid
        self.template_name = template or self.template
        self.template_filename = \
            f'task_{self.template_name}{expert.template_ext}'
        # if (exper.templates_path() / self.template_filename).is_file():
        #     self.template_filename = \
        #         f'{exper.name()}/{self.template_filename}'
        self.variables = variables.copy() if variables else {}
        #self.variables['debug'] = expert.debug
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

    def get_feedback(self, response):
        pass

    def all_vars(self):
        all_vars = expert.template_vars.copy()
        all_vars.update(self.inst.variables)
        all_vars.update(self.variables)
        return all_vars

    def render(self, tplt, tplt_vars={}):
        all_vars = self.inst.variables.copy()
        all_vars.update(self.variables)
        all_vars.update(tplt_vars)
        return expert.render(tplt, all_vars)

    def present(self, tplt_vars={}):
        return self.render(self.template_filename, tplt_vars)

    def then(self, *posargs, **kwargs):
        if isinstance(posargs[0], Task):
            task = posargs[0]
        else:
            if isinstance(posargs[0], type) and issubclass(posargs[0], Task):
                cls = posargs[0]
                posargs = posargs[1:]
            else:
                cls = Task
            task = cls(self.inst, *posargs, **kwargs)
        task.prev_task = self
        self.next_tasks.append(task)
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

    def next_task(self, response=None):
        if len(self.next_tasks) > 1:
            # response is an instance of experiment.TaskResponse
            # response.response is by default treated as an index
            return self.next_tasks[response.response]
        elif len(self.next_tasks) == 0:
            return None
        else:
            return self.next_tasks[0]

    def dummy_resp(self):
        return None


class Consent(Task):
    pass


class Soundcheck(Task):
    template = 'soundcheck'


class Thankyou(Task):
    template = 'thankyou'


class FinalTask(Task):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.variables['exp_progbar_enabled'] = False


class TimedOut(FinalTask):
    template = 'timedout'


class NonConsent(FinalTask):
    template = 'nonconsent'
