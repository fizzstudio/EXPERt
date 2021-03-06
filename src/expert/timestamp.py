
import time


# Pad numbers with leading zeros to a fixed width
def pad(n, width):
    return format(n, f'0{width}')


def make_timestamp(hires=False):
    precise_time = time.time()
    seconds = int(precise_time)
    ltime = time.localtime(seconds)
    fields = [
        str(ltime.tm_year), pad(ltime.tm_mon, 2), pad(ltime.tm_mday, 2),
        pad(ltime.tm_hour, 2), pad(ltime.tm_min, 2), pad(ltime.tm_sec, 2),
    ]
    if hires:
        fields.append(str(precise_time - seconds)[2:])
    return '.'.join(fields)
