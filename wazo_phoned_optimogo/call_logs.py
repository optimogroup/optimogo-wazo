# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn wazo-call-logd CDRs into XSI call-log entries, split by list.

A Yealink phone's "Network CallLog" has three lists — Placed, Received, Missed —
and fetches each from its own XSI sub-endpoint. wazo-call-logd exposes one CDR
stream per user (``GET /users/{uuid}/cdr``); we classify each CDR from *that
user's* point of view:

  * placed   — the user originated the call            (source_user_uuid == user)
  * received — the user was called and answered        (dest/requested == user, answered)
  * missed   — the user was called and did not answer  (dest/requested == user, not answered)

For each entry the phone shows the *other* party: for a placed call that is the
destination; for a received/missed call it is the source. We surface the
number and name wazo-call-logd already resolved (extension for internal, the
national/E.164 number for external, contact name from the directory reverse
lookup), so callbacks from the log dial exactly what a normal dial would.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import NamedTuple

logger = logging.getLogger(__name__)

PLACED = 'placed'
RECEIVED = 'received'
MISSED = 'missed'
LISTS = (PLACED, RECEIVED, MISSED)

# call_direction value for a call that came from outside the PBX. The shared
# reception Missed list is built only from inbound calls: an internal colleague
# who rang your extension and got no answer is your own affair, not something to
# broadcast to everyone else on the reception queue.
INBOUND = 'inbound'


class CallLogEntry(NamedTuple):
    """One XSI ``callLogsEntry`` row (already in phone-facing form)."""

    log_id: str
    number: str
    name: str
    time: str
    country_code: str


def classify(cdr: dict, user_uuid: str) -> str | None:
    """Return which list a CDR belongs to for ``user_uuid``, or None to drop it.

    A call where the user is the source is *placed* (this also covers the user
    dialling internal features like ``*98``). Otherwise, if the user is the
    called/requested party, it is *received* when answered and *missed* when
    not. Anything else (the user appears in neither role — should not happen for
    a per-user CDR feed, but we are defensive) is dropped.
    """
    if cdr.get('source_user_uuid') == user_uuid:
        return PLACED
    is_destination = user_uuid in (
        cdr.get('destination_user_uuid'),
        cdr.get('requested_user_uuid'),
    )
    if is_destination:
        return RECEIVED if cdr.get('answered') else MISSED
    return None


def _other_party(cdr: dict, kind: str) -> tuple[str, str]:
    """Return (number, name) of the party to display for a given list.

    Placed → the destination we called; received/missed → the source who called
    us. Falls back through the fields wazo-call-logd populates so an entry is
    never blank when any identifier is available.
    """
    if kind == PLACED:
        number = cdr.get('destination_extension') or cdr.get('requested_extension') or ''
        name = cdr.get('destination_name') or cdr.get('requested_name') or ''
    else:
        number = cdr.get('source_extension') or ''
        name = cdr.get('source_name') or cdr.get('source_internal_name') or ''
    return number, name


def _format_time(iso_time: str | None) -> str:
    """Normalise a call-logd timestamp to XSI form (millisecond precision).

    call-logd emits ISO-8601 with microseconds and a numeric offset
    (``2026-07-21T11:56:07.628181+10:00``); the XSI schema examples use
    milliseconds (``...811+05:30``). We truncate to milliseconds and keep the
    offset. An unparseable/empty time yields '' rather than raising — a single
    odd CDR must not blank the whole list.
    """
    if not iso_time:
        return ''
    try:
        parsed = datetime.fromisoformat(iso_time)
    except ValueError:
        logger.warning('unparseable CDR time %r', iso_time)
        return ''
    millis = parsed.microsecond // 1000
    base = parsed.strftime('%Y-%m-%dT%H:%M:%S')
    offset = parsed.strftime('%z')  # e.g. +1000
    if offset:
        offset = f'{offset[:3]}:{offset[3:]}'  # +1000 -> +10:00
    return f'{base}.{millis:03d}{offset}'


def to_entry(cdr: dict, kind: str) -> CallLogEntry:
    """Map a single CDR (already classified as ``kind``) to a CallLogEntry."""
    number, name = _other_party(cdr, kind)
    return CallLogEntry(
        log_id=str(cdr.get('id', '')),
        number=number,
        name=name,
        time=_format_time(cdr.get('start')),
        # wazo-call-logd already presents dialable numbers; we do not split a
        # country code out, so leave it blank (the phone dials phoneNumber as-is).
        country_code='',
    )


def split_call_logs(cdrs: list[dict], user_uuid: str) -> dict[str, list[CallLogEntry]]:
    """Split a user's CDRs into {placed, received, missed} lists of entries.

    Preserves the order call-logd returned (newest first) within each list.
    """
    buckets: dict[str, list[CallLogEntry]] = {name: [] for name in LISTS}
    for cdr in cdrs:
        kind = classify(cdr, user_uuid)
        if kind is None:
            continue
        buckets[kind].append(to_entry(cdr, kind))
    return buckets


def is_shared_missed(cdr: dict) -> bool:
    """True if a CDR is an inbound call that nobody answered.

    This is the whole definition of a shared reception miss: it rang the queue
    and no agent picked up (``answered`` is false for the call as a whole, so a
    call a colleague *did* catch is excluded — it is handled, not missed).
    """
    return cdr.get('call_direction') == INBOUND and not cdr.get('answered')


def shared_missed_entries(
    member_feeds: list[list[dict]], limit: int
) -> list[CallLogEntry]:
    """Build the shared Missed list from several queue members' CDR feeds.

    call-logd tags each unanswered queue call to a single member, so no single
    member's feed holds them all; we union every member's inbound-unanswered CDRs
    and de-duplicate by CDR id (the id is global, so the same call seen through
    two feeds collapses to one). The result is ordered newest-first and capped so
    a busy reception cannot produce an unbounded XML document.
    """
    by_id: dict = {}
    for feed in member_feeds:
        for cdr in feed:
            if is_shared_missed(cdr):
                by_id[cdr.get('id')] = cdr
    ordered = sorted(
        by_id.values(), key=lambda cdr: cdr.get('start') or '', reverse=True
    )
    return [to_entry(cdr, MISSED) for cdr in ordered[:limit]]
