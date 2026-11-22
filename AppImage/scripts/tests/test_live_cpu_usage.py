"""The Overview's CPU figure covers the time since the previous request and
never touches the sampler's psutil.cpu_percent baseline."""
import ast
from collections import namedtuple
from pathlib import Path
import threading
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'flask_server.py'
NAMES = {'_LIVE_CPU_MIN_WINDOW', '_LIVE_CPU_MAX_WINDOW', '_live_cpu_usage'}
Times = namedtuple('Times', 'user nice system idle iowait irq softirq steal guest guest_nice')


class LiveCpuUsageTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SERVER.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body
                 if (isinstance(n, ast.FunctionDef) and n.name in NAMES)
                 or (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in NAMES for t in n.targets))]
        self.assertEqual(len(nodes), 3)
        self.clock = [100.0]
        self.samples = []
        test = self

        class FakePsutil:
            @staticmethod
            def cpu_times():
                return test.samples.pop(0)

            @staticmethod
            def cpu_percent(*args, **kwargs):
                raise AssertionError('the sampler owns psutil.cpu_percent')

        self.scope = {'psutil': FakePsutil, 'threading': threading,
                      'time': type('T', (), {'monotonic': staticmethod(lambda: test.clock[0])}),
                      '_live_cpu_lock': threading.Lock(),
                      '_live_cpu_state': {'times': None, 'at': 0.0, 'usage': None}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), 'exec'), self.scope)
        self.usage = self.scope['_live_cpu_usage']

    def advance(self, seconds, sample):
        self.clock[0] += seconds
        self.samples.append(sample)

    def test_first_call_leaves_the_figure_to_the_sampler(self):
        self.advance(0, Times(10, 0, 10, 80, 0, 0, 0, 0, 0, 0))
        self.assertIsNone(self.usage())

    def test_the_figure_is_the_share_of_busy_time_between_calls(self):
        self.advance(0, Times(10, 0, 10, 80, 0, 0, 0, 0, 0, 0))
        self.usage()
        self.advance(2, Times(40, 10, 20, 100, 0, 5, 5, 0, 20, 0))
        self.assertEqual(self.usage(), {'value': 75.0, 'user': 50.0, 'system': 25.0})

    def test_calls_within_the_minimum_window_share_the_last_result(self):
        self.advance(0, Times(0, 0, 0, 100, 0, 0, 0, 0, 0, 0))
        self.usage()
        self.advance(2, Times(50, 0, 0, 150, 0, 0, 0, 0, 0, 0))
        first = self.usage()
        self.clock[0] += 0.1
        self.assertEqual(self.usage(), first)
        self.assertEqual(self.samples, [])

    def test_an_old_snapshot_is_not_averaged_over(self):
        self.advance(0, Times(0, 0, 0, 100, 0, 0, 0, 0, 0, 0))
        self.usage()
        self.advance(600, Times(500, 0, 0, 200, 0, 0, 0, 0, 0, 0))
        self.assertIsNone(self.usage())
        self.advance(2, Times(500, 0, 0, 300, 0, 0, 0, 0, 0, 0))
        self.assertEqual(self.usage()['value'], 0.0)


if __name__ == '__main__':
    unittest.main()
