"""Gabriel AI agent application.

The package is organized inward: ``contracts`` depend on nothing but the
standard library and a schema validator; ``kernel``, ``policy`` and
``planning`` depend on ``contracts``; ``state`` (the owner) depends on those
pure modules; ``tools``, ``workers``, ``models``, ``domains`` and
``interfaces`` depend on the owner but never receive a writable database.
"""

__version__ = "0.1.0"
PROTOCOL_COMMAND = "gabriel.command/1"
PROTOCOL_EVENT = "gabriel.event/1"
CODEC_VERSION = "gabriel.codec/1"
