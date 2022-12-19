
import logging

from pathlib import Path
from typing import Type, Optional, Union

from . import server, exper, tool


ver: str = ''
srv: server.Server
app: server.App
log: logging.Logger

Experiment: Union[Type[exper.Exper], Type[tool.Tool]] = exper.Exper

tool_mode = False
soundcheck_word = 'singapore'

experclass: Optional[Type[Experiment]] = None

# path to the EXPERt directory (remove 'expert/')
expert_path = Path(__file__).parent.parent.absolute()

bundle_name: Optional[str] = None
bundle_mods: list[str] = []
