
import argparse
import sys
import json
import re

from pathlib import Path
from typing import Optional, TypedDict

import argon2


class UserInfo(TypedDict):
    password: str
    lock_time: float
    login_failures: list[float]
    sid: Optional[str]

class Commands:
    bundle_path: Path

    def __init__(self, bundle_path: str) -> None:
        self.bundle_path = Path(bundle_path).resolve()

    def init_user_info(self):
        user_info_path = self.bundle_path / 'user_info.json'
        if user_info_path.is_file():
            sys.exit(f'{user_info_path} already exists')
        with open(user_info_path, 'w') as f:
            json.dump({}, f)

    def add_user(self, userid: str, password: str):
        user_info_path = self.bundle_path / 'user_info.json'
        if not user_info_path.is_file():
            sys.exit(f'{user_info_path} not found')
        # XXX should also reject overly long user IDs
        if not re.match( r'[a-zA-Z][a-zA-Z0-9_]*', userid):
            sys.exit('user ID must start with a letter,' +
                     ' and can only contain letters, digits, and' +
                     ' underscores')
        with open(user_info_path) as f:
            all_user_info: dict[str, UserInfo] = json.load(f)
        if userid in all_user_info:
            sys.exit(f'user \'{id}\' already exists')
        ph = argon2.PasswordHasher()
        hash = ph.hash(password)
        all_user_info[userid] = {'password': hash, 'lock_time': -1, 'login_failures': [], 'sid': None}
        with open(user_info_path, 'w') as f:
            json.dump(all_user_info, f, indent=2)


def parse_args():
    allargs = [
        ['cmd', {'help': 'command'}],
        ['bundle_path', {'help': 'path to experiment bundle folder'}],
        ['params', {'nargs': '*'}]
    ]
    parser = argparse.ArgumentParser()
    for arg in allargs:
        parser.add_argument(arg[0], **arg[1])
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    commands = Commands(args.bundle_path)
    try:
        cmd_func = getattr(commands, args.cmd)
    except:
        sys.exit(f'unrecognized command \'{args.cmd}\'')
    cmd_func(*args.params)
