
from dataclasses import dataclass, field

from flask import render_template, current_app as app

from . import cfg

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

    # set by runexp.py to the concrete class of the experiment
    #experclass = None

    def __init__(self, inst, template=None, variables=None, timeout_secs=None):
        self.inst = inst
        self.sid = inst.sid
        self.template_name = template or self.template
        self.template_filename = \
            f'task_{self.template_name}{cfg.template_ext}'
        # if (exper.templates_path() / self.template_filename).is_file():
        #     self.template_filename = \
        #         f'{exper.name()}/{self.template_filename}'
        self.variables = variables.copy() if variables else {}
        self.variables['debug'] = cfg.debug
        self.variables['prolific_pid'] = inst.prolific_pid
        if inst.prolific_pid:
            self.variables['prolific_completion_url'] = \
                cfg.prolific_completion_url
        self.variables['exper'] = inst.name
        self.variables['expercss'] = \
            f'/expert/{inst.name}/css/main.css'
        self.variables['window_title'] = inst.window_title
        self.variables['sid'] = self.sid
        self.variables['task_type'] = self.template_name
        self.prev_task = None
        self.next_tasks = []
        self.timeout_secs = timeout_secs
        # extra data to be added to each participant response
        self.resp_extra = None

    def get_feedback(self, response):
        pass

    def present(self, tplt_vars={}):
        all_vars = self.variables.copy()
        all_vars.update(tplt_vars)
        return render_template(self.template_filename, **all_vars)

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


# This class exists essentially to flag the task
# so that the server can take the appropriate actions
# when the agree-or-disagree response arrives
class Consent(Task):
    pass


class Soundcheck(Task):

    template = 'soundcheck'


class Thankyou(Task):

    template = 'thankyou'
