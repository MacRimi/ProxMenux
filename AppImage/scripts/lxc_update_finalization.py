"""One process-wide LXC completion state, independent of Flask import name.

AppRun executes flask_server as __main__, while collectors import it as
flask_server. Both completion paths must share this canonical module so
the terminal hook and compatibility HTTP callback cannot consume a run twice.
No guest actions, registry writes or background tasks occur on import.
"""
import threading

lock = threading.RLock()
runs: dict[tuple[int, str], dict] = {}
