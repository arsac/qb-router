import asyncio
import time


async def until(condition_func, call_func, timeout_in_seconds, sleep=1):
    start_time = time.time()
    last_value = await call_func()

    while not condition_func(last_value):
        if time.time() - start_time > timeout_in_seconds:
            raise TimeoutError("Condition not met")
        last_value = await call_func()
        await asyncio.sleep(sleep)
    return last_value
