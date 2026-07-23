# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Find the queue co-members a user shares a "reception" with.

The Missed list on a reception phone is a shared thing: an inbound call that
rings the office queue and nobody answers should show on *every* member's phone,
not just whichever agent wazo-call-logd happened to tag the single unanswered
CDR to. call-logd does not replicate that CDR to each member's per-user feed, so
we reconstruct the shared view ourselves — and to do that we first need to know,
for the authenticated user, who else is in their queue(s).

``comember_uuids`` returns the union of the user's own uuid and every other
user in every queue the user belongs to. It returns an **empty set** when the
user is in no queue at all, which the caller reads as "this is not a reception
phone — keep the personal Missed list", so a plain deskphone is unaffected.

Membership is read from wazo-confd. The queue *list* summary does not always
carry members, so a queue whose summary omits them is fetched in full; the number
of queues inspected is capped so a tenant with an unexpectedly large queue set
cannot turn one History open into hundreds of confd calls (the cap is logged, not
silent, if it is ever hit).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# A reception has a handful of queues at most. This bound only exists so a
# misconfigured or unexpectedly large tenant cannot make membership resolution
# unbounded; hitting it is logged because it means the shared list is built from
# an incomplete view of the user's queues.
_MAX_QUEUES_SCANNED = 50


def _member_uuids(queue: dict) -> set[str]:
    """Return the user uuids in a confd queue's ``members.users`` list."""
    members = queue.get('members') or {}
    return {
        user['uuid']
        for user in members.get('users') or []
        if user.get('uuid')
    }


def _queue_member_uuids(confd_client, summary: dict) -> set[str]:
    """Member uuids of one queue, fetching its detail only if the summary lacks them.

    confd's queue *list* representation may omit the members relation; the single
    queue representation always carries it. We avoid the extra round trip whenever
    the summary already answers the question.
    """
    uuids = _member_uuids(summary)
    if uuids or 'members' in summary or summary.get('id') is None:
        return uuids
    detail = confd_client.queues.get(summary['id'])
    return _member_uuids(detail)


def comember_uuids(confd_client, user_uuid: str) -> set[str]:
    """Return every user sharing a queue with ``user_uuid`` (including it).

    Empty when the user belongs to no queue — the signal to keep the personal
    Missed list rather than build the shared reception one. Queues are matched by
    membership uuid, which is globally unique, so a recursive (cross-tenant) list
    cannot mis-attribute a user to another tenant's queue.

    Any confd transport/permission error propagates to the caller, which decides
    how to degrade (the HTTP layer falls back to the personal list and logs that
    the shared list needs ``confd.queues.read``).
    """
    result = confd_client.queues.list(recurse=True)
    summaries = result.get('items') or []
    if len(summaries) > _MAX_QUEUES_SCANNED:
        logger.warning(
            'tenant has %d queues; only the first %d are scanned for membership, '
            'so a shared Missed list may be incomplete',
            len(summaries),
            _MAX_QUEUES_SCANNED,
        )
        summaries = summaries[:_MAX_QUEUES_SCANNED]

    comembers: set[str] = set()
    is_member = False
    for summary in summaries:
        members = _queue_member_uuids(confd_client, summary)
        if user_uuid in members:
            is_member = True
            comembers |= members
    return comembers if is_member else set()
