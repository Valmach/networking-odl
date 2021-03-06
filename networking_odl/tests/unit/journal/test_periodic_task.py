#
# Copyright (C) 2016 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.
#

import threading
import time

import mock

from networking_odl.common import constants as odl_const
from networking_odl.db import db
from networking_odl.db import models
from networking_odl.journal import periodic_task
from networking_odl.tests.unit import test_base_db


class PeriodicTaskThreadTestCase(test_base_db.ODLBaseDbTestCase):
    def setUp(self):
        super(PeriodicTaskThreadTestCase, self).setUp()
        row = models.OpenDaylightPeriodicTask(task='test-maintenance',
                                              state=odl_const.PENDING)
        self.db_session.add(row)
        self.db_session.flush()

        self.thread = periodic_task.PeriodicTask('test-maintenance', 0.01)
        self.addCleanup(self.thread.cleanup)

    def test__execute_op_no_exception(self):
        with mock.patch.object(periodic_task, 'LOG') as mock_log:
            operation = mock.MagicMock()
            operation.__name__ = "test"
            self.thread.register_operation(operation)
            self.thread._execute_op(operation, self.db_context)
            operation.assert_called()
            mock_log.info.assert_called()
            mock_log.exception.assert_not_called()

    def test__execute_op_with_exception(self):
        with mock.patch.object(periodic_task, 'LOG') as mock_log:
            operation = mock.MagicMock(side_effect=Exception())
            operation.__name__ = "test"
            self.thread._execute_op(operation, self.db_context)
            mock_log.exception.assert_called()

    def test_thread_works(self):
        callback_event = threading.Event()
        count = [0]

        def callback_op(**kwargs):
            count[0] += 1

            # The following should be true on the second call, so we're making
            # sure that the thread runs more than once.
            if count[0] > 1:
                callback_event.set()

        self.thread.register_operation(callback_op)
        self.thread.start()

        # Make sure the callback event was called and not timed out
        self.assertTrue(callback_event.wait(timeout=5))

    def test_thread_continues_after_exception(self):
        exception_event = threading.Event()
        callback_event = threading.Event()

        def exception_op(**kwargs):
            if not exception_event.is_set():
                exception_event.set()
                raise Exception()

        def callback_op(**kwargs):
            callback_event.set()

        for op in [exception_op, callback_op]:
            self.thread.register_operation(op)

        self.thread.start()

        # Make sure the callback event was called and not timed out
        self.assertTrue(callback_event.wait(timeout=5))

    def test_multiple_thread_work(self):
        self.thread1 = periodic_task.PeriodicTask('test-maintenance1', 0.01)
        callback_event = threading.Event()
        callback_event1 = threading.Event()
        self.addCleanup(self.thread1.cleanup)

        def callback_op(**kwargs):
            callback_event.set()

        def callback_op1(**kwargs):
            callback_event1.set()

        self.thread.register_operation(callback_op)
        self.thread.register_operation(callback_op1)
        self.thread.start()
        self.assertTrue(callback_event.wait(timeout=5))

        self.thread1.start()
        self.assertTrue(callback_event1.wait(timeout=5))

    @mock.patch.object(db, "was_periodic_task_executed_recently")
    def test_back_to_back_job(self, mock_status_method):
        callback_event = threading.Event()

        def callback_op(**kwargs):
            callback_event.set()

        self.thread.register_operation(callback_op)
        msg = ("Periodic %s task executed after periodic "
               "interval Skipping execution.")
        with mock.patch.object(periodic_task.LOG, 'info') as mock_log_info:
            mock_status_method.return_value = True
            self.thread.start()
            time.sleep(1)
            mock_log_info.assert_called_with(msg, 'test-maintenance')
            self.assertFalse(callback_event.wait(timeout=1))
            mock_log_info.assert_called_with(msg, 'test-maintenance')
            mock_status_method.return_value = False
            self.assertTrue(callback_event.wait(timeout=2))
