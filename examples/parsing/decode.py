"""
Decoding NEON into Python values, and what an error says.

Usage: uv run python examples/parsing/decode.py
"""

from textwrap import dedent

from neon import Date, Entity, NeonError, decode

config = decode(
    dedent("""\
        # a typical configuration
        application:
            debug: yes
            port: 0x1F90
            started: 2016-06-03 19:00:00 +02:00
            hosts: [alpha, beta]
        services:
            - Mailer(@smtp, timeout: 30)
        big: 12345678901234567890123
    """)
)

app = config["application"]
print("debug:  ", app["debug"])
print("port:   ", app["port"])
print("started:", isinstance(app["started"], Date), app["started"])
print("         ", repr(app["started"]))
print("hosts:  ", app["hosts"])
mailer = config["services"][0]
print("service:", isinstance(mailer, Entity), mailer)
print("big:    ", config["big"])

try:
    decode("a: 1\n  b: 2")
except NeonError as e:
    print()
    print(e.message, e.position)
    print(e)
