#!/usr/bin/env python

import asyncio
import signal
import websockets
import time


connections = {}
occupied_sockets = []
kill_time = {}
kill_tasks = {}


# After this amount of time if the user doesn't send any request to the server they automatically get disconnected.
timeout_sec = 45
# Delay between each request sent to the server
req_delay = 0.5
# The maximum number of times user can violate request delay before they get disconnected
max_delay_violation = 10
# The maximum number of times user can get away with violating request delay
ignore_delay_violation = 5


def err(err_msg):
    return "ERR: " + err_msg

def get_msg_params(msg):
    splitted = msg.split(" ")
    splitted.pop(0)
    return splitted

async def kill_timer(websocket):
    while True:
        # (?) await let other coroutines have a chance to run
        # "create_task() submits the coroutine to run "in the background",
        # i.e. concurrently with the current task and all other tasks, switching between them at await points."
        await asyncio.sleep(0)
        if time.time() - kill_time[websocket] >= timeout_sec:
            return await cb_quit(websocket)

async def cancel_death(func, websocket, *args):
    kill_time[websocket] = time.time()
    return await func(websocket, *args)

async def cb_quit(websocket):
    if websocket in occupied_sockets:
      occupied_sockets.remove(websocket)
        
    for point_name, point in dict(connections).items():
        if point["controller"] == websocket:
            point["controller"] = None
            point["occupied"] = False
            kill_tasks[websocket].cancel()
            del kill_time[websocket]
        elif point["point"] == websocket:
            if point["controller"] != None and point["occupied"] == True:
                occupied_sockets.remove(point["controller"])
                kill_tasks[point["controller"]].cancel()
                del kill_time[point["controller"]]
                await point["controller"].send(err("Connection closed by point. Press any key to continue"))
            kill_tasks[websocket].cancel()
            del kill_time[websocket]

            del connections[point_name]



async def cb_send(websocket, params):
    point_name = params[0]
    if not (point_name in connections):
        await websocket.send(err("point doesn't exist."))
        return

    point = connections[point_name]
    if point["occupied"] == False:
        await websocket.send(err("No one has joined point yet."))
        return

    if point["controller"] != websocket:
        await websocket.send(err("you are NOT him."))
        return

    point["actions"].append(" ".join(params[1:]))
    await websocket.send("Sent action")



async def cb_get(websocket, params):
    point_name = params[0]
    if not (point_name in connections):
        await websocket.send(err("point doesn't exist."))
        return

    point = connections[point_name]
    if point["occupied"] == False:
        await websocket.send(err("No one has joined point yet."))
        return

    if point["point"] != websocket:
        await websocket.send(err("you are NOT him."))
        return

    if not point["actions"]:
        await websocket.send(err("action list is empty."))
        return

    await websocket.send(point["actions"].pop(0))



async def cb_set_point(websocket, params):
    if websocket in occupied_sockets:
      await websocket.send(err("You cannot perform set/join point operations."))
      return

    point_name = params[0]
    if point_name == "" or len(point_name) <= 2 or len(point_name) > 32:
        await websocket.send(err("Invalid point name length."))
        return
    if point_name in connections:
        await websocket.send(err("point has already been set."))
        return

    connections[point_name] = {"point": websocket, "occupied": False, "controller": None, "actions": []}
    occupied_sockets.append(websocket)
    await websocket.send("Point set on: " + point_name)



async def cb_join_point(websocket, params):
    if websocket in occupied_sockets:
      await websocket.send(err("You cannot perform set/join point operations."))
      return

    point_name = params[0]
    if not (point_name in connections) or connections[point_name]["occupied"] == True:
        await websocket.send(err("point doesn't exist or has already been occupied."))
        return

    connections[point_name]["controller"] = websocket
    connections[point_name]["occupied"] = True
    occupied_sockets.append(websocket)
    await websocket.send("Joined point: " + point_name)


async def handler(websocket):
    kill_time[websocket] = time.time()
    kill_tasks[websocket] = asyncio.create_task(kill_timer(websocket))
    last_msg_time = time.time()
    delay_violation = 0
    delay_violation_multiplier = 1

    async for msg in websocket:
        if kill_tasks[websocket].done():
            del kill_tasks[websocket]
            await websocket.send(err("Connection closed."))
            break


        if time.time() - last_msg_time <= req_delay * delay_violation_multiplier:
            delay_violation += 1
            if delay_violation >= max_delay_violation:
                await websocket.send(err("Too many requests."))
                break
            elif delay_violation >= ignore_delay_violation:
                delay_violation_multiplier += 5
                await websocket.send(err("You are sending requests too fast! Time before you can OPEN YOUR MOUTH to SPEAK again: " + str(req_delay * delay_violation_multiplier)))
                continue
        else: # If bro is a law-abiding citizen
            delay_violation = 0
            delay_violation_multiplier = 1


        if msg.startswith("quit"):
            await cb_quit(websocket)
            break

        params = get_msg_params(msg)
        if len(params) == 0:
            await websocket.send(err("invalid number of parameters"))
            continue

        if msg.startswith("send"):         await cancel_death(cb_send,       websocket, params)
        elif msg.startswith("get"):        await cancel_death(cb_get,        websocket, params)
        elif msg.startswith("set-point"):  await cancel_death(cb_set_point,  websocket, params)
        elif msg.startswith("join-point"): await cancel_death(cb_join_point, websocket, params)
        else:                              await websocket.send(err("invalid request"))

        last_msg_time = time.time()


async def main():
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    async with websockets.serve(handler, "", 8001):
        await stop  # run forever


if __name__ == "__main__":
    asyncio.run(main())
