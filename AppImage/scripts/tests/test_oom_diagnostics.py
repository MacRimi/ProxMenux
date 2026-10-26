#!/usr/bin/env python3
"""Regression tests based on LeidenSpain's real LXC OOM block."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxmox_known_errors import (  # noqa: E402
    analyze_oom_event,
    format_oom_diagnosis,
    get_error_context,
)


LXC_OOM = """
apt-get invoked oom-killer: gfp_mask=0x101cca, order=3, oom_score_adj=0
memory: usage 131056kB, limit 131072kB, failcnt 1922
swap: usage 0kB, limit 0kB, failcnt 0
Memory cgroup stats for /lxc/108:
oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=ns,mems_allowed=0,oom_memcg=/lxc/108,task_memcg=/lxc/108/ns/.lxc,task=apt-get,pid=1183877,uid=100000
Memory cgroup out of memory: Killed process 1183877 (apt-get) total-vm:79700kB, anon-rss:65056kB
"""


class OomDiagnosticsTest(unittest.TestCase):
    def test_lxc_memcg_scope_and_limits(self):
        result = analyze_oom_event(LXC_OOM)
        self.assertIsNotNone(result)
        self.assertEqual(result['scope'], 'lxc')
        self.assertEqual(result['ctid'], '108')
        self.assertEqual(result['constraint'], 'CONSTRAINT_MEMCG')
        self.assertEqual(result['memory_usage_kib'], 131056)
        self.assertEqual(result['memory_limit_kib'], 131072)
        self.assertEqual(result['swap_limit_kib'], 0)
        self.assertEqual(result['victim_process'], 'apt-get')
        self.assertEqual(result['victim_pid'], '1183877')

    def test_diagnosis_does_not_blame_host(self):
        diagnosis = format_oom_diagnosis(analyze_oom_event(LXC_OOM))
        self.assertIn('LXC 108', diagnosis)
        self.assertIn('not a host-wide OOM', diagnosis)
        self.assertIn('128.0 MiB used of 128.0 MiB', diagnosis)
        self.assertIn('Killed process: apt-get', diagnosis)

    def test_known_error_context_includes_event_evidence(self):
        context = get_error_context(LXC_OOM, category='memory', detail_level='detailed')
        self.assertIn('Event analysis:', context)
        self.assertIn('LXC 108 memory cgroup', context)


if __name__ == '__main__':
    unittest.main()
