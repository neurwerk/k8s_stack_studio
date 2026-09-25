"""Check a simulator's own listening socket without making a workload request."""

import socket
import sys

with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=2):
    pass
