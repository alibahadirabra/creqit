# Copyright (c) 2015, creqit Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import creqit
from creqit.tests import IntegrationTestCase
from creqit.utils.data import add_to_date, today


class TestDocumentLocks(IntegrationTestCase):
	def test_locking(self):
		todo = creqit.get_doc(doctype="ToDo", description="test").insert()
		todo_1 = creqit.get_doc("ToDo", todo.name)

		todo.lock()
		self.assertRaises(creqit.DocumentLockedError, todo_1.lock)
		todo.unlock()

		todo_1.lock()
		self.assertRaises(creqit.DocumentLockedError, todo.lock)
		todo_1.unlock()

	def test_operations_on_locked_documents(self):
		todo = creqit.get_doc(doctype="ToDo", description="testing operations").insert()
		todo.lock()

		with self.assertRaises(creqit.DocumentLockedError):
			todo.description = "Random"
			todo.save()

		# Checking for persistant locks across all instances.
		doc = creqit.get_doc("ToDo", todo.name)
		self.assertEqual(doc.is_locked, True)

		with self.assertRaises(creqit.DocumentLockedError):
			doc.description = "Random"
			doc.save()

		doc.unlock()
		self.assertEqual(doc.is_locked, False)
		self.assertEqual(todo.is_locked, False)

	def test_locks_auto_expiry(self):
		todo = creqit.get_doc(doctype="ToDo", description=creqit.generate_hash()).insert()
		todo.lock()

		self.assertRaises(creqit.DocumentLockedError, todo.lock)

		with self.freeze_time(add_to_date(today(), days=3)):
			todo.lock()
