#!/usr/bin/env python3
import os
import http.server
import json
import urllib.parse
import numpy
import pandas
from serial import Serial
import time
from threading import Thread
from queue import Queue, Empty


SERIAL_DEVICE = "/dev/ttyUSB0"
SERIAL_RATE = 9600
HTTP_HOST = '127.0.0.1'
HTTP_PORT = 8000

ROOT = os.path.dirname(os.path.realpath(__file__))
WEBROOT = os.path.join(ROOT, "webroot")


class Arduino:
    def __init__(self):
        self.pipe = None
        self.thread = Thread(target=self.interact)
        self.sendq = Queue()
        self.recvq = Queue()
        self.state = {}

    def log_filename(self, key):
        return os.path.join(ROOT, 'log', key)

    def log_value(self, key, value):
        with open(self.log_filename(key), "a") as f:
            f.write("{} {}\n".format(time.time(), value))

    def interact(self):
        serial = Serial(SERIAL_DEVICE, SERIAL_RATE)
        while True:
            try:
                while True:
                    cmd = self.sendq.get(block=False)
                    print("DEBUG COMMAND:", cmd)
                    serial.write(cmd.encode('ascii'))
                    serial.write(b'\n')
            except Empty:
                pass
            key, value = serial.readline().decode('ascii').strip().split(' ')
            print(key, value)
            #key, value = 'temp 18'.split(' ')
            value = int(value)
            self.log_value(key, value)
            self.state[key] = value
            self.recvq.put((key, value))

    def start(self):
        self.thread.start()

    def get(self, key):
        return self.state.get(key, None)

    def set(self, key, value):
        self.sendq.put("{} {}".format(key, int(value)))
        return value

    def timeseries(self, name, start, end=None, resolution=None):
        if end is None:
            end = time.time()
        start = float(start)
        end = float(end)

        log = pandas.read_csv(self.log_filename(name), sep=' ', names=('time', 'value'))
        value = log.value
        value.index = pandas.to_datetime(log.time, unit='s')
        if resolution is not None:
            value = value.resample('{}s'.format(resolution))

        return {
            'time': [t.timestamp() for t in value.index],
            'value': [int(x) for x in value],
        }




ARDUINO = Arduino()

class Handler(http.server.SimpleHTTPRequestHandler):
    def respond(self, code, value):
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(value, indent=4).encode('utf-8') + b'\n')

    def error(self, code, reason):
        self.respond(code, {"ok": False, "error": reason})

    def ok(self, value):
        self.respond(200, {"ok": True, "value": value})

    def do_GET(self):
        if not self.path.startswith('/rpc/'):
            return super().do_GET()
        return self.rpc(action='GET')

    def do_PUT(self):
        if not self.path.startswith('/rpc/'):
            return super().do_PUT()
        return self.rpc(action='PUT')

    def rpc(self, action):
        try:
            path = urllib.parse.urlparse(self.path)
            params = dict(urllib.parse.parse_qsl(path.query))

            try:
                components = path.path.strip('/').split('/')
                name = components[1]
                if action == "GET":
                    if name == 'series':
                        name = components[2]
                        return self.ok(ARDUINO.timeseries(name, **params))
                    else:
                        return self.ok(ARDUINO.get(name))
                else:
                    try:
                        value = int(params['value'])
                        return self.ok(ARDUINO.set(name, value))
                    except KeyError as e:
                        return self.error(400, "No value given.")
                    except ValueError as e:
                        return self.error(400, "Invalid number: {}".format(params['value']))
            except IndexError as e:
                return self.error(400, "{}".format(e))
            except TypeError as e:
                return self.error(400, "{}".format(e))
        except:
            self.error(501, "Internal server error.")
            raise


def main():
    os.chdir(WEBROOT)
    httpd = http.server.HTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    print("Serving on http://0.0.0.0:8000")
    ARDUINO.start()
    httpd.serve_forever()


if __name__ == "__main__":
    main()
