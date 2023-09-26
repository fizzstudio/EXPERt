
from typing import ClassVar, Type, Any

import expert as e
from .experiment import BaseExper, API
from .tasks import Task

class ToolAPI(API):

    def prev_page(self, resp: Any):
        if self._inst.task.prev_task:
            self._inst.prev_task(resp)
        return self._inst.all_vars()

    def goto(self, task_label: str, resp: Any):
        self._inst.go_to(task_label, resp)
        return self._inst.all_vars()

    def goto_id(self, task_id: int, resp: Any):
        self._inst.go_to_id(task_id, resp)
        return self._inst.all_vars()


class Tool(BaseExper):

    api_class: ClassVar[Type[API]] = ToolAPI

    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)

    #     @e.srv.socketio.on('prev_page', namespace=f'/{self.sid}')
    #     def sio_prev_page(resp):
    #         if self.task.prev_task:
    #             self.prev_task(resp)
    #         return self.all_vars()

    #     @e.srv.socketio.on('goto', namespace=f'/{self.sid}')
    #     def sio_goto(task_label, resp):
    #         self.go_to(task_label, resp)
    #         return self.all_vars()

    #     @e.srv.socketio.on('goto_id', namespace=f'/{self.sid}')
    #     def sio_goto_id(task_id, resp):
    #         self.go_to_id(task_id, resp)
    #         return self.all_vars()

    def _will_start(self):
        super()._will_start()
        self.variables['exp_nav_items'] = [
            label for label, task in self.nav_items()]

    def _store_resp(self, resp: Any):
        super()._store_resp(resp)
        self.task.variables['exp_resp'] = resp

    #def _nav(self, resp: Any, dest_task: Task):
    #    self._store_resp(resp)
    #    self.task = dest_task
    #    self.task_cursor = dest_task.id
    #    self._update_vars()
    #    #self._save_responses()
    #    e.srv.dboard.inst_updated(self)

    def prev_task(self, resp: Any):
        self._nav(resp, self.task.prev_task)

    #def next_task(self, resp: Any):
    #    self._nav(resp, self.task.next_task(resp))
    #    super().next_task(resp)

    def go_to(self, task_label: str, resp: Any):
        dest_task = None
        for label, task in self.nav_items():
            if label == task_label:
                dest_task = task
                break
        self._nav(resp, dest_task)

    def go_to_id(self, task_id: int, resp: Any):
        dest_task = self.tasks_by_id[task_id]
        self._nav(resp, dest_task)
