"""A security finding of the health monitor (an expiring certificate, a long
uptime, many failed logins in a day, Fail2Ban bans) is reported as a health
issue with its reason, not as a single failed login with empty fields."""
import ast
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'AppImage/scripts'


def literal(module, name):
    """A dict literal assigned to `name` in the module or in one of its classes."""
    for node in ast.walk(ast.parse((SCRIPTS / module).read_text())):
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f'{name} not found in {module}')


class SecurityHealthNotificationTests(unittest.TestCase):
    def setUp(self):
        self.direct = literal('notification_events.py', '_CATEGORY_TO_EVENT_TYPE')
        self.linked = literal('notification_templates.py', '_HEALTH_CATEGORY_EVENTS')
        self.templates = literal('notification_templates.py', 'TEMPLATES')

    def test_security_findings_are_health_issues(self):
        self.assertEqual(self.direct['security'], 'health_issue_new')
        self.assertEqual(self.linked['security'], 'health_issue_new')

    def test_the_health_issue_carries_the_reason_and_no_login_fields(self):
        template = self.templates['health_issue_new']
        text = template['title'] + template['body']
        self.assertIn('{reason}', text)
        for field in ('{source_ip}', '{username}', '{service}'):
            self.assertNotIn(field, text)

    def test_both_maps_agree_on_every_category(self):
        for category, event_type in self.linked.items():
            self.assertEqual(self.direct.get(category), event_type, category)


if __name__ == '__main__':
    unittest.main()
