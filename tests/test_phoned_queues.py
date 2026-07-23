# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for queue co-member resolution (wazo_phoned_optimogo.queues)."""

import pytest

from wazo_phoned_optimogo import queues

ALICE = 'aaaaaaaa-0000-0000-0000-000000000001'
BOB = 'bbbbbbbb-0000-0000-0000-000000000002'
CAROL = 'cccccccc-0000-0000-0000-000000000003'
DAVE = 'dddddddd-0000-0000-0000-000000000004'


class FakeQueues:
    """confd queues resource: list gives id-only summaries; get gives members."""

    def __init__(self, queues, summaries_carry_members=False):
        self._queues = {q['id']: q for q in queues}
        self._summaries_carry_members = summaries_carry_members
        self.get_calls = []

    def list(self, recurse):
        assert recurse is True
        if self._summaries_carry_members:
            return {'items': list(self._queues.values())}
        return {'items': [{'id': qid} for qid in self._queues]}

    def get(self, queue_id):
        self.get_calls.append(queue_id)
        return self._queues[queue_id]


class FakeConfd:
    def __init__(self, queues, **kwargs):
        self.queues = FakeQueues(queues, **kwargs)


def _queue(queue_id, *members):
    return {'id': queue_id, 'members': {'users': [{'uuid': m} for m in members]}}


def test_member_gets_all_comembers_including_self():
    confd = FakeConfd([_queue(1, ALICE, BOB)])
    assert queues.comember_uuids(confd, ALICE) == {ALICE, BOB}


def test_non_member_gets_empty_set():
    confd = FakeConfd([_queue(1, BOB, CAROL)])
    assert queues.comember_uuids(confd, ALICE) == set()


def test_no_queues_gives_empty_set():
    confd = FakeConfd([])
    assert queues.comember_uuids(confd, ALICE) == set()


def test_union_across_every_queue_the_user_belongs_to():
    confd = FakeConfd([_queue(1, ALICE, BOB), _queue(2, ALICE, CAROL), _queue(3, DAVE)])
    assert queues.comember_uuids(confd, ALICE) == {ALICE, BOB, CAROL}


def test_queue_the_user_is_absent_from_does_not_leak_members():
    confd = FakeConfd([_queue(1, ALICE, BOB), _queue(2, CAROL, DAVE)])
    assert queues.comember_uuids(confd, ALICE) == {ALICE, BOB}


def test_summaries_with_members_avoid_the_detail_fetch():
    confd = FakeConfd([_queue(1, ALICE, BOB)], summaries_carry_members=True)
    assert queues.comember_uuids(confd, ALICE) == {ALICE, BOB}
    assert confd.queues.get_calls == []


def test_summaries_without_members_fall_back_to_detail_fetch():
    confd = FakeConfd([_queue(1, ALICE, BOB)])
    queues.comember_uuids(confd, ALICE)
    assert confd.queues.get_calls == [1]


def test_scan_is_capped(monkeypatch):
    monkeypatch.setattr(queues, '_MAX_QUEUES_SCANNED', 2)
    # The user is only in the third queue, which is beyond the cap, so they read
    # as a non-member — the cap is a safety bound, logged, not silent.
    confd = FakeConfd([_queue(1, BOB), _queue(2, CAROL), _queue(3, ALICE, DAVE)])
    assert queues.comember_uuids(confd, ALICE) == set()
