"""Behavioral boundaries for ended model turns and retained runtime notices."""
import threading
import unittest
from unittest.mock import patch

from oasis_harness import workflows
from oasis_harness.common import HarnessError, operation_lock, read_json
from tests import test_workflows as fixtures


class WaitingContracts(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowContracts()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.native = self.fixture.root, self.fixture.native

    def test_submission_never_wakes_before_actual_final_and_duplicate_does_not_wake(self):
        row = self.fixture.assign()
        native, turn = self.fixture.pending_native_turn(row)
        submitted = self.fixture.complete(row)
        self.assertEqual(submitted['phase'], 'awaiting_terminal')
        self.assertEqual(self.native.sent, 1)
        cache = {}
        workflows.notification_step(self.root, self.native, cache=cache)
        self.assertEqual(self.native.sent, 1)
        self.fixture.finish_native_turn(native, turn)
        ready = workflows.notification_step(self.root, self.native, changed_threads={native['id']}, cache=cache)
        self.assertFalse(ready['pending'])
        self.assertEqual(self.native.sent, 2)
        workflows.notification_step(self.root, self.native, cache={})
        self.assertEqual(self.native.sent, 2)
        self.assertFalse(native['archived'])

    def test_journal_only_event_reuses_unchanged_observations(self):
        row = self.fixture.assign()
        self.fixture.pending_native_turn(row)
        self.fixture.complete(row)
        cache = {}
        workflows.notification_step(self.root, self.native, cache=cache)
        before = self.native.methods().count('thread/turns/list')
        for _ in range(100):
            workflows.notification_step(self.root, self.native, changed_threads=set(), cache=cache)
        self.assertEqual(self.native.methods().count('thread/turns/list'), before)
        self.assertEqual(self.native.sent, 1)

    def test_full_assignment_wait_reuses_notice_and_never_adds_confirmation_turn(self):
        row = self.fixture.assign()
        native, turn = self.fixture.pending_native_turn(row)
        before = list(self.native.calls)
        wait = workflows.dependency_wait(self.root, native['id'], row['cameleer_thread_id'], 'whole assignment', factory=self.native)
        self.assertEqual(self.native.calls, before)
        self.assertEqual(wait['subscription'], 'assignment')
        self.fixture.complete(row)
        self.fixture.finish_native_turn(native, turn)
        workflows.notification_step(self.root, self.native)
        self.assertEqual(self.native.sent, 2)
        workflows.collect(self.root, row['id'], factory=self.native)
        before = list(self.native.calls)
        for _ in range(2):
            result = workflows.dependency_finish(self.root, wait['id'], result='same completed assignment', factory=self.native)
            self.assertFalse(result['end_turn'])
        workflows.notification_step(self.root, self.native)
        self.assertEqual(self.native.calls, before)
        self.assertEqual(self.native.sent, 2)

    def test_partial_parent_wait_other_consumer_and_new_cycle_remain_distinct(self):
        row = self.fixture.assign()
        partial = workflows.dependency_wait(self.root, row['camel_thread_id'], row['cameleer_thread_id'], 'resource released', purpose='partial', factory=self.native)
        workflows.dependency_finish(self.root, partial['id'], result='partial artifact', factory=self.native)
        self.assertEqual(self.native.sent, 2)
        self.native.add('another-consumer')
        other = workflows.dependency_wait(self.root, row['camel_thread_id'], 'another-consumer', 'whole assignment', factory=self.native)
        workflows.dependency_finish(self.root, other['id'], result='another result', factory=self.native)
        self.assertEqual(self.native.sent, 3)
        old = workflows.dependency_wait(self.root, row['camel_thread_id'], row['cameleer_thread_id'], 'whole assignment', factory=self.native)
        followup = workflows.resume_task(self.root, row['id'], 'new result', factory=self.native)
        before = self.native.sent
        self.assertEqual(workflows.dependency_finish(self.root, old['id'], factory=self.native)['phase'], 'superseded')
        self.assertEqual(self.native.sent, before)
        current = workflows.dependency_wait(self.root, followup['camel_thread_id'], followup['cameleer_thread_id'], 'whole assignment', factory=self.native)
        self.assertNotEqual(old['id'], current['id'])

    def test_shared_assignment_failure_cancel_and_distinct_partial_results_are_preserved(self):
        for outcome in ('failed', 'cancelled'):
            row = self.fixture.assign(request_id=outcome)
            alias = workflows.dependency_wait(self.root, row['camel_thread_id'], row['cameleer_thread_id'], 'entire assignment', factory=self.native)
            completed = self.fixture.complete(row, outcome=outcome)
            before = self.native.sent
            mirrored = workflows.dependency_finish(self.root, alias['id'], factory=self.native)
            self.assertEqual(mirrored['phase'], outcome)
            self.assertEqual(mirrored['result_key'], completed['completion']['result_key'])
            self.assertEqual(self.native.sent, before)
            for name in ('first distinct result', 'new distinct result'):
                part = workflows.dependency_wait(self.root, row['camel_thread_id'], row['cameleer_thread_id'], name, purpose='partial', factory=self.native)
                workflows.dependency_finish(self.root, part['id'], result=name, factory=self.native)
            self.assertEqual(self.native.sent, before + 2)

    def test_explicit_assignment_for_another_consumer_binds_producer_cycle(self):
        row = self.fixture.assign()
        self.native.add('another-consumer')
        old = workflows.dependency_wait(self.root, row['camel_thread_id'], 'another-consumer', 'entire assignment', purpose='assignment', factory=self.native)
        workflows.resume_task(self.root, row['id'], 'new producer cycle', factory=self.native)
        before = self.native.sent
        self.assertEqual(workflows.dependency_finish(self.root, old['id'], factory=self.native)['phase'], 'superseded')
        self.assertEqual(self.native.sent, before)
        new = workflows.dependency_wait(self.root, row['camel_thread_id'], 'another-consumer', 'entire assignment', purpose='assignment', factory=self.native)
        self.assertNotEqual(old['id'], new['id'])

    def test_pending_observation_does_not_compete_for_the_foreground_writer_lock(self):
        row = self.fixture.assign()
        native, _ = self.fixture.pending_native_turn(row)
        path = self.root / '.oasis/local/tasks/state.json'
        lock = self.root / '.oasis/local/operations.lock'
        for submitted in (False, True):
            with self.subTest(submitted=submitted):
                if submitted:
                    self.fixture.complete(row)
                before = path.read_bytes()
                with operation_lock(lock):
                    observed = workflows.notification_step(self.root, self.native)
                self.assertTrue(observed['pending'])
                self.assertIn(native['id'], {target['thread_id'] for target in observed['targets']})
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.native.sent, 1)

    def test_terminal_observation_keeps_the_existing_writer_boundary(self):
        row = self.fixture.assign()
        native, turn = self.fixture.pending_native_turn(row)
        self.fixture.complete(row)
        self.fixture.finish_native_turn(native, turn)
        path = self.root / '.oasis/local/tasks/state.json'
        before = path.read_bytes()
        with operation_lock(self.root / '.oasis/local/operations.lock'):
            with self.assertRaisesRegex(HarnessError, 'Operation is already locked'):
                workflows.notification_step(self.root, self.native)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.native.sent, 1)
        workflows.notification_step(self.root, self.native)
        self.assertEqual(self.native.sent, 2)

    def test_duplicate_accepted_completion_does_not_start_an_idle_observer(self):
        row = self.fixture.assign()
        accepted = self.fixture.complete(row)
        path = self.root / '.oasis/local/tasks/state.json'
        before = path.read_bytes()
        with patch('oasis_harness.notifications.ensure_running', side_effect=AssertionError('Accepted duplicate must not launch an owner')) as launch, \
                patch('oasis_harness.shared_runtime.connect', side_effect=AssertionError('Accepted duplicate must not enter the production native factory')) as connect:
            # Actual default production factory: an injected NativeFixture masks
            # the command_scope -> shared owner startup path under test.
            actual = workflows.complete(self.root, row['id'])
        launch.assert_not_called()
        connect.assert_not_called()
        self.assertEqual(actual['completion']['delivery'], accepted['completion']['delivery'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.native.sent, 2)

    def test_duplicate_accepted_dependency_uses_default_factory_without_launch(self):
        self.native.add('producer')
        self.native.add('consumer')
        dependency = workflows.dependency_wait(self.root, 'producer', 'consumer', 'accepted partial artifact', factory=self.native)
        accepted = workflows.dependency_finish(self.root, dependency['id'], result='artifact', factory=self.native)
        path = self.root / '.oasis/local/tasks/state.json'
        before = path.read_bytes()
        with patch('oasis_harness.notifications.ensure_running', side_effect=AssertionError('Accepted duplicate must not launch an owner')) as launch, \
                patch('oasis_harness.shared_runtime.connect', side_effect=AssertionError('Accepted duplicate must not enter the production native factory')) as connect:
            actual = workflows.dependency_finish(self.root, dependency['id'])
        launch.assert_not_called()
        connect.assert_not_called()
        self.assertEqual(actual['delivery'], accepted['delivery'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.native.sent, 1)

    def test_waiting_consumer_is_not_missing_completion_and_partial_result_continues_same_cycle(self):
        row = self.fixture.assign()
        producer = self.native.add('producer', status='active')
        producer['turns'] = [{'id': 'producer-active', 'status': 'inProgress', 'items': []}]
        dependency = workflows.dependency_wait(self.root, 'producer', row['camel_thread_id'], 'interface artifact', factory=self.native)
        workflows.notification_step(self.root, self.native)
        waiting = workflows.task_status(self.root, row['id'])
        self.assertEqual(waiting['phase'], 'waiting_dependency')
        self.assertNotIn('unsubmitted_notice', waiting)
        self.assertEqual(self.native.sent, 1)
        delivered = workflows.dependency_finish(self.root, dependency['id'], result='artifact-ready', factory=self.native)
        self.assertEqual(delivered['delivery']['state'], 'accepted')
        self.assertEqual(producer['status']['type'], 'active')
        completed = self.fixture.complete(row)
        self.assertEqual(completed['native_turn']['state'], 'ready')
        self.assertEqual(completed['cycle'], row['cycle'])
        self.assertNotEqual(completed['assignment_delivery']['turn_id'], completed['native_turn']['id'])
        self.assertEqual(workflows.collect(self.root, row['id'], factory=self.native)['phase'], 'archived')

    def test_missing_result_notice_does_not_hide_new_followup_cycle(self):
        row = self.fixture.assign()
        workflows.notification_step(self.root, self.native)
        self.assertEqual(workflows.task_status(self.root, row['id'])['phase'], 'terminal_unsubmitted')
        follow = workflows.resume_task(self.root, row['id'], 'Correct the followup', factory=self.native)
        self.assertNotIn('unsubmitted_notice', follow)
        native, turn = self.fixture.pending_native_turn(follow)
        self.fixture.complete(follow)
        self.fixture.finish_native_turn(native, turn)
        workflows.notification_step(self.root, self.native)
        self.assertEqual(workflows.task_status(self.root, row['id'])['completion']['delivery']['state'], 'accepted')

    def test_previous_cycle_dependency_never_sends_to_new_assignment(self):
        row = self.fixture.assign()
        self.native.add('producer')
        old = workflows.dependency_wait(self.root, 'producer', row['camel_thread_id'], 'same interface', factory=self.native)
        workflows.resume_task(self.root, row['id'], 'New task cycle', factory=self.native)
        before = self.native.sent
        result = workflows.dependency_finish(self.root, old['id'], result='stale', factory=self.native)
        self.assertEqual(result['phase'], 'superseded')
        self.assertEqual(self.native.sent, before)
        new = workflows.dependency_wait(self.root, 'producer', row['camel_thread_id'], 'same interface', factory=self.native)
        self.assertNotEqual(new['id'], old['id'])

    def test_partial_notice_buffered_during_consumer_turn_does_not_signal_missing_result(self):
        row = self.fixture.assign()
        native, turn = self.fixture.pending_native_turn(row)
        self.native.add('producer')
        dependency = workflows.dependency_wait(self.root, 'producer', native['id'], 'ready interface', factory=self.native)
        sent = workflows.dependency_finish(self.root, dependency['id'], result='ready', factory=self.native)
        self.assertEqual(sent['delivery']['state'], 'pending_recipient')
        self.fixture.finish_native_turn(native, turn)
        workflows.notification_step(self.root, self.native)
        task = workflows.task_status(self.root, row['id'])
        self.assertNotIn('unsubmitted_notice', task)
        self.assertEqual(self.native.sent, 2)  # Assignment and dependency continuation only.
        self.assertEqual(task['dependency_continuations'][0]['dependency_id'], dependency['id'])

    def test_native_failure_without_submission_wakes_once_and_never_archives(self):
        row = self.fixture.assign()
        native, turn = self.fixture.pending_native_turn(row)
        turn['status'], native['status'] = 'failed', {'type': 'idle'}
        workflows.notification_step(self.root, self.native)
        failed = workflows.task_status(self.root, row['id'])
        self.assertEqual(failed['completion']['outcome'], 'failed')
        workflows.notification_step(self.root, self.native)
        self.assertEqual(self.native.sent, 2)
        self.assertFalse(native['archived'])

    def test_same_watch_storm_has_bounded_history_reads(self):
        row = self.fixture.assign()
        native, turn = self.fixture.pending_native_turn(row)
        self.fixture.complete(row)
        self.native.watch_supported = True
        def watch(params):
            for _ in range(100):
                self.native.watch_events.put({'method': 'fs/changed', 'params': {'watchId': params['watchId']}})
            timer = threading.Timer(.03, self.fixture.finish_native_turn, args=(native, turn))
            self.addCleanup(timer.join, 1)
            timer.start()
        self.native.on_watch = watch
        before = self.native.methods().count('thread/turns/list')
        snapshot = workflows._await_terminal(self.root, row, self.native, 1.2)
        reads = self.native.methods().count('thread/turns/list') - before
        self.assertEqual(snapshot['state'], 'ready')
        self.assertLessEqual(reads, 4)
        self.assertEqual(self.native.watches, {})


if __name__ == '__main__':
    unittest.main()
