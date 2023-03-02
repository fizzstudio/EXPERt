
from __future__ import annotations

from typing import ClassVar, Any

#import expert as e
from . import templates


class View:

    template: ClassVar[str] = ''

    template_name: str
    variables: dict[str, Any]

    def __init__(self, template: str | None = None, variables: dict[str, Any] | None = None):
        self.template_name = template or self.template
        # if (exper.templates_path() / self.template_filename).is_file():
        #     self.template_filename = \
        #         f'{exper.name()}/{self.template_filename}'
        self.variables = variables.copy() if variables else {}
        # self.variables['debug'] = expert.debug

    def template_filename(self):
        return f'{self.template_name}{templates.html_ext}'

    def render_vars(self):
        return self.variables.copy()

    def render(self, tplt: str, tplt_vars: dict[str, Any] = {}):
        all_vars = self.render_vars()
        all_vars.update(tplt_vars)
        return templates.render(tplt, all_vars)

    def present(self, tplt_vars: dict[str, Any] = {}):
        return self.render(self.template_filename(), tplt_vars)
