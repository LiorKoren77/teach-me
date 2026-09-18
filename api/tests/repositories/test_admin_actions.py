from __future__ import annotations

from uuid import uuid4

from teachme.repositories.admin_actions import AdminActionRepository


def test_records_and_lists_newest_first(db):
    actions = AdminActionRepository(db)
    subject_id, other_subject = uuid4(), uuid4()
    actions.record(user_id="admin_1", action="upload", subject_id=subject_id, detail={"filename": "a.pdf"})
    actions.record(user_id="admin_2", action="publish", subject_id=other_subject)
    actions.record(user_id="admin_1", action="delete", subject_id=subject_id, source_id=uuid4())

    every = actions.list()
    assert [row.action for row in every] == ["delete", "publish", "upload"]
    assert [row.action for row in actions.list(subject_id=subject_id)] == ["delete", "upload"]
    assert [row.action for row in actions.list(limit=1)] == ["delete"]
    uploaded = every[-1]
    assert uploaded.user_id == "admin_1" and uploaded.detail == {"filename": "a.pdf"}
    assert uploaded.source_id is None and uploaded.created_at is not None


def test_counting_an_action_only_sees_this_user_and_this_hour(db):
    """What the upload cap is measured with: one admin's uploads, in the window, and nothing
    else - not another admin's, not another kind of action, not yesterday's."""
    actions = AdminActionRepository(db)
    actions.record(user_id="admin_1", action="upload")
    actions.record(user_id="admin_1", action="delete")
    actions.record(user_id="admin_2", action="upload")
    old = actions.record(user_id="admin_1", action="upload")
    db.execute("UPDATE admin_actions SET created_at = now() - interval '2 hours' WHERE id = %s", (old,))

    assert actions.count_since(user_id="admin_1", action="upload", seconds=3600) == 1
    assert actions.count_since(user_id="admin_1", action="upload", seconds=3 * 3600) == 2
    assert actions.count_since(user_id="admin_9", action="upload", seconds=3600) == 0


def test_an_audit_row_survives_what_it_describes(db):
    """No foreign keys: a delete is exactly the action whose record must outlive its subject."""
    actions = AdminActionRepository(db)
    subject_id = uuid4()
    actions.record(user_id="admin_1", action="delete", subject_id=subject_id, source_id=uuid4())
    db.commit()
    assert len(actions.list(subject_id=subject_id)) == 1
