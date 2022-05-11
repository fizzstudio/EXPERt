
from flask import (
    render_template
)
from flask_socketio import SocketIO


template_ext = '.html.jinja'
soundcheck_word = 'singapore'


def render(tplt, other_vars={}):
    all_vars = template_vars.copy()
    all_vars.update(other_vars)
    return render_template(tplt, **all_vars)
