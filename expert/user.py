
import time
import json
import secrets

from typing import TypedDict, Optional

import argon2

import expert as e

NOT_LOCKED = -1
LOCK_DURATION = 30*60 # 30 minutes in seconds
LOCK_CRITERIA = {'failures': 4, 'within': 60*5}

ph = argon2.PasswordHasher()

class UserError(Exception):
    msg: str
    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.msg = msg

class UserInfo(TypedDict):
    password: str
    lock_time: float
    login_failures: list[float]
    sid: Optional[str]


def load_all_user_info() -> dict[str, UserInfo]:
    user_info_path = e.experclass.dir_path / 'user_info.json'
    with open(user_info_path) as f:
        return json.load(f)

def save_all_user_info(all_user_info: dict[str, UserInfo]):
    user_info_path = e.experclass.dir_path / 'user_info.json'
    with open(user_info_path, 'w') as f:
        json.dump(all_user_info, f, indent=2)

def update_user_info(userid: str, password: Optional[str] = None, 
                     lock_time: Optional[float] = None):
    all_user_info = load_all_user_info()
    if userid not in all_user_info:
        raise UserError(f'unknown user \'{userid}\'')
    if password is not None:
        all_user_info[userid]['password'] = password
    if lock_time is not None:
        all_user_info[userid]['lock_time'] = lock_time
    save_all_user_info(all_user_info)

def create_sid():
    return secrets.token_urlsafe(16)


class User:
    userid: str
    password: str
    lock_time: float
    login_failures: list[float]
    #sid: Optional[str]

    def __init__(self, userid: str, info: UserInfo):
        self.userid = userid
        self.password = info['password']
        self.lock_time = info['lock_time']
        self.login_failures = info['login_failures']
        #self.sid = info['sid']
        
    def save_info(self):
        all_user_info = load_all_user_info()
        if self.userid not in all_user_info:
            raise UserError(f'no info for user \'{self.userid}\'')
        all_user_info[self.userid]['password'] = self.password
        all_user_info[self.userid]['lock_time'] = self.lock_time
        all_user_info[self.userid]['login_failures'] = self.login_failures
        #all_user_info[self.userid]['sid'] = self.sid
        save_all_user_info(all_user_info)

    @property
    def locked(self):
        return self.lock_time != NOT_LOCKED

    def try_unlock(self, now: float):
        if now - self.lock_time < LOCK_DURATION:
            e.log.info(f'account \'{self.userid}\' is locked')
            return False
        else:
            e.log.info(f'account \'{self.userid}\' lock period expired; unlocking')
            self.lock_time = NOT_LOCKED
            self.save_info()
            return True

    def lock(self, now: float):
        self.lock_time = now
        self.clear_login_failures()

    def record_login_failure(self, now: float):
        self.login_failures.append(now)
        self.save_info()

    def clear_login_failures(self):
        self.login_failures = []
        self.save_info()

    def prune_login_failures(self, now: float):
        # Prune any failures older than LOCK_CRITERIA.within
        self.login_failures = [t for t in self.login_failures 
                               if t > now - LOCK_CRITERIA['within']]
        self.save_info()
        return len(self.login_failures)


class SessionManager:
    sessions: dict[str, User]

    def __init__(self) -> None:
        self.sessions = {}
        all_user_info = load_all_user_info()
        for userid, info in all_user_info.items():
            sid = info.get('sid')
            if sid is not None:
                self.sessions[sid] = User(userid, info)

    def login(self, userid: str, password: str):
        # sec as float since midnight 01/01/1970
        now = time.time()

        #if not username or not password:
        #    throw new UserError('user ID and/or password not provided');
        e.log.info(f'login attempt for user \'{userid}\'')

        all_user_info = load_all_user_info()
        info = all_user_info.get(userid)
        if not info:
            e.log.info(f'no such user \'{userid}\'')
            raise UserError('login failed')

        user = User(userid, info)

        if user.locked and not user.try_unlock(now):
            raise UserError(f'account for user \'{userid}\' is locked')

        e.log.info('checking password ...')
        try:
            ph.verify(user.password, password)
            e.log.info(f'user \'{userid}\' login successful')
            if ph.check_needs_rehash(user.password):
                update_user_info(userid, password=ph.hash(password))
            user.clear_login_failures()
            assert e.experclass and e.experclass.record
            sid = e.experclass.record.lookup_user_sid(userid)
            #if not user.sid:
            if not sid:
                sid = create_sid()
                #user.save_info()
            self.sessions[sid] = user
            return sid
        except argon2.exceptions.VerificationError:
            e.log.info('login failed')
            prev_failures = user.prune_login_failures(now)
            # current failure counts against the limit
            if prev_failures + 1 == LOCK_CRITERIA['failures']:
                e.log.info(f'{LOCK_CRITERIA["failures"]} login failures in' +
                        f' {LOCK_CRITERIA["within"]} seconds;' +
                        f' locking account \'{userid}\'')
                user.lock(now)
                raise UserError('too many login failures')
            else:
                e.log.info(
                    f'{prev_failures + 1}/{LOCK_CRITERIA["failures"]}' +
                    ' allowed login failures before account lock')
                user.record_login_failure(now)
                raise UserError('login failed')
            
    def sessionIsActive(self, sid: str):
        return sid in self.sessions



