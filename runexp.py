
import expert
#from expert import tasks


if __name__ == '__main__':
    expert.init_server()

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
