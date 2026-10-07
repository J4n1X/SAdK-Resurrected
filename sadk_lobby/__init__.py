"""
sadk_lobby — a reverse-engineered stub of the Die Siedler: Aufbruch der Kulturen
(SAdK) online lobby server, speaking the original TinCat 3.0 / NETMSG protocol.

The wire protocol is data-driven from the game's own ``msgdefs.ini`` (copied from the game's ``bin``
folder into ``sadk_lobby/data/``; not distributed) via :mod:`sadk_lobby.msgdefs` + :mod:`sadk_lobby.codec`.
"""
__version__ = "0.4.0"
