"""Successful-completion conditions represent jobs, not daemon liveness."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from proxmenux_oci.custom import template_from_compose
from proxmenux_oci.stack import assess,build_stack,DefaultsUI,ordered_services
from proxmenux_oci.installer import DEFAULT_MODE

COMPOSE='''services:
  app:
    image: example.org/application:3
    ports: ['8080:8080']
    depends_on:
      migration: {condition: service_completed_successfully}
    volumes: [storage:/data]
  migration:
    image: example.org/application:3
    command: [sh, -c, run-migrations]
    depends_on: [db]
    volumes: [storage:/data]
  db:
    image: postgres:16
    environment: {POSTGRES_PASSWORD: synthetic-only}
volumes:
  storage:
'''


class UI(DefaultsUI):
    def confirm(self,text,default=False):return True


class JobPlanning(unittest.TestCase):
    def test_job_order_completion_check_and_no_autostart(self):
        template=template_from_compose(COMPOSE,interpolated=True)
        self.assertEqual(assess(template),[])
        self.assertEqual([s['name'] for s in ordered_services(template)],['db','migration','app'])
        with patch('proxmenux_oci.installer.ask_storage',return_value='local-zfs'), \
             patch('proxmenux_oci.installer.ask_bridge',return_value='vmbr0'), \
             patch('proxmenux_oci.host.timezone',return_value='UTC'), \
             patch('proxmenux_oci.network.ask_addresses',return_value=({'app':'dhcp'},None)):
            plan=build_stack(template,UI(),DEFAULT_MODE)
        services={s['name']:s for s in plan['services']}
        self.assertEqual(services['migration']['healthcheck']['type'],'completed')
        self.assertEqual(services['migration']['deployment']['execution_mode'],'one-shot')
        self.assertFalse(services['migration']['deployment']['onboot'])
        self.assertTrue(services['app']['deployment']['onboot'])
        self.assertNotIn('frontend',services['migration'])
        shared=[m['source'] for name in ['app','migration'] for m in services[name]['deployment']['mounts'] if m['container_path']=='/data']
        self.assertEqual(len(set(shared)),1)

    def test_a_job_cannot_be_treated_as_a_continuously_healthy_daemon(self):
        template=template_from_compose(COMPOSE,interpolated=True)
        template['compose_stack']['services'][0]['compose'].setdefault('depends_on',{})
        main=next(s for s in template['compose_stack']['services'] if s['name']=='app')
        main['compose']['depends_on']['migration']['condition']='service_healthy'
        # Without a health check, a migration-like worker cannot satisfy healthy.
        self.assertTrue(assess(template))

    def test_auto_restart_of_successful_jobs_is_not_silently_enabled(self):
        template=template_from_compose(COMPOSE,interpolated=True)
        job=next(s for s in template['compose_stack']['services'] if s['name']=='migration')
        job['compose']['restart']='always'
        self.assertTrue(any('restart' in error for error in assess(template)))


if __name__=='__main__':unittest.main()
