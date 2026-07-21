# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render XSI CallLogs XML exactly as a Yealink phone expects it.

Shapes verified against the Cisco BroadWorks XSI Interface Specification (R20 and
R23 are identical) *and* live on a T87W (185.87.0.34):

  * A per-type sub-endpoint (``/CallLogs/Placed`` etc.) returns a **bare,
    unnamespaced** lowercase root — ``<placed>…</placed>`` — NOT wrapped in
    ``<CallLogs>``. Returning the wrapper parses without error but renders an
    empty list (learned the hard way during discovery).
  * The combined ``/CallLogs`` endpoint returns ``<CallLogs xmlns="…/xsi">``
    containing all three lists.

Each row is ``<callLogsEntry>`` with children in this order: countryCode,
phoneNumber, name, time, callLogId. The document declares ISO-8859-1, so we emit
latin-1 bytes and XML-escape every value (names can contain ``&``, ``<``).
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .call_logs import LISTS, CallLogEntry

_NS = 'http://schema.broadsoft.com/xsi'
_DECL = '<?xml version="1.0" encoding="ISO-8859-1"?>'
_ENCODING = 'latin-1'


def _entry_xml(entry: CallLogEntry) -> str:
    return (
        '<callLogsEntry>'
        f'<countryCode>{escape(entry.country_code)}</countryCode>'
        f'<phoneNumber>{escape(entry.number)}</phoneNumber>'
        f'<name>{escape(entry.name)}</name>'
        f'<time>{escape(entry.time)}</time>'
        f'<callLogId>{escape(entry.log_id)}</callLogId>'
        '</callLogsEntry>'
    )


def _entries_xml(entries: list[CallLogEntry]) -> str:
    return ''.join(_entry_xml(e) for e in entries)


def render_list(list_name: str, entries: list[CallLogEntry]) -> bytes:
    """Render one call-log list (``placed``/``received``/``missed``) for a sub-endpoint.

    The root element is the bare lowercase list name with no namespace, per the
    captured phone behaviour.
    """
    if list_name not in LISTS:
        raise ValueError(f'unknown call-log list {list_name!r}')
    body = f'{_DECL}<{list_name}>{_entries_xml(entries)}</{list_name}>'
    return body.encode(_ENCODING, 'xmlcharrefreplace')


def render_combined(buckets: dict[str, list[CallLogEntry]]) -> bytes:
    """Render the combined ``<CallLogs>`` document (the ``/CallLogs`` endpoint)."""
    inner = ''.join(
        f'<{name}>{_entries_xml(buckets.get(name, []))}</{name}>' for name in LISTS
    )
    body = f'{_DECL}<CallLogs xmlns="{_NS}">{inner}</CallLogs>'
    return body.encode(_ENCODING, 'xmlcharrefreplace')
