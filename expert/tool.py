
import expert
from . import experiment


class Tool(experiment.BaseExper):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        @expert.socketio.on('prev_page', namespace=f'/{self.sid}')
        def sio_prev_page(resp):
            if self.task.prev_task:
                self.prev_task(resp)
            return self.all_vars()

        @expert.socketio.on('goto', namespace=f'/{self.sid}')
        def sio_goto(task_label, resp):
            self.go_to(task_label, resp)
            return self.all_vars()

        @expert.socketio.on('goto_id', namespace=f'/{self.sid}')
        def sio_goto_id(task_id, resp):
            self.go_to_id(task_id, resp)
            return self.all_vars()

    def assign_profile(self):
        super().assign_profile()
        self.variables['exp_nav_items'] = [
            label for label, task in self.nav_items()]

    def _store_resp(self, resp):
        super()._store_resp(resp)
        self.task.variables['exp_resp'] = resp

    def _nav(self, resp, dest_task):
        self._store_resp(resp)
        self.task = dest_task
        self.task_cursor = dest_task.id
        self._update_vars()
        if self.profile:
            self._save_responses()
        expert.socketio.emit('update_instance', self.status())

    def prev_task(self, resp):
        self._nav(resp, self.task.prev_task)

    def _next_task(self, resp):
        self._nav(resp, self.task.next_task(resp))

    def go_to(self, task_label, resp):
        dest_task = None
        for label, task in self.nav_items():
            if label == task_label:
                dest_task = task
                break
        self._nav(resp, dest_task)

    def go_to_id(self, task_id, resp):
        dest_task = self.tasks_by_id[task_id]
        self._nav(resp, dest_task)
