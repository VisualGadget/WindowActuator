import machine
import time


WDT_ENABLE = False  # Watchdog timer


if WDT_ENABLE:
    print('using watchdog')
    wdt_class = machine.WDT
else:
    # fake watchdog
    class WDT:
        def feed(self):
            pass
    wdt_class = WDT


watchdog = wdt_class()  # global use instance


def sleep_s(interval: int):
    """
    Sleep and feed watchdog

    :param interval: interval, s
    """
    watchdog.feed()
    for _ in range(interval):
        time.sleep(1)
        watchdog.feed()


def retry_on_error(func):
    """
    Decorator to make a function robust by catching all exceptions and retry call attempt
    """
    def looped_call(*args, **kwargs):
        n = 1
        while True:
            if n > 1:
                print(f'Attempt #{n}')
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if n > 50:
                    raise e
                print(f'Function {str(func)} failed {n} times')
                sleep_s(n)
                n += 1

    return looped_call
