
import argparse

import expert
from expert import server


def parse_args():
    allargs = [
        [['-e', '--exper_path'], {'help': 'path to experiment bundle folder'}],
        [['-f', '--config'], {'help': 'path to server config file'}],
        [['-l', '--listen'], {
            'help': 'hostname/IP address (:port) for server to listen on'}],
        (
            [['-t', '--tool'], {
                'action': 'store_true',
                'help': 'run in tool mode'}],
            [['-D', '--dummy'], {
                'type': int,
                'help': 'perform a dummy run with the given instance count'}]
        ),
        (
            [['-r', '--resume'], {
                'help': 'timestamp of experiment run to resume'}],
            [['-p', '--replicate'], {
                'help': 'timestamp of experiment run to replicate'}],
            [['-c', '--conditions'], {
                'help': 'comma-separated (no spaces) list of' +
                ' conditions from which to choose all profiles'}]
        )
    ]
    parser = argparse.ArgumentParser()
    for arg in allargs:
        if isinstance(arg, list):
            parser.add_argument(*arg[0], **arg[1])
        else:
            mutexgrp = parser.add_mutually_exclusive_group()
            for mutex_arg in arg:
                mutexgrp.add_argument(*mutex_arg[0], **mutex_arg[1])
    return parser.parse_args()


if __name__ == '__main__':
    expert.srv = server.Server(parse_args())
    expert.srv.start()

    # if expert.debug:
    #     # route for testing task views
    #     @app.route(f'/{cfg["url_prefix"]}/task/<task>')
    #     def showtask(task):
    #         taskvars = {}
    #         for k, v in request.args.items():
    #             if v.startswith('params:'):
    #                 taskvars[k] = getattr(experparams, v[7:])
    #             else:
    #                 taskvars[k] = v
    #         taskvars['_debug'] = True

    #         t = tasks.Task(None, task, taskvars)

    #         @socketio.on('init_task', namespace='/debug')
    #         def sio_init_task():
    #             return taskvars

    #         @socketio.on('get_feedback', namespace='/debug')
    #         def sio_get_feedback(resp):
    #             return eval(taskvars['fbackval'])

    #         return t.present()
