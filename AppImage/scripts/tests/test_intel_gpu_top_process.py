"""intel_gpu_top runs until it is told to stop, so the Monitor has to hold the
process itself: with a shell in between the signal never reaches it."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'flask_server.py'


class IntelGpuTopProcess(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        self.function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                             and node.name == 'get_detailed_gpu_info')

    def test_no_process_of_the_gpu_sampling_goes_through_a_shell(self):
        calls = [node for node in ast.walk(self.function) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'Popen']
        self.assertTrue(calls)
        for call in calls:
            self.assertNotIn('shell', [keyword.arg for keyword in call.keywords])

    def test_the_command_is_a_list(self):
        assigned = [node.value for node in ast.walk(self.function) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'cmd' for target in node.targets)]
        self.assertTrue(assigned)
        self.assertFalse([value for value in assigned if isinstance(value, ast.JoinedStr)])


if __name__ == '__main__':
    unittest.main()
