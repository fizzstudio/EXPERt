
from typing import ClassVar, Any, Optional

from . import templates


class View:

    template: ClassVar[str] = ''

    template_name: str
    template_filename: str
    variables: dict[str, Any]

    def __init__(self, template=None, variables=None):
        self.template_name = template or self.template
        self.template_filename = \
            f'task_{self.template_name}{templates.html_ext}'
        # if (exper.templates_path() / self.template_filename).is_file():
        #     self.template_filename = \
        #         f'{exper.name()}/{self.template_filename}'
        self.variables = variables.copy() if variables else {}
        # self.variables['debug'] = expert.debug

    def render_vars(self):
        return self.variables.copy()

    def render(self, tplt, tplt_vars={}):
        all_vars = self.render_vars()
        all_vars.update(tplt_vars)
        return templates.render(tplt, all_vars)

    def present(self, tplt_vars={}):
        return self.render(self.template_filename, tplt_vars)
