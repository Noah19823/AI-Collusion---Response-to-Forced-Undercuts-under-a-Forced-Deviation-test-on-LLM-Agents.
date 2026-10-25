"""Run selected unittest files with IP socket connects forbidden.

python tests/run_offline.py test_*integrity.py test_rho_identification.py
With no patterns, run the complete suite. HTTP MockTransport remains usable.
"""
from pathlib import Path
import socket
import sys
import unittest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'tests'))
original=socket.socket.connect
attempted=[]
def no_ip_connect(sock,address):
    if sock.family in (socket.AF_INET,socket.AF_INET6):
        attempted.append(str(address))
        raise AssertionError('IP network connections forbidden in offline verification')
    return original(sock,address)
socket.socket.connect=no_ip_connect
suite=unittest.TestSuite()
for pattern in sys.argv[1:] or ['test_*.py']:
    suite.addTests(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=pattern))
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(f'Offline network guard: {len(attempted)} attempted IP connects; no real provider calls permitted.')
raise SystemExit(0 if result.wasSuccessful() and not attempted else 1)
